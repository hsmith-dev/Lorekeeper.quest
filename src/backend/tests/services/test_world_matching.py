"""E0-WorldCore.4: world_service.match_names, candidates and normalize_name.

The story's I/O matrix (normalize, exact name + alias, longest first, word
boundaries, Player / share / preview visibility, deleted and merged, two
Campaigns, ambiguity, candidates, the benchmark), an EV-4 style canary probe,
and the guard that only app/services/world_matching.py imports rapidfuzz.
"""
from __future__ import annotations

import ast
import random
import statistics
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa

import app.services.world_service as ws
from app.access import MEMBER_VIEW, audience_ctx, ctx_for, set_visibility, share_ctx
from app.db.models import Entity, EntityAlias
from app.domain import entity_types as et
from app.domain.enums import EntityType
from app.schemas.entities import AddAlias, AddMention, CreateEntity, DeleteEntity, Merge
from app.schemas.sources import RecordRef
from app.services.world_service import NameCandidate, NameMatch, apply_change, candidates, match_names
from tests.ev4.fixtures import ev4  # noqa: F401  (registers the fixture)

APP = Path(__file__).resolve().parents[2] / "app"


@pytest_asyncio.fixture
async def gm(ev4, db):
    return await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)


async def _player(ev4, db):
    return await ctx_for(db, (await ev4.actor("player")).user_id, ev4.a.campaign_id)


async def _create(db, ctx, name, **kw) -> Entity:
    kw.setdefault("type", "character")
    if kw["type"] == "character":
        kw.setdefault("kind", "npc")
    change = await apply_change(db, ctx, CreateEntity(name=name, **kw))
    return (await db.execute(sa.select(Entity).where(Entity.id == change.entity_id)
                             .execution_options(populate_existing=True))).scalar_one()


async def _party(db, gm, entity: Entity) -> Entity:
    await set_visibility(db, gm, RecordRef(kind="entity", id=entity.id), "party")
    return entity


async def _alias(db, gm, entity: Entity, alias: str) -> None:
    await apply_change(db, gm, AddAlias(entity_id=entity.id, alias=alias))


def _spans(matches: list[NameMatch]) -> list[tuple[str, uuid.UUID]]:
    return [(m.surface, m.entity_id) for m in matches]


# ── normalize_name ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, key", [("  Brother   Áldric ", "aldric"), ("ALDRIC", "aldric"), ("The King", "king")])
def test_normalize_matrix(text, key):
    assert ws.normalize_name(text) == key


def test_world_service_exports_the_matchers():
    for name in ("normalize_name", "match_names", "candidates", "NameMatch", "NameCandidate", "NAME_PREFIXES"):
        assert name in ws.__all__ and hasattr(ws, name)
    assert not hasattr(ws, "_alias_key")


async def test_alias_keys_use_normalize_name(db, ev4, gm):
    e = await _create(db, gm, "Aldric")
    first = await apply_change(db, gm, AddAlias(entity_id=e.id, alias="Brother  Áldric"))
    again = await apply_change(db, gm, AddAlias(entity_id=e.id, alias="aldric"))
    assert again.id == first.id
    rows = (await db.execute(sa.select(EntityAlias).where(EntityAlias.entity_id == e.id))).scalars().all()
    assert [(a.alias, a.normalized_alias) for a in rows] == [("Brother Áldric", "aldric")]


# ── match_names: the matrix ────────────────────────────────────────────────

async def test_exact_name_and_alias(db, ev4, gm):
    aldric = await _create(db, gm, "Aldric")
    await _alias(db, gm, aldric, "Old Smith")
    text = "Brother Aldric met the old smith."
    hits = await match_names(db, gm, text)
    assert _spans(hits) == [("Brother Aldric", aldric.id), ("the old smith", aldric.id)]
    for m in hits:
        assert m.surface == text[m.start:m.end] and m.score == 1.0 and m.exact is True
        assert m.name == "Aldric" and m.type is EntityType.CHARACTER
    assert (hits[0].alias, hits[0].matched) == (False, "Aldric")
    assert (hits[1].alias, hits[1].matched) == (True, "Old Smith")


async def test_diacritics_and_case(db, ev4, gm):
    aldric = await _create(db, gm, "Aldric")
    assert _spans(await match_names(db, gm, "ÁLDRIC and Áldric")) == [("ÁLDRIC", aldric.id),
                                                                            ("Áldric", aldric.id)]


