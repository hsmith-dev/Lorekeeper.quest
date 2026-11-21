"""E0-Journal.2: the journal writers recompute every index column.

`journal_service.create_journal_entry`, `update_journal_entry`,
`delete_journal_entry` and `reindex_entry` share one recompute path: tsv in
SQL from the stored row, both vectors from one `embed_many`, tags from
`ml /v1/ner` over the Narrative and the Shorthand (manual and legacy links
kept). With `ml` down the save still commits (vectors NULL, no derived tags)
and the `entry_saved` handler enqueues `journal.reembed`. The hash is the
server's. Plus a grep test: nothing outside journal_service assigns a
JournalEntry's text or index columns.

Embeddings and NER are the deterministic FakeMLClient (ENVIRONMENT=test).
"""
from __future__ import annotations

import ast
import hashlib
import logging
import re
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import HTTPException

from app.access import NotFound, ctx_for
from app.clients.errors import ModelServiceUnavailable
from app.clients.fakes import FakeMLClient, fake_vector
from app.core import hooks, pubsub, valkey_client
from app.core.hooks import HookEvent
from app.db.models.campaign import Campaign, Genre
from app.db.models.job import Job
from app.db.models.journal import JournalEntry
from app.db.models.tag import JournalTag, Tag, TagType
from app.domain.enums import JobQueue, Visibility
from app.hooks import journal as journal_hooks
from app.jobs.registry import KINDS
from app.services import dedup_service, embedding_service, journal_service, nlp_service
from tests.ev4.fixtures import bearer, create_user, make_member

BACKEND = Path(__file__).resolve().parents[1]


# ── Fixtures ───────────────────────────────────────────────────────────────

class _DownML:
    """Every ml call fails as an unreachable sidecar does."""

    async def embed(self, texts):
        raise ModelServiceUnavailable("ml sidecar unreachable at http://ml.test:8001")

    async def ner(self, text):
        raise ModelServiceUnavailable("ml sidecar unreachable at http://ml.test:8001")


@pytest.fixture(autouse=True)
def ml_up(monkeypatch):
    up = FakeMLClient()
    monkeypatch.setattr(embedding_service, "_override", up)
    monkeypatch.setattr(nlp_service, "get_ml_client", lambda: up)
    return up


@pytest.fixture
def ml_down(monkeypatch):
    down = _DownML()
    monkeypatch.setattr(embedding_service, "_override", down)
    monkeypatch.setattr(nlp_service, "get_ml_client", lambda: down)
    return down


def _ml(monkeypatch, client) -> None:
    monkeypatch.setattr(embedding_service, "_override", client)
    monkeypatch.setattr(nlp_service, "get_ml_client", lambda: client)


@pytest_asyncio.fixture(autouse=True)
async def valkey():
    """A fakeredis behind dedup_service and core.pubsub."""
    import fakeredis

    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    previous = valkey_client.set_valkey(client)
    yield client
    await hooks.drain()
    valkey_client.set_valkey(previous)
    pubsub._TRAILING.clear()
    await client.aclose()


@pytest.fixture(autouse=True)
def published(monkeypatch):
    """Every `campaign:{id}:events` publish by the journal hooks: (campaign, domain, id)."""
    calls: list[tuple] = []

    async def record(campaign_id, domain, id):  # noqa: A002
        calls.append((campaign_id, domain, id))

    monkeypatch.setattr(journal_hooks, "publish_campaign_event", record)
    return calls


@pytest.fixture
def emitted(monkeypatch):
    """Every hook event the writers emit: (event, campaign_id, refs, actor_ctx)."""
    calls: list[tuple] = []
    real = journal_service.emit

    def record(db, event, *, campaign_id, refs, actor_ctx):
        calls.append((HookEvent(event), campaign_id, refs, actor_ctx))
        real(db, event, campaign_id=campaign_id, refs=refs, actor_ctx=actor_ctx)

    monkeypatch.setattr(journal_service, "emit", record)
    return calls


@pytest_asyncio.fixture
async def world(db):
    owner = await create_user(db, "jw_owner")
    cid = uuid.uuid4()
    db.add(Campaign(id=cid, user_id=owner.id, name="JW", genre=Genre.fantasy))
    await db.commit()
    player = await make_member(db, role="player", campaign_id=cid, label="jw_p")
    gm = await ctx_for(db, owner.id, cid)
    return SimpleNamespace(owner=owner, cid=cid, player=player, gm=gm,
                           player_ctx=await ctx_for(db, player.id, cid))


