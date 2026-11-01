import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, cast, Text
from sqlalchemy.orm.attributes import flag_modified
from app.core.limiter import limiter, user_or_ip

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
    RetrievalCandidate,
    RetrievalDebug,
)
from app.access import GM, CampaignContext, NotFound, ctx_for, role_map
from app.api.deps import get_current_user, get_user_llm_config
from app.services.chat_service import build_chat_messages, rewrite_search_query, check_kobold_health, settings as chat_settings
from app.services.llm_provider import complete_messages
from app.services.retrieval_service import (
    RAG_RELEVANCE_MAX_DISTANCE, SOURCE_DOCUMENTS, hybrid_search_journal, hybrid_search_own_journals,
    retrieve_sources,
)
from app.services.source_service import retrieve_canon_context
from app.services.shorthand_service import get_glossary
from app.services.llm_provider import LLMConfig
from app.services import llm_config_service

router = APIRouter()

# The relevance gate lives in retrieval_service.RAG_RELEVANCE_MAX_DISTANCE
# now (imported above) — one constant shared by journal retrieval, canon
# retrieval, and the transparency panel's reported threshold.


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


class _ChatPrep:
    """Everything the blocking and streaming chat endpoints share: resolved
    campaign, rewritten retrieval query, hybrid-retrieval results, canon
    context, the loaded-or-created session, and the exact messages array for
    the completion. Built by _prepare_chat below."""
    campaign_uuid: uuid.UUID | None
    # The caller's ctx in campaign_uuid (None for a chat with no Campaign).
    # Only a GM ctx (or no Campaign: the user's own GM entries) sees
    # Shorthand, glossary, canon and the system prompt (E0-Access.7).
    ctx: CampaignContext | None
    search_query: str
    rewritten_from: str | None
    journal_context: list[dict]
    sources: list[JournalSource]
    retrieval_candidates: list[RetrievalCandidate]
    canon_sources: list[str]
    session: ChatSession
    history: list[dict]
    chat_messages: list[dict]

    def grounded(self) -> bool:
        return not (self.campaign_uuid and not self.sources and not self.canon_sources)

    @property
    def is_gm(self) -> bool:
        return self.ctx is None or self.ctx.role == GM

    def retrieval_debug(self) -> RetrievalDebug:
        system_prompt = self.chat_messages[0]["content"] if self.chat_messages else None
        return RetrievalDebug(
            query=self.search_query,
            rewritten_from=self.rewritten_from,
            threshold=RAG_RELEVANCE_MAX_DISTANCE,
            candidates=self.retrieval_candidates,
            # The system prompt can carry Shorthand and the glossary: GM only.
            system_prompt=system_prompt if self.is_gm else None,
        )


async def _prepare_chat(
    body: ChatRequest,
    user: User,
    db: AsyncSession,
    config: LLMConfig,
) -> _ChatPrep:
    # --- Resolve campaign context ---
    campaign_name: str | None = None
    genre: str | None = None
    campaign_uuid: uuid.UUID | None = None

    if body.campaign_id:
        try:
            campaign_uuid = uuid.UUID(body.campaign_id)
        except ValueError:
            pass

    ctx: CampaignContext | None = None
    if campaign_uuid:
        try:
            ctx = await ctx_for(db, user.id, campaign_uuid)
            campaign = await db.get(Campaign, ctx.campaign_id)
            if campaign is None:
                raise NotFound()
            campaign_name = campaign.name
            genre = campaign.genre.value
        except NotFound:
            ctx = None
            campaign_uuid = None  # no access — fall back to the user's own history below
    is_gm = ctx is None or ctx.role == GM

    # --- Query rewriting: follow-ups ("what did he find there?") carry no
    # retrieval signal — resolve them against recent history into a
    # standalone query first. Retrieval-only; the model still sees the
    # user's actual message. See chat_service.rewrite_search_query.
    history_for_rewrite: list[dict] = []
    if body.session_id:
        try:
            sid_prev = uuid.UUID(body.session_id)
            prev = await db.execute(
                select(ChatSession).where(ChatSession.id == sid_prev, ChatSession.user_id == user.id)
            )
            prev_session = prev.scalar_one_or_none()
            if prev_session is not None:
                history_for_rewrite = list(prev_session.messages)
        except (ValueError, Exception):
            pass
    search_query = body.message
    rewritten_from: str | None = None
    try:
        rewritten = await rewrite_search_query(body.message, history_for_rewrite, config)
        if rewritten:
            search_query = rewritten
            rewritten_from = body.message
    except Exception:
        pass  # a failed rewrite must never block retrieval

    # --- RAG: hybrid (vector + full-text, RRF-fused) search over journal
    # entries — see retrieval_service.py for why hybrid beats either alone.
    journal_context: list[dict] = []
    sources: list[JournalSource] = []
    retrieval_candidates: list[RetrievalCandidate] = []

    try:
        if ctx is not None:
            # GM: today's columns and gate. Anyone else: Party Narratives of
            # the entries they may see, never the Shorthand.
            results = await hybrid_search_journal(db, search_query, ctx=ctx)
        else:
            # No Campaign: the user's own entries in Campaigns they GM.
            results = await hybrid_search_own_journals(db, search_query, roles=await role_map(db, user))
        for r in results:
            # Hidden means absent: a non-GM gets no Shorthand anywhere (the
            # Party schemas without the field are E0-Access.8).
            shorthand = r.entry.shorthand if is_gm else ""
            retrieval_candidates.append(RetrievalCandidate(
                id=str(r.entry.id),
                shorthand=shorthand[:120],
                session_date=str(r.entry.session_date) if r.entry.session_date else None,
                vector_distance=round(r.vector_distance, 4) if r.vector_distance is not None else None,
                lexical_rank=r.lexical_rank,
                rrf_score=round(r.rrf_score, 5),
                passed_gate=r.passed_gate,
                used=r.used,
            ))
            if r.used:
                item = {
                    "narrative": r.entry.narrative,
                    "session_date": str(r.entry.session_date) if r.entry.session_date else None,
                }
                if is_gm:
                    item["shorthand"] = r.entry.shorthand
                journal_context.append(item)
                sources.append(JournalSource(
                    id=str(r.entry.id),
                    snippet=r.entry.narrative[:200],
                    session_date=str(r.entry.session_date) if r.entry.session_date else None,
                    shorthand=shorthand,
                    distance=round(r.vector_distance, 4) if r.vector_distance is not None else None,
                    method=r.method,
                ))
    except Exception:
        pass  # RAG failure must not break chat

    canon_context: str | None = None
    canon_sources: list[str] = []
    try:
        if ctx is not None:
            # The source_documents provider: nothing for a non-GM ctx while
            # source documents are GM-only.
            found = await retrieve_sources(db, search_query, ctx=ctx, kinds=[SOURCE_DOCUMENTS])
            canon_context, canon_sources = found[SOURCE_DOCUMENTS]
        else:
            canon_context, canon_sources = await retrieve_canon_context(db, search_query, user.id, None)
    except Exception:
        pass  # RAG failure must not break chat

    shorthand_glossary: list[dict] | None = None
    if campaign_uuid and is_gm:  # the glossary is GM-only
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

    history = list(session.messages)
    chat_messages = build_chat_messages(
        body.message, history, campaign_name, genre, journal_context,
        canon_context=canon_context, shorthand_glossary=shorthand_glossary,
    )

    prep = _ChatPrep()
    prep.campaign_uuid = campaign_uuid
    prep.ctx = ctx
    prep.search_query = search_query
    prep.rewritten_from = rewritten_from
    prep.journal_context = journal_context
    prep.sources = sources
    prep.retrieval_candidates = retrieval_candidates
    prep.canon_sources = canon_sources
    prep.session = session
    prep.history = history
    prep.chat_messages = chat_messages
    return prep


