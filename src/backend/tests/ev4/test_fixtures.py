"""The canary seed and the EV-4 actors, against the migrated test DB."""
from __future__ import annotations

import json
import re
import uuid

import pytest
import sqlalchemy as sa

from tests.ev4 import report
from tests.ev4.families import assert_no_canary
from tests.ev4.fixtures import (
    CANARIES, CANARY_RE, create_user, find_canaries, load_seed, seed_canary_campaign,
    validate_seed,
)
from tests.ev4.report import EV4Leak

# Every GM-only field/record today (AR-26: character sheets have no Visibility).
GM_ONLY_KINDS = {
    "SHORTHAND", "NPCNOTES", "QUESTNOTES", "TERM", "TERMMEANING", "TERMUSAGE", "PLANTITLE", "PLAN",
    "CHATTITLE", "CHATMSG", "CHATREPLY", "SOURCETITLE", "SOURCEFILE", "SOURCECHUNK", "SHEET", "SHEETDATA",
    "SHEETSECRET",
}
# Party-visible fields: never a placeholder.
PARTY_FIELDS = {
    "campaign": ("name", "description"),
    "journal_entries": ("narrative",),
    "npcs": ("name", "description", "role", "status"),
    "quests": ("title", "description", "status"),
}


# ── The seed file (no DB) ──────────────────────────────────────────────────

def test_seed_file_has_a_placeholder_for_every_gm_only_kind():
    kinds = set(re.findall(r"\{canary:([A-Z0-9]+)\}", json.dumps(load_seed())))
    assert kinds == GM_ONLY_KINDS


def test_seed_party_fields_hold_no_placeholder():
    seed = load_seed()
    for key, fields in PARTY_FIELDS.items():
        rows = seed[key] if isinstance(seed[key], list) else [seed[key]]
        for row in rows:
            for f in fields:
                assert "{canary:" not in json.dumps(row.get(f)), f"{key}.{f} is Party-visible"


@pytest.mark.parametrize("mutate, match", [
    (lambda s: s["npcs"][0].update(secret="{canary:NPCSECRET}"), r"npcs: unknown keys \['secret'\]"),
    (lambda s: s["campaign"].update(motto="x"), r"campaign: unknown keys \['motto'\]"),
    (lambda s: s["source_documents"][0]["chunks"][0].update(page=1), r"source_documents.chunks: unknown keys"),
    (lambda s: s["character_sheet_templates"][0]["sheets"][0].update(gm_notes="x"),
     r"character_sheet_templates.sheets: unknown keys"),
])
def test_seed_keys_the_seeder_does_not_map_fail(mutate, match):
    seed = load_seed()
    validate_seed(seed)
    mutate(seed)
    with pytest.raises(ValueError, match=match):
        validate_seed(seed)


# ── Seeding ────────────────────────────────────────────────────────────────

async def test_seed_replaces_every_placeholder(ev4, db):
    a = ev4.a
    assert {c.kind for c in a.canaries} == GM_ONLY_KINDS
    assert all(CANARIES[c.token] == c and c.campaign_id == a.campaign_id for c in a.canaries)
    found: set[str] = set()
    for table in ("journal_entries", "npcs", "quests", "shorthand_terms", "session_plans", "chat_sessions",
                  "source_documents", "source_chunks", "character_sheets"):
        rows = (await db.execute(
            sa.text(f"SELECT to_jsonb(t)::text FROM {table} t WHERE campaign_id = :c"), {"c": a.campaign_id}
        )).scalars().all()
        assert rows, f"no {table} rows seeded"
        text = "\n".join(rows)
        assert "{canary:" not in text
        assert set(find_canaries(text)) <= a.tokens
        assert find_canaries(text), f"{table} holds no canary"
        found |= set(find_canaries(text))
    assert a.tokens <= found, f"minted but never stored: {sorted(a.tokens - found)}"


async def test_canaries_are_unique_per_seeding(ev4, db):
    other = await seed_canary_campaign(db, await create_user(db, "second_owner"))
    assert other.campaign_id != ev4.a.campaign_id
    assert not other.tokens & ev4.a.tokens
    assert len(ev4.a.tokens) == len(ev4.a.canaries), "a token was reused within one seeding"
    for token in ev4.a.tokens:
        assert CANARY_RE.fullmatch(token)
        assert uuid.UUID(token.split("-", 2)[2]).version == 4


# ── Actors and the positive control (AC 3) ─────────────────────────────────

