"""EV-4 probes for Party-only search and retrieval (E0-Access.7).

Journal search, NPC/Quest entry lists, the Chronicler (blocking and
streaming) and reindex. Every probe first indexes the seeded entries the way
the write paths do (narrative_tsv + embedding over Shorthand + Narrative,
then `index_party_fields`), with deterministic fake embeddings, so the GM
and Party columns are both populated and a non-GM search has something to
find. The GM-only change used by the counts-and-ranking checks puts the
query word into a seeded entry's Shorthand and adds a GM-only and a
Private-to-the-Owner entry whose Narratives contain it.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import sqlalchemy as sa

from tests.ev4.families import assert_captured_context_clean, assert_counts_and_ranking_unchanged, assert_no_canary
from tests.ev4.fixtures import mint_canary
from tests.ev4.registry import ev4_probe
from tests.ev4.report import record_leak

INN_QUESTION = "What happened at the Drowsy Dragon with the innkeeper?"


@contextmanager
def fake_embeddings():
    """embedding_service.embed -> app.clients.fakes.fake_vector for the block."""
    from app.clients.fakes import fake_vector
    from app.services import embedding_service

    real = embedding_service.embed
    embedding_service.embed = fake_vector
    try:
        yield
    finally:
        embedding_service.embed = real


async def _index(db, entry) -> None:
    """What journal_service.create_journal_entry writes for a saved entry."""
    from app.services import embedding_service
    from app.services.retrieval_service import index_party_fields

    doc = f"{entry.shorthand} {entry.narrative}"
    await db.flush()
    await db.execute(sa.text("UPDATE journal_entries SET narrative_tsv = to_tsvector('english', :doc) WHERE id = :id"),
                     {"doc": doc, "id": str(entry.id)})
    entry.embedding = embedding_service.embed(doc)
    await index_party_fields(db, entry)


async def index_seeded(ev4) -> None:
    from app.db.models.journal import JournalEntry

    for seeded in (ev4.a, ev4.b):
        if seeded is None:
            continue
        for entry_id in seeded.ids.get("journal_entries", []):
            await _index(ev4.db, await ev4.db.get(JournalEntry, entry_id))
    await ev4.db.commit()


async def add_entry(ev4, narrative: str, *, visibility: str = "party", shorthand: str | None = None,
                    author: uuid.UUID | None = None, kind: str = "gm") -> uuid.UUID:
    from app.db.models.journal import JournalEntry

    a = ev4.a.campaign_id
    entry = JournalEntry(
        id=uuid.uuid4(), user_id=author or ev4.a.owner_id, campaign_id=a,
        shorthand=shorthand if shorthand is not None else mint_canary("SHORTHAND", a).token,
        narrative=narrative, entry_hash=uuid.uuid4().hex, kind=kind, visibility=visibility,
    )
    ev4.db.add(entry)
    await _index(ev4.db, entry)
    await ev4.db.commit()
    return entry.id


async def gm_only_change(ev4, word: str) -> None:
    """Changes only a GM of A may see: `word` in the Shorthand of a seeded
    entry whose Narrative lacks it, plus a GM-only entry and an entry Private
    to the Owner that mention it."""
    from app.db.models.journal import JournalEntry

    a = ev4.a.campaign_id
    entry = await ev4.db.get(JournalEntry, ev4.a.ids["journal_entries"][1])  # its Narrative lacks the word
    entry.shorthand = f"{entry.shorthand} {word} {word} {word}"
    await _index(ev4.db, entry)
    await ev4.db.commit()
    await add_entry(ev4, f"{mint_canary('GMENTRY', a).token} {word} {word} plots in secret.", visibility="gm")
    await add_entry(ev4, f"{mint_canary('PRIVATEENTRY', a).token} {word} {word} is the Owner's note.",
                    visibility="private")


async def use_fake_llm(ev4, actor) -> None:
    """A personal provider for the actor, so chat resolves an LLM config
    (answered by the fake LLM under ENVIRONMENT=test) instead of 402."""
    from app.db.models.user_settings import UserSettings

    if actor.user_id is None:
        return
    existing = await ev4.db.scalar(sa.select(UserSettings).where(UserSettings.user_id == actor.user_id))
    if existing is None:
        ev4.db.add(UserSettings(user_id=actor.user_id, llm_provider="fake"))
    else:
        existing.llm_provider = "fake"
    await ev4.db.commit()


def _trace(body: dict) -> list:
    """What retrieval decided, as the actor sees it: candidates and sources."""
    retrieval = body.get("retrieval") or {}
    return [
        [(c["id"], c["vector_distance"], c["lexical_rank"], c["passed_gate"], c["used"])
         for c in retrieval.get("candidates", [])],
        [s["id"] for s in body.get("sources", [])],
        body.get("canon_sources"),
        retrieval.get("system_prompt"),
    ]


def _sse_meta(text: str) -> dict:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line == "event: meta" and i + 1 < len(lines) and lines[i + 1].startswith("data: "):
            return json.loads(lines[i + 1][len("data: "):])
    raise ValueError(f"no meta event in the stream: {text[:200]!r}")


def _check_trace_unchanged(actor, url: str, before: list, after: list) -> None:
    if before != after:
        record_leak(f"EV-4 leak: a GM-only change moved {actor.name}'s retrieval trace at {url}",
                    [f"before {before!r:.300}", f"after {after!r:.300}"])


# ── Journal search ─────────────────────────────────────────────────────────

@ev4_probe("GET", "/api/journals/")
async def probe_journal_search(ev4, actor):
    a = ev4.a.campaign_id
    with fake_embeddings():
        await index_seeded(ev4)
        urls = [f"/api/journals/?campaign_id={a}&search=innkeeper", "/api/journals/?search=innkeeper"]
        for url in urls:
            assert_no_canary(actor, await actor.get(url))
        if actor.user_id is None:
            return
        r = await actor.get(urls[0])
        assert r.status_code == 200 and r.json()["total"] >= 1, r.text  # non-vacuous: the inn entry is found
        await assert_counts_and_ranking_unchanged(actor, urls, lambda: gm_only_change(ev4, "innkeeper"))


# ── Entries for an NPC / a Quest ───────────────────────────────────────────

async def _entity_entries_probe(ev4, actor, url: str, name: str) -> None:
    with fake_embeddings():
        await index_seeded(ev4)
        await add_entry(ev4, f"The party met {name} on the road and shared a meal.")
        r = await actor.get(url)
        assert_no_canary(actor, r)
        if actor.user_id is None:
            return
        assert r.status_code == 200 and len(r.json()) >= 1, r.text
        await assert_counts_and_ranking_unchanged(actor, url, lambda: gm_only_change(ev4, name))


@ev4_probe("GET", "/api/npcs/{npc_id}/entries")
async def probe_npc_entries(ev4, actor):
    npc_id = ev4.a.ids["npcs"][0]
    await _entity_entries_probe(ev4, actor, f"/api/npcs/{npc_id}/entries", "Barnaby")


@ev4_probe("GET", "/api/quests/{quest_id}/entries")
async def probe_quest_entries(ev4, actor):
    quest_id = ev4.a.ids["quests"][0]
    await _entity_entries_probe(ev4, actor, f"/api/quests/{quest_id}/entries", "Find the missing caravan")


# ── The Chronicler ─────────────────────────────────────────────────────────

async def _chat_probe(ev4, actor, url: str, trace_of) -> None:
    a = ev4.a.campaign_id
    await use_fake_llm(ev4, actor)
    with fake_embeddings():
        await index_seeded(ev4)
        bodies = [{"message": INN_QUESTION, "campaign_id": str(a)}, {"message": INN_QUESTION}]
        if ev4.b is not None:
            bodies.append({"message": INN_QUESTION, "campaign_id": str(ev4.b.campaign_id)})
        for body in bodies:
            r = await assert_captured_context_clean(actor, lambda: actor.post(url, json=body), label=f"{url} {body}")
            assert_no_canary(actor, r)
        if actor.user_id is None:
            return
        body = bodies[0]
        r = await actor.post(url, json=body)
        assert r.status_code == 200, r.text
        before = trace_of(r)
        assert any(row[4] for row in before[0]), before  # non-vacuous: the inn entry is used
        await gm_only_change(ev4, "innkeeper")
        r = await assert_captured_context_clean(actor, lambda: actor.post(url, json=body), label=f"{url} after")
        assert_no_canary(actor, r)
        _check_trace_unchanged(actor, url, before, trace_of(r))


@ev4_probe("POST", "/api/chat/")
async def probe_chat(ev4, actor):
    await _chat_probe(ev4, actor, "/api/chat/", lambda r: _trace(r.json()))


@ev4_probe("POST", "/api/chat/stream")
async def probe_chat_stream(ev4, actor):
    await _chat_probe(ev4, actor, "/api/chat/stream", lambda r: _trace(_sse_meta(r.text)))


# ── Reindex ────────────────────────────────────────────────────────────────

@ev4_probe("POST", "/api/journals/reindex")
async def probe_reindex(ev4, actor):
    a = ev4.a.campaign_id
    url = f"/api/journals/reindex?campaign_id={a}"
    search = f"/api/journals/?campaign_id={a}&search=innkeeper"
    with fake_embeddings():
        await index_seeded(ev4)
        assert_no_canary(actor, await actor.post(url))
        if actor.user_id is None:
            return
        gm = await ev4.actor("gm_owner")

        async def mutate():
            await gm_only_change(ev4, "innkeeper")
            r = await gm.post(url)  # the GM's reindex rewrites every row's Party fields
            assert r.status_code == 200, r.text

        await assert_counts_and_ranking_unchanged(actor, search, mutate)
