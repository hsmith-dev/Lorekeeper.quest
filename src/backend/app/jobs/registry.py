"""The Job kind registry (AD-2, E0-Jobs.2).

Every Job has a registered kind. The kind, not the caller, decides the queue,
so `enqueue` has no `queue` argument. A feature registers its kinds at import
time:

    register(JobKind(name="extraction.run", queue=JobQueue.ONSAVE, timeout_s=300,
                     handler="app.services.extraction:handle", resources=frozenset({"llm"})))

`handler` is "module:attr", resolved when the Job runs (so registering a kind
never imports the feature's code): `async def handle(job, ctx, db)`.
A handler must not call `db.commit()`: the wrapper (app/jobs/worker.py)
commits the handler's writes together with `done`, and rolls them back when
the handler raises.

E0-Jobs.3 adds `gate_class`; it is not here yet.
"""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.domain.enums import JobQueue

# What a kind may hold a lease on (AD-5). `llm` is serialised by E0-LLM's
# slot, the others by resource leases (E0-Jobs.5).
RESOURCES: frozenset[str] = frozenset({"llm", "nli", "ocr", "stt", "tts", "cpu_heavy"})
# Who may see a kind's result: always the GMs, or the Audience of the rows it
# was derived from (derived_sources).
RESULT_AUDIENCES: frozenset[str] = frozenset({"gm", "derived"})

# jobs.kind is String(64).
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_HANDLER_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")

Handler = Callable[[Any, Any, Any], Awaitable[Any]]


@dataclass(frozen=True)
class JobKind:
    name: str
    queue: JobQueue
    timeout_s: int
    handler: str
    resources: frozenset[str] = field(default_factory=frozenset)
    live_safe: bool = False
    result_audience: str = "gm"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or len(self.name) > 64 or not _NAME_RE.match(self.name):
            raise ValueError(f"JobKind: name must be dotted lowercase ('area.action', <= 64 chars), got {self.name!r}")
        try:
            object.__setattr__(self, "queue", JobQueue(self.queue))
        except ValueError:
            raise ValueError(f"JobKind {self.name}: unknown queue {self.queue!r}") from None
        if isinstance(self.timeout_s, bool) or not isinstance(self.timeout_s, int) or self.timeout_s <= 0:
            raise ValueError(f"JobKind {self.name}: timeout_s must be a positive int, got {self.timeout_s!r}")
        if not isinstance(self.handler, str) or not _HANDLER_RE.match(self.handler):
            raise ValueError(f"JobKind {self.name}: handler must be 'module:attr', got {self.handler!r}")
        resources = frozenset(self.resources)
        if not resources <= RESOURCES:
            raise ValueError(f"JobKind {self.name}: unknown resources {sorted(resources - RESOURCES)}")
        object.__setattr__(self, "resources", resources)
        if not isinstance(self.live_safe, bool):
            raise ValueError(f"JobKind {self.name}: live_safe must be a bool")
        if self.result_audience not in RESULT_AUDIENCES:
            raise ValueError(f"JobKind {self.name}: result_audience must be one of {sorted(RESULT_AUDIENCES)}")

    def load_handler(self) -> Handler:
        module, _, attr = self.handler.partition(":")
        return getattr(importlib.import_module(module), attr)


KINDS: dict[str, JobKind] = {}


def register(kind: JobKind) -> JobKind:
    """Add `kind`. Registering the same definition again is a no-op (module
    re-import); a different definition under a taken name is a ValueError."""
    if not isinstance(kind, JobKind):
        raise TypeError("register: expected a JobKind")
    existing = KINDS.get(kind.name)
    if existing is not None and existing != kind:
        raise ValueError(f"register: job kind {kind.name!r} is already registered differently")
    KINDS[kind.name] = kind
    return kind


def get_kind(name: str) -> JobKind:
    """The registered kind, or ValueError."""
    kind = KINDS.get(name) if isinstance(name, str) else None
    if kind is None:
        raise ValueError(f"unknown job kind {name!r}")
    return kind


# Built-in: does nothing. For tests and smoke checks of the whole pipeline.
SYSTEM_NOOP = register(JobKind(
    name="system.noop", queue=JobQueue.INTERACTIVE, timeout_s=30, handler="app.jobs.builtin:noop",
    live_safe=True,
))

__all__ = ["KINDS", "RESOURCES", "RESULT_AUDIENCES", "SYSTEM_NOOP", "JobKind", "get_kind", "register"]
