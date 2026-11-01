"""E0-Access.7: Party-only search and retrieval.

`hybrid_search_journal` with a ctx (GM columns for a GM, Party columns and
`visible_clause` for anyone else, `narrative_only`, `entry_ids`), the
campaign-less `hybrid_search_own_journals`, the source providers,
`index_party_fields` on every write path, the backfill script, the per
(Campaign, author) dedup key, and the routes switched to the ctx path
(journal search, NPC/Quest entries, chat). Embeddings are the deterministic
`app.clients.fakes.fake_vector` (random-looking unit vectors: two different
texts are ~1.0 apart, so no vector hit passes the 0.65 gate and only lexical
evidence can unlock it).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings, strategies as st

from app.access import GM, ctx_for, role_map, scoped_select
from app.clients.fakes import fake_vector
from app.db.models.campaign import Campaign, Genre
from app.db.models.journal import JournalEntry
from app.db.models.shorthand import ShorthandTerm
from app.db.models.user_settings import UserSettings
from app.schemas.sources import SourceKind
from app.services import dedup_service, embedding_service, journal_service, llm_provider, retrieval_service
from app.services.retrieval_service import (
    SOURCE_DOCUMENTS, hybrid_search_journal, hybrid_search_own_journals, index_party_fields, registered_sources,
    retrieve_sources,
)
from scripts import backfill_party_embeddings
from tests.ev4.fixtures import bearer, create_user, make_member


@pytest.fixture(autouse=True)
def fake_embed(monkeypatch):
    monkeypatch.setattr(embedding_service, "embed", fake_vector)


class FakeValkey:
    """The two calls dedup_service makes (the suite does not start Valkey)."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return int(key in self.keys)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.keys[key] = value


@pytest.fixture(autouse=True)
def fake_valkey(monkeypatch) -> FakeValkey:
    store = FakeValkey()
    monkeypatch.setattr(dedup_service, "get_valkey", lambda: store)
    return store


@dataclass
class World:
    owner: object
    co_gm: object
    p: object
    q: object
    a: uuid.UUID

    async def ctx(self, db, who: str, campaign_id: uuid.UUID | None = None):
        return await ctx_for(db, getattr(self, who).id, campaign_id or self.a)


async def _campaign(db, owner, name: str = "A") -> uuid.UUID:
    cid = uuid.uuid4()
    db.add(Campaign(id=cid, user_id=owner.id, name=name, genre=Genre.fantasy))
    await db.commit()
    return cid


@pytest_asyncio.fixture
async def world(db) -> World:
    owner = await create_user(db, "pr_owner")
    a = await _campaign(db, owner)
    co_gm = await make_member(db, role="co_gm", campaign_id=a, label="pr_co_gm")
    p = await make_member(db, role="player", campaign_id=a, label="pr_p")
    q = await make_member(db, role="player", campaign_id=a, label="pr_q")
    return World(owner, co_gm, p, q, a)


async def add_entry(db, campaign_id, author, narrative: str, *, shorthand: str = "plain notes", kind: str = "gm",
                    visibility: str = "party", party: bool = True, vectors: bool = True) -> JournalEntry:
    """An entry as the write path stores it: narrative_tsv and embedding over
    Shorthand + Narrative, then the Party fields (unless party=False)."""
    entry = JournalEntry(user_id=author.id, campaign_id=campaign_id, shorthand=shorthand, narrative=narrative,
                         entry_hash=uuid.uuid4().hex, kind=kind, visibility=visibility)
    db.add(entry)
    await reindex_gm(db, entry, vectors=vectors)
    if party:
        await index_party_fields(db, entry)
    await db.flush()
    return entry


async def reindex_gm(db, entry, *, vectors: bool = True) -> None:
    await db.flush()
    doc = f"{entry.shorthand} {entry.narrative}"
    await db.execute(sa.text("UPDATE journal_entries SET narrative_tsv = to_tsvector('english', :doc) WHERE id = :id"),
                     {"doc": doc, "id": str(entry.id)})
    if vectors:
        entry.embedding = fake_vector(doc)


async def search(db, query, ctx, **kw):
    return await hybrid_search_journal(db, query, ctx=ctx, **kw)


def ids(results) -> set[uuid.UUID]:
    return {r.entry.id for r in results}


