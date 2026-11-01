"""Job error codes (AD-4).

`JobErrorCode` is the closed, append-only StrEnum stored in jobs.error_code.
It is defined in app/domain/enums.py, because the Job model imports it and
app.domain is the only layer below app.db (AD-1); Job code imports it from
here.

A Job that fails with a code in TERMINAL_CODES fails at once (no retry): the
terminal LLM errors (app.core.errors.TERMINAL: a missing config, unusable
output after repairs, a prompt that cannot fit) and `permission_changed`
(the starter lost the rights the Job needs). Every other code is in
RETRYABLE_CODES: the Job is retried while attempts < max_attempts, then
shown as failed with that code.
"""
from __future__ import annotations

from app.core import errors as llm_errors
from app.domain.enums import JobErrorCode

# JobErrorCode(...) raises ValueError at import if a terminal LLM error's code is not a member.
TERMINAL_CODES: frozenset[JobErrorCode] = frozenset(
    {JobErrorCode(cls.code) for cls in llm_errors.TERMINAL} | {JobErrorCode.PERMISSION_CHANGED}
)
RETRYABLE_CODES: frozenset[JobErrorCode] = frozenset(JobErrorCode) - TERMINAL_CODES

__all__ = ["JobErrorCode", "RETRYABLE_CODES", "TERMINAL_CODES"]
