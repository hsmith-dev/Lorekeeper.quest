"""The hook dispatcher: features react to committed changes (AD-17, E0-Journal.1).

    emit(db, HookEvent.ENTRY_SAVED, campaign_id=entry.campaign_id,
         refs={"journal_id": entry.id, ...}, actor_ctx=ctx)
    await db.commit()          # handlers are scheduled here, run after it returns

A handler is `async def handler(db, event, payload)`, registered for one event
(`register_handler`, done for every feature by app/hooks/__init__.py):

    async def on_entry_saved(db, event, payload):
        ctx = await ctx_for(db, payload.actor_ctx.user_id, payload.campaign_id)
        await enqueue(db, ctx, "extraction.run", {...}, idempotency_key=...)

`actor_ctx` is None for worker events (`job_finished`): such a handler builds
a ctx itself, e.g. from the Job's starter (`jobs.ctx_user_id`) and Campaign.

* **When.** `emit` defers the event on the session (app/core/after_commit.py).
  Nothing happens unless the root transaction commits; rolling back the root,
  or the savepoint the emit was made in, discards it.
* **Where.** After commit the events are handed to a background task on the
  running event loop (`schedule`): `commit()` never waits for a handler, and
  a hung handler cannot block it. Events run in emit order, each event's
  handlers in registration order. `visibility_changed` comes through the
  set_visibility bridge (app/hooks/__init__.py) as a task of its own per
  Campaign: ordered within that Campaign's refs, not interleaved with the
  `emit`ted events of the same commit.
* **How.** Every handler call gets a fresh session on the committed session's
  engine (never the committed session), and the dispatcher commits it after
  the handler returns, so an `enqueue` goes through the Jobs outbox.
* **Failure.** A handler that raises or runs over HANDLER_TIMEOUT_S has its
  session rolled back and is logged `hook_failed` with the event, the handler
  and the campaign_id (never the refs or the payload); the other handlers
  still run.
* **Delivery** is at most once: a crash between commit and dispatch loses the
  event. Durable work belongs in a Job (the outbox).

A process that owns a short event loop (`asyncio.run` in the worker and the
reaper) must `await drain()` before the loop ends and its engine is disposed.
The web process drains on lifespan shutdown.

`load_handlers()` imports app.hooks (the handler list) the first time an event
is emitted or scheduled, so a process that never imported it still runs its
handlers. app.core may not import app.hooks statically (AD-1 layers).
"""
from __future__ import annotations

import asyncio
import contextvars
import importlib
import json
import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable, Iterable

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.after_commit import defer, register_channel

logger = logging.getLogger(__name__)

CHANNEL = "hooks"
HANDLERS_MODULE = "app.hooks"
HANDLER_TIMEOUT_S: float = 30


class HookEvent(StrEnum):
    ENTRY_SAVED = "entry_saved"
    ENTRY_UPDATED = "entry_updated"
    ENTRY_DELETED = "entry_deleted"
    VISIBILITY_CHANGED = "visibility_changed"
    CANON_CHANGED = "canon_changed"
    ROLE_CHANGED = "role_changed"
    JOB_FINISHED = "job_finished"
    LIVE_SESSION_ENDED = "live_session_ended"


@dataclass(frozen=True)
class HookPayload:
    """What every handler gets. `refs` is the event's own shape (a dict, or a
    list of RecordRef for visibility_changed); `actor_ctx` is the
    CampaignContext that made the change, or None (the worker)."""

    campaign_id: uuid.UUID
    refs: Any
    actor_ctx: Any


Handler = Callable[[AsyncSession, HookEvent, HookPayload], Awaitable[Any]]

_HANDLERS: dict[HookEvent, list[Handler]] = {}
_TASKS: set[asyncio.Task] = set()
_loaded = False


def register_handler(event: HookEvent | str, handler: Handler) -> Handler:
    """Run `handler(db, event, payload)` after every committed `event`.
    Registering the same handler for an event twice is a no-op."""
    event = HookEvent(event)
    handlers = _HANDLERS.setdefault(event, [])
    if handler not in handlers:
        handlers.append(handler)
    return handler


def handlers_for(event: HookEvent | str) -> list[Handler]:
    return list(_HANDLERS.get(HookEvent(event), ()))


def load_handlers() -> None:
    """Import app.hooks once, which registers every feature's handlers."""
    global _loaded
    if not _loaded:
        importlib.import_module(HANDLERS_MODULE)
        _loaded = True