async def _persist_chat_turn(
    db: AsyncSession, prep: _ChatPrep, user: User, config: LLMConfig, user_message: str, reply: str
) -> None:
    prep.session.messages = prep.history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": reply},
    ]
    prep.session.message_count = len(prep.session.messages)
    flag_modified(prep.session, "messages")
    await db.commit()
    await llm_config_service.meter(db, user, config, user_message, reply)


@router.post("/", response_model=ChatResponse)
@limiter.limit("20/minute", key_func=user_or_ip)
async def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> ChatResponse:
    prep = await _prepare_chat(body, user, db, config)
    reply = await complete_messages(
        prep.chat_messages, config, max_tokens=600,
        timeout=chat_settings.kobold_timeout_seconds,
    )
    await _persist_chat_turn(db, prep, user, config, body.message, reply)
    return ChatResponse(
        reply=reply,
        session_id=str(prep.session.id),
        sources=prep.sources,
        canon_sources=prep.canon_sources,
        grounded=prep.grounded(),
        retrieval=prep.retrieval_debug(),
    )


@router.post("/stream")
@limiter.limit("20/minute", key_func=user_or_ip)
async def chat_stream(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
):
    """Server-sent-events version of POST / — same retrieval, same
    persistence, but tokens render as they generate. Event order: one `meta`
    event (session id, sources, grounded flag, retrieval trace — all known
    before generation starts), then `delta` events, then `done` (or `error`
    if the model was unreachable before any token arrived). The frontend
    falls back to the blocking endpoint if this one fails."""
    import json as _json
    from fastapi.responses import StreamingResponse
    from starlette.background import BackgroundTask
    from app.services import llm_provider

    prep = await _prepare_chat(body, user, db, config)
    # Reserve the local-LLM slot before the stream starts, so a busy gate is
    # a normal 503 {"code": "llm_busy"} (LLMBusy handler) rather than a
    # stream that opens and then fails. A no-op slot for BYOK.
    slot = await llm_provider.reserve_slot(config)

    async def event_stream():
        error: HTTPException | None = None
        parts: list[str] = []
        try:
            meta = {
                "session_id": str(prep.session.id),
                "sources": [s.model_dump() for s in prep.sources],
                "canon_sources": prep.canon_sources,
                "grounded": prep.grounded(),
                "retrieval": prep.retrieval_debug().model_dump(),
            }
            yield f"event: meta\ndata: {_json.dumps(meta)}\n\n"
            # held(): stream_messages' own gate acquire becomes a no-op.
            with slot.held():
                try:
                    async for delta in llm_provider.stream_messages(
                        prep.chat_messages, config, max_tokens=600,
                        timeout=chat_settings.kobold_timeout_seconds,
                    ):
                        parts.append(delta)
                        yield f"event: delta\ndata: {_json.dumps({'text': delta})}\n\n"
                except HTTPException as exc:
                    error = exc
        finally:
            # Also on client disconnect (generator closed mid-stream).
            await slot.release()
        if error is not None:
            yield f"event: error\ndata: {_json.dumps({'detail': error.detail})}\n\n"
            return
        reply = "".join(parts).strip()
        if reply:
            await _persist_chat_turn(db, prep, user, config, body.message, reply)
        yield f"event: done\ndata: {_json.dumps({'reply': reply})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        # If the client is gone before the generator ever starts, its finally
        # never runs; this frees the slot then (release is idempotent).
        background=BackgroundTask(slot.release),
    )
