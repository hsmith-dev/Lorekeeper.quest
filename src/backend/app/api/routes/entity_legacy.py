"""The old-link resolver (E0-WorldCore.6), mounted at /api/entities before
the Entity API.

    GET /legacy/{legacy_type}/{legacy_id}     legacy_type: npc | quest (Party read)

An old NPC or Quest link (`?npc=<id>`, a bookmarked legacy id) names a
legacy row (or, for an Entity made after the upgrade, which the legacy lists
show under its own id, that Entity id); this answers `{"entity_id", "type"}` of the Entity that row
became, as ctx sees it. A merged Entity resolves to its survivor, following
`merged_into_id` (at most MAX_HOPS, never round a cycle) over rows ctx can
read through `scoped_select`, and answers the first live one. Anything
else (an unknown `legacy_type`, a non-UUID, no such legacy id, an Entity ctx
cannot see, deleted, of the other kind, another Campaign's, a merge chain
that ends somewhere ctx cannot see) is the one `404 {"detail":"Not found"}`.
A deleted or merged-away Entity is GM-only (the registry's `gm_when`), so a
non-GM never follows a merge: an absorbed legacy NPC never reveals where it went.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import CampaignContext, entity_ctx_for_request, not_found, scoped_select
from app.api.deps import PARTY_READ, get_current_user
from app.db.models.entity import Entity
from app.db.models.user import User
from app.db.session import get_db
from app.domain import legacy_world as lw
from app.domain.enums import EntityType

router = APIRouter()

MAX_HOPS = 10
_TYPES = {"npc": lw.NPC_TYPES, "quest": lw.QUEST_TYPES}


class LegacyLinkResponse(BaseModel):
    entity_id: uuid.UUID
    type: EntityType


async def _one(db: AsyncSession, ctx: CampaignContext, *where) -> Entity | None:
    return (await db.execute(scoped_select(Entity, ctx).where(*where)
                             .execution_options(populate_existing=True))).scalars().first()


@router.get("/legacy/{legacy_type}/{legacy_id}", response_model=LegacyLinkResponse, openapi_extra=PARTY_READ,
            responses={404: {"description": "Not found (hidden, missing, deleted or the other kind alike)."}})
async def resolve_legacy_link(
    request: Request,
    legacy_type: str,
    legacy_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LegacyLinkResponse:
    if legacy_type not in _TYPES:
        not_found()
    ctx = await entity_ctx_for_request(request, db, user, legacy_id, "player", legacy=legacy_type)
    column = Entity.legacy_npc_id if legacy_type == "npc" else Entity.legacy_quest_id
    wanted = uuid.UUID(str(legacy_id))
    # An Entity id too: the legacy lists show an Entity made after the upgrade under its own id.
    entity = (await _one(db, ctx, Entity.id == wanted)) or (await _one(db, ctx, column == wanted))
    if entity is None or entity.type not in _TYPES[legacy_type]:
        not_found()
    seen: set[uuid.UUID] = set()
    for _ in range(MAX_HOPS + 1):
        if entity.id in seen:
            break
        seen.add(entity.id)
        if entity.merged_into_id is None:
            if entity.deleted_at is not None:
                break
            return LegacyLinkResponse(entity_id=entity.id, type=EntityType(entity.type))
        entity = await _one(db, ctx, Entity.id == entity.merged_into_id)
        if entity is None:
            break
    not_found()