async def _row(db, entry_id):
    return (await db.execute(sa.select(JournalEntry).where(JournalEntry.id == entry_id)
                             .execution_options(populate_existing=True))).scalar_one_or_none()


async def _tsv_hits(db, entry_id, word):
    q = sa.func.plainto_tsquery("english", word)
    return (await db.execute(sa.select(JournalEntry.narrative_tsv.op("@@")(q), JournalEntry.party_tsv.op("@@")(q))
                             .where(JournalEntry.id == entry_id))).one()


async def _links(db, entry_id) -> dict[tuple[str, str | None], str | None]:
    rows = (await db.execute(sa.select(Tag.name, Tag.tag_type, JournalTag.source_field)
                             .join(Tag, Tag.id == JournalTag.tag_id).where(JournalTag.journal_id == entry_id))).all()
    return {(name, getattr(tag_type, "value", tag_type)): source for name, tag_type, source in rows}


def _close(a, b) -> bool:
    return a is not None and len(a) == len(b) and all(abs(x - y) < 1e-5 for x, y in zip(a, b))


def _dedup_key(world, h) -> str:
    return f"dedup:{world.cid}:{world.owner.id}:{h}"


async def _create(db, world, notes="Mira at the mill", narrative="Borin Stonebeard travelled toward Waterdeep.",
                  **kw):
    return await journal_service.create_journal_entry(db, world.gm, notes, None, narrative=narrative, **kw)


# ── The hash ───────────────────────────────────────────────────────────────

def test_entry_hash_is_utils_hashNotes():
    # utils/hashNotes.ts: sha256(notes.trim().toLowerCase()), hex.
    assert journal_service.compute_entry_hash("  Mira AT the Mill \n") == \
        hashlib.sha256(b"mira at the mill").hexdigest()


# ── Create ─────────────────────────────────────────────────────────────────

async def test_create_with_ml_up_sets_every_index_column(db, world, emitted, published):
    entry = await _create(db, world)
    row = await _row(db, entry.id)
    assert row.entry_hash == journal_service.compute_entry_hash("Mira at the mill")
    # narrative_tsv covers Shorthand + Narrative, party_tsv the Narrative only.
    assert tuple(await _tsv_hits(db, entry.id, "mill")) == (True, False)
    assert tuple(await _tsv_hits(db, entry.id, "travelled")) == (True, True)
    assert _close(list(row.embedding), fake_vector("Mira at the mill Borin Stonebeard travelled toward Waterdeep."))
    assert _close(list(row.party_embedding), fake_vector("Borin Stonebeard travelled toward Waterdeep."))
    assert await _links(db, entry.id) == {
        ("Borin Stonebeard", "character"): "narrative", ("Waterdeep", "location"): "narrative",
        ("Mira", "character"): "shorthand",
    }
    [(event, campaign_id, refs, actor)] = emitted
    assert (event, campaign_id, actor) == (HookEvent.ENTRY_SAVED, world.cid, world.gm)
    assert refs == {"journal_id": entry.id, "kind": "gm", "previous_entry_hash": None,
                    "entry_hash": row.entry_hash, "changed_fields": ["narrative", "shorthand"]}
    await hooks.drain()
    assert published == [(world.cid, "journal", entry.id)]
    jobs = (await db.execute(sa.select(Job).where(Job.kind == "journal.reembed",
                                                  Job.campaign_id == world.cid))).scalars().all()
    assert jobs == []  # nothing fell back


