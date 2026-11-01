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

`gate_class` (E0-Jobs.3) is the LLM gate class the kind's model calls queue
in (app/core/llm_gate.py); None means the queue's class (`class_for_queue`).

The worker imports every module in KIND_MODULES at start (`load_kind_modules`),
so a kind registered at import time is known before the first Job runs. A
module that calls `register` belongs in that tuple; tests/jobs/test_worker.py
fails when one is missing. The same goes for `register_backfill`
(app/jobs/backfill.py): the data_backfills runner in the worker only runs
backfills whose module was imported.

`resources` (E0-Jobs.5) drives admission (app/jobs/admission.py): nli, stt,
tts, ocr and cpu_heavy are leased one Job at a time; llm, nli, tts and
cpu_heavy pause for a Live Session unless the kind is `live_safe`.
"""
from __future__ import annotations

import importlib
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.core.llm_gate import GateClass
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
    gate_class: GateClass | None = None

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
        if self.gate_class is not None:
            try:
                object.__setattr__(self, "gate_class", GateClass(self.gate_class))
            except ValueError:
                raise ValueError(f"JobKind {self.name}: unknown gate_class {self.gate_class!r}") from None

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


# Modules that register kinds (and backfills) at import time, imported by the
# worker at start (LorekeeperWorker). This module's own built-ins need no entry.
KIND_MODULES: tuple[str, ...] = ()


def load_kind_modules() -> None:
    """Import every module in KIND_MODULES (registering their kinds)."""
    for module in KIND_MODULES:
        importlib.import_module(module)


# Built-in: does nothing. For tests and smoke checks of the whole pipeline.
SYSTEM_NOOP = register(JobKind(
    name="system.noop", queue=JobQueue.INTERACTIVE, timeout_s=30, handler="app.jobs.builtin:noop",
    live_safe=True,
))

# Built-in (E0-Jobs.8): the daily sweep of the files_data volume, one cursor
# Job per Campaign (app/jobs/files_gc.py; scheduled by the reaper). Disk and
# rows only, no model: live_safe, no resource leases.
FILES_GC = register(JobKind(
    name="files.gc", queue=JobQueue.BACKFILL, timeout_s=600, handler="app.jobs.files_gc:handle",
    live_safe=True,
))

__all__ = [
    "FILES_GC", "KINDS", "KIND_MODULES", "RESOURCES", "RESULT_AUDIENCES", "SYSTEM_NOOP", "JobKind", "get_kind",
    "load_kind_modules", "register",
]