async def test_longest_first(db, ev4, gm):
    mira, vale = await _create(db, gm, "Mira"), await _create(db, gm, "Mira Vale")
    assert _spans(await match_names(db, gm, "Mira Vale and Mira")) == [("Mira Vale", vale.id), ("Mira", mira.id)]


async def test_overlap_keeps_the_longer_then_leftmost(db, ev4, gm):
    ab, bc = await _create(db, gm, "Ash Bell"), await _create(db, gm, "Bell Cox")
    assert _spans(await match_names(db, gm, "Ash Bell Cox")) == [("Ash Bell", ab.id)]  # same length: leftmost
    assert _spans(await match_names(db, gm, "Ash Bell Cox Bell Cox")) == [("Ash Bell", ab.id), ("Bell Cox", bc.id)]
    long = await _create(db, gm, "Bell Cox Dunn")
    assert _spans(await match_names(db, gm, "Ash Bell Cox Dunn")) == [("Bell Cox Dunn", long.id)]


async def test_word_boundary_and_separators(db, ev4, gm):
    mira, vale = await _create(db, gm, "Mira"), await _create(db, gm, "Mira Vale")
    assert await match_names(db, gm, "Miranda and Amira") == []
    assert _spans(await match_names(db, gm, "Mira's horse")) == [("Mira", mira.id)]
    assert _spans(await match_names(db, gm, "Mira-Vale, Mira.Vale, Mira\nVale")) == [
        ("Mira-Vale", vale.id), ("Mira.Vale", vale.id), ("Mira\nVale", vale.id)]
    # A blank line or other punctuation splits a name.
    assert _spans(await match_names(db, gm, "Mira\n\nVale; Mira, Vale")) == [
        ("Mira", mira.id), ("Mira", mira.id)]
    # A curly apostrophe (U+2019) and Unicode hyphens (U+2010, U+2011) join tokens too.
    obrien = await _create(db, gm, "Seamus")
    await _alias(db, gm, obrien, "O'Brien")
    jean = await _create(db, gm, "Jean-Luc")
    text = "O’Brien met Jean‐Luc and Jean‑Luc."
    assert _spans(await match_names(db, gm, text)) == [
        ("O’Brien", obrien.id), ("Jean‐Luc", jean.id), ("Jean‑Luc", jean.id)]


async def test_prefix_extension(db, ev4, gm):
    king = await _create(db, gm, "The King")
    aldric = await _create(db, gm, "Aldric")
    assert _spans(await match_names(db, gm, "Long live the King! Sir Brother Aldric bows.")) == [
        ("the King", king.id), ("Sir Brother Aldric", aldric.id)]
    # "King Aldric": the longer, extended Aldric span wins over "King".
    assert _spans(await match_names(db, gm, "King Aldric")) == [("King Aldric", aldric.id)]


async def test_types_filter(db, ev4, gm):
    person = await _create(db, gm, "Hollow")
    place = await _create(db, gm, "Hollow Keep", type="location")
    assert _spans(await match_names(db, gm, "Hollow Keep")) == [("Hollow Keep", place.id)]
    assert _spans(await match_names(db, gm, "Hollow Keep", types=[EntityType.CHARACTER])) == [("Hollow", person.id)]
    assert _spans(await match_names(db, gm, "Hollow Keep", types=["location"])) == [("Hollow Keep", place.id)]
    assert await match_names(db, gm, "") == []


# ── Visibility ─────────────────────────────────────────────────────────────

async def _visibility_world(db, ev4, gm):
    secret = await _create(db, gm, "Gorrim")
    mira = await _party(db, gm, await _create(db, gm, "Mira"))
    db.add(EntityAlias(campaign_id=ev4.a.campaign_id, entity_id=mira.id, alias="Silver", normalized_alias="silver",
                       visibility_floor="gm"))
    tobin = await _party(db, gm, await _create(db, gm, "Tobin"))
    await _alias(db, gm, tobin, "Toby")
    await db.execute(sa.update(Entity).where(Entity.id == tobin.id).values(field_visibility={"aliases": "gm"}))
    await _alias(db, gm, secret, "Grim")
    await db.flush()
    return secret, mira, tobin


