"""Journal hooks (E0-Journal.2): the journal writers' events -> the campaign
event stream, and the `journal.reembed` fallback.

`journal_service.create_journal_entry` / `update_journal_entry` emit
`entry_saved` / `entry_updated` with refs `{journal_id, kind,
previous_entry_hash, entry_hash, changed_fields}`; `delete_journal_entry`
emits `entry_deleted {journal_id, kind}`. After the commit:

  * saved / updated publish one keyed `{domain: "journal", id}` invalidation
    on `campaign:{campaign_id}:events` (a client re-reads the entry through
    its own ctx); deleted publishes the unkeyed `{domain: "journal", id:
    null}`, so a deleted id is never sent;
  * saved / updated enqueue a `journal.reembed` Job (key
    `journal.reembed:{journal_id}:{entry_hash}`) when the entry still has that
    hash and a NULL vector: the save fell back because `ml` was down. The Job
    runs as the actor (their ctx now).

Hooks are at most once: a crash between the commit and this handler loses
the Job, and the entry keeps NULL vectors until the next `/reindex`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.access import NotFound, ctx_for
from app.core.hooks import Handler, HookEvent, HookPayload
from app.core.pubsub import publish_campaign_event
from app.jobs.enqueue import enqueue
from app.services import journal_service

logger = logging.getLogger(__name__)

DOMAIN = "journal"


async def _publish(payload: HookPayload, journal_id: Any) -> None:
    try:
        await publish_campaign_event(payload.campaign_id, DOMAIN, journal_id)
    except Exception as exc:  # a failed publish never stops the reembed check
        # No refs and no message: only the Campaign and the error's class.
        logger.error(json.dumps({"event": "journal_publish_failed", "campaign_id": str(payload.campaign_id),
                                 "error_type": type(exc).__name__}))


async def on_entry_written(db: Any, event: HookEvent, payload: HookPayload) -> None:
    refs = payload.refs or {}
    journal_id = refs.get("journal_id")
    if journal_id is None:
        return
    await _publish(payload, journal_id)
    actor = payload.actor_ctx
    entry_hash = refs.get("entry_hash")
    if actor is None or getattr(actor, "user_id", None) is None or not entry_hash:
        return
    try:
        ctx = await ctx_for(db, actor.user_id, payload.campaign_id)
    except NotFound:
        return  # the actor lost access since the save
    if await journal_service.needs_reembed(db, ctx, journal_id, entry_hash):
        await enqueue(db, ctx, journal_service.REEMBED_KIND,
                      {"journal_id": str(journal_id), "entry_hash": entry_hash},
                      idempotency_key=journal_service.reembed_key(journal_id, entry_hash))


async def on_entry_deleted(db: Any, event: HookEvent, payload: HookPayload) -> None:
    await _publish(payload, None)


HANDLERS: list[tuple[HookEvent, Handler]] = [
    (HookEvent.ENTRY_SAVED, on_entry_written),
    (HookEvent.ENTRY_UPDATED, on_entry_written),
    (HookEvent.ENTRY_DELETED, on_entry_deleted),
]
