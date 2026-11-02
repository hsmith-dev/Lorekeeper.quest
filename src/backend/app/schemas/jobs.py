"""Job API schemas (E0-Jobs.7, AD-5).

`JobResponse` is what `GET /api/jobs/{id}` and each row of `GET /api/jobs/`
return, built only by `app.access.job_response` (which decides `result_ref`
and `queue_position` for the ctx). `JobStatsResponse` is the admin System
tab's counts (`GET /api/admin/jobs/stats`).
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.domain.enums import JobStatus


class JobResponse(BaseModel):
    """One Job as the ctx may see it. `result_ref` is the raw value for a
    writable GM, else `{"kind", "id"}` of a result the ctx can see now, else
    null. `queue_position` is set for queued Jobs only: how many Jobs the ctx
    can see sit ahead in the same queue (a lower bound: hidden Jobs are never
    counted)."""

    id: uuid.UUID
    kind: str
    status: JobStatus
    progress: float | None = None
    stage: str | None = None
    eta_seconds: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    result_ref: dict[str, Any] | None = None
    attempts: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queue_position: int | None = None


class JobListResponse(BaseModel):
    """The ctx's visible Jobs, newest first."""

    jobs: list[JobResponse]


class JobStatsResponse(BaseModel):
    """Job counts across every Campaign, for operators. `by_status` and each
    `by_queue[queue]` have every status (zero when none)."""

    total: int
    by_status: dict[str, int]
    by_queue: dict[str, dict[str, int]]


__all__ = ["JobListResponse", "JobResponse", "JobStatsResponse"]
