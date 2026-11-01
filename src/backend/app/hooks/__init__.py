"""Hook handlers: how features react to committed changes (AD-17, E0-Journal.1).

    from app.hooks import HookEvent, emit
    emit(db, HookEvent.ENTRY_SAVED, campaign_id=..., refs={...}, actor_ctx=ctx)

The dispatcher is app/core/hooks.py (when and how handlers run). This package
is where the handlers live: one module per feature, `app/hooks/<feature>.py`,
each listed in HANDLERS below with one line, e.g.

    *extraction.HANDLERS,       # E1: [(HookEvent.ENTRY_SAVED, on_entry_saved), ...]

A handler is `async def handler(db, event, payload)`; `payload` is a
HookPayload `{campaign_id, refs, actor_ctx}`. It runs after the commit, in a
fresh session the dispatcher commits when it returns, so it may `enqueue`
(app.jobs.enqueue). A per-user handler builds `access.ctx_for(db, user_id,
campaign_id)` itself. `actor_ctx` is None for worker events (`job_finished`):
build a ctx from the Job's starter and Campaign instead of reading it. A failure is logged `hook_failed` and never reaches the
code that committed.

`visibility_changed` is not emitted here: `set_visibility` already queues it
(app/access/visibility.py), and the listener below hands it to the dispatcher
with `refs` = the changed RecordRefs and `actor_ctx` = the GM's ctx. It is
scheduled as its own task per Campaign, so it is ordered per Campaign only,
not interleaved with the `emit` order of the same commit.

Imported by app/main.py (web) and on first use by app/core/hooks.py
(`load_handlers`, so the worker registers them too).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.access.visibility import register_visibility_listener
from app.core.after_commit import committed_bind
from app.core.hooks import Handler, HookEvent, HookPayload, emit, register_handler, schedule
from app.hooks import world

logger = logging.getLogger(__name__)

# (event, handler) pairs, one line per feature: the shared append point.
HANDLERS: list[tuple[HookEvent, Handler]] = [
    *world.HANDLERS,            # E0-WorldCore.3: canon_changed -> campaign events
]

for _event, _handler in HANDLERS:
    register_handler(_event, _handler)


def _visibility_changed(campaign_id: uuid.UUID, refs: list, actor_ctx: Any) -> None:
    """The `visibility_changed` bridge: called by set_visibility's after-commit
    dispatch, once per Campaign."""
    schedule(committed_bind(), [(HookEvent.VISIBILITY_CHANGED,
                                 HookPayload(campaign_id=campaign_id, refs=list(refs), actor_ctx=actor_ctx))])


register_visibility_listener(_visibility_changed)


__all__ = ["HANDLERS", "HookEvent", "HookPayload", "emit"]