def trace(results) -> list[tuple]:
    return [(r.entry.id, r.vector_distance, r.lexical_rank, round(r.rrf_score, 10), r.passed_gate, r.used)
            for r in results]


def find(results, entry_id):
    return next((r for r in results if r.entry.id == entry_id), None)


# ── The matrix ─────────────────────────────────────────────────────────────

async def test_shorthand_only_word_never_matches_or_moves_a_player(db, world):
    hidden = await add_entry(db, world.a, world.owner, "The party rested at the old inn.",
                             shorthand="Zorblax hides in the cellar")
    await add_entry(db, world.a, world.owner, "The road north was quiet.")
    question = "Where is Zorblax hiding?"
    p = await world.ctx(db, "p")

    before = await search(db, question, p)
    r = find(before, hidden.id)
    assert r is None or (r.lexical_rank is None and not r.used and not r.passed_gate)

    # A GM-only edit: more of the word in the Shorthand, GM columns rewritten.
    hidden.shorthand = "Zorblax Zorblax Zorblax and Quillon"
    await reindex_gm(db, hidden)
    await index_party_fields(db, hidden)
    await db.flush()
    after = await search(db, question, p)
    assert trace(after) == trace(before)

    # The GM still finds it through the Shorthand (narrative_tsv, proper-noun bypass).
    gm = find(await search(db, question, await world.ctx(db, "owner")), hidden.id)
    assert gm is not None and gm.lexical_rank is not None and gm.used
    co_gm = find(await search(db, question, await world.ctx(db, "co_gm")), hidden.id)
    assert co_gm is not None and co_gm.used


async def test_player_candidates_are_the_entries_they_may_see(db, world):
    e1 = await add_entry(db, world.a, world.owner, "A lantern in the hall.")
    e2 = await add_entry(db, world.a, world.p, "My own lantern diary.", kind="player", visibility="private")
    e3 = await add_entry(db, world.a, world.q, "Q's private lantern.", kind="player", visibility="private")
    e4 = await add_entry(db, world.a, world.owner, "The GM's lantern secret.", visibility="gm")
    e5 = await add_entry(db, world.a, world.q, "Q shares a lantern story.", kind="player", visibility="party")
    assert ids(await search(db, "lantern", await world.ctx(db, "p"))) == {e1.id, e2.id, e5.id}
    assert ids(await search(db, "lantern", await world.ctx(db, "q"))) == {e1.id, e3.id, e5.id}
    assert ids(await search(db, "lantern", await world.ctx(db, "owner"))) == {e1.id, e2.id, e3.id, e4.id, e5.id}


async def test_no_party_vector_is_not_a_vector_candidate(db, world):
    control = await add_entry(db, world.a, world.owner, "The tower bell rang twice.")
    unfilled = await add_entry(db, world.a, world.owner, "Goblins crossed the river.")
    unfilled.party_embedding = None
    await db.flush()
    p_results = await search(db, "anything unrelated", await world.ctx(db, "p"))
    assert unfilled.id not in ids(p_results)  # no fallback to `embedding`
    assert find(p_results, control.id).vector_distance is not None
    gm_results = await search(db, "anything unrelated", await world.ctx(db, "owner"))
    assert find(gm_results, unfilled.id).vector_distance is not None  # GM: `embedding`, as before


async def test_entry_ids_only_narrow(db, world):
    a = await add_entry(db, world.a, world.owner, "The lantern glowed.")
    await add_entry(db, world.a, world.owner, "A second lantern.")
    hidden = await add_entry(db, world.a, world.owner, "A GM-only lantern.", visibility="gm")
    p = await world.ctx(db, "p")
    assert ids(await search(db, "lantern", p, entry_ids={a.id})) == {a.id}
    assert await search(db, "lantern", p, entry_ids=set()) == []
    assert await search(db, "lantern", p, entry_ids={hidden.id}) == []  # visibility first
    assert ids(await search(db, "lantern", await world.ctx(db, "owner"), entry_ids={hidden.id})) == {hidden.id}


