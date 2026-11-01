"""EV-4 counters and the leak exception.

A leak is an EV4Leak (an AssertionError, so the probe's test fails and the
build with it) and +1 on the session's leak count. Family self-tests plant
leaks on purpose; they run inside ``scoped()`` so those never reach the
session's count.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field


class EV4Leak(AssertionError):
    """A response, header or captured LLM context showed an actor something
    it may not see."""


@dataclass
class Report:
    leaks: int = 0
    details: list[str] = field(default_factory=list)


_current = Report()


def current() -> Report:
    return _current


def leak_count() -> int:
    return _current.leaks


def record_leak(message: str, hits=(), *, count: int = 1) -> None:
    """Count ``count`` leaks and raise EV4Leak listing ``hits``.

    The leak count is canary hits plus family assertion failures: a canary
    check counts each token it found, any other family failure counts one.
    """
    hits = [str(h) for h in hits]
    text = message if not hits else message + "\n" + "\n".join(f"  - {h}" for h in hits)
    _current.leaks += max(1, count)
    _current.details.append(text)
    raise EV4Leak(text)


@contextmanager
def scoped():
    """A fresh Report for the block (self-tests); the session's is restored after."""
    global _current
    saved, _current = _current, Report()
    try:
        yield _current
    finally:
        _current = saved


def summary_line(*, probes: int, exemptions: int, pending: int, leaks: int | None = None) -> str:
    leaks = leak_count() if leaks is None else leaks
    return f"EV-4: probes={probes} exemptions={exemptions} pending={pending} leaks={leaks}"
