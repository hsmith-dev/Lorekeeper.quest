import { useEffect, useSyncExternalStore } from "react";
import { useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { getPreviewCampaignId, previewHeaders, subscribePreview } from "../lib/preview";
import { useCurrentCampaign } from "./useCurrentCampaign";

// Campaign invalidations pushed by the server (E0-Access.11, AD-5):
// GET /api/campaigns/{id}/events, a server-sent event stream.
//
//   event: subscribed      {}                    the subscription is live: refetch
//   event: invalidate      {domain, id | null}   refetch [domain, campaignId] (and friends)
//   event: ping            {}                    keep-alive
//   event: access_changed  {"detail":"Not found"} the grant changed; the stream ends
//
// Resync contract: there are no event ids and no replay. Anything read before
// `subscribed` may be stale, so every `subscribed` (the first one and the one
// after each reconnect) refetches the Campaign's queries. Every gap is closed
// by reconnect, then `subscribed`, then refetch.
//
// Reconnects: backoff 1 s doubling to 30 s with jitter, reset by `subscribed`.
// After `access_changed` it reconnects once at once (a promotion fires it
// too). It stops on 401 and 404 (no account, or no longer a Member).
//
// Transport: fetch + ReadableStream with the bearer header (no EventSource,
// never a token in the URL), behind `openFetchStream`. E0-Jobs.9's lib/sse.ts replaces
// that one function. The server filters every event for the caller; nothing
// here decides what a user may see.

export const EVENTS_PATH = (campaignId: string) => `/api/campaigns/${encodeURIComponent(campaignId)}/events`;

export const BACKOFF_BASE_MS = 1_000;
export const BACKOFF_MAX_MS = 30_000;

// ─── Frames ──────────────────────────────────────────────────────────────────

export interface SseFrame {
  event: string;
  data: unknown;
}

/** Parse one SSE frame ("event: x\ndata: {...}"); multi-line data is joined with "\n". */
export function parseSseFrame(frame: string): SseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const raw of frame.split(/\r\n|\r|\n/)) {
    if (raw === "" || raw.startsWith(":")) continue;
    const colon = raw.indexOf(":");
    const field = colon === -1 ? raw : raw.slice(0, colon);
    let value = colon === -1 ? "" : raw.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

/** A stateful splitter: feed decoded text chunks, get whole frames back. */
export function createFrameSplitter(): (chunk: string) => SseFrame[] {
  let buffer = "";
  return (chunk: string) => {
    buffer += chunk;
    const frames: SseFrame[] = [];
    for (;;) {
      const match = /\r\n\r\n|\n\n|\r\r/.exec(buffer);
      if (!match) break;
      const frame = parseSseFrame(buffer.slice(0, match.index));
      buffer = buffer.slice(match.index + match[0].length);
      if (frame) frames.push(frame);
    }
    return frames;
  };
}

// ─── What to refetch ─────────────────────────────────────────────────────────

export interface Invalidation {
  domain: string;
  id: string | null;
}

/** Domains that say "refetch everything of this Campaign" (never an id). */
export const BROADCAST_DOMAINS = new Set(["visibility", "role"]);

// Query keys that hold this Campaign's rows without the Campaign id at
// position 1 (cross-Campaign lists and item details).
export const CROSS_CAMPAIGN_KEYS = new Set(["journals", "journal", "chat-sessions", "campaigns", "tags"]);

// Existing query keys whose name differs from the event domain.
const DOMAIN_ALIASES: Record<string, (campaignId: string, id: string | null) => QueryKey[]> = {
  journal: (_c, id) => [["journals"], id ? ["journal", id] : ["journal"]],
  character_sheets: (c) => [["characterSheets", c]],
  session_plans: (c) => [["session-plans", c]],
};

export function campaignRoleQueryKey(campaignId: string): QueryKey {
  return ["campaignRole", campaignId];
}

/** True for a query that holds data of `campaignId` (refetched on resync). */
export function isCampaignQuery(queryKey: QueryKey, campaignId: string): boolean {
  if (queryKey[1] === campaignId) return true;
  return typeof queryKey[0] === "string" && CROSS_CAMPAIGN_KEYS.has(queryKey[0]);
}

export function parseInvalidation(data: unknown): Invalidation | null {
  if (!data || typeof data !== "object") return null;
  const { domain, id } = data as { domain?: unknown; id?: unknown };
  if (typeof domain !== "string" || domain.length === 0) return null;
  if (id !== null && id !== undefined && typeof id !== "string") return null;
  return { domain, id: typeof id === "string" ? id : null };
}

export interface Refetch {
  all: boolean;
  keys: QueryKey[];
}

/** The query keys one invalidation refetches; `all` means every Campaign query. */
export function invalidationKeys(inv: Invalidation, campaignId: string): Refetch {
  const keys: QueryKey[] = [[inv.domain, campaignId]];
  if (inv.domain === "role") keys.push(campaignRoleQueryKey(campaignId));
  const alias = DOMAIN_ALIASES[inv.domain];
  if (alias) keys.push(...alias(campaignId, inv.id));
  return { all: BROADCAST_DOMAINS.has(inv.domain), keys };
}

function refetchCampaign(queryClient: QueryClient, campaignId: string): void {
  void queryClient.invalidateQueries({ predicate: (q) => isCampaignQuery(q.queryKey, campaignId) });
}

/**
 * Apply one frame to the query cache and say what it was. Refetches are
 * started, not awaited: the stream keeps being read while they run.
 */
export function applyFrame(
  queryClient: QueryClient,
  campaignId: string,
  frame: SseFrame,
): "subscribed" | "invalidate" | "access_changed" | "other" {
  if (frame.event === "subscribed") {
    refetchCampaign(queryClient, campaignId);
    return "subscribed";
  }
  if (frame.event === "access_changed") {
    void queryClient.invalidateQueries({ queryKey: campaignRoleQueryKey(campaignId) });
    return "access_changed";
  }
  if (frame.event !== "invalidate") return "other";
  const inv = parseInvalidation(frame.data);
  if (!inv) return "other";
  const { all, keys } = invalidationKeys(inv, campaignId);
  for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
  if (all) refetchCampaign(queryClient, campaignId);
  return "invalidate";
}

// ─── Reconnect policy ────────────────────────────────────────────────────────

/** How one connection ended. */
export type StreamOutcome =
  | { kind: "status"; status: number } // the server answered without a stream
  | { kind: "ended"; accessChanged: boolean; subscribed: boolean } // a stream that ran, then ended
  | { kind: "error" } // network failure
  | { kind: "aborted" };

export interface ReconnectState {
  /** Failed attempts since the last `subscribed`. */
  attempt: number;
  /** An `access_changed` reconnect was just used and no stream has subscribed since. */
  accessRetryUsed: boolean;
}

export type ReconnectDecision = { action: "stop"; reason: string } | { action: "reconnect"; delayMs: number };

export function backoffMs(attempt: number, random: () => number = Math.random): number {
  const ceiling = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** Math.max(0, attempt));
  return Math.round(ceiling * (0.5 + random() / 2));
}

