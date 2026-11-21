"""EV-4 probes for the Chronicler (E0-Access.8, E0-QA.14).

Stored sessions: the list, one session and delete. Each authenticated actor
gets two sessions of their own in Campaign A, live and archived, holding a
turn that cites a Party entry (plain text) and turns a non-GM may no longer
see (a reply citing a GM-only entry, and a legacy turn with no `refs`),
whose texts are canaries. The Owner's seeded session (canary title and
messages) is another user's to everyone else.

POST /api/chat/ and /stream: one question per hidden source (the inn, the
Shorthand, a GM-only entry, a source document, the glossary). Each ask runs
under the captured-context check with forbidden markers (the glossary and
canon blocks, `Notes` lines, plain Shorthand and secret text) for a non-GM,
and a GM run of the same question must capture that hidden content (the
check is never vacuous). The trace (candidates, sources, canon sources,
system prompt, citations and the fake reply, whose digest covers the whole
prompt) is identical before and after a GM-only change. A demoted Co-GM's
sessions in A are gone (list, GET, POST) and their old uploads in A no
longer reach a chat with no Campaign.
"""
from __future__ import annotations

import dataclasses
import json
import uuid

import sqlalchemy as sa

from tests.ev4.families import (
    assert_captured_context_clean, assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary,
)
from tests.ev4.fixtures import GM, PLAYER, mint_canary
from tests.ev4.probes._support import (
    MISSING, add_chat_session, assert_same_answer, authenticated, is_gm_of_a, redacted_messages, row_count,
)
from tests.ev4.probes.retrieval import add_entry as add_indexed_entry
from tests.ev4.probes.retrieval import fake_embeddings, gm_only_change, index_seeded, use_fake_llm
from tests.ev4.registry import ev4_probe
from tests.ev4.report import record_leak

ACTORS = ("anon_share", "player", "cross_gm_player", "co_gm")
SESSIONS = "/api/chat/sessions"
MISSING_URL = f"{SESSIONS}/{MISSING}"


async def _own_sessions(ev4, actor):
    """(live, archived) sessions of `actor` in A, both with redacted turns."""
    live = await add_chat_session(ev4, actor.user_id, await redacted_messages(ev4))
    archived = await add_chat_session(ev4, actor.user_id, await redacted_messages(ev4), archived=True)
    return live, archived


def _owner_session(ev4):
    return ev4.a.ids["chat_sessions"][0]


async def _listed(actor, url: str) -> set[str]:
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    return {s["id"] for s in r.json()}


async def _gm_only_change(ev4) -> None:
    """Changes only a GM of A may see: the Shorthand of the cited Party entry,
    and a new session of the Owner's that mentions the searched words."""
    from app.db.models.journal import JournalEntry

    a = ev4.a.campaign_id
    entry = await ev4.db.get(JournalEntry, ev4.a.ids["journal_entries"][0])
    entry.shorthand = f"{entry.shorthand} {mint_canary('SHORTHAND', a).token} quiet guards"
    await ev4.db.commit()
    await add_chat_session(ev4, ev4.a.owner_id, [
        {"role": "user", "content": "Was the inn quiet?", "refs": []},
        {"role": "assistant", "content": f"{mint_canary('CHATREPLY', a).token} quiet guards.", "refs": []},
    ])


@ev4_probe("GET", "/api/chat/sessions", actors=ACTORS)
async def probe_chat_sessions(ev4, actor):
    r = await actor.get(SESSIONS)
    assert_no_canary(actor, r)
    if not authenticated(actor):
        return
    live, archived = await _own_sessions(ev4, actor)
    gm = is_gm_of_a(ev4, actor)
    listed = await _listed(actor, SESSIONS)
    assert str(live) in listed, listed  # non-vacuous: the actor's own live session
    if str(_owner_session(ev4)) in listed:
        record_leak(f"EV-4 leak: {actor.name} lists another user's chat session", [str(_owner_session(ev4))])
    if not gm and str(archived) in listed:
        record_leak(f"EV-4 leak: {actor.name} (not a GM of A) lists an archived session", [str(archived)])
    if gm:
        assert str(archived) in listed, listed  # a GM ctx still reads archived sessions

    # Search matches only what the actor may still read: "guards" is only
    # in the reply citing a GM-only entry, "quiet" in the visible reply.
    found = await _listed(actor, f"{SESSIONS}?search=guards")
    if not gm and found & {str(live), str(archived)}:
        record_leak(f"EV-4 leak: {actor.name}'s search matched a redacted message", sorted(found))
    if gm:
        assert str(live) in found, found
    assert str(live) in await _listed(actor, f"{SESSIONS}?search=quiet")
    await assert_counts_and_ranking_unchanged(
        actor, [SESSIONS, f"{SESSIONS}?search=quiet", f"{SESSIONS}?search=guards"], lambda: _gm_only_change(ev4))