async def test_narrative_only_uses_party_columns_for_a_gm(db, world):
    hidden = await add_entry(db, world.a, world.owner, "The party slept.", shorthand="Zorblax lurks")
    visible = await add_entry(db, world.a, world.owner, "Zorblax waved from the bridge.")
    unfilled = await add_entry(db, world.a, world.owner, "The mill burned.")
    unfilled.party_embedding = None
    await db.flush()
    gm = await world.ctx(db, "owner")
    full = await search(db, "Who is Zorblax?", gm)
    narrow = await search(db, "Who is Zorblax?", gm, narrative_only=True)
    assert find(full, hidden.id).used
    r = find(narrow, hidden.id)
    assert r is not None and r.lexical_rank is None and not r.used  # only a (gated-out) vector candidate
    assert find(narrow, visible.id).used
    assert unfilled.id not in ids(narrow)
    assert ids(narrow) <= ids(full)


async def test_campaign_scope(db, world):
    other = await _campaign(db, world.owner, "B")
    await add_entry(db, other, world.owner, "A lantern elsewhere.")
    mine = await add_entry(db, world.a, world.owner, "A lantern here.")
    assert ids(await search(db, "lantern", await world.ctx(db, "owner"))) == {mine.id}


# ── Write paths ────────────────────────────────────────────────────────────

async def _party_state(db, entry_id):
    row = (await db.execute(sa.select(
        JournalEntry.party_tsv == sa.func.to_tsvector("english", JournalEntry.narrative),
        JournalEntry.party_tsv.op("@@")(sa.func.plainto_tsquery("english", "zorblax")),
        JournalEntry.narrative_tsv.op("@@")(sa.func.plainto_tsquery("english", "zorblax")),
        JournalEntry.party_embedding,
    ).where(JournalEntry.id == entry_id))).one()
    return row


def _close(a, b) -> bool:
    return a is not None and len(a) == len(b) and all(abs(x - y) < 1e-5 for x, y in zip(a, b))


async def test_create_journal_entry_indexes_party_fields(db, world, monkeypatch):
    monkeypatch.setattr(journal_service, "extract_tags", lambda text: [])
    narrative = "The party crossed the bridge at dawn."
    entry = await journal_service.create_journal_entry(
        db, world.owner.id, world.a, "Zorblax watched", uuid.uuid4().hex, None, narrative=narrative)
    tsv_ok, party_hit, gm_hit, vec = await _party_state(db, entry.id)
    assert tsv_ok and not party_hit and gm_hit
    assert _close(list(vec), fake_vector(narrative))


async def test_embedding_failure_leaves_party_embedding_null_and_saves(db, world, monkeypatch):
    def broken(text):
        raise RuntimeError("Embedding model not loaded")

    monkeypatch.setattr(journal_service, "extract_tags", lambda text: [])
    monkeypatch.setattr(embedding_service, "embed", broken)
    entry = await journal_service.create_journal_entry(
        db, world.owner.id, world.a, "notes", uuid.uuid4().hex, None, narrative="Saved anyway.")
    tsv_ok, _, _, vec = await _party_state(db, entry.id)
    assert tsv_ok and vec is None


async def test_index_party_fields_clears_a_stale_vector(db, world, monkeypatch):
    entry = await add_entry(db, world.a, world.owner, "Old words.")
    assert entry.party_embedding is not None
    entry.narrative = "New words entirely."
    def broken(text):
        raise RuntimeError("down")

    monkeypatch.setattr(embedding_service, "embed", broken)
    await index_party_fields(db, entry)
    await db.flush()
    tsv_ok, _, _, vec = await _party_state(db, entry.id)
    assert tsv_ok and vec is None


async def test_reindex_route_sets_party_fields(db, world, client):
    entry = await add_entry(db, world.a, world.owner, "The tower fell.", shorthand="Zorblax did it",
                            party=False, vectors=False)
    await db.commit()
    r = await client.post(f"/api/journals/reindex?campaign_id={world.a}", headers=bearer(world.owner))
    assert r.status_code == 200, r.text
    tsv_ok, party_hit, gm_hit, vec = await _party_state(db, entry.id)
    assert tsv_ok and not party_hit and gm_hit
    assert _close(list(vec), fake_vector("The tower fell."))


# ── Backfill ───────────────────────────────────────────────────────────────