def _uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def emit(db: AsyncSession | Session, event: HookEvent | str, *, campaign_id: uuid.UUID | str, refs: Any,
         actor_ctx: Any) -> None:
    """Queue `event` for dispatch when `db`'s root transaction commits.
    An unknown event (or a campaign_id that is not a UUID) raises ValueError
    here: a programming error, not a runtime one."""
    event = HookEvent(event)  # ValueError for an unknown event
    payload = HookPayload(campaign_id=_uuid(campaign_id), refs=refs, actor_ctx=actor_ctx)
    load_handlers()
    defer(db, CHANNEL, (event, payload))


# ── Dispatch ───────────────────────────────────────────────────────────────

def _session_factory(bind: Engine | Connection | AsyncEngine) -> async_sessionmaker[AsyncSession]:
    if isinstance(bind, Connection):
        bind = bind.engine
    engine = bind if isinstance(bind, AsyncEngine) else AsyncEngine(bind)
    return async_sessionmaker(engine, expire_on_commit=False)


def _name(handler: Any) -> str:
    module = getattr(handler, "__module__", None)
    qualname = getattr(handler, "__qualname__", None) or repr(handler)
    return f"{module}.{qualname}" if module else qualname


def _log_failure(event: HookEvent, handler: Handler, payload: HookPayload, reason: str,
                 error: BaseException | None = None) -> None:
    # Never the refs, the payload or the exception's message or traceback:
    # they can carry GM-only text, bound SQL parameters or refs. Only its class.
    fields = {"event": "hook_failed", "hook_event": event.value, "handler": _name(handler),
              "campaign_id": str(payload.campaign_id), "reason": reason}
    if error is not None:
        fields["error_type"] = type(error).__name__
    logger.error(json.dumps(fields))


async def _call(factory: async_sessionmaker[AsyncSession], event: HookEvent, payload: HookPayload,
                handler: Handler) -> None:
    async with factory() as db:
        timeout = asyncio.timeout(HANDLER_TIMEOUT_S)
        try:
            async with timeout:
                await handler(db, event, payload)
            # Outside the timeout: the commit runs the outbox (an eager Job
            # under JOBS_EAGER), which must not be cancelled half-way.
            await db.commit()
        except Exception as exc:
            timed_out = isinstance(exc, TimeoutError) and timeout.expired()
            _log_failure(event, handler, payload, "timeout" if timed_out else "error", exc)
            try:
                await db.rollback()
            except Exception as rollback_exc:
                logger.warning("hook session rollback failed: %s", type(rollback_exc).__name__)


async def _run(factory: async_sessionmaker[AsyncSession],
               work: list[tuple[HookEvent, HookPayload, tuple[Handler, ...]]]) -> None:
    for event, payload, handlers in work:
        for handler in handlers:
            await _call(factory, event, payload, handler)


def schedule(bind: Any, events: Iterable[tuple[HookEvent | str, HookPayload]]) -> asyncio.Task | None:
    """Run the handlers of `events` (in order) in a background task on the
    running loop, each in a fresh session on `bind`'s engine. The handlers
    are those registered now. Returns the task, or None when no event has a
    handler (or there is no loop or bind to run them on, logged)."""
    load_handlers()
    work = []
    for event, payload in events:
        event = HookEvent(event)
        handlers = tuple(handlers_for(event))
        if handlers:
            work.append((event, payload, handlers))
    if not work:
        return None
    if bind is None:
        logger.warning("hook events dropped: no database bind to run their handlers on",
                       extra={"events": [e.value for e, _p, _h in work]})
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("hook events dropped: no running event loop",
                       extra={"events": [e.value for e, _p, _h in work]})
        return None
    # A fresh context: handlers inherit nothing from the committing code
    # (a running Job's log fields, the committed bind).
    task = loop.create_task(_run(_session_factory(bind), work), context=contextvars.Context())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


async def drain(timeout: float | None = None) -> None:
    """Wait for every hook task on this loop, including those that the
    handlers' own commits schedule. With `timeout`, give up after that many
    seconds (logged; the tasks keep running)."""
    loop = asyncio.get_running_loop()

    async def wait_all() -> None:
        while True:
            pending = [t for t in _TASKS if not t.done() and t.get_loop() is loop]
            if not pending:
                return
            # asyncio.wait, not gather: a drain timeout must not cancel them.
            await asyncio.wait(pending)

    if timeout is None:
        await wait_all()
        return
    try:
        async with asyncio.timeout(timeout):
            await wait_all()
    except TimeoutError:
        logger.warning("hook drain timed out; handlers still running were left")


async def _on_commit(session: Session, items: list[tuple[HookEvent, HookPayload]]) -> None:
    schedule(session.get_bind(), items)


register_channel(CHANNEL, _on_commit)


__all__ = ["HANDLER_TIMEOUT_S", "HookEvent", "HookPayload", "drain", "emit", "handlers_for", "load_handlers",
           "register_handler", "schedule"]