@ev4_probe("GET", "/api/chat/sessions/{session_id}", actors=ACTORS)
async def probe_chat_session(ev4, actor):
    # Another user's session, a malformed id and a missing one are the same 404.
    await assert_hidden_equals_missing(actor, f"{SESSIONS}/{_owner_session(ev4)}", MISSING_URL)
    await assert_hidden_equals_missing(actor, f"{SESSIONS}/not-a-uuid", MISSING_URL)
    if not authenticated(actor):
        return
    live, archived = await _own_sessions(ev4, actor)
    gm = is_gm_of_a(ev4, actor)
    url = f"{SESSIONS}/{live}"
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    messages = r.json()["messages"]
    redacted = [m for m in messages if m["redacted"]]
    if gm:
        assert not redacted, messages  # a GM ctx sees what the reply cited, and legacy turns
    else:
        # Non-vacuous: the cited-GM-only reply and both legacy turns.
        assert len(redacted) == 3 and all(m["refs"] == [] for m in redacted), messages
        assert "shorthand" not in r.text
    if gm:
        r = await actor.get(f"{SESSIONS}/{archived}")
        assert r.status_code == 200, r.text  # read-only for a GM ctx
    else:
        await assert_hidden_equals_missing(actor, f"{SESSIONS}/{archived}", MISSING_URL)
    await assert_counts_and_ranking_unchanged(actor, url, lambda: _gm_only_change(ev4))


@ev4_probe("DELETE", "/api/chat/sessions/{session_id}", actors=ACTORS)
async def probe_chat_session_delete(ev4, actor):
    from app.db.models.chat import ChatSession

    owner_session = _owner_session(ev4)
    await assert_hidden_equals_missing(actor, f"{SESSIONS}/{owner_session}", MISSING_URL, method="DELETE")
    if await row_count(ev4, ChatSession, ChatSession.id == owner_session) != 1:
        record_leak(f"EV-4 leak: {actor.name} deleted another user's chat session", [str(owner_session)])
    if not authenticated(actor):
        return
    live, archived = await _own_sessions(ev4, actor)
    # Archived sessions are read-only, even to a GM ctx: DELETE answers like a missing one.
    await assert_hidden_equals_missing(actor, f"{SESSIONS}/{archived}", MISSING_URL, method="DELETE")
    if await row_count(ev4, ChatSession, ChatSession.id == archived) != 1:
        record_leak(f"EV-4 leak: {actor.name} deleted an archived session", [str(archived)])
    r = await actor.delete(f"{SESSIONS}/{live}")
    assert_no_canary(actor, r)
    assert r.status_code == 204, r.text  # the actor's own live session
    assert await row_count(ev4, ChatSession, ChatSession.id == live) == 0


# ── POST /api/chat/ and /api/chat/stream ───────────────────────────────────

CHAT_URL, STREAM_URL = "/api/chat/", "/api/chat/stream"
MISSING_ID = MISSING

# One question per hidden source. Each passes retrieval's gate for a GM:
# a proper noun from the entry ("Drowsy Dragon", "Obsidian Crown"), or the
# source chunk embedded as the question is (fake vectors: distance 0).
INN_QUESTION = "What happened at the Drowsy Dragon with the innkeeper?"
SHORTHAND_QUESTION = "Is the innkeeper of the Drowsy Dragon the lich?"
GM_ENTRY_QUESTION = "Where is the Obsidian Crown hidden?"
SOURCE_QUESTION = "Where is the lich's phylactery kept?"
GLOSSARY_QUESTION = "What does our table's shorthand mean?"
QUESTIONS = (
    ("inn", INN_QUESTION),
    ("shorthand", SHORTHAND_QUESTION),
    ("gm_entry", GM_ENTRY_QUESTION),
    ("source", SOURCE_QUESTION),
    ("glossary", GLOSSARY_QUESTION),
)

