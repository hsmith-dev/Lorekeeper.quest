import { useEffect, useSyncExternalStore } from "react";
import { useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { getPreviewCampaignId, subscribePreview } from "../lib/preview";
import { openSse, type Connect, type SseFrame } from "../lib/sse";
import { getJob, JOB_STREAM_PATH, listJobs } from "../services/api/jobs";
import { JOB_STATUSES, type Job, type JobEvent, type JobListResponse } from "../types/jobs";
import { useCurrentCampaign } from "./useCurrentCampaign";

// Background Jobs of a Campaign (E0-Jobs.9, AD-5): the list, one Job, and the
// server's Job stream GET /api/jobs/stream?campaign_id= through lib/sse.ts.
//
//   event: subscribed      {}                          the subscription is live: refetch the Jobs
//   event: job             {job_id, kind, status, ...} merged into the list and the detail
//   event: ping            {}                          keep-alive (filtered by lib/sse.ts)
//   event: access_changed  {"detail":"Not found"}      the grant changed; the stream ends
//
// Query keys: ['jobs', campaignId] is the default list (GET /api/jobs/),
// ['jobs', campaignId, jobId] one Job (GET /api/jobs/{id}). Resync contract:
// every `subscribed` refetches both; the server keeps no event ids. A `job`
// event patches the cached rows at once; on a status change (or a Job not in
// the list) the list and the detail are refetched, since a status change moves
// a Job between sections and the event carries no queue position or times.
// Reconnects and stops (401, 404) are lib/sse.ts's; the server filters every
// event for the caller.

export function jobsListKey(campaignId: string): QueryKey {
  return ["jobs", campaignId];
}

export function jobKey(campaignId: string, jobId: string): QueryKey {
  return ["jobs", campaignId, jobId];
}

// ─── Merging (pure) ──────────────────────────────────────────────────────────

const nullableNumber = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const nullableString = (v: unknown): string | null => (typeof v === "string" ? v : null);

/** A `job` event's data, or null when malformed (no id, unknown status). */
export function parseJobEvent(data: unknown): JobEvent | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;
  if (typeof d.job_id !== "string" || d.job_id.length === 0) return null;
  if (typeof d.status !== "string" || !(JOB_STATUSES as readonly string[]).includes(d.status)) return null;
  if (typeof d.kind !== "string") return null;
  const ref = d.result_ref;
  return {
    job_id: d.job_id,
    kind: d.kind,
    status: d.status as JobEvent["status"],
    progress: nullableNumber(d.progress),
    stage: nullableString(d.stage),
    eta_seconds: nullableNumber(d.eta_seconds),
    error_code: nullableString(d.error_code),
    error_message: nullableString(d.error_message),
    result_ref: ref && typeof ref === "object" && !Array.isArray(ref) ? (ref as Record<string, unknown>) : null,
  };
}

/** `job` with the event's fields applied. */
export function mergeJobEvent(job: Job, ev: JobEvent): Job {
  return {
    ...job,
    kind: ev.kind,
    status: ev.status,
    progress: ev.progress,
    stage: ev.stage,
    eta_seconds: ev.eta_seconds,
    error_code: ev.error_code,
    error_message: ev.error_message,
    result_ref: ev.result_ref,
    // Only a queued Job has a queue position; the refetch sets the new one.
    queue_position: ev.status === "queued" ? job.queue_position : null,
  };
}

export interface ListMerge {
  list: JobListResponse;
  /** The Job was in the list. */
  found: boolean;
  /** Its status differs from the cached one. */
  statusChanged: boolean;
}

/** The list with the event's Job patched (same list when not found). */
export function mergeJobList(list: JobListResponse, ev: JobEvent): ListMerge {
  const index = list.jobs.findIndex((j) => j.id === ev.job_id);
  if (index === -1) return { list, found: false, statusChanged: false };
  const old = list.jobs[index];
  const jobs = [...list.jobs];
  jobs[index] = mergeJobEvent(old, ev);
  return { list: { ...list, jobs }, found: true, statusChanged: old.status !== ev.status };
}

// ─── The cache ───────────────────────────────────────────────────────────────

function refetchJobs(queryClient: QueryClient, campaignId: string): void {
  // Prefix match: the list and every Job detail of the Campaign.
  void queryClient.invalidateQueries({ queryKey: jobsListKey(campaignId) });
}

/**
 * Apply one frame of the Job stream to the query cache and say what it was.
 * Refetches are started, not awaited.
 */