async def test_create_with_ml_down_saves_and_enqueues_reembed(db, world, ml_down, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        entry = await _create(db, world)
    row = await _row(db, entry.id)
    assert row is not None and row.embedding is None and row.party_embedding is None
    assert tuple(await _tsv_hits(db, entry.id, "mill")) == (True, False)
    assert await _links(db, entry.id) == {}
    assert any("embedding skipped" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)

    await hooks.drain()
    key = journal_service.reembed_key(entry.id, row.entry_hash)
    assert key == f"journal.reembed:{entry.id}:{row.entry_hash}"
    job = (await db.execute(sa.select(Job).where(Job.idempotency_key == key)
                            .execution_options(populate_existing=True))).scalar_one()
    assert job.kind == "journal.reembed" and job.payload == {"journal_id": str(entry.id),
                                                             "entry_hash": row.entry_hash}

    # ml down: the Job raises (so it retries).
    with pytest.raises(ModelServiceUnavailable):
        await journal_service.reembed_job(job, world.gm, db)
    await db.rollback()

    # ml back: the Job fills both vectors and the tags.
    _ml(monkeypatch, FakeMLClient())
    await journal_service.reembed_job(job, world.gm, db)
    await db.commit()
    row = await _row(db, entry.id)
    assert _close(list(row.party_embedding), fake_vector(row.narrative))
    assert row.embedding is not None
    assert ("Waterdeep", "location") in await _links(db, entry.id)


async def test_reembed_job_for_an_edited_or_deleted_entry_is_a_noop(db, world, ml_down):
    entry = await _create(db, world)
    stale = SimpleNamespace(payload={"journal_id": str(entry.id), "entry_hash": "0" * 64})
    gone = SimpleNamespace(payload={"journal_id": str(uuid.uuid4()), "entry_hash": entry.entry_hash})
    # ml is down, yet neither raises: nothing to do.
    assert await journal_service.reembed_job(stale, world.gm, db) is None
    assert await journal_service.reembed_job(gone, world.gm, db) is None


def test_reembed_kind_is_registered():
    kind = KINDS["journal.reembed"]
    assert kind.queue == JobQueue.ONSAVE and kind.resources == frozenset({"cpu_heavy"})
    assert kind.live_safe is False
    assert kind.load_handler() is journal_service.reembed_job


async def test_duplicate_create_is_409(db, world):
    await _create(db, world)
    # The DB path (no Valkey check in the service): same normalized Shorthand.
    with pytest.raises(HTTPException) as exc:
        await _create(db, world, notes="  MIRA at the mill ", narrative="Other words.")
    assert exc.value.status_code == 409
    # Another author is not a duplicate.
    other = await create_user(db, "jw_other")
    c2 = uuid.uuid4()
    db.add(Campaign(id=c2, user_id=other.id, name="Other", genre=Genre.fantasy))
    await db.commit()
    await journal_service.create_journal_entry(db, await ctx_for(db, other.id, c2), "Mira at the mill", None,
                                               narrative="Fine.")


async def test_generate_route_ignores_the_client_hash_and_409s_on_the_server_one(db, world, client, valkey):
    async def post(notes, **extra):
        return await client.post("/api/journals/generate", headers=bearer(world.owner), json={
            "notes": notes, "campaign_id": str(world.cid), "narrative": "Something happened.", **extra})

    r = await post("Mira at the mill", entry_hash="h" * 64)
    assert r.status_code == 201, r.text
    h = journal_service.compute_entry_hash("Mira at the mill")
    assert (await _row(db, uuid.UUID(r.json()["id"]))).entry_hash == h
    assert await valkey.exists(_dedup_key(world, h)) == 1
    # No hash sent at all, and a different client hash: still the same notes.
    assert (await post("mira at the mill ")).status_code == 409
    assert (await post("Mira at the mill", entry_hash="x" * 64)).status_code == 409


# ── Offline / unreviewed saves ─────────────────────────────────────────────

async def test_offline_and_unreviewed_saves_land_gm(db, world, client, monkeypatch):
    r = await client.post("/api/journals/generate", headers=bearer(world.owner), json={
        "notes": "queued offline", "campaign_id": str(world.cid), "narrative": "Saved later.", "offline": True})
    assert r.status_code == 201, r.text
    assert (await _row(db, uuid.UUID(r.json()["id"]))).visibility == Visibility.GM

    reviewed = await _create(db, world, notes="reviewed", narrative="Read and kept.")
    assert (await _row(db, reviewed.id)).visibility == Visibility.PARTY

    async def drafted(*_args, **_kw):
        return "A generated narrative."

    monkeypatch.setattr(journal_service, "generate_draft_narrative", drafted)
    one_step = await journal_service.create_journal_entry(db, world.gm, "one step", None)
    row = await _row(db, one_step.id)
    assert row.narrative == "A generated narrative." and row.visibility == Visibility.GM


# ── Update ─────────────────────────────────────────────────────────────────

async def test_update_text_recomputes_every_index_column(db, world, emitted, valkey):
    entry = await _create(db, world)
    old_hash = entry.entry_hash
    await valkey.set(_dedup_key(world, old_hash), "1")
    emitted.clear()

    entry = await journal_service.update_journal_entry(db, world.gm, entry, {"narrative": "Mira smiled at Elturel."})
    row = await _row(db, entry.id)
    assert row.entry_hash == old_hash  # the Shorthand did not change
    assert tuple(await _tsv_hits(db, entry.id, "smiled")) == (True, True)
    assert tuple(await _tsv_hits(db, entry.id, "travelled")) == (False, False)
    assert _close(list(row.party_embedding), fake_vector("Mira smiled at Elturel."))
    assert _close(list(row.embedding), fake_vector("Mira at the mill Mira smiled at Elturel."))
    # Mira is in both: the Narrative wins. The old Narrative's tags are gone.
    assert await _links(db, entry.id) == {("Mira", "character"): "narrative", ("Elturel", "location"): "narrative"}
    [(event, _cid, refs, _actor)] = emitted
    assert event == HookEvent.ENTRY_UPDATED
    assert refs == {"journal_id": entry.id, "kind": "gm", "previous_entry_hash": old_hash,
                    "entry_hash": old_hash, "changed_fields": ["narrative"]}

    emitted.clear()
    entry = await journal_service.update_journal_entry(db, world.gm, entry, {"notes": "Brand new notes"})
    new_hash = journal_service.compute_entry_hash("Brand new notes")
    assert (await _row(db, entry.id)).entry_hash == new_hash
    assert tuple(await _tsv_hits(db, entry.id, "brand")) == (True, False)
    [(_e, _c, refs, _a)] = emitted
    assert (refs["previous_entry_hash"], refs["entry_hash"], refs["changed_fields"]) == (
        old_hash, new_hash, ["shorthand"])
    assert await valkey.exists(_dedup_key(world, old_hash)) == 0
    assert await valkey.exists(_dedup_key(world, new_hash)) == 1


async def test_update_keeps_manual_and_legacy_links(db, world):
    entry = await _create(db, world, notes="nothing much", narrative="quiet day.")
    assert await _links(db, entry.id) == {}
    tags = {name: Tag(name=name, tag_type=TagType.character) for name in ("Mira", "Pelor", "Ghost", "Stale")}
    db.add_all(tags.values())
    await db.flush()
    db.add_all([
        JournalTag(journal_id=entry.id, tag_id=tags["Mira"].id, source_field=None),        # legacy, re-derived
        JournalTag(journal_id=entry.id, tag_id=tags["Ghost"].id, source_field=None),       # legacy, not
        JournalTag(journal_id=entry.id, tag_id=tags["Pelor"].id, source_field="manual"),   # manual, re-derived
        JournalTag(journal_id=entry.id, tag_id=tags["Stale"].id, source_field="narrative"),
    ])
    await db.commit()
    await journal_service.update_journal_entry(db, world.gm, entry, {"narrative": "Mira prayed beside Pelor."})
    assert await _links(db, entry.id) == {
        ("Mira", "character"): "narrative", ("Ghost", "character"): None, ("Pelor", "character"): "manual",
    }


async def test_update_collision_is_409_and_writes_nothing(db, world, valkey):
    a = await _create(db, world, notes="alpha notes", narrative="A.")
    b = await _create(db, world, notes="beta notes", narrative="B.")
    b_id = b.id
    # The Valkey key (set by the create) catches it first.
    with pytest.raises(HTTPException) as exc:
        await journal_service.update_journal_entry(db, world.gm, b, {"notes": " Alpha Notes"})
    assert exc.value.status_code == 409
    assert (await _row(db, b_id)).shorthand == "beta notes"
    # Without the key (expired), the unique constraint does.
    await valkey.flushall()
    b = await _row(db, b_id)
    with pytest.raises(HTTPException) as exc:
        await journal_service.update_journal_entry(db, world.gm, b, {"notes": "ALPHA NOTES", "narrative": "x"})
    assert exc.value.status_code == 409
    await db.rollback()
    row = await _row(db, b_id)
    assert (row.shorthand, row.narrative, row.entry_hash) == (
        "beta notes", "B.", journal_service.compute_entry_hash("beta notes"))
    assert (await _row(db, a.id)).shorthand == "alpha notes"


async def test_update_date_or_visibility_recomputes_nothing(db, world, emitted, monkeypatch):
    entry = await _create(db, world)
    emitted.clear()
    calls = []
    real_vis = journal_service.set_visibility

    async def no_recompute(*_a, **_kw):
        raise AssertionError("a date or Visibility change must not recompute the index")

    async def spy_vis(db_, ctx, ref, value, **kw):
        calls.append((ref, value))
        return await real_vis(db_, ctx, ref, value, **kw)

    monkeypatch.setattr(journal_service, "_recompute_index", no_recompute)
    monkeypatch.setattr(journal_service, "set_visibility", spy_vis)
    entry = await journal_service.update_journal_entry(db, world.gm, entry, {"session_date": date(2026, 6, 1)})
    entry = await journal_service.update_journal_entry(db, world.gm, entry, {"visibility": "gm"})
    row = await _row(db, entry.id)
    assert row.session_date == date(2026, 6, 1) and row.visibility == Visibility.GM
    assert [ref.kind for ref, _v in calls] == ["journal"] and calls[0][0].id == entry.id
    assert [refs["changed_fields"] for _e, _c, refs, _a in emitted] == [["session_date"], ["visibility"]]
    # Nothing changed: no event.
    await journal_service.update_journal_entry(db, world.gm, entry, {"visibility": "gm"})
    assert len(emitted) == 2


async def test_update_refuses_unknown_fields(db, world):
    entry = await _create(db, world)
    with pytest.raises(ValueError):
        await journal_service.update_journal_entry(db, world.gm, entry, {"entry_hash": "x"})


# ── Delete ─────────────────────────────────────────────────────────────────

async def test_delete_removes_row_links_and_dedup_key(db, world, emitted, published, valkey):
    entry = await _create(db, world)
    entry_id, h = entry.id, entry.entry_hash
    assert await _links(db, entry_id)
    assert await valkey.exists(_dedup_key(world, h)) == 1
    emitted.clear()
    # A Player may not delete a GM entry: the one 404, untouched.
    with pytest.raises(NotFound):
        await journal_service.delete_journal_entry(db, world.player_ctx, entry_id)
    with pytest.raises(NotFound):
        await journal_service.delete_journal_entry(db, world.gm, uuid.uuid4())
    assert emitted == []

    await journal_service.delete_journal_entry(db, world.gm, entry_id)
    assert await _row(db, entry_id) is None
    assert await db.scalar(sa.select(sa.func.count()).select_from(JournalTag)
                           .where(JournalTag.journal_id == entry_id)) == 0
    assert await valkey.exists(_dedup_key(world, h)) == 0
    [(event, cid, refs, _a)] = emitted
    assert (event, cid, refs) == (HookEvent.ENTRY_DELETED, world.cid, {"journal_id": entry_id, "kind": "gm"})
    await hooks.drain()
    assert published[-1] == (world.cid, "journal", None)  # unkeyed: a deleted id is never sent
    # The same notes can be saved again.
    await _create(db, world)


# ── Reindex ────────────────────────────────────────────────────────────────

async def test_reindex_route_uses_reindex_entry_and_emits_nothing(db, world, client, emitted):
    entry = JournalEntry(user_id=world.owner.id, campaign_id=world.cid, shorthand="Zorblax did it",
                         narrative="The tower fell near Neverwinter.", entry_hash=uuid.uuid4().hex)
    db.add(entry)
    await db.commit()
    r = await client.post(f"/api/journals/reindex?campaign_id={world.cid}", headers=bearer(world.owner))
    assert r.status_code == 200 and r.json() == {"reindexed": 1}, r.text
    row = await _row(db, entry.id)
    assert _close(list(row.embedding), fake_vector("Zorblax did it The tower fell near Neverwinter."))
    assert _close(list(row.party_embedding), fake_vector("The tower fell near Neverwinter."))
    assert tuple(await _tsv_hits(db, entry.id, "zorblax")) == (True, False)
    assert ("Neverwinter", "location") in await _links(db, entry.id)
    assert emitted == []


async def test_reindex_entry_strict_raises_before_writing(db, world, ml_down):
    entry = JournalEntry(user_id=world.owner.id, campaign_id=world.cid, shorthand="s", narrative="n",
                         entry_hash=uuid.uuid4().hex, embedding=[0.0] * 383 + [1.0])
    db.add(entry)
    await db.commit()
    with pytest.raises(ModelServiceUnavailable):
        await journal_service.reindex_entry(db, entry, strict=True)
    await db.rollback()
    assert list((await _row(db, entry.id)).embedding)[-1] == pytest.approx(1.0)


# ── attach_tag ─────────────────────────────────────────────────────────────

async def test_attach_tag_writes_a_manual_link(db, world, client):
    entry = await _create(db, world, notes="no names", narrative="quiet.")
    r = await client.post(f"/api/journals/{entry.id}/tags", headers=bearer(world.owner),
                          json={"name": "Ilmater", "tag_type": "character"})
    assert r.status_code == 201, r.text
    assert await _links(db, entry.id) == {("Ilmater", "character"): "manual"}


# ── The grep test: one writer ──────────────────────────────────────────────

# A JournalEntry's text and index columns. The last four are JournalEntry's
# alone; `narrative`, `shorthand` and `embedding` also name columns of other
# models (TrainingSample, SourceChunk), so those count only on a value that
# came from an expression naming JournalEntry.
PROTECTED = frozenset({"narrative", "shorthand", "embedding", "narrative_tsv", "party_tsv", "party_embedding",
                       "entry_hash"})
JOURNAL_ONLY = frozenset({"narrative_tsv", "party_tsv", "party_embedding", "entry_hash"})
WRITER = "app/services/journal_service.py"
# make_snapshot.py writes a historic schema snapshot with raw SQL on purpose.
EXEMPT = frozenset({WRITER, "scripts/make_snapshot.py"})
RAW_SQL = re.compile(r"\b(?:UPDATE\s+journal_entries\s+SET|INSERT\s+INTO\s+journal_entries)\b", re.I)
MODEL = "JournalEntry"


def _mentions(node: ast.AST | None, names: set[str]) -> bool:
    return node is not None and any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(node))