/** Decide what follows `outcome`, updating `state` in place. */
export function nextStep(
  outcome: StreamOutcome,
  state: ReconnectState,
  random: () => number = Math.random,
): ReconnectDecision {
  if (outcome.kind === "aborted") return { action: "stop", reason: "aborted" };
  if (outcome.kind === "status" && (outcome.status === 401 || outcome.status === 404)) {
    return { action: "stop", reason: String(outcome.status) };
  }
  if (outcome.kind === "ended" && outcome.subscribed) {
    state.attempt = 0;
    state.accessRetryUsed = false;
  }
  if (outcome.kind === "ended" && outcome.accessChanged && !state.accessRetryUsed) {
    state.accessRetryUsed = true;
    return { action: "reconnect", delayMs: 0 };
  }
  const delayMs = backoffMs(state.attempt, random);
  state.attempt += 1;
  return { action: "reconnect", delayMs };
}

// ─── Transport (E0-Jobs.9 replaces openFetchStream with lib/sse.ts) ──────────

export type OpenStream = (
  url: string,
  headers: Record<string, string>,
  signal: AbortSignal,
  onFrame: (frame: SseFrame) => void,
) => Promise<{ kind: "status"; status: number } | { kind: "ended" } | { kind: "error" } | { kind: "aborted" }>;

