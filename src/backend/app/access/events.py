"""Campaign events: who receives which invalidation (E0-Access.11, AD-5).

    watch_ctx = ctx                                   # require_campaign("player", preview=False)
    filter_ctx = stream_ctx(request, ctx)             # the member view under the preview header
    gen = campaign_event_stream(filter_ctx, bind=bind)
    return sse_response(gen, ctx=watch_ctx, bind=bind)

`campaign:{campaign_id}:events` carries invalidation keys `{domain, id}`
(app/core/pubsub.py). Publishers do not filter; this module does, per
viewer, at delivery time:

* a writable GM ctx receives every well-formed invalidation;
* a **broadcast** domain (`visibility`, `role`) reaches every viewer, always
  with `id: null` (it says "refetch", never which record);
* a **keyed** event of a registered domain reaches a non-GM only when
  `scoped_select(model, ctx)` finds that id *now* (visible after the change);
* an **unkeyed** event of a registered domain reaches a non-GM unless the
  domain's model can never be visible to them (always-GM);
* anything else (an unknown domain, a malformed message) reaches no
  non-GM, not even its domain name; a non-UUID id reaches nobody.

The payload is rebuilt from `domain` and `id` only: any other key a
publisher adds is dropped. A check that cannot run (DB error) ends the
stream (`EventCheckFailed`) instead of silently dropping the event: the
client reconnects, receives `subscribed` and refetches.

Resync (see app/core/pubsub.py): the stream's first frame is
`event: subscribed`, sent once the subscription is live; the client
refetches on every `subscribed`.

After a `set_visibility` commit this module publishes one unkeyed
`visibility` invalidation per Campaign (a registered visibility listener);
app/access/grants.py publishes `role` after a grant change commits.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.context import CampaignContext, _narrow_for_preview
from app.access.policy import GM
from app.access.registry import AlwaysGM, registration, scoped_select
from app.access.visibility import register_visibility_listener
from app.core import pubsub
from app.db.models.character_sheet import CharacterSheet
from app.db.models.journal import JournalEntry
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.session_plan import SessionPlan
from app.db.models.shorthand import ShorthandTerm
from app.db.models.source import SourceDocument
from app.db.models.entity import Entity, EntityRelationship

logger = logging.getLogger(__name__)

VISIBILITY_DOMAIN = "visibility"
ROLE_DOMAIN = "role"
BROADCAST_DOMAINS: frozenset[str] = frozenset({VISIBILITY_DOMAIN, ROLE_DOMAIN})


class EventCheckFailed(Exception):
    """A visibility check could not run: the stream must end (and resync)."""


@dataclass(frozen=True)
class EventDomain:
    domain: str
    model: type
    where: Any = None  # an SQL predicate narrowing which rows are this domain


_DOMAINS: dict[str, EventDomain] = {}


def register_event_domain(domain: str, model: type, *, where: Any = None) -> EventDomain:
    """Map an invalidation domain to the registered model whose `id` its keys
    name (`where` narrows the rows, e.g. a journal kind). A domain nobody
    registered reaches GMs only. Re-registering the same model is a no-op; a
    different one, or a broadcast domain, raises ValueError."""
    if not isinstance(domain, str) or not domain:
        raise ValueError("register_event_domain: domain must be a non-empty string")
    if domain in BROADCAST_DOMAINS:
        raise ValueError(f"register_event_domain: {domain!r} is a broadcast domain")
    registration(model)  # UnregisteredModel for an unregistered model
    if not hasattr(model, "id"):
        raise ValueError(f"register_event_domain: {model.__name__} has no `id` column")
    existing = _DOMAINS.get(domain)
    if existing is not None:
        if existing.model is model:
            return existing
        raise ValueError(f"register_event_domain: {domain!r} is already {existing.model.__name__}")
    entry = EventDomain(domain, model, where)
    _DOMAINS[domain] = entry
    return entry


def event_domains() -> list[str]:
    return sorted(_DOMAINS)


# ── Contexts ───────────────────────────────────────────────────────────────

def stream_ctx(request: Request, ctx: CampaignContext) -> CampaignContext:
    """The ctx a stream filters with: `ctx` itself, or the read-only member
    view for a GM request carrying `X-Lorekeeper-Preview: member` (only
    narrows). The stream still stands on (is watched with) `ctx`."""
    return _narrow_for_preview(request, ctx)


def _sees_everything(ctx: CampaignContext) -> bool:
    return ctx.role == GM and not ctx.read_only


# ── The filter ─────────────────────────────────────────────────────────────

def _parse(data: Any) -> tuple[str, str | None] | None:
    if not isinstance(data, dict):
        return None
    domain, raw_id = data.get("domain"), data.get("id")
    if not isinstance(domain, str) or not domain:
        return None
    if raw_id is None:
        return domain, None
    if not isinstance(raw_id, str):
        return None
    return domain, raw_id


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        return None


def _never_visible(model: type, ctx: CampaignContext) -> bool:
    """True when no row of `model` can be visible to the (non-GM) ctx."""
    reg = registration(model)
    return isinstance(reg, AlwaysGM) and reg.owner_field is None


def _needs_query(ctx: CampaignContext, data: Any) -> bool:
    """Whether `deliverable` will query: a keyed event of a registered
    domain for a ctx that does not see everything."""
    parsed = _parse(data)
    return (parsed is not None and parsed[1] is not None and parsed[0] in _DOMAINS
            and not _sees_everything(ctx))


async def deliverable(session: AsyncSession | None, ctx: CampaignContext, data: Any) -> dict | None:
    """The `{domain, id}` payload `ctx` may receive for one invalidation's
    `data`, or None (drop it). Raises EventCheckFailed when the visibility
    query fails (or is needed and no session was given)."""
    parsed = _parse(data)
    if parsed is None:
        return None
    domain, raw_id = parsed
    if domain in BROADCAST_DOMAINS:
        return {"domain": domain, "id": None}
    row_id = None
    if raw_id is not None:
        row_id = _uuid(raw_id)
        if row_id is None:
            return None  # not a key of ours: nobody gets it
    if _sees_everything(ctx):
        return {"domain": domain, "id": None if row_id is None else str(row_id)}
    entry = _DOMAINS.get(domain)
    if entry is None:
        return None
    if row_id is None:
        return None if _never_visible(entry.model, ctx) else {"domain": domain, "id": None}
    stmt = scoped_select(entry.model, ctx).where(entry.model.id == row_id)
    if entry.where is not None:
        stmt = stmt.where(entry.where)
    if session is None:
        raise EventCheckFailed(f"{domain}: a keyed event needs a session")
    try:
        found = (await session.execute(sa.select(sa.exists(stmt.with_only_columns(entry.model.id))))).scalar()
    except Exception as exc:
        raise EventCheckFailed(domain) from exc
    return {"domain": domain, "id": str(row_id)} if found else None


async def campaign_event_stream(ctx: CampaignContext, *, bind: Any = None) -> AsyncIterator[tuple[str, Any]]:
    """`(event, data)` for the SSE route: `subscribed` first (once the
    subscription is live), then each `invalidate` that `ctx` may receive.
    Other event names on the channel are dropped. Each check runs in its own
    short session on `bind` (default: the app engine). Ends when the
    listener ends, or when a check fails (logged)."""
    if bind is None:
        from app.db.session import AsyncSessionLocal

        bind = AsyncSessionLocal.kw["bind"]
    listener = pubsub.listen_campaign_events(ctx.campaign_id, announce=True)
    try:
        async for event, data in listener:
            if event == pubsub.SUBSCRIBED_EVENT:
                yield event, {}
                continue
            if event != pubsub.INVALIDATE_EVENT:
                continue
            try:
                if _needs_query(ctx, data):
                    async with AsyncSession(bind=bind, expire_on_commit=False) as session:
                        payload = await deliverable(session, ctx, data)
                else:
                    payload = await deliverable(None, ctx, data)
            except Exception:
                # Fail closed, but never drop silently: end the stream so the
                # client reconnects, gets `subscribed` and refetches.
                logger.warning(json.dumps({"event": "campaign_event_check_failed",
                                           "campaign_id": str(ctx.campaign_id)}), exc_info=True)
                return
            if payload is not None:
                yield pubsub.INVALIDATE_EVENT, payload
    finally:
        await listener.aclose()


# ── Publishing `visibility` after a set_visibility commit ──────────────────

async def _publish_visibility(campaign_id: uuid.UUID, refs: list, actor_ctx: Any) -> None:
    await pubsub.publish_campaign_event(campaign_id, VISIBILITY_DOMAIN, None)


register_visibility_listener(_publish_visibility)


# ── Built-in domains ───────────────────────────────────────────────────────
# The keys E0-Journal (`journal`) and E0-WorldCore (`entities`,
# `relationships`) publish, and the existing list domains. NPCs and Quests
# are always GM (B1-D4): their keys never reach a Player.

register_event_domain("journal", JournalEntry)
register_event_domain("entities", Entity)
register_event_domain("relationships", EntityRelationship)
register_event_domain("character_sheets", CharacterSheet)
register_event_domain("session_plans", SessionPlan)
register_event_domain("sources", SourceDocument)
register_event_domain("shorthand", ShorthandTerm)
register_event_domain("npcs", NpcEntry)
register_event_domain("quests", Quest)


__all__ = [
    "BROADCAST_DOMAINS", "EventCheckFailed", "EventDomain", "ROLE_DOMAIN", "VISIBILITY_DOMAIN",
    "campaign_event_stream", "deliverable", "event_domains", "register_event_domain", "stream_ctx",
]
