"""Work that runs only once a session's root transaction commits (AD-17).

    register_channel("visibility_changed", on_commit)    # once, at import
    defer(db, "visibility_changed", item)                 # inside a transaction
    await db.commit()                                     # on_commit(session, [item, ...])

The shared copy of the "collect in `session.info`, drop on rollback, act
after commit" plumbing, used by `set_visibility` (app/access/visibility.py) and
the hook dispatcher (app/core/hooks.py). Two modules keep their own copies:
the Jobs outbox (app/jobs/outbox.py, flush-tracked semantics) and the grant
changes in app/access/grants.py (E0-Access.10-owned).

* `defer` tags each item with the innermost open transaction. Rolling back a
  savepoint drops the items deferred inside it; rolling back (or closing) the
  root transaction drops everything.
* After the root transaction commits, each channel with items gets one call,
  `await callback(session, items)` (items in defer order), channels in
  registration order. The callbacks run inside `commit()`, before it returns,
  once every other `after_commit` listener has run. A callback must not use
  `session` for queries (its transaction is over): open a new session on
  `session.get_bind()` (or `committed_bind()`), or schedule work.
* A callback's error is logged, never raised: the change has committed.
* `committed_bind()` is the committed session's bind while the callbacks run
  (None otherwise), for code a callback calls that has no session in hand
  (a visibility listener scheduling hooks).

The listeners are on the sync `Session` class, so they apply to every
AsyncSession. The callbacks are awaited through `await_only`, inside the
AsyncSession's greenlet; a plain sync Session commit skips them (logged).
"""
from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy import event
from sqlalchemy.orm import Session, SessionTransaction
from sqlalchemy.util.concurrency import await_only, in_greenlet

logger = logging.getLogger(__name__)

PENDING_KEY = "lorekeeper.after_commit.pending"
COMMITTED_KEY = "lorekeeper.after_commit.committed"

Callback = Callable[[Session, list], Awaitable[Any]]

_CHANNELS: dict[str, Callback] = {}
_bind: contextvars.ContextVar[Any] = contextvars.ContextVar("lorekeeper_committed_bind", default=None)


@dataclass(frozen=True)
class _Deferred:
    channel: str
    item: Any
    transaction: SessionTransaction | None


def register_channel(name: str, callback: Callback) -> Callback:
    """Call `await callback(session, items)` after each root commit that
    deferred items on `name`. Channels run in registration order.
    Registering the same callback again is a no-op; a different one for a
    name that has one raises ValueError."""
    if not isinstance(name, str) or not name:
        raise ValueError("register_channel: name must be a non-empty string")
    existing = _CHANNELS.get(name)
    if existing is not None and existing is not callback:
        raise ValueError(f"register_channel: {name!r} already has a callback")
    _CHANNELS[name] = callback
    return callback


def _sync(session: Any) -> Session:
    return getattr(session, "sync_session", session)


def defer(session: Any, channel: str, item: Any) -> None:
    """Hand `item` to `channel`'s callback when `session` (an AsyncSession
    or its sync Session) commits its root transaction. Dropped if the
    transaction it was deferred in (a savepoint, or the root) rolls back.
    An unregistered channel raises ValueError."""
    if channel not in _CHANNELS:
        raise ValueError(f"defer: unknown channel {channel!r}")
    sync = _sync(session)
    if not sync.in_transaction():
        # Begin now (no IO): the item belongs to a transaction, so a close()
        # without commit discards it instead of leaving it for the next one.
        sync.begin()
    txn = sync.get_nested_transaction() or sync.get_transaction()
    sync.info.setdefault(PENDING_KEY, []).append(_Deferred(channel, item, txn))


def committed_bind() -> Any:
    """The bind of the session whose after-commit callbacks are running now,
    else None."""
    return _bind.get()


# ── Session listeners ──────────────────────────────────────────────────────

def _within(txn: SessionTransaction | None, ancestor: SessionTransaction) -> bool:
    while txn is not None:
        if txn is ancestor:
            return True
        txn = txn.parent
    return False


@event.listens_for(Session, "after_soft_rollback")
def _drop_rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    if previous_transaction.parent is None:
        session.info.pop(PENDING_KEY, None)
        return
    pending = session.info.get(PENDING_KEY)
    if pending:
        session.info[PENDING_KEY] = [d for d in pending if not _within(d.transaction, previous_transaction)]


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return  # a savepoint release: not durable yet
    pending = session.info.pop(PENDING_KEY, None)
    if pending:
        # Run at the end of the transaction (_after_transaction_end), once
        # every other after_commit listener (the Jobs outbox) is done.
        session.info[COMMITTED_KEY] = pending


async def _run(session: Session, bind: Any, pending: list[_Deferred]) -> None:
    # Set here, in the coroutine: await_only runs it in the caller's context.
    token = _bind.set(bind)
    try:
        for name, callback in list(_CHANNELS.items()):
            items = [d.item for d in pending if d.channel == name]
            if not items:
                continue
            try:
                await callback(session, items)
            except Exception:
                logger.exception("after-commit callback failed", extra={"channel": name})
    finally:
        _bind.reset(token)


@event.listens_for(Session, "after_transaction_end")
def _after_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is not None:
        return
    # A root transaction that ended without committing leaves nothing behind.
    session.info.pop(PENDING_KEY, None)
    committed = session.info.pop(COMMITTED_KEY, None)
    if not committed:
        return
    if not in_greenlet():
        logger.warning("changes committed outside an AsyncSession: after-commit work was skipped",
                       extra={"channels": sorted({d.channel for d in committed})})
        return
    try:
        bind = session.get_bind()
    except Exception:
        bind = None
    try:
        await_only(_run(session, bind, committed))
    except Exception:
        logger.exception("after-commit dispatch failed")


__all__ = ["committed_bind", "defer", "register_channel"]
