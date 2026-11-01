"""The Chronicler (E0-Access.8): chat, its stored sessions and their citations.

Every body is built GM-shaped here and projected through
`access.project_chat`: a GM ctx gets the GM schemas (Shorthand, canon
sources, the system prompt in the trace), anyone else the Party schemas,
which have none of those. A chat in a Campaign uses the caller's ctx there
(`ctx_for_request`: preview narrows, a POST in preview is 404); a chat with
no Campaign reads the user's own entries in the Campaigns they GM, through
their `role_map`.

Stored messages are `{role, content, refs, grounded}` (`StoredChatMessage`).
A message whose refs the reader can no longer all see is redacted on read
and left out of the prompt history; an archived session is never replayed,
never posted to, and to a Player is absent (list) or 404. Denied, hidden,
another user's and missing sessions are the same 404.

Account gate (app/api/deps.py, E0-Access.6): listing and reading stored
sessions are Party reads (openapi_extra=PARTY_READ), open to a Player with
no paid account. Chat itself (hosted AI), delete and health stay gated.
"""
import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Text, cast, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.access import (
    PLAYER, PREVIEW_HEADER, CHAT_DETAIL, CHAT_META, CHAT_REPLY, GM, CampaignContext, NotFound, RoleMap, check_chat_session,
    ctx_for, ctx_for_request, grant_changed, grant_watch, not_found, owned_get, project_chat, replay_history, resolve_sources,
    role_map, scoped_get, session_visible_text, visible_refs,
)
from app.access.context import PREVIEW_MEMBER
from app.access.policy import NOT_FOUND_DETAIL
from app.api.deps import PARTY_READ, get_current_user, get_user_llm_config
from app.core.limiter import limiter, user_or_ip
from app.db.models.campaign import Campaign
from app.db.models.chat import ChatSession
from app.db.models.journal import JournalEntry
from app.db.models.user import User
from app.db.session import get_db
from app.domain.enums import EntryKind
from app.schemas.chat import (
    ChatGMResponse, ChatRequest, ChatSessionDetailGM, ChatSessionSummary, StoredChatMessage,
)
from app.schemas.sources import SourceKind, SourceRef
from app.services import llm_config_service
from app.services.chat_service import (
    build_chat_messages, check_kobold_health, rewrite_search_query, settings as chat_settings,
)
from app.services.llm_provider import LLMConfig, complete_messages
from app.services.retrieval_service import (
    RAG_RELEVANCE_MAX_DISTANCE, SOURCE_DOCUMENTS, hybrid_search_journal, hybrid_search_own_journals,
    retrieve_sources,
)
from app.services.shorthand_service import get_glossary
from app.services.source_service import retrieve_canon_context

router = APIRouter()
logger = logging.getLogger(__name__)

# The relevance gate lives in retrieval_service.RAG_RELEVANCE_MAX_DISTANCE
# now (imported above) — one constant shared by journal retrieval, canon
# retrieval, and the transparency panel's reported threshold.

_GM_OR_PARTY = ("GM: the GM schema; Player or member preview: the Party schema (no `shorthand`, no "
                "`system_prompt`, empty `canon_sources`).")
_LIST_LIMIT = 50
_SEARCH_POOL = 200  # sessions the SQL prefilter hands to the visible-text match

ChatScope = CampaignContext | RoleMap


@router.get("/health")
async def chat_health() -> dict:
    """Check whether the KoboldCpp backend is reachable."""
    online = await check_kobold_health()
    return {"ai_online": online}


async def _own_session(db: AsyncSession, user: User, session_id: str) -> ChatSession:
    """The user's own session `session_id`; the one 404 for a bad id, a
    missing session or another user's (`access.owned_get`)."""
    return await owned_get(db, ChatSession, user.id, session_id)


async def _campaign_name(db: AsyncSession, scope: "ChatScope") -> str | None:
    """The name of the Campaign `scope` reads in (None for a campaign-less
    session, read with a role map)."""
    if not isinstance(scope, CampaignContext):
        return None
    return (await scoped_get(db, Campaign, scope, scope.campaign_id)).name