TEXT = "Gorrim, Grim, Silver, Mira, Toby and Tobin."


async def test_player_share_and_preview_see_only_party_names(db, ev4, gm):
    secret, mira, tobin = await _visibility_world(db, ev4, gm)
    everything = await match_names(db, gm, TEXT)
    assert [m.surface for m in everything] == ["Gorrim", "Grim", "Silver", "Mira", "Toby", "Tobin"]
    ctxs = [await _player(ev4, db), await share_ctx(db, ev4.a.share_token),
            audience_ctx(ev4.a.campaign_id, MEMBER_VIEW, by=gm)]
    for ctx in ctxs:
        assert _spans(await match_names(db, ctx, TEXT)) == [("Mira", mira.id), ("Tobin", tobin.id)], ctx
        found = {c.entity_id for c in await candidates(db, ctx, "Gorim", limit=100)}
        assert secret.id not in found
        for surface in ("Silver", "Toby", "Grim"):
            assert all(c.matched not in ("Silver", "Toby", "Grim") for c in await candidates(db, ctx, surface,
                                                                                               limit=100))


async def test_canary_never_reaches_a_player(db, ev4, gm):
    canary = f"Canary{uuid.uuid4().hex[:8]}"
    hidden = await _create(db, gm, canary)
    party = await _party(db, gm, await _create(db, gm, "Wendel"))
    db.add(EntityAlias(campaign_id=ev4.a.campaign_id, entity_id=party.id, alias=f"{canary} Two",
                       normalized_alias="x", visibility_floor="gm"))
    await db.flush()
    absorbed = await _create(db, gm, f"{canary} Three")
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id, survivor_id=party.id))
    player = await _player(ev4, db)
    text = f"{canary}, {canary} Two, {canary} Three, Wendel"
    out = repr(await match_names(db, player, text)) + repr(await candidates(db, player, canary, limit=100))
    assert canary not in out
    assert str(hidden.id) not in out and str(absorbed.id) not in out
    assert str(party.id) in out


async def test_deleted_and_merged(db, ev4, gm):
    gone = await _create(db, gm, "Dellen")
    await apply_change(db, gm, DeleteEntity(entity_id=gone.id))
    survivor = await _party(db, gm, await _create(db, gm, "Sarn"))
    absorbed = await _create(db, gm, "Maddock")
    await _alias(db, gm, absorbed, "Mad Dog")
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id, survivor_id=survivor.id))
    text = "Dellen, Maddock, Mad Dog, Sarn"
    assert _spans(await match_names(db, gm, text)) == [
        ("Maddock", survivor.id), ("Mad Dog", survivor.id), ("Sarn", survivor.id)]
    assert _spans(await match_names(db, await _player(ev4, db), text)) == [("Sarn", survivor.id)]
    for c in await candidates(db, gm, "Maddock", limit=100):
        assert c.entity_id not in (absorbed.id, gone.id)


async def test_merged_names_resolve_through_the_chain_with_a_cycle_guard(db, ev4, gm):
    # Rows set by hand (no merge alias): the merged rows' own names must resolve.
    end = await _create(db, gm, "Ender")
    mid, first = await _create(db, gm, "Middle"), await _create(db, gm, "Firstly")
    await db.execute(sa.update(Entity).where(Entity.id == mid.id).values(merged_into_id=end.id))
    await db.execute(sa.update(Entity).where(Entity.id == first.id).values(merged_into_id=mid.id))
    loop_a, loop_b = await _create(db, gm, "Loopa"), await _create(db, gm, "Loopb")
    await db.execute(sa.update(Entity).where(Entity.id == loop_a.id).values(merged_into_id=loop_b.id))
    await db.execute(sa.update(Entity).where(Entity.id == loop_b.id).values(merged_into_id=loop_a.id))
    dead = await _create(db, gm, "Deadend")
    orphan = await _create(db, gm, "Orphan")
    await db.execute(sa.update(Entity).where(Entity.id == orphan.id).values(merged_into_id=dead.id))
    await apply_change(db, gm, DeleteEntity(entity_id=dead.id))
    hits = await match_names(db, gm, "Firstly Middle Ender Loopa Loopb Orphan Deadend")
    assert _spans(hits) == [("Firstly", end.id), ("Middle", end.id), ("Ender", end.id)]
    assert [m.alias for m in hits] == [True, True, False]