# Context markers (app/services/chat_service.build_chat_messages) and plain
# secret text a non-GM's prompt must never hold. None is in a question.
GLOSSARY_BLOCK = "[This campaign's shorthand glossary:]"
CANON_BLOCK = "[Canonical campaign source material"
NOTES_LINE = "- Notes"
GM_ENTRY_SECRET = "lies in the vault beneath the old mill"
SOURCE_SECRET = "phylactery is in the cellar"  # seeds/ev4_canary.json SOURCECHUNK
SHORTHAND_SECRETS = ("innkeeper is the lich", "caravan taken by the cult")  # the seeded Shorthand
FORBIDDEN = (GLOSSARY_BLOCK, CANON_BLOCK, NOTES_LINE, GM_ENTRY_SECRET, SOURCE_SECRET, *SHORTHAND_SECRETS)


def _gm_must(hidden: dict) -> dict[str, tuple[str, ...]]:
    """What a GM's captured prompt for each question must hold: the hidden
    content the same question would leak to anyone else."""
    return {
        "inn": (GLOSSARY_BLOCK, NOTES_LINE),
        "shorthand": (NOTES_LINE, SHORTHAND_SECRETS[0]),
        "gm_entry": (GM_ENTRY_SECRET, hidden["gm_entry"]),
        "source": (CANON_BLOCK, SOURCE_SECRET),
        "glossary": (GLOSSARY_BLOCK, hidden["term"]),
    }


async def _hidden_sources(ev4) -> dict:
    """The GM-only answers: a GM entry naming the Obsidian Crown (indexed),
    and the seeded source chunk embedded as SOURCE_QUESTION is."""
    from app.db.models.source import SourceChunk
    from app.services import embedding_service

    a = ev4.a.campaign_id
    canary = mint_canary("GMENTRY", a)
    await add_indexed_entry(ev4, f"{canary.token} The Obsidian Crown {GM_ENTRY_SECRET}.", visibility="gm")
    chunk = await ev4.db.get(SourceChunk, ev4.a.ids["source_chunks"][0])
    chunk.embedding = await embedding_service.embed(SOURCE_QUESTION)
    await ev4.db.commit()
    return {"gm_entry": canary.token, "term": ev4.a.canary("TERM").token}


def _sse_event(text: str, name: str) -> dict:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line == f"event: {name}" and i + 1 < len(lines) and lines[i + 1].startswith("data: "):
            return json.loads(lines[i + 1][len("data: "):])
    raise ValueError(f"no {name} event in the stream: {text[:200]!r}")


def _trace(body: dict, reply) -> list:
    """What the ask decided, as the actor sees it: candidates, sources, canon
    sources, the system prompt, citations (ids, order, count), and the reply
    (the fake LLM's digest covers the whole prompt)."""
    retrieval = body.get("retrieval") or {}
    return [
        [(c["id"], c["vector_distance"], c["lexical_rank"], c["passed_gate"], c["used"])
         for c in retrieval.get("candidates", [])],
        [s["id"] for s in body.get("sources", [])],
        body.get("canon_sources"),
        retrieval.get("system_prompt"),
        [(c["ref"]["kind"], c["ref"]["id"], c["ref"].get("field"), c["title"], c["quote"])
         for c in body.get("citations", [])],
        reply,
    ]


def _body(url: str, r) -> dict:
    return _sse_event(r.text, "meta") if url == STREAM_URL else r.json()


def _trace_of(url: str, r) -> list:
    if url == STREAM_URL:
        return _trace(_sse_event(r.text, "meta"), _sse_event(r.text, "done").get("reply"))
    body = r.json()
    return _trace(body, body.get("reply"))


def _check_trace_unchanged(actor, label: str, before: list, after: list) -> None:
    if before != after:
        record_leak(f"EV-4 leak: a GM-only change moved {actor.name}'s retrieval trace at {label}",
                    [f"before {before!r:.300}", f"after {after!r:.300}"])


def _gm_anywhere(actor) -> bool:
    return any(grant == GM for grant in actor.grants.values())


def _member(actor, campaign_id) -> bool:
    return authenticated(actor) and actor.grants.get(campaign_id) in (GM, PLAYER)


async def _captured_prompt(actor, url: str, body: dict) -> tuple:
    """(response, prompt text) of `actor`'s ask, for a positive control. A
    failed ask or one that reached no LLM is probe misuse (ValueError)."""
    from app.services import llm_provider

    with llm_provider.capture() as cap:
        r = await actor.post(url, json=body)
    if r.status_code != 200 or not cap.calls:
        raise ValueError(f"positive control {url} {body} as {actor.name}: {r.status_code}, {len(cap.calls)} "
                         f"LLM call(s) ({r.text[:200]!r})")
    return r, json.dumps([c.messages for c in cap.calls], ensure_ascii=False)


