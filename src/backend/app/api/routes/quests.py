import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.quest import Quest
from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.schemas.quest import QuestCreate, QuestUpdate, QuestResponse, QuestSuggestResponse
from app.schemas.journal import JournalLiteResponse
from app.api.deps import get_current_user, get_user_llm_config, get_campaign_with_access
from app.services.chat_service import suggest_quests, generate_quest_description
from app.services.llm_provider import LLMConfig, is_hosted_default
from app.services import billing_service

router = APIRouter()


async def _get_accessible_quest(db: AsyncSession, quest_id: uuid.UUID, user: User) -> Quest:
    """Fetch a quest and verify the requester has access to its campaign (owner
    or member) — like NPCs, quests are shared campaign knowledge, so any member
    may read/edit/delete them."""
    quest = await db.get(Quest, quest_id)
    if not quest:
        raise HTTPException(status_code=404, detail="Quest not found")
    await get_campaign_with_access(db, quest.campaign_id, user)
    return quest


@router.get("/", response_model=list[QuestResponse])
async def list_quests(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[QuestResponse]:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(Quest)
        .where(Quest.campaign_id == campaign_id)
        .order_by(Quest.status, Quest.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/", response_model=QuestResponse, status_code=201)
async def create_quest(
    body: QuestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuestResponse:
    await get_campaign_with_access(db, body.campaign_id, user)
    quest = Quest(user_id=user.id, **body.model_dump())
    db.add(quest)
    await db.commit()
    await db.refresh(quest)
    return quest


@router.put("/{quest_id}", response_model=QuestResponse)
async def update_quest(
    quest_id: uuid.UUID,
    body: QuestUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuestResponse:
    quest = await _get_accessible_quest(db, quest_id, user)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(quest, field, value)
    await db.commit()
    await db.refresh(quest)
    return quest


@router.delete("/{quest_id}", status_code=204)
async def delete_quest(
    quest_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    quest = await _get_accessible_quest(db, quest_id, user)
    await db.delete(quest)
    await db.commit()


@router.get("/{quest_id}", response_model=QuestResponse)
async def get_quest(
    quest_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuestResponse:
    return await _get_accessible_quest(db, quest_id, user)


@router.get("/{quest_id}/entries", response_model=list[JournalLiteResponse])
async def get_quest_entries(
    quest_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[JournalLiteResponse]:
    quest = await _get_accessible_quest(db, quest_id, user)
    entries_result = await db.execute(
        select(JournalEntry)
        .where(
            JournalEntry.campaign_id == quest.campaign_id,
            or_(
                JournalEntry.shorthand.ilike(f"%{quest.title}%"),
                JournalEntry.narrative.ilike(f"%{quest.title}%"),
            ),
        )
        .order_by(JournalEntry.created_at.desc())
        .limit(20)
    )
    return list(entries_result.scalars().all())


@router.post("/{quest_id}/generate")
async def generate_quest_description_route(
    quest_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> dict:
    quest = await _get_accessible_quest(db, quest_id, user)
    campaign = await db.get(Campaign, quest.campaign_id)
    entries_result = await db.execute(
        select(JournalEntry)
        .where(
            JournalEntry.campaign_id == quest.campaign_id,
            or_(
                JournalEntry.shorthand.ilike(f"%{quest.title}%"),
                JournalEntry.narrative.ilike(f"%{quest.title}%"),
            ),
        )
        .order_by(JournalEntry.created_at.desc())
        .limit(10)
    )
    rows = list(entries_result.scalars().all())
    entries_data = [{"shorthand": e.shorthand} for e in rows]
    desc = await generate_quest_description(
        quest.title,
        entries_data,
        campaign.name if campaign else None,
        campaign.genre.value if campaign else None,
        config=config,
    )
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, desc)
    return {"description": desc}


@router.post("/suggest", response_model=QuestSuggestResponse)
async def suggest_quests_from_journals(
    campaign_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> QuestSuggestResponse:
    campaign = await get_campaign_with_access(db, campaign_id, user)

    entries_result = await db.execute(
        select(JournalEntry.shorthand)
        .where(JournalEntry.campaign_id == campaign_id)
        .order_by(JournalEntry.created_at.desc())
        .limit(8)
    )
    rows = entries_result.all()
    if not rows:
        raise HTTPException(status_code=422, detail="No journal entries found for this campaign.")

    entries_data = [{"shorthand": r.shorthand} for r in rows]
    suggestions = await suggest_quests(entries_data, campaign.name, campaign.genre.value, config=config)
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, "\n".join(suggestions))
    return QuestSuggestResponse(suggestions=suggestions)
