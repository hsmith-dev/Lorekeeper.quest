"""Grant changes (E0-Access.10, AD-13): the only grant mutators, the
`access:` publish and `grant_watch`.

    changed = await change_member_role(db, member, CampaignRole.PLAYER)
    await remove_member(db, member)
    await revoke_share_token(db, token)
    await campaign_grants_removed(db, campaign_id)     # before deleting the Campaign
    await db.commit()                                  # then access:{campaign_id}:{grant_id} is published

    reason = await grant_watch(ctx, bind=db.bind)      # returns when the grant changed

A grant is a `campaign_members` row (a Member) or a `campaign_share_tokens`
row (a Share Link). Each change bumps the grant's `access_epoch` when the row
survives (a role change that changes the role, a revocation, the lazy expiry
bump in `share.resolve_share_token`); a removal deletes the row, and a
missing grant counts as changed. Every change queues
`publish_grant_change(campaign_id, grant_id)`, which runs after the root
transaction commits. A rollback (of the root, or of the savepoint the change
was made in) discards it. After the grant publishes, one unkeyed `role`
invalidation per Campaign goes out on `campaign:{campaign_id}:events`
(E0-Access.11). The Owner has no grant row: their channel is
`access:{campaign_id}:owner`, published when the Campaign is deleted.

Only app/access/ publishes on `access:` channels (tests/access/test_grants.py
scans app/ for it). With no Valkey client the publish is a no-op and
`grant_watch` relies on its poll; a Valkey error is logged, never raised.

`grant_watch(*ctxs)` returns as soon as an `access:` message for one of the
ctxs' grants arrives, or a poll (an immediate one, then every GRANT_POLL_S)
finds a grant missing or changed. It polls in its own session, never the
caller's. A poll that cannot run fires the watch (fail closed).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction
from sqlalchemy.util.concurrency import await_only, in_greenlet

from app.access.context import CampaignContext, _resolve
from app.access.policy import ANON
from app.db.models.campaign_member import CampaignMember
from app.db.models.share_token import CampaignShareToken
from app.domain.enums import CampaignRole

logger = logging.getLogger(__name__)

GRANT_POLL_S = 15
PUBLISH_TIMEOUT_S = 2
CHANNEL_PREFIX = "access:"
OWNER_GRANT = "owner"
PENDING_KEY = "lorekeeper.access.grant_changed"

# What grant_watch returns: why it fired.
FIRED_MESSAGE = "message"
FIRED_CHANGED = "changed"
FIRED_POLL_FAILED = "poll_failed"


def grant_channel(campaign_id: uuid.UUID, grant_id: uuid.UUID | None) -> str:
    """`access:{campaign_id}:{grant_id}`; the Owner (no grant row) is `owner`."""
    return f"{CHANNEL_PREFIX}{campaign_id}:{grant_id if grant_id is not None else OWNER_GRANT}"


async def publish_grant_change(campaign_id: uuid.UUID, grant_id: uuid.UUID | None) -> None:
    """Publish on the grant's channel now. Callers queue it (the mutators
    below) so it runs after commit. No Valkey client: a no-op. A Valkey error
    or a publish slower than PUBLISH_TIMEOUT_S is logged, never raised."""
    from app.core.valkey_client import get_valkey

    try:
        client = get_valkey()
    except RuntimeError:
        return
    channel = grant_channel(campaign_id, grant_id)
    try:
        await asyncio.wait_for(client.publish(channel, "changed"), PUBLISH_TIMEOUT_S)
    except Exception:
        logger.warning(json.dumps({"event": "grant_publish_failed", "channel": channel}), exc_info=True)


# ── After-commit queue ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Pending:
    campaign_id: uuid.UUID
    grant_id: uuid.UUID | None
    transaction: SessionTransaction | None


def _queue(db: AsyncSession | Session, campaign_id: uuid.UUID, grant_id: uuid.UUID | None) -> None:
    session = db.sync_session if isinstance(db, AsyncSession) else db
    txn = session.get_nested_transaction() or session.get_transaction()
    session.info.setdefault(PENDING_KEY, []).append(_Pending(campaign_id, grant_id, txn))


def _within(txn: SessionTransaction | None, ancestor: SessionTransaction) -> bool:
    while txn is not None:
        if txn is ancestor:
            return True
        txn = txn.parent
    return False


async def _dispatch(pending: Sequence[_Pending]) -> None:
    seen: set[tuple[uuid.UUID, uuid.UUID | None]] = set()
    campaigns: list[uuid.UUID] = []
    for p in pending:
        key = (p.campaign_id, p.grant_id)
        if key in seen:
            continue
        seen.add(key)
        await publish_grant_change(p.campaign_id, p.grant_id)
        if p.campaign_id not in campaigns:
            campaigns.append(p.campaign_id)
    # E0-Access.11: one unkeyed `role` invalidation per Campaign, so every
    # open screen refetches Roles and Members (no id: it names nobody).
    from app.core.pubsub import publish_campaign_event

    for campaign_id in campaigns:
        try:
            await publish_campaign_event(campaign_id, "role", None)
        except Exception:
            logger.warning(json.dumps({"event": "role_invalidation_failed"}), exc_info=True)


@event.listens_for(Session, "after_soft_rollback")
def _drop_rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    if previous_transaction.parent is None:
        session.info.pop(PENDING_KEY, None)
        return
    pending = session.info.get(PENDING_KEY)
    if pending:
        session.info[PENDING_KEY] = [p for p in pending if not _within(p.transaction, previous_transaction)]


@event.listens_for(Session, "after_transaction_end")
def _clear_on_end(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        session.info.pop(PENDING_KEY, None)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return  # a savepoint release: not durable yet
    pending = session.info.pop(PENDING_KEY, None)
    if not pending:
        return
    if not in_greenlet():
        logger.warning("grant changes committed outside an AsyncSession: the access publish was skipped")
        return
    try:
        await_only(_dispatch(pending))
    except Exception:
        logger.exception("grant change publish after commit failed")


# ── Mutators ───────────────────────────────────────────────────────────────
# The callers authorize (the routes load the row with their ctx); these do
# the write, the epoch bump and the queued publish. None of them commits.

async def change_member_role(db: AsyncSession, member: CampaignMember, role: CampaignRole | str) -> bool:
    """Set the Member's stored Role. A real change bumps `access_epoch` and
    queues the publish; the same Role changes nothing. Returns whether it
    changed. An unknown role is ValueError."""
    new = CampaignRole(role)
    if CampaignRole(member.role) == new:
        return False
    member.role = new
    member.access_epoch = (member.access_epoch or 0) + 1
    await db.flush()
    _queue(db, member.campaign_id, member.id)
    return True


async def remove_member(db: AsyncSession, member: CampaignMember) -> None:
    """Delete the Member's grant (the watch treats a missing grant as
    changed) and queue the publish."""
    campaign_id, grant_id = member.campaign_id, member.id
    await db.delete(member)
    await db.flush()
    _queue(db, campaign_id, grant_id)


async def revoke_share_token(db: AsyncSession, token: CampaignShareToken) -> bool:
    """Revoke the Share Link, bump its `access_epoch` and queue the publish.
    An already revoked link changes nothing. Returns whether it changed."""
    if token.revoked:
        return False
    token.revoked = True
    token.access_epoch = (token.access_epoch or 0) + 1
    await db.flush()
    _queue(db, token.campaign_id, token.id)
    return True


async def campaign_grants_removed(db: AsyncSession, campaign_id: uuid.UUID) -> None:
    """Call before deleting a Campaign: queue the publish for every grant the
    delete cascades away (each Member, each Share Link, and the Owner)."""
    members = (await db.execute(
        sa.select(CampaignMember.id).where(CampaignMember.campaign_id == campaign_id)
    )).scalars().all()
    tokens = (await db.execute(
        sa.select(CampaignShareToken.id).where(CampaignShareToken.campaign_id == campaign_id)
    )).scalars().all()
    for grant_id in [*members, *tokens, None]:
        _queue(db, campaign_id, grant_id)


def _unbumped_expired(token: str) -> list:
    T = CampaignShareToken
    return [T.token == token, T.revoked.is_(False), T.expires_at.is_not(None),
            T.expires_at <= sa.func.now(), T.updated_at <= T.expires_at]


async def bump_expired_share_token(db: AsyncSession, token: str) -> bool:
    """The lazy expiry bump, at most once per token: an expired, non-revoked
    token not yet bumped (`updated_at <= expires_at`) gets `access_epoch + 1`
    and `updated_at` past `expires_at`, and the publish runs after that
    commits. Returns whether it bumped. Called by `share.resolve_share_token`
    when no live token matched.

    A read-only SELECT in the caller's session finds the candidate; only then
    does the conditional UPDATE run and commit in its own session on
    `db.bind`. The caller's session is never written or committed, and any
    error is logged and answered False (the caller still says not_found)."""
    T = CampaignShareToken
    try:
        found = (await db.execute(sa.select(T.id).where(*_unbumped_expired(token)))).first()
        if found is None:
            return False
        async with AsyncSession(bind=db.bind, expire_on_commit=False) as own:
            row = (await own.execute(
                sa.update(T)
                .where(*_unbumped_expired(token))
                # greatest(): the bumped row never matches `updated_at <= expires_at` again.
                .values(access_epoch=T.access_epoch + 1,
                        updated_at=sa.func.greatest(sa.func.now(),
                                                    T.expires_at + sa.text("interval '1 microsecond'")))
                .returning(T.id, T.campaign_id)
                .execution_options(synchronize_session=False)
            )).first()
            if row is None:
                return False  # another request bumped it first
            _queue(own, row.campaign_id, row.id)
            await own.commit()
        return True
    except Exception:
        logger.warning(json.dumps({"event": "share_expiry_bump_failed"}), exc_info=True)
        return False


# ── grant_watch ────────────────────────────────────────────────────────────

def _is_token_ctx(ctx: CampaignContext) -> bool:
    return ctx.role == ANON


def _check_watchable(ctx: CampaignContext) -> None:
    if not isinstance(ctx, CampaignContext):
        raise TypeError(f"grant_watch: expected CampaignContexts, got {ctx!r}")
    if _is_token_ctx(ctx):
        if ctx.grant_id is None:
            raise ValueError("grant_watch: a Share Link ctx needs its grant_id (the token id)")
        return
    if ctx.read_only or ctx.is_system or ctx.user_id is None:
        raise ValueError("grant_watch: needs a user's request ctx or a Share Link ctx")


async def _changed(session: AsyncSession, ctx: CampaignContext) -> bool:
    if _is_token_ctx(ctx):
        token = await session.get(CampaignShareToken, ctx.grant_id, populate_existing=True)
        if token is None or token.revoked or token.campaign_id != ctx.campaign_id:
            return True
        if token.expires_at is not None and token.expires_at <= datetime.now(timezone.utc):
            return True
        return (token.access_epoch or 0) != ctx.access_epoch
    now = await _resolve(session, ctx.user_id, ctx.campaign_id)
    if now is None:
        return True
    return (now.role, now.grant_id, now.access_epoch) != (ctx.role, ctx.grant_id, ctx.access_epoch)


async def _poll(bind: Any, ctxs: Sequence[CampaignContext]) -> str | None:
    try:
        async with AsyncSession(bind=bind, expire_on_commit=False) as session:
            for ctx in ctxs:
                if await _changed(session, ctx):
                    return FIRED_CHANGED
    except Exception:
        logger.warning(json.dumps({"event": "grant_watch_poll_failed"}), exc_info=True)
        return FIRED_POLL_FAILED
    return None


async def grant_changed(*ctxs: CampaignContext, bind: Any = None) -> bool:
    """One check of the ctxs' grants, the same as a `grant_watch` poll: True
    when one is missing or changed, or the check cannot run (fail closed)."""
    if not ctxs:
        raise ValueError("grant_changed: needs at least one ctx")
    for ctx in ctxs:
        _check_watchable(ctx)
    return await _poll(_default_bind(bind), ctxs) is not None


def _default_bind(bind: Any) -> Any:
    if bind is not None:
        return bind
    from app.db.session import AsyncSessionLocal

    return AsyncSessionLocal.kw["bind"]


async def _subscribe(channels: Sequence[str]) -> Any | None:
    from app.core.valkey_client import get_valkey

    try:
        client = get_valkey()
    except RuntimeError:
        return None
    pubsub = None
    try:
        pubsub = client.pubsub()
        await pubsub.subscribe(*channels)
        return pubsub
    except Exception:
        logger.warning(json.dumps({"event": "grant_watch_subscribe_failed"}), exc_info=True)
        await _close(pubsub)
        return None


async def _close(pubsub: Any | None) -> None:
    if pubsub is None:
        return
    try:
        await pubsub.unsubscribe()
    except Exception:
        pass
    try:
        await pubsub.aclose()
    except Exception:
        pass


async def _message_within(pubsub: Any, channels: set[str], seconds: float) -> tuple[bool, Any | None]:
    """Wait up to `seconds` for a message on `channels`. Returns (arrived,
    pubsub), with pubsub None once it failed (the watch then only polls)."""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, pubsub
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=remaining)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(json.dumps({"event": "grant_watch_listen_failed"}), exc_info=True)
            await _close(pubsub)
            await asyncio.sleep(max(0.0, deadline - time.monotonic()))
            return False, None
        if message is None:
            continue
        channel = message.get("channel")
        if isinstance(channel, bytes):
            channel = channel.decode()
        if message.get("type") == "message" and channel in channels:
            return True, pubsub


async def grant_watch(*ctxs: CampaignContext, bind: Any = None) -> str:
    """Return (with the reason: "message", "changed" or "poll_failed") as
    soon as one of the ctxs' grants changes: an `access:` message for it
    arrives, or a poll (an immediate one, then every GRANT_POLL_S) finds it
    missing or changed. A user ctx has changed when `_resolve` finds it
    missing or with another role, grant_id or access_epoch; a Share Link
    ctx (`grant_id` = the token id) when the token is missing, revoked,
    expired or at another epoch. Polls run in their own session on `bind`
    (default: the app engine). Reduced and system ctxs are ValueError."""
    if not ctxs:
        raise ValueError("grant_watch: needs at least one ctx")
    for ctx in ctxs:
        _check_watchable(ctx)
    bind = _default_bind(bind)
    channels = {grant_channel(ctx.campaign_id, ctx.grant_id) for ctx in ctxs}
    pubsub = await _subscribe(sorted(channels))  # before the first poll: no change slips between
    try:
        while True:
            fired = await _poll(bind, ctxs)
            if fired is not None:
                return fired
            if pubsub is None:
                await asyncio.sleep(GRANT_POLL_S)
                continue
            arrived, pubsub = await _message_within(pubsub, channels, GRANT_POLL_S)
            if arrived:
                return FIRED_MESSAGE
    finally:
        await _close(pubsub)
