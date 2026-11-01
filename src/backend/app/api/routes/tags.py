from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
import uuid

from app.access import (
    WITH_COUNT, ctx_for_request, project_all, role_map, scoped_select, scoped_select_multi,
)
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.tag import Tag, JournalTag
from app.schemas.tag import TagWithCountGMResponse
from app.api.deps import get_current_user

router = APIRouter()


@router.get("/", response_model=None, responses={200: {
    "model": list[TagWithCountGMResponse],
    "description": "GM: the GM schema; Player or member preview: the Party schema (hidden categories null).",
}})
async def list_tags(
    request: Request,
    campaign_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tags on the entries the caller may see, each with the number of its
    links the caller may see. A tag found only in GM content (a Shorthand
    tag, a GM-only entry) is absent for a Player, and counts no hidden link."""
    if campaign_id:
        ctx = await ctx_for_request(request, db, user, campaign_id)
        links = scoped_select(JournalTag, ctx)
        scope = ctx
    else:
        roles = await role_map(db, user)
        links = scoped_select_multi(JournalTag, roles)
        scope = roles

    counted = (await db.execute(
        links.with_only_columns(JournalTag.tag_id, func.count(JournalTag.journal_id)).group_by(JournalTag.tag_id)
    )).all()
    counts = {tag_id: n for tag_id, n in counted}
    if not counts:
        return []
    tags = (await db.execute(
        select(Tag).where(Tag.id.in_(counts)).options(selectinload(Tag.custom_category))
    )).scalars().all()
    tags = sorted(tags, key=lambda t: (-counts[t.id], t.name, str(t.id)))
    return await project_all(db, tags, scope, variant=WITH_COUNT, extra=lambda t: {"entry_count": counts[t.id]})
