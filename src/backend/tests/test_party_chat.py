"""E0-Access.8: Player-safe Chronicler chat with SourceRef citations.

The matrix of the spec: a Player's chat (blocking and streaming) is built
only from what they may see and answered in the Party schemas; a GM's is
unchanged plus citations; `resolve_sources` and the resolver registry;
stored messages; redaction on read and on replay (since-hidden refs, legacy
messages); archived sessions; session and Campaign mismatches; session
search; the campaign-less (role map) path. Embeddings are the deterministic
`fake_vector` (only lexical evidence passes the gate), the LLM is the fake
provider, and prompts are read through `llm_provider.capture()`.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from app.access import (
    CHAT_DETAIL, CHAT_META, CHAT_REPLY, PREVIEW_HEADER, PROJECTIONS, REDACTED_NOTICE, check_party_schemas,
    register_resolver, registered_resolvers, resolve_sources, visible_refs,
)
from app.access import sources as access_sources
from app.db.models.campaign_member import CampaignMember
from app.db.models.chat import ChatSession
from app.db.models.shorthand import ShorthandTerm
from app.domain.enums import CampaignRole
from app.schemas.chat import (
    ChatMetaParty, ChatPartyResponse, ChatSessionDetailParty, JournalSourceParty, RetrievalCandidateParty,
    RetrievalDebugParty,
)
from app.schemas.sources import ResolvedSource, SourceKind, SourceRef
from app.services import llm_provider
from app.services.chat_service import build_chat_messages
from tests.ev4.fixtures import bearer, create_user
from tests.test_party_retrieval import (  # noqa: F401  (fixtures: world, and the autouse fakes)
    _campaign, _fake_llm_for, add_entry, fake_embed, fake_valkey, reindex_gm, world,
)

NOT_FOUND = {"detail": "Not found"}
MISSING = "00000000-0000-4000-8000-000000000000"
QUESTION = "What happened with Zorblax?"


def ref(entry, field: str | None = "narrative", kind: SourceKind | None = None) -> SourceRef:
    kind = kind or (SourceKind.PLAYER_JOURNAL if str(entry.kind) == "player" else SourceKind.JOURNAL)
    return SourceRef(kind=kind, id=entry.id, field=field)


def stored_ref(entry, field: str | None = "narrative") -> dict:
    return ref(entry, field).model_dump(mode="json", exclude_none=True)


async def add_session(db, user, messages, *, campaign_id=None, archived: bool = False, title: str = "Chat") -> ChatSession:
    session = ChatSession(user_id=user.id, campaign_id=campaign_id, title=title, messages=messages,
                          message_count=len(messages),
                          archived_at=datetime.now(timezone.utc) if archived else None)
    db.add(session)
    await db.commit()
    return session


def prompt_text(cap) -> str:
    return json.dumps([c.messages for c in cap.calls])


def sse_meta(text: str) -> dict:
    return json.loads(text.split("event: meta\ndata: ", 1)[1].split("\n", 1)[0])


def keys_anywhere(value, found: set | None = None) -> set:
    found = set() if found is None else found
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            keys_anywhere(v, found)
    elif isinstance(value, list):
        for v in value:
            keys_anywhere(v, found)
    return found


# ── Schemas ────────────────────────────────────────────────────────────────

def test_party_chat_schemas_carry_no_gm_field():
    check_party_schemas()
    for schema in (ChatPartyResponse, ChatMetaParty, ChatSessionDetailParty):
        text = json.dumps(schema.model_json_schema())
        assert "shorthand" not in text and "system_prompt" not in text, schema
    assert "shorthand" not in JournalSourceParty.model_fields
    assert "shorthand" not in RetrievalCandidateParty.model_fields
    assert "system_prompt" not in RetrievalDebugParty.model_fields
    for variant in (CHAT_META, CHAT_REPLY, CHAT_DETAIL):
        assert (ChatSession, variant) in PROJECTIONS
    # The Party schema always empties canon_sources.
    assert ChatPartyResponse(reply="r", session_id="s", canon_sources=["CANON"]).canon_sources == []


async def test_build_chat_messages_for_a_non_gm_ctx(world):
    from app.access import CampaignContext, owner

    player = CampaignContext(campaign_id=world.a, user_id=world.p.id, role="player", is_owner=False,
                             audience=owner(world.p.id))
    history = [{"role": "user", "content": "hi", "refs": [], "grounded": True},
               {"role": "assistant", "content": "hello", "refs": [{"kind": "journal", "id": MISSING}]}]
    journal = [{"narrative": "N", "session_date": None, "shorthand": "SECRETWORD"}]
    glossary = [{"term": "GLOSSTERM", "meaning": "m"}]
    out = build_chat_messages("Q", history, "A", "fantasy", journal, canon_context="CANONCHUNK",
                              shorthand_glossary=glossary, ctx=player)
    text = json.dumps(out)
    assert "SECRETWORD" not in text and "GLOSSTERM" not in text and "CANONCHUNK" not in text and "Notes" not in text
    assert out[1:3] == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    # No relevant entries (the canon dropped): the note rides in the final user turn.
    out = build_chat_messages("Q", [], "A", "fantasy", [], canon_context="CANONCHUNK", ctx=player)
    assert out[-1]["role"] == "user" and out[-1]["content"].startswith("[Note from the app")
    # GM (and no ctx): unchanged.
    out = build_chat_messages("Q", [], "A", "fantasy", journal, canon_context="CANONCHUNK", shorthand_glossary=glossary)
    text = json.dumps(out)
    assert "SECRETWORD" in text and "GLOSSTERM" in text and "CANONCHUNK" in text


# ── resolve_sources and the registry ───────────────────────────────────────

async def test_resolve_sources_matrix(db, world, monkeypatch, caplog):
    monkeypatch.setattr(access_sources, "_MISSING_LOGGED", set())
    vis = await add_entry(db, world.a, world.owner, "The party met Zorblax.", shorthand="SECRETWORD")
    hidden = await add_entry(db, world.a, world.owner, "GM-only prose.", visibility="gm")
    mine = await add_entry(db, world.a, world.p, "P's own note.", kind="player", visibility="private")
    theirs = await add_entry(db, world.a, world.q, "Q's private note.", kind="player", visibility="private")
    await db.commit()
    unregistered = SourceRef(kind=SourceKind.CANON_NOTE, id=uuid.uuid4())
    refs = [
        ref(vis), ref(hidden), SourceRef(kind=SourceKind.JOURNAL, id=uuid.uuid4(), field="narrative"),
        ref(vis, kind=SourceKind.PLAYER_JOURNAL),  # wrong kind
        ref(vis, field="shorthand"), ref(vis, field=None), unregistered, ref(vis), ref(mine), ref(theirs),
        ref(vis, field="no_such_field"),
    ]
    p = await world.ctx(db, "p")
    gm = await world.ctx(db, "owner")
    with caplog.at_level(logging.WARNING, logger="app.access.sources"):
        assert await visible_refs(db, refs, p) == [ref(vis), ref(mine)]
        cited = await resolve_sources(db, refs, p)
        await resolve_sources(db, refs, gm)
    assert [c.ref for c in cited] == [ref(vis), ref(mine)]
    assert all(isinstance(c, ResolvedSource) for c in cited)
    assert cited[0].quote == "The party met Zorblax." and cited[0].title == "Journal entry"
    assert cited[1].title == "Player journal"
    assert "SECRETWORD" not in json.dumps([c.model_dump(mode="json") for c in cited])
    assert [r for r in await visible_refs(db, refs, gm)] == [
        ref(vis), ref(hidden), ref(vis, field="shorthand"), ref(vis, field=None), ref(mine), ref(theirs),
    ]
    gm_cited = {c.ref: c for c in await resolve_sources(db, refs, gm)}
    assert gm_cited[ref(vis, field="shorthand")].quote == "SECRETWORD"
    missing_logs = [r for r in caplog.records if "resolver_missing" in r.getMessage()]
    assert len(missing_logs) == 1 and "canon_note" in missing_logs[0].getMessage()


async def test_resolve_sources_with_a_role_map(db, world):
    from app.access import role_map

    mine = await _campaign(db, world.p, "P's own")
    own = await add_entry(db, mine, world.p, "Own GM prose.", shorthand="OWNSHORTHAND")
    in_a = await add_entry(db, world.a, world.owner, "A's prose.", shorthand="SECRETWORD")
    await db.commit()
    roles = await role_map(db, world.p)
    # P is GM of their own Campaign (whole record ok) and a Player in A
    # (Narrative only; whole record never).
    assert await visible_refs(db, [ref(own, None), ref(in_a, None), ref(in_a)], roles) == [ref(own, None), ref(in_a)]


def test_register_resolver_rules():
    assert {"journal", "player_journal"} <= set(registered_resolvers())
    with pytest.raises(ValueError):
        register_resolver(SourceKind.JOURNAL, lambda row, r: ("t", "q"))
    with pytest.raises(ValueError):
        register_resolver("not_a_kind", lambda row, r: ("t", "q"))
    with pytest.raises(ValueError):  # no model: nothing to check visibility against
        register_resolver(SourceKind.CANON_NOTE, lambda row, r: ("t", "q"))
    # Re-registering the same resolver is a no-op.
    assert register_resolver(SourceKind.JOURNAL, access_sources.resolve_journal,
                             model=access_sources.JournalEntry) is access_sources.resolve_journal


# ── Chat: Player and GM ────────────────────────────────────────────────────

async def test_player_chat_is_party_shaped_and_cites_only_visible(db, world, client):
    vis = await add_entry(db, world.a, world.owner, "The party met Zorblax at the Drowsy Dragon.",
                          shorthand="SECRETWORD Zorblax is a lich")
    gm_only = await add_entry(db, world.a, world.owner, "Zorblax GMONLYTEXT plots.", visibility="gm")
    db.add(ShorthandTerm(user_id=world.owner.id, campaign_id=world.a, term="GLOSSTERM", meaning="GLOSSMEANING"))
    await _fake_llm_for(db, world.owner, world.p)
    body = {"message": QUESTION, "campaign_id": str(world.a)}

    with llm_provider.capture() as cap:
        r = await client.post("/api/chat/", headers=bearer(world.p), json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    for secret in ("SECRETWORD", "GLOSSTERM", "GMONLYTEXT"):
        assert secret not in r.text and secret not in prompt_text(cap)
    keys = keys_anywhere(data)
    assert "shorthand" not in keys and "system_prompt" not in keys
    assert data["canon_sources"] == []
    assert [s["id"] for s in data["sources"]] == [str(vis.id)]
    assert str(gm_only.id) not in {c["id"] for c in data["retrieval"]["candidates"]}
    assert [c["ref"] for c in data["citations"]] == [
        {"kind": "journal", "id": str(vis.id), "field": "narrative", "span": None}]
    assert data["citations"][0]["quote"].startswith("The party met Zorblax")

    # Stored: {role, content, refs, grounded}; the user turn {role, content, refs: []}.
    session = await db.get(ChatSession, uuid.UUID(data["session_id"]))
    await db.refresh(session)
    assert session.messages[0] == {"role": "user", "content": QUESTION, "refs": []}
    assert session.messages[1] == {"role": "assistant", "content": data["reply"],
                                   "refs": [stored_ref(vis)], "grounded": True}

    # Streaming: the same projection in the meta event.
    with llm_provider.capture() as cap:
        r = await client.post("/api/chat/stream", headers=bearer(world.p), json=body)
    assert r.status_code == 200
    meta = sse_meta(r.text)
    assert "shorthand" not in keys_anywhere(meta) and "system_prompt" not in keys_anywhere(meta)
    assert [c["ref"]["id"] for c in meta["citations"]] == [str(vis.id)] and meta["canon_sources"] == []
    for secret in ("SECRETWORD", "GLOSSTERM", "GMONLYTEXT"):
        assert secret not in r.text and secret not in prompt_text(cap)


async def test_gm_chat_keeps_shorthand_glossary_and_trace(db, world, client):
    vis = await add_entry(db, world.a, world.owner, "The party met Zorblax at the Drowsy Dragon.",
                          shorthand="SECRETWORD Zorblax is a lich")
    db.add(ShorthandTerm(user_id=world.owner.id, campaign_id=world.a, term="GLOSSTERM", meaning="GLOSSMEANING"))
    await _fake_llm_for(db, world.owner)
    body = {"message": QUESTION, "campaign_id": str(world.a)}
    with llm_provider.capture() as cap:
        r = await client.post("/api/chat/", headers=bearer(world.owner), json=body)
    assert r.status_code == 200, r.text
    system = cap.calls[-1].messages[0]["content"]
    assert "SECRETWORD" in system and "GLOSSTERM" in system and "- Notes" in system
    data = r.json()
    assert "SECRETWORD" in data["retrieval"]["system_prompt"]
    assert data["sources"][0]["shorthand"].startswith("SECRETWORD")
    assert all("shorthand" in c for c in data["retrieval"]["candidates"])
    assert [c["ref"] for c in data["citations"]] == [{"kind": "journal", "id": str(vis.id), "field": None,
                                                     "span": None}]
    with llm_provider.capture() as cap:
        r = await client.post("/api/chat/stream", headers=bearer(world.owner), json=body)
    assert "SECRETWORD" in sse_meta(r.text)["retrieval"]["system_prompt"]


async def test_a_gm_only_change_leaves_a_players_chat_unchanged(db, world, client):
    await add_entry(db, world.a, world.owner, "The party met Zorblax at the Drowsy Dragon.")
    other = await add_entry(db, world.a, world.owner, "The road north was quiet.")
    await _fake_llm_for(db, world.p)
    body = {"message": QUESTION, "campaign_id": str(world.a)}

    def trace(data):
        return ([(c["id"], c["lexical_rank"], c["used"]) for c in data["retrieval"]["candidates"]],
                [s["id"] for s in data["sources"]], [c["ref"]["id"] for c in data["citations"]])

    before = trace((await client.post("/api/chat/", headers=bearer(world.p), json=body)).json())
    assert before[2]
    # GM-only: a hidden entry, and the Shorthand of a visible one.
    await add_entry(db, world.a, world.owner, "Zorblax Zorblax Zorblax in secret.", visibility="gm")
    other.shorthand = "Zorblax Zorblax Zorblax"
    await reindex_gm(db, other)
    await db.commit()
    assert trace((await client.post("/api/chat/", headers=bearer(world.p), json=body)).json()) == before


# ── Redaction on read and replay ───────────────────────────────────────────

async def test_since_hidden_and_legacy_messages_are_redacted_and_never_replayed(db, world, client):
    vis = await add_entry(db, world.a, world.owner, "The inn was quiet.")
    later_hidden = await add_entry(db, world.a, world.owner, "The vault lies under the inn.")
    await db.commit()
    session = await add_session(db, world.p, [
        {"role": "user", "content": "Tell me about the inn.", "refs": []},
        {"role": "assistant", "content": "VISIBLEREPLY quiet.", "refs": [stored_ref(vis)], "grounded": True},
        {"role": "user", "content": "And the vault?", "refs": []},
        {"role": "assistant", "content": "HIDDENREPLY under the inn.", "refs": [stored_ref(later_hidden)],
         "grounded": True},
        {"role": "user", "content": "LEGACYQUESTION"},
        {"role": "assistant", "content": "LEGACYREPLY"},
    ], campaign_id=world.a)
    later_hidden.visibility = "gm"
    await db.commit()

    r = await client.get(f"/api/chat/sessions/{session.id}", headers=bearer(world.p))
    assert r.status_code == 200, r.text
    msgs = r.json()["messages"]
    assert [m["redacted"] for m in msgs] == [False, False, False, True, True, True]
    for m in msgs[3:]:
        assert m["content"] == REDACTED_NOTICE and m["refs"] == []
    assert "HIDDENREPLY" not in r.text and "LEGACY" not in r.text
    assert msgs[1]["refs"] == [{"kind": "journal", "id": str(vis.id), "field": "narrative", "span": None}]

    await _fake_llm_for(db, world.p)
    for url in ("/api/chat/", "/api/chat/stream"):
        with llm_provider.capture() as cap:
            r = await client.post(url, headers=bearer(world.p), json={
                "message": "Tell me more", "campaign_id": str(world.a), "session_id": str(session.id)})
        assert r.status_code == 200, r.text
        text = prompt_text(cap)
        assert "VISIBLEREPLY" in text
        assert "HIDDENREPLY" not in text and "LEGACY" not in text
        final = cap.calls[-1].messages
        for m in final[1:]:
            assert set(m) == {"role", "content"}
        # Nothing relevant retrieved: the grounding note is in the final user turn.
        assert final[-1]["role"] == "user" and final[-1]["content"].startswith("[Note from the app")
    # The stored messages are never rewritten: redaction is on read.
    await db.refresh(session)
    assert session.messages[3]["content"] == "HIDDENREPLY under the inn."

    # A GM ctx of their own: legacy messages are shown.
    gm_session = await add_session(db, world.owner, [{"role": "user", "content": "LEGACYQUESTION"},
                                                     {"role": "assistant", "content": "LEGACYREPLY"}],
                                   campaign_id=world.a)
    r = await client.get(f"/api/chat/sessions/{gm_session.id}", headers=bearer(world.owner))
    assert r.status_code == 200 and not any(m["redacted"] for m in r.json()["messages"])
    assert "LEGACYREPLY" in r.text


async def test_campaign_less_session_redacts_after_a_demotion(db, world, client):
    entry = await add_entry(db, world.a, world.owner, "Prose in A.", shorthand="SECRETWORD")
    await db.commit()
    session = await add_session(db, world.co_gm, [
        {"role": "user", "content": "q", "refs": []},
        {"role": "assistant", "content": "GMCITED", "refs": [stored_ref(entry, None)], "grounded": True},
        {"role": "assistant", "content": "LEGACYREPLY"},
    ])
    url = f"/api/chat/sessions/{session.id}"
    r = await client.get(url, headers=bearer(world.co_gm))
    assert r.status_code == 200, r.text
    assert [m["redacted"] for m in r.json()["messages"]] == [False, False, False]
    member = (await db.execute(sa.select(CampaignMember).where(CampaignMember.user_id == world.co_gm.id))).scalar_one()
    member.role = CampaignRole.PLAYER
    await db.commit()
    r = await client.get(url, headers=bearer(world.co_gm))
    assert [m["redacted"] for m in r.json()["messages"]] == [False, True, True]
    assert "GMCITED" not in r.text and "LEGACYREPLY" not in r.text


# ── Archived sessions ──────────────────────────────────────────────────────

async def test_archived_sessions(db, world, client):
    await _fake_llm_for(db, world.owner, world.p)
    p_archived = await add_session(db, world.p, [{"role": "user", "content": "ARCHIVEDTEXT", "refs": []}],
                                   campaign_id=world.a, archived=True, title="P archived")
    p_live = await add_session(db, world.p, [], campaign_id=world.a, title="P live")
    gm_archived = await add_session(db, world.owner, [{"role": "user", "content": "x", "refs": []}],
                                    campaign_id=world.a, archived=True)
    missing = await client.get(f"/api/chat/sessions/{MISSING}", headers=bearer(world.p))
    assert missing.status_code == 404 and missing.json() == NOT_FOUND

    r = await client.get("/api/chat/sessions", headers=bearer(world.p))
    listed = {s["id"] for s in r.json()}
    assert str(p_live.id) in listed and str(p_archived.id) not in listed
    url = f"/api/chat/sessions/{p_archived.id}"
    for method in ("GET", "DELETE"):
        r = await client.request(method, url, headers=bearer(world.p))
        assert r.status_code == 404 and r.content == missing.content, (method, r.text)
    body = {"message": "hi", "campaign_id": str(world.a)}
    r = await client.post("/api/chat/", headers=bearer(world.p), json={**body, "session_id": str(p_archived.id)})
    assert r.status_code == 404 and r.json() == NOT_FOUND
    assert await db.get(ChatSession, p_archived.id) is not None

    # A GM ctx of the same user: listed and readable, read-only (no POST, no DELETE).
    r = await client.get("/api/chat/sessions", headers=bearer(world.owner))
    assert {s["id"]: s for s in r.json()}[str(gm_archived.id)]["archived_at"] is not None
    gm_url = f"/api/chat/sessions/{gm_archived.id}"
    assert (await client.get(gm_url, headers=bearer(world.owner))).status_code == 200
    r = await client.post("/api/chat/", headers=bearer(world.owner), json={**body, "session_id": str(gm_archived.id)})
    assert r.status_code == 404 and r.json() == NOT_FOUND
    r = await client.delete(gm_url, headers=bearer(world.owner))
    assert r.status_code == 404 and r.json() == NOT_FOUND
    assert await db.get(ChatSession, gm_archived.id) is not None
    # In member preview the GM lists as a Player: the archived session is absent.
    r = await client.get("/api/chat/sessions", headers={**bearer(world.owner), PREVIEW_HEADER: "member"})
    assert str(gm_archived.id) not in {s["id"] for s in r.json()}


# ── Mismatches and denials: one 404 ────────────────────────────────────────

async def test_session_and_campaign_mismatches_are_404(db, world, client):
    await _fake_llm_for(db, world.p, world.owner)
    mine = await _campaign(db, world.p, "P's own")
    q_session = await add_session(db, world.q, [], campaign_id=world.a)
    p_other = await add_session(db, world.p, [], campaign_id=mine)
    p_in_a = await add_session(db, world.p, [], campaign_id=world.a)
    outsider = await create_user(db, "pc_outsider")
    hidden = await _campaign(db, outsider, "Hidden")
    a = str(world.a)
    cases = [
        {"message": "hi", "campaign_id": a, "session_id": MISSING},
        {"message": "hi", "campaign_id": a, "session_id": "not-a-uuid"},
        {"message": "hi", "campaign_id": a, "session_id": str(q_session.id)},   # another user's
        {"message": "hi", "campaign_id": a, "session_id": str(p_other.id)},     # another Campaign
        {"message": "hi", "session_id": str(p_in_a.id)},                        # campaign-less vs A
        {"message": "hi", "campaign_id": str(hidden)},                          # not the user's Campaign
        {"message": "hi", "campaign_id": "not-a-uuid"},
        {"message": "hi", "campaign_id": MISSING},
    ]
    for url in ("/api/chat/", "/api/chat/stream"):
        for case in cases:
            r = await client.post(url, headers=bearer(world.p), json=case)
            assert r.status_code == 404 and r.json() == NOT_FOUND, (url, case, r.text)
    # Another user's session through the session routes.
    for method in ("GET", "DELETE"):
        r = await client.request(method, f"/api/chat/sessions/{q_session.id}", headers=bearer(world.p))
        assert r.status_code == 404 and r.json() == NOT_FOUND
    # A POST in member preview is 404 (preview only narrows).
    r = await client.post("/api/chat/", headers={**bearer(world.owner), PREVIEW_HEADER: "member"},
                          json={"message": "hi", "campaign_id": a})
    assert r.status_code == 404 and r.json() == NOT_FOUND
    assert await db.scalar(sa.select(sa.func.count()).select_from(ChatSession)
                           .where(ChatSession.user_id == world.owner.id)) == 0


# ── Search ─────────────────────────────────────────────────────────────────

async def test_search_skips_redacted_messages(db, world, client):
    hidden = await add_entry(db, world.a, world.owner, "Hidden prose.", visibility="gm")
    await db.commit()
    messages = [{"role": "user", "content": "plain question", "refs": []},
                {"role": "assistant", "content": "ZEBRAWORD cited", "refs": [stored_ref(hidden)], "grounded": True},
                {"role": "assistant", "content": "QUAGGAWORD legacy"}]
    p_session = await add_session(db, world.p, messages, campaign_id=world.a)
    gm_session = await add_session(db, world.owner, messages, campaign_id=world.a)
    for word in ("ZEBRAWORD", "quaggaword"):
        r = await client.get(f"/api/chat/sessions?search={word}", headers=bearer(world.p))
        assert r.status_code == 200 and str(p_session.id) not in {s["id"] for s in r.json()}
        r = await client.get(f"/api/chat/sessions?search={word}", headers=bearer(world.owner))
        assert str(gm_session.id) in {s["id"] for s in r.json()}
    r = await client.get("/api/chat/sessions?search=plain", headers=bearer(world.p))
    assert str(p_session.id) in {s["id"] for s in r.json()}


async def test_sessions_of_a_campaign_left_are_hidden(db, world, client):
    session = await add_session(db, world.q, [{"role": "user", "content": "hi", "refs": []}], campaign_id=world.a)
    await db.execute(sa.delete(CampaignMember).where(CampaignMember.user_id == world.q.id))
    await db.commit()
    r = await client.get("/api/chat/sessions", headers=bearer(world.q))
    assert str(session.id) not in {s["id"] for s in r.json()}
    r = await client.get(f"/api/chat/sessions/{session.id}", headers=bearer(world.q))
    assert r.status_code == 404 and r.json() == NOT_FOUND


# ── Review additions ───────────────────────────────────────────────────────

async def test_campaign_less_replay_and_search_after_a_demotion(db, world, client):
    entry = await add_entry(db, world.a, world.owner, "Prose in A.", shorthand="SECRETWORD")
    await db.commit()
    await _fake_llm_for(db, world.co_gm)
    session = await add_session(db, world.co_gm, [
        {"role": "user", "content": "q", "refs": []},
        {"role": "assistant", "content": "GMCITED", "refs": [stored_ref(entry, None)], "grounded": True},
        {"role": "assistant", "content": "LEGACYREPLY"},
    ])
    member = (await db.execute(sa.select(CampaignMember).where(CampaignMember.user_id == world.co_gm.id))).scalar_one()
    member.role = CampaignRole.PLAYER
    await db.commit()
    with llm_provider.capture() as cap:
        r = await client.post("/api/chat/", headers=bearer(world.co_gm),
                              json={"message": "And then?", "session_id": str(session.id)})
    assert r.status_code == 200, r.text
    prompt = prompt_text(cap)
    assert cap.calls and "GMCITED" not in prompt and "LEGACYREPLY" not in prompt
    for word in ("GMCITED", "LEGACYREPLY"):
        r = await client.get(f"/api/chat/sessions?search={word}", headers=bearer(world.co_gm))
        assert str(session.id) not in {s["id"] for s in r.json()}


async def test_archived_campaign_less_session_is_hidden_from_a_player(db, world, client):
    # A Campaign deleted under an archived session leaves campaign_id NULL.
    session = await add_session(db, world.p, [{"role": "user", "content": "x", "refs": []}], archived=True)
    r = await client.get("/api/chat/sessions", headers=bearer(world.p))
    assert str(session.id) not in {s["id"] for s in r.json()}
    r = await client.get(f"/api/chat/sessions/{session.id}", headers=bearer(world.p))
    assert r.status_code == 404 and r.json() == NOT_FOUND


async def test_preview_reads_of_sessions(db, world, client):
    gm_session = await add_session(db, world.owner, [{"role": "assistant", "content": "LEGACYREPLY"}],
                                   campaign_id=world.a)
    own = await add_session(db, world.owner, [{"role": "assistant", "content": "OWNLEGACY"}])
    preview = {**bearer(world.owner), PREVIEW_HEADER: "member"}
    # A Campaign session in preview: the member view owns no session, the one 404.
    r = await client.get(f"/api/chat/sessions/{gm_session.id}", headers=preview)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    # A campaign-less one reads as a Player everywhere: legacy turns redacted;
    # deleting it in preview is 404.
    r = await client.get(f"/api/chat/sessions/{own.id}", headers=preview)
    assert r.status_code == 200 and "OWNLEGACY" not in r.text
    r = await client.delete(f"/api/chat/sessions/{own.id}", headers=preview)
    assert r.status_code == 404
    assert await db.get(ChatSession, own.id) is not None


async def test_a_failing_resolver_drops_only_its_ref(db, world, monkeypatch, caplog):
    vis = await add_entry(db, world.a, world.owner, "The party met Zorblax.")
    other = await add_entry(db, world.a, world.p, "P's note.", kind="player")
    await db.commit()
    resolvers = dict(access_sources._RESOLVERS)
    bad = access_sources.Resolver(SourceKind.PLAYER_JOURNAL, lambda row, r: ("only one",),
                                  access_sources.JournalEntry,
                                  access_sources._RESOLVERS[SourceKind.PLAYER_JOURNAL].where)
    resolvers[SourceKind.PLAYER_JOURNAL] = bad
    monkeypatch.setattr(access_sources, "_RESOLVERS", resolvers)
    p = await world.ctx(db, "p")
    with caplog.at_level(logging.WARNING, logger="app.access.sources"):
        cited = await resolve_sources(db, [ref(vis), ref(other)], p)
    assert [c.ref for c in cited] == [ref(vis)]
    assert any("resolver_failed" in r.getMessage() for r in caplog.records)


def test_source_ref_span_must_be_ordered():
    SourceRef(kind=SourceKind.JOURNAL, id=uuid.uuid4(), span=(0, 4))
    for bad in ((-1, 2), (5, 2)):
        with pytest.raises(ValueError):
            SourceRef(kind=SourceKind.JOURNAL, id=uuid.uuid4(), span=bad)
