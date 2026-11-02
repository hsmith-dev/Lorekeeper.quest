"""World hooks (E0-WorldCore.3): `canon_changed` -> the campaign event stream.

`world_service.apply_change` emits `canon_changed {campaign_id, refs: [entity
ids], actor_ctx}`. After the commit, this handler publishes one keyed
`{domain: "entities", id}` invalidation per Entity on
`campaign:{campaign_id}:events` through `core.pubsub.publish_campaign_event`
(E0-Jobs.6). It adds no channel. The event carries ids only: a client
re-reads the Entity through its own ctx, so a Player learns nothing beyond
"something with this id changed". A rolled-back change emits nothing
(the dispatcher drops the event).

Importing this module also imports world_service, which registers the
`entity` and `entity_relationship` Visibility kinds and their writer.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import app.services.world_service as world_service
from app.core.hooks import Handler, HookEvent, HookPayload
from app.core.pubsub import publish_campaign_event

logger = logging.getLogger(__name__)


async def on_canon_changed(db: Any, event: HookEvent, payload: HookPayload) -> None:
    seen: set[str] = set()
    for entity_id in payload.refs or ():
        key = str(entity_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            await publish_campaign_event(payload.campaign_id, world_service.DOMAIN, entity_id)
        except Exception as exc:  # one failed publish never stops the other refs
            # No refs and no message: only the Campaign and the error's class.
            logger.error(json.dumps({"event": "canon_changed_publish_failed", "campaign_id": str(payload.campaign_id),
                                     "error_type": type(exc).__name__}))


HANDLERS: list[tuple[HookEvent, Handler]] = [
    (HookEvent.CANON_CHANGED, on_canon_changed),
]
