"""Resident-memory budget for the lazy models (NLI, OCR).

Each lazy model declares a cost in MB (ML_NLI_COST_MB, ML_OCR_COST_MB). A
model counts against ML_RESIDENT_BUDGET_MB from the moment its load is
reserved until it is evicted (or its load fails). When a load would go over
the budget, the least-recently-used *idle* lazy models are evicted if that
frees enough room; otherwise the request gets BudgetExceeded (503
ml_budget) and nothing is evicted.

The budget counts declared costs, not measured RSS deltas: RSS moves with
whatever else is in flight (NER activations, allocator caching), so a
measured delta would make the 503 decision noisy. /v1/status reports RSS so
the declared costs can be tuned.

Locking: the budget lock, then a slot lock, never the reverse. `in_use`
changes only under the budget lock, so a slot seen with in_use == 0 while
the budget lock is held cannot start serving until that lock is released;
that is what keeps eviction off a model that is serving a request.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc
import threading
import time
from typing import Callable

from ml_service.models import ModelSlot


class BudgetExceeded(Exception):
    """Loading this model would exceed the resident budget even after
    evicting every idle lazy model (or its cost alone exceeds the budget)."""

    def __init__(self, name: str, cost_mb: int, budget_mb: int, resident_mb: int):
        super().__init__(
            f"loading {name} ({cost_mb} MB) would exceed the {budget_mb} MB budget "
            f"({resident_mb} MB of lazy models resident)"
        )
        self.name = name
        self.cost_mb = cost_mb
        self.budget_mb = budget_mb
        self.resident_mb = resident_mb


class ModelLoadFailed(Exception):
    """A lazy model's loader raised (500). The slot is `failed` and its
    reservation is released once no request is waiting on it."""

    def __init__(self, name: str, error: str):
        super().__init__(f"{name} failed to load: {error}")
        self.name = name
        self.error = error


def release_memory() -> None:
    """Return freed model memory to the OS where possible: gc.collect(), then
    glibc's malloc_trim(0). A no-op for the trim off glibc (macOS, musl)."""
    gc.collect()
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        trim = libc.malloc_trim
    except (OSError, AttributeError):
        return
    trim.argtypes = [ctypes.c_size_t]
    trim(0)


class ResidentBudget:
    def __init__(self, budget_mb: int, on_evict: Callable[[], None] = release_memory):
        self.budget_mb = budget_mb
        self.lock = threading.Lock()
        self._slots: list[LazySlot] = []
        self._on_evict = on_evict
        self.evictions = 0

    def register(self, slot: "LazySlot") -> None:
        with self.lock:
            self._slots.append(slot)

    @property
    def resident_mb(self) -> int:
        """Declared MB of lazy models that are loaded or loading."""
        return sum(s.cost_mb for s in self._slots if s.reserved)

    def acquire(self, slot: "LazySlot") -> None:
        """Mark `slot` in use, reserving its cost first if it is not resident.
        Raises BudgetExceeded with nothing evicted when the room cannot be made."""
        evicted: list[LazySlot] = []
        with self.lock:
            if not slot.reserved:
                resident = self.resident_mb
                if slot.cost_mb > self.budget_mb:
                    raise BudgetExceeded(slot.name, slot.cost_mb, self.budget_mb, resident)
                shortfall = resident + slot.cost_mb - self.budget_mb
                if shortfall > 0:
                    idle = sorted(
                        (s for s in self._slots if s is not slot and s.reserved and s.in_use == 0),
                        key=lambda s: s.last_used,
                    )
                    freed = 0
                    for s in idle:
                        if freed >= shortfall:
                            break
                        evicted.append(s)
                        freed += s.cost_mb
                    if freed < shortfall:
                        raise BudgetExceeded(slot.name, slot.cost_mb, self.budget_mb, resident)
                    for s in evicted:
                        s.evict()  # budget lock -> slot lock; s.in_use == 0, so the slot lock is free
                    self.evictions += len(evicted)
                slot.reserved = True
            slot.in_use += 1
            slot.last_used = time.monotonic()
        if evicted:
            self._on_evict()  # outside the budget lock: gc can take a while

    def release(self, slot: "LazySlot") -> None:
        with self.lock:
            slot.in_use -= 1
            slot.last_used = time.monotonic()
            if slot.in_use == 0 and not slot.is_loaded:
                # The load failed and nobody else is waiting to retry it.
                slot.reserved = False


class LazySlot(ModelSlot):
    """A model that loads on its first request and counts against the budget."""

    lazy = True

    def __init__(self, name: str, kind: str, loader: Callable[[], object],
                 cost_mb: int, budget: ResidentBudget):
        super().__init__(name, kind, loader)
        self.cost_mb = cost_mb
        self._budget = budget
        self.in_use = 0          # requests holding this slot; changes only under the budget lock
        self.reserved = False    # counted in the budget (loading or loaded)
        self.last_used = 0.0
        budget.register(self)

    def run(self, fn: Callable[[object], object]) -> object:
        self._budget.acquire(self)
        try:
            with self.lock:
                try:
                    model = self._ensure_loaded()
                except Exception as exc:
                    raise ModelLoadFailed(self.name, self.error or repr(exc)) from exc
                return fn(model)
        finally:
            self._budget.release(self)

    def evict(self) -> None:
        """Called by the budget, under its lock, only when in_use == 0."""
        self.unload()
        self.reserved = False