async def test_two_campaigns(db, ev4, gm):
    cross = await ev4.actor("cross_gm_player")
    b_gm = await ctx_for(db, cross.user_id, ev4.b.campaign_id)
    mine, theirs = await _create(db, gm, "Mira"), await _create(db, b_gm, "Mira")
    assert _spans(await match_names(db, gm, "Mira")) == [("Mira", mine.id)]
    assert _spans(await match_names(db, b_gm, "Mira")) == [("Mira", theirs.id)]
    assert [c.entity_id for c in await candidates(db, gm, "Mira", limit=100) if c.name == "Mira"] == [mine.id]
    assert [c.entity_id for c in await candidates(db, b_gm, "Mira", limit=100) if c.name == "Mira"] == [theirs.id]


# ── Ambiguity ──────────────────────────────────────────────────────────────

async def test_ambiguity_name_then_mentions_then_created_at_then_id(db, ev4, gm):
    entry = ev4.a.ids["journal_entries"][0]
    by_alias = await _create(db, gm, "Bramwell")
    await _alias(db, gm, by_alias, "Bram")
    by_name = await _create(db, gm, "Bram")
    await apply_change(db, gm, AddMention(entity_id=by_alias.id, journal_id=entry))
    assert _spans(await match_names(db, gm, "Bram")) == [("Bram", by_name.id)]  # a name beats an alias

    await _create(db, gm, "Corin")
    loud = await _create(db, gm, "Corin")
    await apply_change(db, gm, AddMention(entity_id=loud.id, journal_id=entry))
    assert _spans(await match_names(db, gm, "Corin")) == [("Corin", loud.id)]  # more visible Mentions

    newer, older = await _create(db, gm, "Daven"), await _create(db, gm, "Daven")
    now = datetime.now(timezone.utc)
    await db.execute(sa.update(Entity).where(Entity.id == newer.id).values(created_at=now))
    await db.execute(sa.update(Entity).where(Entity.id == older.id).values(created_at=now - timedelta(days=1)))
    assert _spans(await match_names(db, gm, "Daven")) == [("Daven", older.id)]

    twins = [await _create(db, gm, "Evran"), await _create(db, gm, "Evran")]
    await db.execute(sa.update(Entity).where(Entity.id.in_([t.id for t in twins])).values(created_at=now))
    assert _spans(await match_names(db, gm, "Evran")) == [("Evran", min(twins, key=lambda t: str(t.id)).id)]


async def test_mentions_count_only_visible_ones(db, ev4, gm):
    first, second = ev4.a.ids["journal_entries"][:2]
    a = await _party(db, gm, await _create(db, gm, "Fennick"))
    b = await _party(db, gm, await _create(db, gm, "Fennick"))
    for entry in (first, second):
        await apply_change(db, gm, AddMention(entity_id=a.id, journal_id=entry))
    await apply_change(db, gm, AddMention(entity_id=b.id, journal_id=first))
    await set_visibility(db, gm, RecordRef(kind="journal", id=second), "gm")
    by_id = {c.entity_id: c.mention_count for c in await candidates(db, gm, "Fennick", limit=100)}
    assert (by_id[a.id], by_id[b.id]) == (2, 1)
    player = await _player(ev4, db)
    by_id = {c.entity_id: c.mention_count for c in await candidates(db, player, "Fennick", limit=100)}
    assert (by_id[a.id], by_id[b.id]) == (1, 1)


# ── candidates ─────────────────────────────────────────────────────────────