async def _session_scope(request: Request, db: AsyncSession, user: User, session: ChatSession) -> ChatScope:
    """The ctx a session is read with: the caller's ctx in its Campaign (404
    once they are no longer a Member), or their role map for a session with
    no Campaign. In member preview a Campaign session is 404 (the member
    view is nobody's, so it owns no session), and a campaign-less one reads
    as a Player everywhere; any write in preview is 404."""
    if session.campaign_id is not None:
        return await ctx_for_request(request, db, user, session.campaign_id)
    roles = await role_map(db, user)
    if request.headers.get(PREVIEW_HEADER) == PREVIEW_MEMBER:
        if request.method.upper() not in ("GET", "HEAD", "OPTIONS"):
            not_found()
        roles = RoleMap({cid: PLAYER for cid in roles}, user_id=roles.user_id)
    return roles


def _summary(session: ChatSession, campaign_name: str | None) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=str(session.id),
        title=session.title,
        campaign_id=str(session.campaign_id) if session.campaign_id else None,
        campaign_name=campaign_name,
        message_count=session.message_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
        archived_at=session.archived_at,
    )


@router.get("/sessions", response_model=list[ChatSessionSummary], openapi_extra=PARTY_READ)
async def list_sessions(
    request: Request,
    search: str | None = Query(None, max_length=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionSummary]:
    """The user's sessions, newest first: those with no Campaign, and those
    of Campaigns they still belong to; archived ones only where they are GM.
    `search` matches the title or the text of a message the user may still
    read (a redacted message matches nothing)."""
    roles = await role_map(db, user)
    if request.headers.get(PREVIEW_HEADER) == PREVIEW_MEMBER:
        # Preview only narrows: list (and search) as if a Player everywhere.
        roles = RoleMap({cid: PLAYER for cid in roles}, user_id=roles.user_id)
    gm_ids = [cid for cid, role in roles.items() if role == GM]
    member_ids = list(roles)
    all_gm = all(role == GM for role in roles.values())
    query = (
        select(ChatSession, Campaign.name)
        .outerjoin(Campaign, ChatSession.campaign_id == Campaign.id)
        .where(
            ChatSession.user_id == user.id,
            or_(ChatSession.campaign_id.is_(None),
                ChatSession.campaign_id.in_(member_ids) if member_ids else false()),
            or_(ChatSession.archived_at.is_(None),
                ChatSession.campaign_id.is_(None) if all_gm else false(),
                ChatSession.campaign_id.in_(gm_ids) if gm_ids else false()),
        )
        .order_by(ChatSession.updated_at.desc())
    )
    if not search:
        rows = (await db.execute(query.limit(_LIST_LIMIT))).all()
        return [_summary(s, name) for s, name in rows]

    # SQL narrows (a superset: ILIKE over the stored JSON), then only the
    # title and the messages the user may still read are matched.
    term = f"%{search}%"
    query = query.where(ChatSession.title.ilike(term) | cast(ChatSession.messages, Text).ilike(term))
    rows = (await db.execute(query.limit(_SEARCH_POOL))).all()
    needle = search.lower()
    out: list[ChatSessionSummary] = []
    for session, name in rows:
        if needle in (session.title or "").lower():
            out.append(_summary(session, name))
        else:
            try:
                texts = await session_visible_text(db, session, roles)
            except NotFound:
                continue
            if any(needle in t.lower() for t in texts):
                out.append(_summary(session, name))
        if len(out) >= _LIST_LIMIT:
            break
    return out


@router.get("/sessions/{session_id}", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": ChatSessionDetailGM, "description": _GM_OR_PARTY}})
async def get_session(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One of the user's sessions, its messages redacted by what they may
    see now. An archived session is readable by a GM ctx only."""
    session = await _own_session(db, user, session_id)
    scope = await _session_scope(request, db, user, session)
    return await project_chat(db, session, scope, CHAT_DETAIL,
                              extra={"campaign_name": await _campaign_name(db, scope)})


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    session = await _own_session(db, user, session_id)
    scope = await _session_scope(request, db, user, session)  # a DELETE in preview is 404
    check_chat_session(session, scope)
    if session.archived_at is not None:
        not_found()  # archived sessions are read-only, even to a GM ctx
    await db.delete(session)
    await db.commit()


class _ChatPrep:
    """Everything the blocking and streaming chat endpoints share, built by
    _prepare_chat: the session, the scope its body is projected with, the
    exact messages array for the completion, the GM-shaped body, the
    projected SSE meta, and what the assistant turn stores."""
    ctx: CampaignContext | None  # None: a chat with no Campaign
    scope: ChatScope
    session: ChatSession
    stored: list[dict]           # the session's messages as stored (never rewritten)
    chat_messages: list[dict]
    body: dict[str, Any]         # GM-shaped: sources, canon_sources, grounded, retrieval, citations
    meta: dict[str, Any]         # the SSE meta event, projected for the ctx
    refs: list[SourceRef]        # what the reply drew on (all visible to the ctx)
    grounded: bool


def _entry_ref(entry: JournalEntry, is_gm: bool) -> SourceRef:
    """The citation of a retrieved entry: the whole record for a GM, the
    Narrative alone for anyone else (Design Notes: `field=None` includes the
    Shorthand)."""
    kind = SourceKind.PLAYER_JOURNAL if str(entry.kind) == EntryKind.PLAYER.value else SourceKind.JOURNAL
    return SourceRef(kind=kind, id=entry.id, field=None if is_gm else "narrative")


async def _prepare_chat(
    request: Request,
    body: ChatRequest,
    user: User,
    db: AsyncSession,
    config: LLMConfig,
) -> _ChatPrep:
    # --- Resolve the ctx: a denied, missing or malformed Campaign (and a
    # POST in preview) is the one 404, never a silent fall-back.
    ctx: CampaignContext | None = None
    campaign_name: str | None = None
    genre: str | None = None
    if body.campaign_id:
        ctx = await ctx_for_request(request, db, user, body.campaign_id)
        campaign = await db.get(Campaign, ctx.campaign_id)
        if campaign is None:
            not_found()
        campaign_name = campaign.name
        genre = campaign.genre.value
        scope: ChatScope = ctx
    else:
        scope = await role_map(db, user)
    # No Campaign: the user's own entries in Campaigns they GM, read as GM.
    is_gm = ctx is None or ctx.is_gm

    # --- The session: the user's own, of this Campaign (or of none), not
    # archived. History is what may be replayed: {role, content} of the
    # messages ctx may still see.
    session: ChatSession | None = None
    if body.session_id:
        session = await _own_session(db, user, body.session_id)
        if session.campaign_id != (ctx.campaign_id if ctx is not None else None) or session.archived_at is not None:
            not_found()
        check_chat_session(session, scope)
    history = await replay_history(db, session, scope)

    # --- Query rewriting: follow-ups ("what did he find there?") carry no
    # retrieval signal — resolve them against recent (replayable) history
    # into a standalone query first. Retrieval-only; the model still sees
    # the user's actual message. See chat_service.rewrite_search_query.
    search_query = body.message
    rewritten_from: str | None = None
    try:
        rewritten = await rewrite_search_query(body.message, history, config)
        if rewritten:
            search_query = rewritten
            rewritten_from = body.message
    except Exception:
        pass  # a failed rewrite must never block retrieval

    # --- RAG: hybrid (vector + full-text, RRF-fused) search over journal
    # entries — see retrieval_service.py for why hybrid beats either alone.
    # Every candidate is re-checked through access.visible_refs.
    journal_context: list[dict] = []
    sources: list[dict] = []
    candidates: list[dict] = []
    refs: list[SourceRef] = []
    citations: list = []
    try:
        if ctx is not None:
            # GM: today's columns and gate. Anyone else: Party Narratives of
            # the entries they may see, never the Shorthand.
            results = await hybrid_search_journal(db, search_query, ctx=ctx)
        else:
            results = await hybrid_search_own_journals(db, search_query, roles=scope)
        entry_refs = {r.entry.id: _entry_ref(r.entry, is_gm) for r in results}
        shown = set(await visible_refs(db, entry_refs.values(), scope))
        for r in results:
            ref = entry_refs[r.entry.id]
            if ref not in shown:
                continue
            entry = r.entry
            session_date = str(entry.session_date) if entry.session_date else None
            candidate = {
                "id": str(entry.id),
                "session_date": session_date,
                "vector_distance": round(r.vector_distance, 4) if r.vector_distance is not None else None,
                "lexical_rank": r.lexical_rank,
                "rrf_score": round(r.rrf_score, 5),
                "passed_gate": r.passed_gate,
                "used": r.used,
            }
            if is_gm:
                candidate["shorthand"] = entry.shorthand[:120]
            candidates.append(candidate)
            if r.used:
                item = {"narrative": entry.narrative, "session_date": session_date}
                source = {
                    "id": str(entry.id),
                    "snippet": entry.narrative[:200],
                    "session_date": session_date,
                    "distance": round(r.vector_distance, 4) if r.vector_distance is not None else None,
                    "method": r.method,
                }
                if is_gm:
                    item["shorthand"] = entry.shorthand
                    source["shorthand"] = entry.shorthand
                journal_context.append(item)
                sources.append(source)
                refs.append(ref)
        citations = await resolve_sources(db, refs, scope)
    except Exception:
        # RAG failure must not break chat, and must not leave a half-built
        # body (sources and stored refs without their citations).
        journal_context, sources, candidates, refs, citations = [], [], [], [], []

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
    if ctx is not None and ctx.is_gm:  # the glossary is GM-only
        try:
            shorthand_glossary = await get_glossary(db, ctx.campaign_id)
        except Exception:
            pass  # same — a glossary lookup failure must not break chat

    if session is None:
        session = ChatSession(
            user_id=user.id,
            campaign_id=ctx.campaign_id if ctx is not None else None,
            title=body.message[:80].strip() or "New conversation",
            messages=[],
            message_count=0,
        )
        db.add(session)
        await db.flush()

    chat_messages = build_chat_messages(
        body.message, history, campaign_name, genre, journal_context,
        canon_context=canon_context, shorthand_glossary=shorthand_glossary, ctx=ctx,
    )
    grounded = not (ctx is not None and not sources and not canon_sources)

    prep = _ChatPrep()
    prep.ctx = ctx
    prep.scope = scope
    prep.session = session
    prep.stored = list(session.messages or [])
    prep.chat_messages = chat_messages
    prep.refs = refs
    prep.grounded = grounded
    prep.body = {
        "session_id": str(session.id),
        "sources": sources,
        "canon_sources": canon_sources,
        "grounded": grounded,
        "retrieval": {
            "query": search_query,
            "rewritten_from": rewritten_from,
            "threshold": RAG_RELEVANCE_MAX_DISTANCE,
            "candidates": candidates,
            # The system prompt can carry Shorthand and the glossary: GM only.
            "system_prompt": chat_messages[0]["content"] if is_gm and chat_messages else None,
        },
        "citations": citations,
    }
    prep.meta = (await project_chat(db, session, scope, CHAT_META, extra=prep.body)).model_dump(mode="json")
    return prep


async def _persist_chat_turn(
    db: AsyncSession, prep: _ChatPrep, user: User, config: LLMConfig, user_message: str, reply: str
) -> None:
    """Append the turn as stored messages: refs and the grounded flag, never
    titles or quotes. Earlier messages stay as stored (redaction is on read)."""
    prep.session.messages = prep.stored + [
        StoredChatMessage(role="user", content=user_message).stored(),
        StoredChatMessage(role="assistant", content=reply, refs=prep.refs, grounded=prep.grounded).stored(),
    ]
    prep.session.message_count = len(prep.session.messages)
    flag_modified(prep.session, "messages")
    await db.commit()
    await llm_config_service.meter(db, user, config, user_message, reply)


@router.post("/", response_model=None,
             responses={200: {"model": ChatGMResponse, "description": _GM_OR_PARTY}})
@limiter.limit("20/minute", key_func=user_or_ip)
async def chat(
    request: Request,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
):
    prep = await _prepare_chat(request, body, user, db, config)
    reply = await complete_messages(
        prep.chat_messages, config, max_tokens=600,
        timeout=chat_settings.kobold_timeout_seconds,
    )
    out = await project_chat(db, prep.session, prep.scope, CHAT_REPLY, extra={**prep.body, "reply": reply})
    await _persist_chat_turn(db, prep, user, config, body.message, reply)
    return out


async def _cancel(task: "asyncio.Future") -> None:
    """Cancel `task` and wait for it to finish, swallowing its outcome. A
    cancellation aimed at the current task (a client disconnect while
    waiting) is re-raised."""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
    except Exception:
        pass


async def _watched_grants(db: AsyncSession, user: User, prep: _ChatPrep) -> tuple[list[CampaignContext], bool]:
    """The grants a stream stands on (E0-Access.10) and whether one is
    already lost: the chat's ctx in its Campaign, or, with no Campaign, the
    user's Co-GM grants in the role map (the Campaigns whose entries it
    reads as GM). A Campaign the role map read as GM that no longer is
    (the grant removed or demoted since) means the stream is revoked. The
    Owner's own Campaigns are watched only through their ctx (deleting the
    Campaign)."""
    if prep.ctx is not None:
        return [prep.ctx], False
    watched = []
    for campaign_id, role in prep.scope.items():
        if role != GM:
            continue
        try:
            ctx = await ctx_for(db, user, campaign_id)
        except NotFound:
            return [], True
        if ctx.role != GM:
            return [], True
        if ctx.grant_id is not None:
            watched.append(ctx)
    return watched, False


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
    event (session id, sources, grounded flag, retrieval trace, citations —
    all known before generation starts, projected like the blocking reply),
    then `delta` events, then `done` (or `error` if the model was unreachable
    before any token arrived). The frontend falls back to the blocking
    endpoint if this one fails.

    The stream stands on the caller's grant (E0-Access.10): when
    `grant_watch` fires mid-stream (a role change, a removal, a deleted
    Campaign), no further delta is sent, the upstream LLM request is
    closed, the turn is not persisted and the stream ends with
    `error {"detail": "Not found"}`."""
    import json as _json
    from fastapi.responses import StreamingResponse
    from starlette.background import BackgroundTask
    from app.services import llm_provider

    prep = await _prepare_chat(request, body, user, db, config)
    watched, lost = await _watched_grants(db, user, prep)
    # Reserve the local-LLM slot before the stream starts, so a busy gate is
    # a normal 503 {"code": "llm_busy"} (LLMBusy handler) rather than a
    # stream that opens and then fails. A no-op slot for BYOK.
    slot = await llm_provider.reserve_slot(config)

    async def event_stream():
        error: HTTPException | None = None
        revoked = False
        parts: list[str] = []
        # E0-Access.10: every chunk races the grant watch. When the grant
        # changes, nothing more is sent, the upstream request is closed and
        # nothing is persisted.
        watch = asyncio.ensure_future(grant_watch(*watched, bind=db.bind)) if watched else None
        stream = chunk = None
        deferred: BaseException | None = None
        try:
            # A grant changed while _prepare_chat ran (retrieval, the query
            # rewrite): nothing built on the old grant goes out, no LLM call.
            if lost or (watched and await grant_changed(*watched, bind=db.bind)):
                revoked = True
            else:
                yield f"event: meta\ndata: {_json.dumps(prep.meta)}\n\n"
                # held(): stream_messages' own gate acquire becomes a no-op.
                with slot.held():
                    stream = llm_provider.stream_messages(
                        prep.chat_messages, config, max_tokens=600,
                        timeout=chat_settings.kobold_timeout_seconds,
                    )
                    try:
                        while True:
                            chunk = asyncio.ensure_future(anext(stream))
                            waiting = {chunk} if watch is None else {chunk, watch}
                            await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                            if watch is not None and watch.done():
                                # Fired (or failed: fail closed). A chunk that
                                # arrived at the same moment is dropped.
                                revoked = True
                                if not watch.cancelled() and watch.exception() is not None:
                                    logger.warning(json.dumps({"event": "grant_watch_failed"}),
                                                   exc_info=watch.exception())
                                await _cancel(chunk)
                                break
                            try:
                                delta = chunk.result()
                            except StopAsyncIteration:
                                break
                            parts.append(delta)
                            yield f"event: delta\ndata: {_json.dumps({'text': delta})}\n\n"
                    except HTTPException as exc:
                        error = exc
        finally:
            # Also on client disconnect (generator closed mid-stream). A
            # cancellation of this task is re-raised after the cleanup.
            for task in (watch, chunk):  # chunk: a disconnect mid-wait, the generator must not be running
                if task is not None:
                    try:
                        await _cancel(task)
                    except asyncio.CancelledError as exc:
                        deferred = exc
            if stream is not None:
                with suppress(Exception):
                    await stream.aclose()  # closes the upstream HTTP request
            await slot.release()
            if deferred is not None:
                raise deferred
        if revoked:
            yield f"event: error\ndata: {_json.dumps({'detail': NOT_FOUND_DETAIL})}\n\n"
            return
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