async def _gm_control(ev4, url: str, hidden: dict) -> None:
    """The same questions as the Owner: each captured prompt holds the hidden
    content, so a non-GM's clean prompt means something."""
    gm = await ev4.actor("gm_owner")
    await use_fake_llm(ev4, gm)
    must = _gm_must(hidden)
    for key, question in QUESTIONS:
        _, text = await _captured_prompt(gm, url, {"message": question, "campaign_id": str(ev4.a.campaign_id)})
        missing = [m for m in must[key] if m not in text]
        if missing:
            raise ValueError(f"GM positive control for the {key} question at {url}: the GM's prompt lacks "
                             f"{missing}; the non-GM check would be vacuous")


async def _chat_probe(ev4, actor, url: str) -> None:
    a = ev4.a.campaign_id
    await use_fake_llm(ev4, actor)
    with fake_embeddings():
        await index_seeded(ev4)
        hidden = await _hidden_sources(ev4)
        if authenticated(actor):
            await _gm_control(ev4, url, hidden)
        gated = () if is_gm_of_a(ev4, actor) else FORBIDDEN
        a_calls = 1 if _member(actor, a) else 0

        async def ask(body: dict, label: str, forbidden=gated, min_calls=a_calls):
            r = await assert_captured_context_clean(actor, lambda: actor.post(url, json=body), label=f"{url} {label}",
                                                    forbidden=forbidden, min_calls=min_calls)
            assert_no_canary(actor, r)
            return r

        before: dict[str, list] = {}
        for key, question in QUESTIONS:
            r = await ask({"message": question, "campaign_id": str(a)}, key)
            if authenticated(actor):
                assert r.status_code == 200, r.text
                before[key] = _trace_of(url, r)
        # No Campaign, and Campaign B (GM: cross_gm_player only).
        await ask({"message": INN_QUESTION}, "no campaign", forbidden=() if _gm_anywhere(actor) else FORBIDDEN,
                  min_calls=1 if authenticated(actor) else 0)
        if ev4.b is not None:
            b = ev4.b.campaign_id
            await ask({"message": INN_QUESTION, "campaign_id": str(b)}, "campaign B",
                      forbidden=() if actor.grants.get(b) == GM else FORBIDDEN,
                      min_calls=1 if _member(actor, b) else 0)
        if not authenticated(actor):
            return
        inn = before["inn"]
        assert any(row[4] for row in inn[0]), inn  # non-vacuous: the inn entry is used
        assert inn[4], inn  # ... and cited

        # A GM-only change (Shorthand edit, a GM entry, a Private entry): every
        # question's trace, reply included, is unchanged.
        await gm_only_change(ev4, "innkeeper")
        for key, question in QUESTIONS:
            r = await ask({"message": question, "campaign_id": str(a)}, f"{key} after")
            assert r.status_code == 200, r.text
            _check_trace_unchanged(actor, f"{url} {key}", before[key], _trace_of(url, r))

        # A session of the actor's in A holding turns they may no longer see
        # (a reply citing a GM-only entry, legacy turns): none of it goes back
        # into the prompt (nor the query rewrite), and the reply is clean.
        body = {"message": INN_QUESTION, "campaign_id": str(a)}
        sid = await add_chat_session(ev4, actor.user_id, await redacted_messages(ev4))
        r = await ask({**body, "session_id": str(sid)}, "replay")
        assert r.status_code == 200, r.text
        # An archived session is never posted to: the one 404, as for a missing one.
        archived = await add_chat_session(ev4, actor.user_id, await redacted_messages(ev4), archived=True)
        assert_same_answer(actor, await actor.post(url, json={**body, "session_id": str(archived)}),
                           await actor.post(url, json={**body, "session_id": MISSING_ID}), f"{url} archived session")


@ev4_probe("POST", "/api/chat/")
async def probe_chat(ev4, actor):
    await _chat_probe(ev4, actor, CHAT_URL)


@ev4_probe("POST", "/api/chat/stream")
async def probe_chat_stream(ev4, actor):
    await _chat_probe(ev4, actor, STREAM_URL)


# ── A demoted Co-GM ────────────────────────────────────────────────────────

DEMOTED_QUESTION = "Where does the green dragon sleep?"
DEMOTED_SECRET = "the green dragon sleeps under the old bridge"


async def _member_row(ev4, user_id) -> uuid.UUID:
    from app.db.models.campaign_member import CampaignMember

    return (await ev4.db.execute(sa.select(CampaignMember.id).where(
        CampaignMember.campaign_id == ev4.a.campaign_id, CampaignMember.user_id == user_id))).scalar_one()