def _key_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == MODEL:
        return node.attr
    return None


class _IndexWriteFinder(ast.NodeVisitor):
    """Assignments to a JournalEntry's text or index columns (see PROTECTED)."""

    def __init__(self) -> None:
        self.found: list[tuple[int, str]] = []
        self.scopes: list[set[str]] = [set()]

    def names(self) -> set[str]:
        return {MODEL} | self.scopes[-1]

    def _flag(self, node: ast.AST, what: str) -> None:
        self.found.append((getattr(node, "lineno", 0), what))

    def _hit(self, attr: str, base: ast.AST) -> bool:
        return attr in JOURNAL_ONLY or (attr in PROTECTED and _mentions(base, self.names()))

    def _track(self, target: ast.AST) -> None:
        for n in ast.walk(target):
            if isinstance(n, ast.Name):
                self.scopes[-1].add(n.id)

    def _targets(self, target: ast.AST) -> None:
        for n in ast.walk(target):
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and self._hit(n.attr, n.value):
                self._flag(n, f"assigns `.{n.attr}`")

    def _function(self, node) -> None:
        args = node.args
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
        self.scopes.append({a.arg for a in params if a is not None and _mentions(a.annotation, {MODEL})})
        self.generic_visit(node)
        self.scopes.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def _assign(self, targets: list[ast.AST], value: ast.AST | None) -> None:
        if _mentions(value, self.names()):
            for t in targets:
                self._track(t)
        for t in targets:
            self._targets(t)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._assign(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assign([node.target], node.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._assign([node.target], node.value)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._assign([node.target], node.value)
        self.generic_visit(node)

    def _loop(self, node) -> None:
        self._assign([node.target], node.iter)
        self.generic_visit(node)

    visit_For = visit_AsyncFor = visit_comprehension = _loop

    def visit_With(self, node) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._assign([item.optional_vars], item.context_expr)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id == MODEL:
            for kw in node.keywords:
                if kw.arg in PROTECTED:
                    self._flag(node, f"constructs JournalEntry({kw.arg}=...)")
        if isinstance(func, ast.Name) and func.id == "setattr" and len(node.args) >= 2:
            attr = _key_name(node.args[1])
            if attr is not None and self._hit(attr, node.args[0]):
                self._flag(node, f"setattr(..., {attr!r})")
        if isinstance(func, ast.Attribute) and func.attr in {"values", "on_conflict_do_update"} \
                and _mentions(func.value, {MODEL}):
            keys = [kw.arg for kw in node.keywords if kw.arg not in (None, "set_")]
            dicts = [a for a in node.args if isinstance(a, ast.Dict)]
            dicts += [kw.value for kw in node.keywords if kw.arg in (None, "set_") and isinstance(kw.value, ast.Dict)]
            keys += [_key_name(k) for d in dicts for k in d.keys if k is not None]
            for key in keys:
                if key in PROTECTED:
                    self._flag(node, f"writes {key} through .{func.attr}(...)")
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and RAW_SQL.search(arg.value):
                self._flag(node, "writes journal_entries in raw SQL")
            if isinstance(arg, ast.JoinedStr) and RAW_SQL.search(ast.unparse(arg)):
                self._flag(node, "writes journal_entries in raw SQL")
        self.generic_visit(node)


def find_index_writes(source: str) -> list[tuple[int, str]]:
    finder = _IndexWriteFinder()
    finder.visit(ast.parse(source))
    return finder.found


def _scanned_files():
    for top in ("app", "scripts"):
        for path in sorted((BACKEND / top).rglob("*.py")):
            rel = path.relative_to(BACKEND).as_posix()
            if rel not in EXEMPT:
                yield rel, path


def test_only_journal_service_writes_journal_index_columns():
    found = [f"{rel}:{line}: {what}" for rel, path in _scanned_files()
             for line, what in find_index_writes(path.read_text(encoding="utf-8"))]
    assert not found, ("only app/services/journal_service.py writes a JournalEntry's text and index columns "
                       "(E0-Journal.2); call its writers instead:\n" + "\n".join(found))
    assert (BACKEND / WRITER).is_file()


@pytest.mark.parametrize("source", [
    # The pre-E0-Journal.2 reindex route.
    "async def r(db, ctx):\n    res = await db.execute(scoped_select(JournalEntry, ctx))\n"
    "    entries = list(res.scalars().all())\n    for entry in entries:\n        entry.embedding = [1.0]\n",
    # The pre-E0-Journal.2 seed.
    "async def s(session, h):\n    entry = await session.scalar(select(JournalEntry).where(JournalEntry.entry_hash == h))\n"
    "    if entry.embedding is None:\n        entry.embedding = [0.0]\n",
    "async def f(db, i):\n    e = await db.get(JournalEntry, i)\n    e.narrative = 'x'\n",
    "def f(entry: JournalEntry):\n    entry.shorthand += 'x'\n",
    "def f(x):\n    x.party_embedding = None\n",
    "def f(x, h):\n    x.entry_hash = h\n",
    "def f():\n    return JournalEntry(shorthand='s', narrative='n')\n",
    "async def f(db, v):\n    await db.execute(update(JournalEntry).where(JournalEntry.id == 1).values(embedding=v))\n",
    "async def f(db, v):\n    await db.execute(update(JournalEntry).values({JournalEntry.narrative_tsv: v}))\n",
    "async def f(db):\n    await db.execute(text(\"UPDATE journal_entries SET narrative_tsv = NULL\"))\n",
    "def f(entry, h):\n    setattr(entry, 'entry_hash', h)\n",
    "def f(rows: list[JournalEntry]):\n    for r in rows:\n        r.narrative = ''\n",
])
def test_the_grep_finds_index_writes(source):
    assert find_index_writes(source), source


@pytest.mark.parametrize("source", [
    "def f(content, v):\n    chunk = SourceChunk(content=content)\n    chunk.embedding = v\n",
    "def f(s):\n    sample = TrainingSample(shorthand=s)\n    sample.narrative = 'n'\n",
    "def f(cid, uid):\n    return JournalEntry(campaign_id=cid, user_id=uid, kind='gm')\n",
    "async def f(db, q):\n    return await db.execute(select(JournalEntry).where(JournalEntry.narrative_tsv.op('@@')(q)))\n",
    "async def f(db):\n    await db.execute(update(Tag).values(name='x'))\n",
])
def test_the_grep_leaves_other_writes_alone(source):
    assert find_index_writes(source) == [], source


def test_dedup_drop_hash_exists():
    assert callable(dedup_service.drop_hash)
