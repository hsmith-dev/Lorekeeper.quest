// Job API types (E0-Jobs.7 routes, E0-Jobs.9 client). Mirrors
// src/backend/app/schemas/jobs.py and the `job` stream event of
// app/core/pubsub.py.

/** Exactly the server's JobStatus (app/domain/enums.py). */
export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export const JOB_STATUSES: readonly JobStatus[] = ["queued", "running", "done", "failed", "cancelled"];

/**
 * Why a Job failed (JobErrorCode, closed and append-only). Kept open with
 * `string` so a newer server code never breaks the client.
 */
export type JobErrorCode =
  | "llm_config"
  | "ai_output_unusable"
  | "permission_changed"
  | "model_unavailable"
  | "llm_unavailable"
  | "llm_busy"
  | "timeout"
  | "interrupted"
  | "internal"
  | "prompt_too_large"
  | (string & {});

/** `GET /api/jobs/{id}` and each row of `GET /api/jobs/`. */
export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  /** 0..1, or null when not reported. */
  progress: number | null;
  stage: string | null;
  eta_seconds: number | null;
  error_code: JobErrorCode | null;
  error_message: string | null;
  /** Raw for a writable GM; `{kind, id}` of a result a non-GM can see now; else null. */
  result_ref: Record<string, unknown> | null;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Queued Jobs only: how many visible Jobs sit ahead in the same queue. */
  queue_position: number | null;
}

/** `GET /api/jobs/?campaign_id=`: the caller's visible Jobs, newest first. */
export interface JobListResponse {
  jobs: Job[];
}

/** `POST /api/jobs/{id}/retry` (202). */
export interface JobAccepted {
  job_id: string;
}

/** The `job` stream event (`GET /api/jobs/stream`). */
export interface JobEvent {
  job_id: string;
  kind: string;
  status: JobStatus;
  progress: number | null;
  stage: string | null;
  eta_seconds: number | null;
  error_code: JobErrorCode | null;
  error_message: string | null;
  result_ref: Record<string, unknown> | null;
}
