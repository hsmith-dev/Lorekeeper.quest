"""Built-in Job handlers (app/jobs/registry.py registers them)."""
from __future__ import annotations

from typing import Any


async def noop(job: Any, ctx: Any, db: Any) -> None:
    """`system.noop`: does nothing, so the Job ends `done`."""
    return None
