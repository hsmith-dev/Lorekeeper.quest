from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import uuid

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.tag import Tag, JournalTag
from app.db.models.tag_category import TagCategory
from app.db.models.journal import JournalEntry
from app.schemas.tag import TagWithCount, TagCategoryRef
from app.api.deps import get_current_user, get_campaign_with_access, accessible_campaign_ids

router = APIRouter()


@router.get("/", response_model=list[TagWithCount])
async def list_tags(
    campaign_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TagWithCount]:
    if campaign_id:
        await get_campaign_with_access(db, campaign_id, user)
        scope = JournalEntry.campaign_id == campaign_id
    else:
        scope = JournalEntry.campaign_id.in_(await accessible_campaign_ids(db, user))

    query = (
        select(Tag, TagCategory, func.count(JournalTag.journal_id).label("entry_count"))
        .join(JournalTag, Tag.id == JournalTag.tag_id)
        .join(JournalEntry, JournalTag.journal_id == JournalEntry.id)
        .outerjoin(TagCategory, Tag.custom_category_id == TagCategory.id)
        .where(scope)
        .group_by(Tag.id, TagCategory.id)
        .order_by(func.count(JournalTag.journal_id).desc())
    )

    result = await db.execute(query)
    rows = result.all()
    return [
        TagWithCount(
            id=tag.id, name=tag.name, tag_type=tag.tag_type,
            custom_category=TagCategoryRef.model_validate(category) if category else None,
            entry_count=count,
        )
        for tag, category, count in rows
    ]
