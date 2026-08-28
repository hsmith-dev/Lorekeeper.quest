import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, Text
from sqlalchemy.orm.attributes import flag_modified
from app.core.limiter import limiter

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.db.models.chat import ChatSession
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionSummary,
    ChatSessionDetail,
    ChatMessage,
    JournalSource,
)
from app.api.deps import get_current_user, get_user_llm_config, get_campaign_with_access
from app.services.chat_service import generate_chat_reply, check_kobold_health
from app.services.embedding_service import embed
from app.services.source_service import retrieve_canon_context
from app.services.shorthand_service import get_glossary
from app.services.llm_provider import LLMConfig, is_hosted_default
from app.services import billing_service

router = APIRouter()

# Max cosine distance (0 = identical, 2 = opposite) for a journal entry or
# canon chunk to count as relevant retrieval context. Shared with
# source_service.retrieve_canon_context via its threshold parameter. See the
# retrieval block in chat() below for why a cutoff exists at all.
RAG_RELEVANCE_MAX_DISTANCE = 0.75


@router.get("/health")
async def chat_health() -> dict:
    """Check whether the KoboldCpp backend is reachable."""
    online = await check_kobold_health()
    return {"ai_online": online}


@router.get("/sessions", response_model=list[ChatSessionSummary])
async def list_sessions(
    search: str | None = Query(None, max_length=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionSummary]:
    query = (
        select(ChatSession, Campaign.name)
        .outerjoin(Campaign, ChatSession.campaign_id == Campaign.id)
        .where(ChatSession.user_id == user.id)
    )
    if search:
        term = f"%{search}%"
        query = query.where(
            ChatSession.title.ilike(term)
            | cast(ChatSession.messages, Text).ilike(term)
        )
    query = query.order_by(ChatSession.updated_at.desc()).limit(50)
    result = await db.execute(query)
    rows = result.all()
    return [
        ChatSessionSummary(
            id=str(session.id),
            title=session.title,
            campaign_id=str(session.campaign_id) if session.campaign_id else None,
            campaign_name=campaign_name,
            message_count=session.message_count,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
        for session, campaign_name in rows
    ]


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionDetail:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(ChatSession, Campaign.name)
        .outerjoin(Campaign, ChatSession.campaign_id == Campaign.id)
        .where(ChatSession.id == sid, ChatSession.user_id == user.id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    session, campaign_name = row
    return ChatSessionDetail(
        id=str(session.id),
        title=session.title,
        campaign_id=str(session.campaign_id) if session.campaign_id else None,
        campaign_name=campaign_name,
        message_count=session.message_count,
        messages=[ChatMessage(**m) for m in session.messages],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        select(ChatSession).where(ChatSession.id == sid, ChatSession.user_id == user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    await db.commit()


@router.post("/", response_model=ChatResponse)
@limiter.limit("20/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> ChatResponse:
    # --- Resolve campaign context ---
    campaign_name: str | None = None
    genre: str | None = None
    campaign_uuid: uuid.UUID | None = None

    if body.campaign_id:
        try:
            campaign_uuid = uuid.UUID(body.campaign_id)
        except ValueError:
            pass

    if campaign_uuid:
        try:
            campaign = await get_campaign_with_access(db, campaign_uuid, user)
            campaign_name = campaign.name
            genre = campaign.genre.value
        except HTTPException:
            campaign_uuid = None  # no access — fall back to the user's own history below

    # --- RAG: vector similarity search over journal entries ---
    journal_context: list[dict] = []
    sources: list[JournalSource] = []

    try:
        query_embedding = embed(body.message)
        if campaign_uuid:
            # A selected campaign is shared context — every member's entries count,
            # not just the entries this particular user happened to write.
            base_filter = JournalEntry.campaign_id == campaign_uuid
        else:
            base_filter = JournalEntry.user_id == user.id

        # Relevance-gated, not just top-k: without the distance cutoff this
        # always returned the 3 nearest entries no matter how unrelated the
        # question was — off-topic questions got real journal entries stuffed
        # into the prompt AND cited as confident "sources" in the UI, which is
        # exactly the ungrounded behavior RAG is supposed to prevent. Cosine
        # distance here is 0 (identical) to 2 (opposite); ~0.75 keeps
        # clearly-related entries (paraphrases of logged events score well
        # under it) while dropping the unrelated ones.
        distance = JournalEntry.embedding.cosine_distance(query_embedding)
        similar = await db.execute(
            select(JournalEntry, distance.label("dist"))
            .where(base_filter, JournalEntry.embedding.isnot(None))
            .order_by(distance)
            .limit(3)
        )
        for entry, dist in similar.all():
            if dist is not None and dist > RAG_RELEVANCE_MAX_DISTANCE:
                continue
            journal_context.append({
                "narrative": entry.narrative,
                "shorthand": entry.shorthand,
                "session_date": str(entry.session_date) if entry.session_date else None,
            })
            sources.append(JournalSource(
                id=str(entry.id),
                snippet=entry.narrative[:200],
                session_date=str(entry.session_date) if entry.session_date else None,
                shorthand=entry.shorthand,
            ))
    except Exception:
        pass  # RAG failure must not break chat

    canon_context: str | None = None
    canon_sources: list[str] = []
    try:
        canon_context, canon_sources = await retrieve_canon_context(
            db, body.message, user.id, campaign_uuid
        )
    except Exception:
        pass  # RAG failure must not break chat

    shorthand_glossary: list[dict] | None = None
    if campaign_uuid:
        try:
            shorthand_glossary = await get_glossary(db, campaign_uuid)
        except Exception:
            pass  # same — a glossary lookup failure must not break chat

    # --- Load or create session ---
    session: ChatSession | None = None

    if body.session_id:
        try:
            sid = uuid.UUID(body.session_id)
        except ValueError:
            sid = None
        if sid:
            res = await db.execute(
                select(ChatSession).where(ChatSession.id == sid, ChatSession.user_id == user.id)
            )
            session = res.scalar_one_or_none()

    if session is None:
        title = body.message[:80].strip() or "New conversation"
        session = ChatSession(
            user_id=user.id,
            campaign_id=campaign_uuid,
            title=title,
            messages=[],
            message_count=0,
        )
        db.add(session)
        await db.flush()

    # --- Generate reply ---
    history = list(session.messages)
    reply = await generate_chat_reply(
        message=body.message,
        history=history,
        campaign_name=campaign_name,
        genre=genre,
        journal_context=journal_context,
        config=config,
        canon_context=canon_context,
        shorthand_glossary=shorthand_glossary,
    )

    # --- Persist messages ---
    session.messages = history + [
        {"role": "user", "content": body.message},
        {"role": "assistant", "content": reply},
    ]
    session.message_count = len(session.messages)
    flag_modified(session, "messages")
    await db.commit()

    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, body.message, reply)

    return ChatResponse(
        reply=reply,
        session_id=str(session.id),
        sources=sources,
        canon_sources=canon_sources,
        # See ChatResponse.grounded — only False when a campaign was selected
        # yet nothing relevant was retrieved to ground the reply.
        grounded=not (campaign_uuid and not sources and not canon_sources),
    )
