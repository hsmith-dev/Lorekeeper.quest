"""app.jobs: background Jobs (AD-2 to AD-5).

Layer (AD-1, .importlinter): between app.api and app.services. It may import
app.services, app.access, app.schemas, app.db, app.core and app.domain;
routes and hooks import it.

E0-Jobs.1 shipped the error codes; E0-Jobs.2 adds the kind registry
(`registry`), `enqueue` + `job_accepted`, the after-commit outbox (`outbox`,
whose session listeners importing this package installs) and the minimal
`run_job` wrapper (`worker`). E0-Jobs.3 makes `worker` the full wrapper
(rights check, LLM config, retries, heartbeat, timeout, progress) plus the
LorekeeperWorker process (`python -m app.jobs.worker`). E0-Jobs.4 adds the
reaper. E0-Jobs.5 adds admission (`admission`: heavy-model resource leases,
the Live Session hold `hold`/`renew`/`release`, the delayed set) and cursor
Jobs plus the data_backfills runner (`backfill`: `run_cursor`, `CursorStep`,
`register_backfill`).
"""
from app.jobs import outbox  # noqa: F401  (installs the session listeners)
from app.jobs.admission import hold, release, renew
from app.jobs.backfill import CursorStep, register_backfill, run_cursor
from app.jobs.enqueue import enqueue, job_accepted
from app.jobs.errors import RETRYABLE_CODES, TERMINAL_CODES, JobErrorCode
from app.jobs.registry import KINDS, JobKind, get_kind, register

__all__ = [
    "CursorStep", "JobErrorCode", "JobKind", "KINDS", "RETRYABLE_CODES", "TERMINAL_CODES", "enqueue", "get_kind",
    "hold", "job_accepted", "register", "register_backfill", "release", "renew", "run_cursor",
]