async def test_backfill_is_idempotent_and_reports_failures(db, world):
    plain = await add_entry(db, world.a, world.owner, "Backfill me please.", party=False)
    stale = await add_entry(db, world.a, world.owner, "Stale tsv here.")
    failing = await add_entry(db, world.a, world.owner, "EMBED-FAIL on purpose.", party=False)
    await db.execute(sa.update(JournalEntry).where(JournalEntry.id == stale.id)
                     .values(party_tsv=sa.func.to_tsvector("english", "something else"), party_embedding=None)
                     .execution_options(synchronize_session=False))
    await db.commit()

    def embed(text):
        if "EMBED-FAIL" in text:
            raise RuntimeError("model down")
        return fake_vector(text)

    dry = await backfill_party_embeddings.backfill(db, dry_run=True, embed=embed)
    assert dry.tsv_updated >= 3 and dry.embedding_pending >= 3 and dry.embedded == 0
    assert (await _party_state(db, plain.id))[3] is None  # a dry run writes nothing

    first = await backfill_party_embeddings.backfill(db, batch_size=2, embed=embed)
    assert first.tsv_updated >= 3 and first.embedded >= 2 and first.batches >= 2
    assert failing.id in first.failed
    for e in (plain, stale):
        tsv_ok, _, _, vec = await _party_state(db, e.id)
        assert tsv_ok and _close(list(vec), fake_vector(e.narrative))
    tsv_ok, _, _, vec = await _party_state(db, failing.id)
    assert tsv_ok and vec is None
    assert "failed" in first.summary()

    second = await backfill_party_embeddings.backfill(db, batch_size=2, embed=embed)
    assert second.tsv_updated == 0 and second.embedded == 0
    assert failing.id in second.failed


# ── Dedup ──────────────────────────────────────────────────────────────────

async def test_dedup_key_is_per_campaign_and_author(fake_valkey):
    a, b, u, v = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    h = uuid.uuid4().hex
    await dedup_service.store_hash(a, u, h)
    assert list(fake_valkey.keys) == [f"dedup:{a}:{u}:{h}"]
    assert await dedup_service.check_hash(a, u, h)
    assert not await dedup_service.check_hash(b, u, h)
    assert not await dedup_service.check_hash(a, v, h)


async def test_generate_409_only_for_the_same_campaign_and_author(db, world, client, monkeypatch):
    monkeypatch.setattr(journal_service, "extract_tags", lambda text: [])
    other = await _campaign(db, world.owner, "B")
    h = uuid.uuid4().hex

    async def post(user, campaign_id):
        return await client.post("/api/journals/generate", headers=bearer(user), json={
            "notes": "n", "campaign_id": str(campaign_id), "entry_hash": h, "narrative": "Something happened."})

    assert (await post(world.owner, world.a)).status_code == 201
    assert (await post(world.owner, world.a)).status_code == 409
    assert (await post(world.owner, other)).status_code == 201
    assert (await post(world.p, world.a)).status_code == 201


# ── Providers ──────────────────────────────────────────────────────────────

async def test_source_providers(db, world, monkeypatch):
    assert {SourceKind.JOURNAL.value, SourceKind.PLAYER_JOURNAL.value, SOURCE_DOCUMENTS} <= set(registered_sources())
    gm_entry = await add_entry(db, world.a, world.owner, "A lantern.")
    player_entry = await add_entry(db, world.a, world.p, "My lantern.", kind="player")
    p = await world.ctx(db, "p")
    found = await retrieve_sources(db, "lantern", ctx=p, kinds=[SourceKind.JOURNAL, SourceKind.PLAYER_JOURNAL])
    assert ids(found["journal"]) == {gm_entry.id}
    assert ids(found["player_journal"]) == {player_entry.id}

    calls = []

    async def canon(db_, query_text, user_id, campaign_id, **kw):
        calls.append((user_id, campaign_id))
        return "canon", ["Doc"]

    monkeypatch.setattr(retrieval_service.source_service, "retrieve_canon_context", canon)
    assert (await retrieve_sources(db, "q", ctx=p, kinds=[SOURCE_DOCUMENTS]))[SOURCE_DOCUMENTS] == (None, [])
    assert calls == []
    gm = await world.ctx(db, "owner")
    assert (await retrieve_sources(db, "q", ctx=gm, kinds=[SOURCE_DOCUMENTS]))[SOURCE_DOCUMENTS] == ("canon", ["Doc"])
    assert calls == [(world.owner.id, world.a)]
    with pytest.raises(KeyError):
        await retrieve_sources(db, "q", ctx=gm, kinds=["nope"])