export function applyJobFrame(
  queryClient: QueryClient,
  campaignId: string,
  frame: SseFrame,
): "subscribed" | "job" | "access_changed" | "other" {
  if (frame.event === "subscribed") {
    refetchJobs(queryClient, campaignId);
    return "subscribed";
  }
  if (frame.event === "access_changed") return "access_changed";
  if (frame.event !== "job") return "other";
  const ev = parseJobEvent(frame.data);
  if (!ev) return "other";

  let refetchList = true;
  let statusChanged = false;
  const list = queryClient.getQueryData<JobListResponse>(jobsListKey(campaignId));
  if (list && Array.isArray(list.jobs)) {
    const merged = mergeJobList(list, ev);
    if (merged.found) {
      queryClient.setQueryData(jobsListKey(campaignId), merged.list);
      statusChanged = merged.statusChanged;
      refetchList = merged.statusChanged;
    }
  }
  const detailKey = jobKey(campaignId, ev.job_id);
  const detail = queryClient.getQueryData<Job>(detailKey);
  if (detail) {
    if (detail.status !== ev.status) statusChanged = true;
    queryClient.setQueryData(detailKey, mergeJobEvent(detail, ev));
  }
  if (refetchList) void queryClient.invalidateQueries({ queryKey: jobsListKey(campaignId), exact: true });
  if (statusChanged) void queryClient.invalidateQueries({ queryKey: detailKey, exact: true });
  return "job";
}

// ─── The loop ────────────────────────────────────────────────────────────────

export interface RunJobStreamOptions {
  campaignId: string;
  queryClient: QueryClient;
  signal: AbortSignal;
  connect?: Connect;
  headers?: () => Record<string, string> | null;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  random?: () => number;
  /** Called once when the stream stops for good (not on abort). */
  onStop?: (reason: string) => void;
}

/** Follow the Campaign's Job stream until stopped (401, 404, no token) or aborted. */
export function runJobStream({
  campaignId,
  queryClient,
  signal,
  connect,
  headers,
  sleep,
  random,
  onStop,
}: RunJobStreamOptions): Promise<string> {
  return openSse(JOB_STREAM_PATH(campaignId), {
    signal,
    connect,
    headers,
    sleep,
    random,
    onEvent: (frame) => void applyJobFrame(queryClient, campaignId, frame),
    onStop: (reason) => {
      // No account, or no longer a Member: the Job queries answer that themselves.
      if (reason === "401" || reason === "404") refetchJobs(queryClient, campaignId);
      onStop?.(reason);
    },
  });
}

// ─── React ───────────────────────────────────────────────────────────────────

/**
 * Keep `campaignId`'s Job queries fresh from the Job stream while mounted.
 * Reopens when the Campaign or preview changes; does nothing without a
 * Campaign or a token.
 */
export function useJobStream(campaignId: string | null | undefined): void {
  const queryClient = useQueryClient();
  const previewing = useSyncExternalStore(subscribePreview, getPreviewCampaignId, getPreviewCampaignId);
  useEffect(() => {
    if (!campaignId) return;
    const controller = new AbortController();
    void runJobStream({ campaignId, queryClient, signal: controller.signal });
    return () => controller.abort();
  }, [campaignId, queryClient, previewing]);
}

/** Mounted once in the app shell: the current Campaign's Job stream. */
export function JobStreamSubscriber(): null {
  const { current } = useCurrentCampaign();
  useJobStream(current?.id);
  return null;
}

const notFound = (error: unknown) => (error as { response?: { status?: number } })?.response?.status === 404;

/** The caller's visible Jobs of `campaignId` (running, queued, last 24 h), newest first. */
export function useJobs(campaignId: string | null | undefined) {
  return useQuery<JobListResponse>({
    queryKey: jobsListKey(campaignId ?? ""),
    queryFn: async () => (await listJobs(campaignId as string)).data,
    enabled: !!campaignId,
    retry: (count, error) => !notFound(error) && count < 2,
  });
}

/** One Job, under ['jobs', campaignId, jobId]; `campaignId` defaults to the current Campaign. */
export function useJob(jobId: string | null | undefined, campaignId?: string | null) {
  const queryClient = useQueryClient();
  const { current } = useCurrentCampaign();
  const cid = campaignId ?? current?.id ?? null;
  return useQuery<Job>({
    queryKey: jobKey(cid ?? "", jobId ?? ""),
    queryFn: async () => (await getJob(jobId as string)).data,
    enabled: !!jobId && !!cid,
    // The list row, until the detail arrives.
    placeholderData: () =>
      cid && jobId
        ? queryClient.getQueryData<JobListResponse>(jobsListKey(cid))?.jobs.find((j) => j.id === jobId)
        : undefined,
    retry: (count, error) => !notFound(error) && count < 2,
  });
}