async def test_gm_npc_listing_is_a_positive_control(ev4):
    gm, anon = await ev4.actor("gm_owner"), await ev4.actor("anon_share")
    r = await gm.get(f"/api/npcs/?campaign_id={ev4.a.campaign_id}")
    assert r.status_code == 200, r.text
    assert ev4.a.canary("NPCNOTES").token in r.text
    assert_no_canary(gm, r)  # the GM may see their own Campaign's canaries

    for viewer in (anon, await ev4.actor("anonymous")):
        before = report.leak_count()
        with report.scoped() as scoped, pytest.raises(EV4Leak, match="NPCNOTES"):
            assert_no_canary(viewer, r)
        assert scoped.leaks == 1
        assert report.leak_count() == before


async def test_share_reads_as_anon_share_are_clean(ev4):
    anon = await ev4.actor("anon_share")
    token = anon.share_token
    journal_id = ev4.a.ids["journal_entries"][0]
    for path in ("", "/journals", f"/journals/{journal_id}", "/npcs", "/quests"):
        r = await anon.get(f"/api/share/{token}{path}")
        assert r.status_code == 200, (path, r.text)
        assert_no_canary(anon, r)
    npcs = (await anon.get(f"/api/share/{token}/npcs")).json()
    assert [n["name"] for n in npcs] == ["Barnaby"]
    journals = (await anon.get(f"/api/share/{token}/journals")).json()
    assert journals["total"] == len(ev4.a.ids["journal_entries"])


async def test_anonymous_actor_is_refused(ev4):
    anon = await ev4.actor("anonymous")
    r = await anon.get(f"/api/npcs/?campaign_id={ev4.a.campaign_id}")
    assert r.status_code in (401, 403)
    assert_no_canary(anon, r)


async def test_may_see_only_as_gm_of_the_canary_campaign(ev4):
    canary = ev4.a.canary("NPCNOTES")
    assert (await ev4.actor("gm_owner")).may_see(canary)
    assert (await ev4.actor("gm_owner")).may_see(canary.token)
    assert not (await ev4.actor("anon_share")).may_see(canary)
    assert not (await ev4.actor("anonymous")).may_see(canary)
    assert not (await ev4.actor("gm_owner")).may_see(f"CANARY-NPCNOTES-{uuid.uuid4()}")


async def test_unknown_actor_name_fails(ev4):
    with pytest.raises(KeyError, match="gm_owner"):
        await ev4.actor("nobody")


# ── Roles ──────────────────────────────────────────────────────────────────

async def _stored_role(db, campaign_id, user_id) -> str | None:
    return await db.scalar(sa.text(
        "SELECT role::text FROM campaign_members WHERE campaign_id = :c AND user_id = :u"
    ), {"c": campaign_id, "u": user_id})


async def test_make_member_writes_role(ev4, db):
    user = await ev4.make_member(role="player")
    assert await _stored_role(db, ev4.a.campaign_id, user.id) == "player"


@pytest.mark.parametrize("role", ["gm", "co_gm"])
async def test_make_member_gm_is_stored_as_co_gm(ev4, db, role):
    user = await ev4.make_member(role=role)
    assert await _stored_role(db, ev4.a.campaign_id, user.id) == "co_gm"


async def test_make_member_rejects_unknown_role(ev4):
    with pytest.raises(ValueError, match="unknown role 'owner'"):
        await ev4.make_member(role="owner")


@pytest.mark.parametrize("name, stored", [
    ("player", "player"), ("player_2", "player"), ("co_gm", "co_gm"), ("cross_gm_player", "player"),
])
async def test_role_actors_resolve_lazily(ev4, db, name, stored):
    actor = await ev4.actor(name)
    a = ev4.a.campaign_id
    assert actor.grants[a] == ("gm" if name == "co_gm" else "player")
    assert await _stored_role(db, a, actor.user_id) == stored
    if name == "cross_gm_player":
        assert actor.may_see(ev4.b.canary("NPCNOTES"))
        assert not actor.may_see(ev4.a.canary("NPCNOTES"))
        # Owns Campaign B, so no member row there (the Owner never has one).
        assert await _stored_role(db, ev4.b.campaign_id, actor.user_id) is None


async def test_module_level_make_member(ev4, db):
    # E0-Access.13 calls tests.ev4.fixtures.make_member(db, role=..., campaign_id=...).
    from tests.ev4.fixtures import make_member

    user = await make_member(db, role="gm", campaign_id=ev4.a.campaign_id)
    row = (await db.execute(sa.text(
        "SELECT role::text, access_epoch, created_at IS NOT NULL, updated_at IS NOT NULL "
        "FROM campaign_members WHERE campaign_id = :c AND user_id = :u"
    ), {"c": ev4.a.campaign_id, "u": user.id})).one()
    assert tuple(row) == ("co_gm", 0, True, True)
