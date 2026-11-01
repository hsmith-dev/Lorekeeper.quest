"""`jobs` and `data_backfills` (F2-jobs-files, E0-Jobs.1; AD-2, AD-4).

The `jobs` row is the authority for a Job; RQ only carries its id. Nothing
here enqueues or runs anything: `enqueue` (app/jobs/enqueue.py) creates rows
and the worker wrapper (app/jobs/worker.py) runs them.

`kind`, `ctx_kind` and `ctx_audience` are open sets with no CHECK: the kind
registry (E0-Jobs.2) and the ctx rebuild (E0-Jobs.3) own their vocabularies.
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import REAL, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import JobErrorCode, JobQueue, JobStatus, check_expr

# The statuses a Job holds its idempotency key in (AD-4): a key is unique
# among unfinished Jobs only, so a `done` Job's key can be used again.
ACTIVE_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)
_ACTIVE_WHERE = text("status IN (" + ", ".join(f"'{s.value}'" for s in ACTIVE_STATUSES) + ")")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(check_expr(JobStatus, "status"), name="ck_jobs_status"),
        CheckConstraint(check_expr(JobQueue, "queue"), name="ck_jobs_queue"),
        CheckConstraint(check_expr(JobErrorCode, "error_code"), name="ck_jobs_error_code"),
        Index("uq_jobs_idempotency_key_active", "idempotency_key", unique=True, postgresql_where=_ACTIVE_WHERE),
        Index("ix_jobs_campaign_status_created", "campaign_id", "status", "created_at"),
        Index("ix_jobs_status_queue_created", "status", "queue", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    queue: Mapped[JobQueue] = mapped_column(String(16), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        String(16), nullable=False, default=JobStatus.QUEUED, server_default=JobStatus.QUEUED.value)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    # The starter's ctx, rebuilt against current membership when the Job runs (AD-13).
    ctx_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ctx_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    ctx_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    progress: Mapped[float | None] = mapped_column(REAL, nullable=True)
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[JobErrorCode | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    depends_on_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The owner read rule (app/access/registry.py): a Player sees the Jobs they started.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Not mapped: the status the dependency (depends_on_job_id) finished with,
    # set by the worker wrapper (app/jobs/worker.py) before the handler runs.
    # None for a Job without a dependency.
    dependency_status = None
    # Not mapped (E0-Jobs.3), set by the worker wrapper before the handler
    # runs: the starter's User, and for kinds with `llm` in their resources
    # the LLMConfig resolved for that User (meter with
    # llm_config_service.meter(db, job.starter, job.llm_config, ...)).
    starter = None
    llm_config = None
    # Not mapped: the wrapper's progress writer (see `report`).
    _reporter = None
    # Not mapped (E0-Jobs.5): set by app.jobs.backfill.run_cursor when a
    # cursor step succeeded and more remain. The wrapper then puts the row
    # back in `queued` (with the step's writes) and pushes it again, instead
    # of `done`.
    _continue = False

    async def report(self, progress: float, stage: str | None = None, eta_seconds: int | None = None) -> None:
        """Write progress (0..1), stage and ETA to this Job's row at once, in
        a short transaction of its own, so readers see it while the Job runs.
        Only inside a running Job (the wrapper injects the writer)."""
        if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not 0 <= progress <= 1:
            raise ValueError(f"Job.report: progress must be a number in [0, 1], got {progress!r}")
        if stage is not None and not isinstance(stage, str):
            raise ValueError(f"Job.report: stage must be a str or None, got {stage!r}")
        if eta_seconds is not None and (isinstance(eta_seconds, bool) or not isinstance(eta_seconds, int)
                                        or eta_seconds < 0):
            raise ValueError(f"Job.report: eta_seconds must be a non-negative int or None, got {eta_seconds!r}")
        if self._reporter is None:
            raise RuntimeError("Job.report: only a running Job can report progress")
        await self._reporter(float(progress), stage, eta_seconds)


class DataBackfill(Base):
    """One per-row backfill (AD-18), run as a cursor Job (E0-Jobs.5). Global:
    no campaign_id; the name is the key."""

    __tablename__ = "data_backfills"
    __table_args__ = (
        CheckConstraint(check_expr(JobStatus, "status"), name="ck_data_backfills_status"),
    )

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[JobStatus] = mapped_column(
        String(16), nullable=False, default=JobStatus.QUEUED, server_default=JobStatus.QUEUED.value)
    cursor: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
