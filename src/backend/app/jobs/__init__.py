"""app.jobs: background Jobs (AD-2 to AD-5).

Layer (AD-1, .importlinter): between app.api and app.services. It may import
app.services, app.access, app.schemas, app.db, app.core and app.domain;
routes and hooks import it. E0-Jobs.1 ships the error codes only; `enqueue`,
the kind registry and the worker come in E0-Jobs.2 to E0-Jobs.5.
"""
from app.jobs.errors import RETRYABLE_CODES, TERMINAL_CODES, JobErrorCode

__all__ = ["JobErrorCode", "RETRYABLE_CODES", "TERMINAL_CODES"]
