import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.shorthand import ShorthandTerm


async def get_glossary(db: AsyncSession, campaign_id: uuid.UUID) -> list[dict]:
    """The campaign's shorthand terms, formatted for ai_service.py/
    chat_service.py to fold into their system prompts — see
    ai_service._shorthand_block and chat_service.generate_chat_reply's
    shorthand_glossary param. Every caller that generates text for a
    campaign should pull this in, the same way canon_context already is,
    so a table's own vocabulary ("BBEG", a PC's nickname, etc.) gets
    understood instead of guessed at or ignored."""
    result = await db.execute(
        select(ShorthandTerm).where(ShorthandTerm.campaign_id == campaign_id).order_by(ShorthandTerm.term)
    )
    return [{"term": t.term, "meaning": t.meaning, "usage": t.usage} for t in result.scalars().all()]