async def test_candidates(db, ev4, gm):
    aldric = await _create(db, gm, "Aldric")
    other = await _create(db, gm, "Zephyrine Quill")
    smith = await _create(db, gm, "Hobb")
    await _alias(db, gm, smith, "Aldred the Smith")
    await apply_change(db, gm, AddMention(entity_id=aldric.id, journal_id=ev4.a.ids["journal_entries"][0]))
    top = await candidates(db, gm, "Aldrik")
    assert isinstance(top[0], NameCandidate) and top[0].entity_id == aldric.id
    assert 0 < top[0].score <= 1 and top[0].mention_count == 1 and top[0].matched == "Aldric"
    assert len(top) <= 3
    assert [c.score for c in top] == sorted((c.score for c in top), reverse=True)
    assert all(c.score > 0 for c in await candidates(db, gm, "Aldrik", limit=100))
    exact = await candidates(db, gm, "Brother ALDRIC")
    assert (exact[0].entity_id, exact[0].score) == (aldric.id, 1.0)
    assert (await candidates(db, gm, "Aldred the Smith"))[0].entity_id == smith.id
    place = await _create(db, gm, "Aldrich", type="location")
    places = {c.entity_id for c in await candidates(db, gm, "Aldrik", type="location", limit=100)}
    people = {c.entity_id for c in await candidates(db, gm, "Aldrik", type="character", limit=100)}
    assert place.id in places and aldric.id not in places and smith.id not in places
    assert aldric.id in people and place.id not in people
    assert other.id not in places
    assert await candidates(db, gm, "   ") == []
    assert len(await candidates(db, gm, "Aldrik", limit=1)) == 1


@pytest.mark.parametrize("limit", [0, -1, 101, True, 2.5, "3"])
async def test_candidates_limit(db, ev4, gm, limit):
    with pytest.raises(ValueError):
        await candidates(db, gm, "Aldric", limit=limit)


async def test_candidates_tie_break(db, ev4, gm):
    entry = ev4.a.ids["journal_entries"][0]
    b, a = await _create(db, gm, "Gamma Brin"), await _create(db, gm, "Gamma Arn")
    loud = await _create(db, gm, "Gamma Crin")
    await apply_change(db, gm, AddMention(entity_id=loud.id, journal_id=entry))
    ranked = [c for c in await candidates(db, gm, "Gamma", limit=100) if c.name.startswith("Gamma")]
    assert len({c.score for c in ranked}) == 1  # WRatio ties: partial match of the same token
    assert [c.entity_id for c in ranked] == [loud.id, a.id, b.id]


# ── Benchmark (EV-5 row match_names) ───────────────────────────────────────

_SYL = ["ar", "bel", "cor", "dun", "el", "fen", "gar", "hal", "is", "jor", "kel", "lor", "mor", "nev", "or", "pel",
        "quin", "ros", "sel", "tor", "ul", "var", "wen", "yor", "zan"]


def _word(rng: random.Random, n: int = 3) -> str:
    return "".join(rng.choice(_SYL) for _ in range(n)).capitalize()


async def test_benchmark_300_entities_600_aliases_500_words(db, ev4, gm, capsys):
    rng = random.Random(4)
    a = ev4.a.campaign_id
    names: list[str] = []
    for i in range(300):
        name = f"{_word(rng)} {_word(rng)}" if i % 3 else _word(rng)
        entity = Entity(id=uuid.uuid4(), campaign_id=a, type="character", kind="npc", name=name,
                        status=et.default_status("character"),
                        visibility="party" if i % 2 else "gm")
        db.add(entity)
        names.append(name)
        for j in range(2):
            alias = f"{_word(rng, 2)} the {_word(rng, 2)}" if j else _word(rng, 4)
            db.add(EntityAlias(campaign_id=a, entity_id=entity.id, alias=alias,
                               normalized_alias=ws.normalize_name(alias)))
            names.append(alias)
    await db.flush()
    filler = ["the", "party", "went", "north", "and", "met", "an", "old", "friend", "at", "dawn", "who", "said"]
    words: list[str] = []
    while len(words) < 500:
        words.extend(rng.choice(names).split() if rng.random() < 0.15 else [rng.choice(filler)])
    text = " ".join(words[:500]) + "."
    timings = []
    for _ in range(7):
        t0 = time.perf_counter()
        hits = await match_names(db, gm, text)
        timings.append(time.perf_counter() - t0)
    median_ms = statistics.median(timings) * 1000
    with capsys.disabled():
        print(f"\n[benchmark] match_names 300 Entities / 600 aliases / 500 words: median {median_ms:.1f} ms "
              f"(min {min(timings) * 1000:.1f}, max {max(timings) * 1000:.1f}, n=7), {len(hits)} hits")
    assert hits
    assert median_ms <= 200


# ── Guards ─────────────────────────────────────────────────────────────────

def test_only_world_matching_imports_rapidfuzz():
    importers = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            if any(m == "rapidfuzz" or m.startswith("rapidfuzz.") for m in mods):
                importers.append(path.relative_to(APP).as_posix())
    assert importers == ["services/world_matching.py"]
