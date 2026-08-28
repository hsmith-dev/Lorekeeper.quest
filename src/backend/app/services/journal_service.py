import uuid
from datetime import date
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.db.models.journal import JournalEntry
from app.db.models.tag import Tag, JournalTag, TagType
from app.services.ai_service import generate_narrative
from app.services.nlp_service import extract_tags, ExtractedTag
from app.services.dedup_service import store_hash
from app.services.embedding_service import embed
from app.services.source_service import retrieve_canon_context
from app.services.shorthand_service import get_glossary
from app.services.llm_provider import LLMConfig


async def generate_draft_narrative(
    db: AsyncSession,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    notes: str,
    config: LLMConfig | None = None,
) -> str:
    """The generation half of create_journal_entry, pulled out on its own so a
    narrative can be previewed and edited before anything is persisted (see
    POST /api/journals/generate-draft) — create_journal_entry calls this too
    when the caller doesn't already have an edited narrative to save."""
    from app.db.models.campaign import Campaign
    campaign_result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = campaign_result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        canon_context, _ = await retrieve_canon_context(db, notes, user_id, campaign_id)
    except Exception:
        canon_context = None  # RAG failure must not block journal generation
    try:
        shorthand_glossary = await get_glossary(db, campaign_id)
    except Exception:
        shorthand_glossary = None  # same — a glossary lookup failure must not block generation

    # Quick-entry length preference (Settings → AI). Same must-not-block
    # posture as the lookups above — a missing row just means no preference.
    paragraph_limit: int | None = None
    try:
        from app.db.models.user_settings import UserSettings
        us_result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
        us = us_result.scalar_one_or_none()
        if us is not None:
            paragraph_limit = us.narrative_paragraph_limit
    except Exception:
        pass

    return await generate_narrative(
        notes, genre=campaign.genre.value, config=config,
        canon_context=canon_context, shorthand_glossary=shorthand_glossary,
        paragraph_limit=paragraph_limit,
    )


async def create_journal_entry(
    db: AsyncSession,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    notes: str,
    entry_hash: str,
    session_date: date | None,
    config: LLMConfig | None = None,
    narrative: str | None = None,
) -> JournalEntry:
    """Persist a journal entry. If `narrative` isn't supplied (the one-step
    generate-and-save path, still supported for callers that skip the
    preview step — e.g. the offline sync queue, which runs unattended and has
    no user present to review anything), it's generated here via
    generate_draft_narrative exactly as before. If it IS supplied — the
    normal interactive path now: generate a draft, let the user read/edit it,
    then save — no LLM call happens in this function at all."""
    if narrative is None:
        narrative = await generate_draft_narrative(db, user_id, campaign_id, notes, config)

    extracted: list[ExtractedTag] = extract_tags(narrative)

    entry = JournalEntry(
        user_id=user_id,
        campaign_id=campaign_id,
        shorthand=notes,
        narrative=narrative,
        entry_hash=entry_hash,
        session_date=session_date,
    )
    db.add(entry)
    await db.flush()

    for et in extracted:
        result = await db.execute(
            select(Tag).where(Tag.name == et.name.title(), Tag.tag_type == et.tag_type)
        )
        tag = result.scalar_one_or_none()
        if not tag:
            tag = Tag(name=et.name.title(), tag_type=et.tag_type)
            db.add(tag)
            await db.flush()
        junction = JournalTag(journal_id=entry.id, tag_id=tag.id)
        db.add(junction)

    await db.execute(
        text("UPDATE journal_entries SET narrative_tsv = to_tsvector('english', :narrative) WHERE id = :id"),
        {"narrative": narrative, "id": str(entry.id)},
    )

    # Generate and store embedding for RAG retrieval
    try:
        entry.embedding = embed(f"{notes} {narrative}")
    except Exception:
        pass  # embedding failure must not block journal creation

    await db.commit()
    await store_hash(entry_hash)

    await db.refresh(entry)
    result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == entry.id).options(selectinload(JournalEntry.tags).selectinload(Tag.custom_category))
    )
    return result.scalar_one()
