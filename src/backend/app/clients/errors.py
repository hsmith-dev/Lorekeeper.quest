"""Typed errors for sidecar model services (the `ml` and `stt` sidecars).

Kept apart from app/core/errors.py's LLM family: these are internal-service
failures, not user-facing LLM outcomes, and have no global HTTP mapping:
each caller decides how to surface them (the voice upload route maps a 4xx
to 422 and anything else to 503; E0-Platform.6 decides for the ml callers).
Same shape, though: class-level `code`, and a RETRYABLE tuple for Jobs. The
client itself never retries; whoever owns the work decides.
"""


class ModelServiceError(Exception):
    """The sidecar answered, but not with what the contract promises: a 4xx,
    a body that is not the documented shape, the wrong model or dimension,
    or a vector count that does not match the texts sent. Retrying the same
    request will not fix it, so it is terminal."""

    code: str = "model_service_error"

    def __init__(self, detail: str, status_code: int | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class ModelServiceUnavailable(ModelServiceError):
    """The sidecar is down, unreachable, timed out, or answered 5xx. Transient
    from a Job's view (it may still be loading models, or restarting)."""

    code = "model_service_unavailable"


# `except ModelServiceError` catches both; only Unavailable is worth a retry.
RETRYABLE: tuple[type[ModelServiceError], ...] = (ModelServiceUnavailable,)


def is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, RETRYABLE)