async def test_own_journals_only_in_gm_campaigns(db, world):
    mine = await _campaign(db, world.p, "P's own")
    in_mine = await add_entry(db, mine, world.p, "A lantern in my campaign.")
    q_in_mine = await make_member(db, role="player", campaign_id=mine, user=world.q)
    await add_entry(db, mine, q_in_mine, "Q's lantern in P's campaign.", kind="player")
    await add_entry(db, world.a, world.p, "P's lantern in A.", kind="player")
    await add_entry(db, world.a, world.owner, "The owner's lantern in A.")
    roles = await role_map(db, world.p)
    assert roles[mine] == GM and roles[world.a] == "player"
    assert ids(await hybrid_search_own_journals(db, "lantern", roles=roles)) == {in_mine.id}


# ── Routes ─────────────────────────────────────────────────────────────────

async def test_journal_search_route(db, world, client):
    hidden = await add_entry(db, world.a, world.owner, "The party slept.", shorthand="SECRETWORD lantern")
    seen = await add_entry(db, world.a, world.owner, "A lantern in the hall.")
    await add_entry(db, world.a, world.owner, "The GM's lantern.", visibility="gm")
    await db.commit()
    url = f"/api/journals/?campaign_id={world.a}&search=lantern"

    r = await client.get(url, headers=bearer(world.p))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["id"] for i in body["items"]] == [str(seen.id)] and body["total"] == 1
    assert "shorthand" not in body["items"][0] and "tags" in body["items"][0]
    assert "SECRETWORD" not in r.text

    r = await client.get(url, headers=bearer(world.owner))
    body = r.json()
    assert str(seen.id) in {i["id"] for i in body["items"]} and str(hidden.id) in {i["id"] for i in body["items"]}
    assert body["total"] == 3 and all("shorthand" in i for i in body["items"])

    # Cross-Campaign: P's Player Campaign A plus their own GM Campaign.
    mine = await _campaign(db, world.p, "P's own")
    own = await add_entry(db, mine, world.p, "Party prose.", shorthand="lantern only in notes")
    await db.commit()
    r = await client.get("/api/journals/?search=lantern", headers=bearer(world.p))
    body = r.json()
    assert {i["id"] for i in body["items"]} == {str(seen.id), str(own.id)}
    assert all("shorthand" not in i for i in body["items"])


async def test_entity_entries_routes(db, world, client):
    from app.db.models.npc import NpcEntry
    from app.db.models.quest import Quest

    npc = NpcEntry(user_id=world.owner.id, campaign_id=world.a, name="Barnaby")
    quest = Quest(user_id=world.owner.id, campaign_id=world.a, title="Find the caravan")
    db.add_all([npc, quest])
    await add_entry(db, world.a, world.owner, "We met someone.", shorthand="Barnaby Find the caravan")
    seen = await add_entry(db, world.a, world.owner, "Barnaby said: Find the caravan.")
    await add_entry(db, world.a, world.owner, "Barnaby, GM-only. Find the caravan.", visibility="gm")
    await db.commit()
    for url in (f"/api/npcs/{npc.id}/entries", f"/api/quests/{quest.id}/entries"):
        r = await client.get(url, headers=bearer(world.p))
        assert r.status_code == 200, r.text
        assert [i["id"] for i in r.json()] == [str(seen.id)]
        assert "shorthand" not in r.json()[0] and r.json()[0]["narrative"]
        r = await client.get(url, headers=bearer(world.owner))
        assert len(r.json()) == 3 and all("shorthand" in i for i in r.json())


async def _fake_llm_for(db, *users) -> None:
    for u in users:
        db.add(UserSettings(user_id=u.id, llm_provider="fake"))
    await db.commit()


