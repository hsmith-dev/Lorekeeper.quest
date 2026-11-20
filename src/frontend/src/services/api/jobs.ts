// Jobs API client (E0-Jobs.7 routes). Uses the shared axios instance in
// services/api.ts (auth header, preview header, 401/402 handling). The stream
// itself goes through lib/sse.ts (hooks/useJobStream.ts).
import api from "../api";
import type { Job, JobAccepted, JobListResponse, JobStatus } from "../../types/jobs";

// The same base URL as services/api.ts (empty: same origin).
const API_BASE: string = import.meta.env.VITE_API_URL ?? "";

/** `GET /api/jobs/stream?campaign_id=`: the Campaign's Job events (SSE, bearer header). */
export const JOB_STREAM_PATH = (campaignId: string) =>
  `${API_BASE}/api/jobs/stream?campaign_id=${encodeURIComponent(campaignId)}`;

/** The caller's visible Jobs of `campaignId`, newest first: running, queued and the last 24 h (or one status). */
export const listJobs = (campaignId: string, status?: JobStatus) =>
  api.get<JobListResponse>("/api/jobs/", { params: { campaign_id: campaignId, ...(status ? { status } : {}) } });

/** One Job (its Campaign comes from the row). 404 when hidden or missing. */
export const getJob = (jobId: string) => api.get<Job>(`/api/jobs/${encodeURIComponent(jobId)}`);

/** Queue a failed Job again: 202 `{job_id}`; 409 unless failed. */
export const retryJob = (jobId: string) => api.post<JobAccepted>(`/api/jobs/${encodeURIComponent(jobId)}/retry`);

/** Cancel a queued Job: 200 with the cancelled Job; 409 unless queued. */
export const cancelJob = (jobId: string) => api.post<Job>(`/api/jobs/${encodeURIComponent(jobId)}/cancel`);