export const openFetchStream: OpenStream = async (url, headers, signal, onFrame) => {
  let resp: Response;
  try {
    resp = await fetch(url, { headers: { Accept: "text/event-stream", ...headers }, signal, cache: "no-store" });
  } catch {
    return signal.aborted ? { kind: "aborted" } : { kind: "error" };
  }
  if (!resp.ok || !resp.body) return { kind: "status", status: resp.status };
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const split = createFrameSplitter();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const frame of split(decoder.decode(value, { stream: true }))) onFrame(frame);
    }
  } catch {
    return signal.aborted ? { kind: "aborted" } : { kind: "error" };
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // already released
    }
  }
  return signal.aborted ? { kind: "aborted" } : { kind: "ended" };
};

// ─── The loop ────────────────────────────────────────────────────────────────

export function streamHeaders(): Record<string, string> | null {
  let token: string | null = null;
  try {
    token = localStorage.getItem("lk_token");
  } catch {
    token = null;
  }
  if (!token) return null;
  return { Authorization: `Bearer ${token}`, ...previewHeaders() };
}

export interface RunOptions {
  campaignId: string;
  queryClient: QueryClient;
  signal: AbortSignal;
  open?: OpenStream;
  headers?: () => Record<string, string> | null;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  random?: () => number;
  /** Called once when the loop stops for good (not on abort). */
  onStop?: (reason: string) => void;
}

const abortableSleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done);
  });

/** Connect, apply frames, reconnect per `nextStep`, until stopped or aborted. */
export async function runCampaignEvents({
  campaignId,
  queryClient,
  signal,
  open = openFetchStream,
  headers = streamHeaders,
  sleep = abortableSleep,
  random = Math.random,
  onStop,
}: RunOptions): Promise<string> {
  const state: ReconnectState = { attempt: 0, accessRetryUsed: false };
  for (;;) {
    if (signal.aborted) return "aborted";
    const hdrs = headers();
    if (!hdrs) {
      onStop?.("no_token");
      return "no_token";
    }
    let subscribed = false;
    let accessChanged = false;
    const result = await open(EVENTS_PATH(campaignId), hdrs, signal, (frame) => {
      const kind = applyFrame(queryClient, campaignId, frame);
      if (kind === "subscribed") {
        subscribed = true;
        state.attempt = 0;
        state.accessRetryUsed = false;
      } else if (kind === "access_changed") {
        accessChanged = true;
      }
    });
    const outcome: StreamOutcome = result.kind === "ended" ? { kind: "ended", accessChanged, subscribed } : result;
    if (outcome.kind === "status" && outcome.status === 404) {
      // No longer a Member: let the screens notice (role and Campaign data).
      void queryClient.invalidateQueries({ queryKey: campaignRoleQueryKey(campaignId) });
      refetchCampaign(queryClient, campaignId);
    }
    const step = nextStep(outcome, state, random);
    if (step.action === "stop") {
      if (step.reason !== "aborted") onStop?.(step.reason);
      return step.reason;
    }
    if (step.delayMs > 0) await sleep(step.delayMs, signal);
  }
}

// ─── React ───────────────────────────────────────────────────────────────────

/**
 * Keep `campaignId`'s queries fresh from the server's event stream while
 * mounted. Reopens when the Campaign or preview changes; does nothing
 * without a Campaign or a token.
 */
export function useCampaignEvents(campaignId: string | null | undefined): void {
  const queryClient = useQueryClient();
  const previewing = useSyncExternalStore(subscribePreview, getPreviewCampaignId, getPreviewCampaignId);
  useEffect(() => {
    if (!campaignId) return;
    const controller = new AbortController();
    void runCampaignEvents({ campaignId, queryClient, signal: controller.signal });
    return () => controller.abort();
  }, [campaignId, queryClient, previewing]);
}

/** Mounted once in the app shell: the current Campaign's event stream. */
export function CampaignEventsSubscriber(): null {
  const { current } = useCurrentCampaign();
  useCampaignEvents(current?.id);
  return null;
}