async def test_chat_player_gets_no_gm_text_and_gm_keeps_it(db, world, client):
    await add_entry(db, world.a, world.owner, "The party met Zorblax at the Drowsy Dragon.",
                    shorthand="SECRETWORD Zorblax is a lich")
    db.add(ShorthandTerm(user_id=world.owner.id, campaign_id=world.a, term="GLOSSTERM", meaning="GLOSSMEANING"))
    await _fake_llm_for(db, world.owner, world.p)
    body = {"message": "What happened with Zorblax?", "campaign_id": str(world.a)}

    with llm_provider.capture() as cap:
        r = await client.post("/api/chat/", headers=bearer(world.p), json=body)
    assert r.status_code == 200, r.text
    prompt = json.dumps([c.messages for c in cap.calls])
    for secret in ("SECRETWORD", "GLOSSTERM", "GLOSSMEANING", "- Notes"):
        assert secret not in prompt and secret not in r.text
    data = r.json()
    assert data["sources"] and all(s["shorthand"] == "" for s in data["sources"])
    assert data["retrieval"]["system_prompt"] is None
    assert all(c["shorthand"] == "" for c in data["retrieval"]["candidates"])

    with llm_provider.capture() as cap:
        r = await client.post("/api/chat/stream", headers=bearer(world.p), json=body)
    assert r.status_code == 200
    assert "SECRETWORD" not in r.text and "GLOSSTERM" not in r.text
    assert "SECRETWORD" not in json.dumps([c.messages for c in cap.calls])
    meta = json.loads(r.text.split("event: meta\ndata: ", 1)[1].split("\n", 1)[0])
    assert meta["retrieval"]["system_prompt"] is None

    # Positive control: the GM's prompt still has the Shorthand and the glossary.
    with llm_provider.capture() as cap:
        r = await client.post("/api/chat/", headers=bearer(world.owner), json=body)
    assert r.status_code == 200, r.text
    system = cap.calls[-1].messages[0]["content"]
    assert "SECRETWORD" in system and "GLOSSTERM" in system and "- Notes" in system
    assert "SECRETWORD" in r.json()["retrieval"]["system_prompt"]


async def test_chat_without_campaign_uses_own_gm_entries(db, world, client):
    mine = await _campaign(db, world.p, "P's own")
    own = await add_entry(db, mine, world.p, "The party met Zorblax at the gate.")
    await add_entry(db, world.a, world.p, "Zorblax in A, my Player entry.", kind="player")
    await add_entry(db, world.a, world.owner, "Zorblax in A, the GM's entry.", shorthand="SECRETWORD")
    await _fake_llm_for(db, world.p)
    r = await client.post("/api/chat/", headers=bearer(world.p), json={"message": "Tell me about Zorblax"})
    assert r.status_code == 200, r.text
    assert {c["id"] for c in r.json()["retrieval"]["candidates"]} == {str(own.id)}
    assert "SECRETWORD" not in r.text


# ── Property: narrative_only and entry_ids only narrow ────────────────────

WORDS = ("lantern", "Zorblax", "mill", "dragon", "Quillon", "river", "goblin", "tower")
words = st.sampled_from(WORDS)
row_spec = st.fixed_dictionaries({
    "shorthand": st.lists(words, min_size=1, max_size=3),
    "narrative": st.lists(words, min_size=1, max_size=4),
    "visibility": st.sampled_from(("party", "gm", "private")),
    "kind": st.sampled_from(("gm", "player")),
    "author": st.sampled_from(("owner", "p", "q")),
    "party_vector": st.booleans(),
})


@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(data=st.data())
async def test_narrow_only_property(db, world, data):
    # At most 8 rows: below the per-retriever pool of 10, so the wider call
    # never truncates a candidate the narrower one keeps.
    rows = data.draw(st.lists(row_spec, min_size=1, max_size=8), label="rows")
    query = " ".join(data.draw(st.lists(words, min_size=1, max_size=3), label="query"))
    who = data.draw(st.sampled_from(("owner", "co_gm", "p", "q")), label="ctx")
    picks = data.draw(st.one_of(st.none(), st.sets(st.integers(0, len(rows) - 1))), label="entry_ids")
    sp = await db.begin_nested()
    try:
        made = []
        for s in rows:
            e = await add_entry(db, world.a, getattr(world, s["author"]), " ".join(s["narrative"]) + ".",
                                shorthand=" ".join(s["shorthand"]), kind=s["kind"], visibility=s["visibility"])
            if not s["party_vector"]:
                e.party_embedding = None
            made.append(e)
        await db.flush()
        ctx = await world.ctx(db, who)
        visible = {e.id for e in (await db.execute(scoped_select(JournalEntry, ctx))).scalars().all()}
        base = ids(await search(db, query, ctx))
        narrow = ids(await search(db, query, ctx, narrative_only=True))
        assert base <= visible and narrow <= visible
        assert narrow <= base
        if picks is not None:
            chosen = {made[i].id for i in picks}
            for kw in ({}, {"narrative_only": True}):
                got = ids(await search(db, query, ctx, entry_ids=chosen, **kw))
                assert got <= chosen and got <= ids(await search(db, query, ctx, **kw))
    finally:
        await sp.rollback()