async def _demotion_probe(ev4, actor, url: str) -> None:
    """While Co-GM of A the actor uploads a source document in A and chats
    in a live session there. Once the Owner demotes them to Player: the
    session is not listed, GET and POST with its id answer like a missing
    one, a new message in A carries no archived turn, and a chat with no
    Campaign reads none of their A uploads (prompt, canon_sources, trace)."""
    from app.db.models.source import SourceChunk, SourceDocument
    from app.services import embedding_service

    a = ev4.a.campaign_id
    await use_fake_llm(ev4, actor)
    with fake_embeddings():
        await index_seeded(ev4)
        title = mint_canary("XSRC", a).token
        doc = SourceDocument(id=uuid.uuid4(), user_id=actor.user_id, campaign_id=a, title=title,
                             filename=f"{title}.txt")
        ev4.db.add(doc)
        await ev4.db.flush()
        ev4.db.add(SourceChunk(id=uuid.uuid4(), source_document_id=doc.id, user_id=actor.user_id, campaign_id=a,
                               chunk_index=0, content=f"{mint_canary('SOURCECHUNK', a).token} {DEMOTED_SECRET}.",
                               embedding=await embedding_service.embed(DEMOTED_QUESTION)))
        await ev4.db.commit()
        turn = mint_canary("CHATCOGM", a).token
        session = await add_chat_session(ev4, actor.user_id, [
            {"role": "user", "content": f"{turn} where does it sleep?", "refs": []},
            {"role": "assistant", "content": f"{turn} {DEMOTED_SECRET}.", "refs": [], "grounded": False},
        ])

        # Positive controls while Co-GM: the upload reaches a chat with no
        # Campaign, and the session's turns are replayed in A.
        _, text = await _captured_prompt(actor, url, {"message": DEMOTED_QUESTION})
        if DEMOTED_SECRET not in text:
            raise ValueError(f"positive control: the Co-GM's chat with no Campaign at {url} did not read their "
                             "upload; the demotion check would be vacuous")
        _, text = await _captured_prompt(actor, url, {"message": DEMOTED_QUESTION, "campaign_id": str(a),
                                                      "session_id": str(session)})
        if turn not in text:
            raise ValueError(f"positive control: the Co-GM's session turns were not replayed at {url}")

        owner = await ev4.actor("gm_owner")
        r = await owner.patch(f"/api/campaigns/{a}/members/{await _member_row(ev4, actor.user_id)}",
                              json={"role": "player"})
        assert r.status_code == 200 and r.json()["role"] == "player", r.text
        demoted = dataclasses.replace(actor, name=f"{actor.name}+demoted", grants={**actor.grants, a: PLAYER})

        listed = await demoted.get(SESSIONS)
        assert_no_canary(demoted, listed)
        assert listed.status_code == 200, listed.text
        if str(session) in {s["id"] for s in listed.json()}:
            record_leak(f"EV-4 leak: {demoted.name} still lists their archived Co-GM session", [str(session)])
        await assert_hidden_equals_missing(demoted, f"{SESSIONS}/{session}", MISSING_URL)
        body = {"message": DEMOTED_QUESTION, "campaign_id": str(a)}
        assert_same_answer(demoted, await demoted.post(url, json={**body, "session_id": str(session)}),
                           await demoted.post(url, json={**body, "session_id": MISSING_ID}),
                           f"{url} archived Co-GM session")

        forbidden = (*FORBIDDEN, DEMOTED_SECRET)
        r = await assert_captured_context_clean(demoted, lambda: demoted.post(url, json=body),
                                                label=f"{url} new message in A after the demotion",
                                                forbidden=forbidden, min_calls=1)
        assert_no_canary(demoted, r)
        assert r.status_code == 200, r.text
        r = await assert_captured_context_clean(demoted, lambda: demoted.post(url, json={"message": DEMOTED_QUESTION}),
                                                label=f"{url} no Campaign after the demotion",
                                                forbidden=forbidden, min_calls=1)
        assert_no_canary(demoted, r)
        assert r.status_code == 200, r.text
        canon = _body(url, r).get("canon_sources")
        if canon:
            record_leak(f"EV-4 leak: {demoted.name}'s chat with no Campaign still reads their A uploads",
                        [repr(canon)[:200]])


@ev4_probe("POST", "/api/chat/", actors=("co_gm",))
async def probe_chat_demoted_co_gm(ev4, actor):
    await _demotion_probe(ev4, actor, CHAT_URL)


@ev4_probe("POST", "/api/chat/stream", actors=("co_gm",))
async def probe_chat_stream_demoted_co_gm(ev4, actor):
    await _demotion_probe(ev4, actor, STREAM_URL)
