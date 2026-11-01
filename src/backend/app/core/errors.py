"""Typed LLM errors (AD-8/AD-4) and the one place they map to HTTP.

Every AI path — a route, an SSE stream, a Job — raises one of these instead
of hand-building an HTTPException, so a given failure looks the same to the
client wherever it happened: the handler registered in app/main.py renders
`{"detail": <readable text>, "code": <stable machine code>}` with the class's
status. The one exception is deps.get_user_llm_config, which deliberately
re-raises LLMConfigError as the legacy `{"detail"}` 402 (no `code`) that
existing callers and the frontend rely on. Jobs don't go through HTTP at all; they import RETRYABLE/TERMINAL
below to decide whether a failed attempt is worth another try.

llm_provider.complete_messages/stream_messages still raise HTTPException(503)
for a down backend (AD-8 leaves the provider alone); callers that want the
typed form wrap that as LLMUnavailable themselves.
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class LLMError(Exception):
    """Base of the family. Subclasses set code/status_code; detail is the
    human-readable message shown to the user, headers ride along on the
    response (only LLMConfigError uses them today)."""

    code: str = "llm_error"
    status_code: int = 500

    def __init__(self, detail: str, headers: dict[str, str] | None = None):
        super().__init__(detail)
        self.detail = detail
        self.headers = headers or {}


class LLMConfigError(LLMError):
    """No usable LLM for this user (no personal key, no hosted access, or the
    hosted quota is spent). 402 with X-Gate-Reason so the frontend routes the
    user to Settings instead of /subscribe — same header the old inline
    HTTPException in deps.get_user_llm_config carried."""

    code = "llm_config"
    status_code = 402

    def __init__(self, detail: str, reason: str = "llm-config"):
        super().__init__(detail, headers={"X-Gate-Reason": reason})
        self.reason = reason


class LLMBusy(LLMError):
    """Waited the full gate timeout for a local-LLM slot and didn't get one.
    Transient by nature — a retry later will usually succeed."""

    code = "llm_busy"
    status_code = 503


class LLMUnavailable(LLMError):
    """The backend is down, unreachable, or rejected the model (e.g. Ollama
    with a model it doesn't have). Also transient from a Job's view: the
    operator may bring it back."""

    code = "llm_unavailable"
    status_code = 503


class StructuredOutputError(LLMError):
    """The model's output still failed schema validation after the allowed
    repair turns — "AI output unusable". `errors` keeps the last validation
    errors (a JSON-safe list) for logs and Job records; they are deliberately
    not put in the response body, so validation internals don't leak."""

    code = "ai_output_unusable"
    status_code = 422

    def __init__(self, detail: str, attempts: int = 0, errors: list | None = None):
        super().__init__(detail)
        self.attempts = attempts
        self.errors = list(errors or [])


class PromptBudgetError(LLMError):
    """Required prompt parts don't fit the context window. Never silently
    truncated (see the epic's "no silent truncation" rule) — the call fails."""

    code = "prompt_too_large"
    status_code = 422


# For Jobs: busy/unavailable can clear up by themselves, so retry. A missing
# config, unusable output after repairs, or a prompt that can't fit won't
# change on a retry of the same input, so fail the Job outright.
# PromptBudgetError being terminal is the one additive call here — retrying
# an identical prompt can't make it fit.
RETRYABLE: tuple[type[LLMError], ...] = (LLMBusy, LLMUnavailable)
TERMINAL: tuple[type[LLMError], ...] = (LLMConfigError, StructuredOutputError, PromptBudgetError)


def llm_error_response(exc: LLMError) -> JSONResponse:
    """The single LLMError -> HTTP mapping. Also usable directly by code that
    has to build a response itself (e.g. an SSE route before streaming)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=exc.headers or None,
    )


async def llm_exception_handler(request: Request, exc: LLMError) -> JSONResponse:
    return llm_error_response(exc)
