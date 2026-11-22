"""E0-WorldCore.6: /api/npcs and /api/quests as adapters over `entities`.

The GM (the Owner of the canary Campaign A) and a Player drive the legacy
routes: ids (legacy id for a copied Entity, Entity id otherwise, either id
accepted), the value maps both ways, writes that skip unchanged fields, the
422 on a character <-> faction change, soft delete, entries from confirmed
Mentions only, Locations/Items/deleted/merged Entities as the 404, and the
AI helpers reading Entities. What a Player may not see is EV-4's
(tests/ev4/probes/npcs.py, quests.py, entity_legacy.py).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import sqlalchemy as sa

from app.access import ctx_for, set_visibility
from app.db.models.entity import Entity, EntityChange
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.tag import TagType
from app.domain import legacy_world as lw
from app.schemas.npc import NpcGMResponse, NpcPartyResponse
from app.schemas.quest import QuestGMResponse, QuestPartyResponse
from app.schemas.sources import RecordRef
from app.services.world_service import apply_change
from tests.ev4.fixtures import ev4  # noqa: F401  (registers the fixture)
from tests.ev4.probes._support import MISSING, world_npc, world_quest

NOT_FOUND = {"detail": "Not found"}


async def _gm(ev4):
    return await ctx_for(ev4.db, ev4.a.owner_id, ev4.a.campaign_id)


async def _create(ev4, **change) -> uuid.UUID:
    change.setdefault("op", "create_entity")
    if change.get("type") == "character":
        change.setdefault("kind", "npc")
    row = await apply_change(ev4.db, await _gm(ev4), change)
    await ev4.db.commit()
    return row.entity_id


async def _publish(ev4, entity_id, field=None, value="party") -> None:
    await set_visibility(ev4.db, await _gm(ev4), RecordRef(kind="entity", id=entity_id, field=field), value)
    await ev4.db.commit()


async def _entity(ev4, entity_id) -> Entity:
    return (await ev4.db.execute(sa.select(Entity).where(Entity.id == entity_id)
                                 .execution_options(populate_existing=True))).scalar_one()


async def _changes(ev4, entity_id) -> list[tuple[str, str | None]]:
    rows = (await ev4.db.execute(sa.select(EntityChange.op, EntityChange.field)
                                 .where(EntityChange.entity_id == entity_id)
                                 .order_by(EntityChange.created_at, EntityChange.id))).all()
    return [tuple(r) for r in rows]


# ── Reads ──────────────────────────────────────────────────────────────────

async def test_gm_list_shows_copied_and_new_npcs_in_the_legacy_shape(ev4):
    gm = await ev4.actor("gm_owner")
    legacy_id = await world_npc(ev4)  # Barnaby, copied
    new = await _create(ev4, type="character", name="Aldric", status="missing")
    await _create(ev4, type="faction", name="Ashen Hand", status="disbanded")
    await _create(ev4, type="location", name="Bree")
    await _create(ev4, type="item", name="Bell")
    r = await gm.get(f"/api/npcs/?campaign_id={ev4.a.campaign_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["name"] for b in body] == ["Aldric", "Ashen Hand", "Barnaby"]
    assert all(set(b) == set(NpcGMResponse.model_fields) for b in body)
    by_name = {b["name"]: b for b in body}
    assert by_name["Barnaby"]["id"] == str(legacy_id) and by_name["Aldric"]["id"] == str(new)
    assert (by_name["Aldric"]["role"], by_name["Aldric"]["status"]) == ("npc", "unknown")  # missing -> unknown
    assert (by_name["Ashen Hand"]["role"], by_name["Ashen Hand"]["status"]) == ("faction", "dead")
    assert by_name["Barnaby"]["notes"] == ev4.a.canary("NPCNOTES").token
    # Either id reaches the copied NPC, and both answer the legacy id.
    for any_id in (legacy_id, lw.legacy_entity_id("npc", legacy_id)):
        r = await gm.get(f"/api/npcs/{any_id}")
        assert r.status_code == 200 and r.json()["id"] == str(legacy_id), r.text


async def test_player_list_is_empty_until_published_then_party_shaped(ev4):
    player = await ev4.actor("player")
    await world_npc(ev4)
    shown = await _create(ev4, type="character", name="Mira", gm_notes="secret", status="deceased",
                          description="A sailor")
    url = f"/api/npcs/?campaign_id={ev4.a.campaign_id}"
    assert (await player.get(url)).json() == []
    await _publish(ev4, shown)
    body = (await player.get(url)).json()
    assert body == [{"id": str(shown), "campaign_id": str(ev4.a.campaign_id), "name": "Mira", "role": "npc",
                     "status": "dead", "description": "A sailor"}]
    assert set(body[0]) == set(NpcPartyResponse.model_fields)
    # A hidden status reads as unset.
    await _publish(ev4, shown, "status", "gm")
    assert (await player.get(f"/api/npcs/{shown}")).json()["status"] == "unknown"


async def test_locations_items_deleted_and_merged_are_not_npcs(ev4):
    gm = await ev4.actor("gm_owner")
    location = await _create(ev4, type="location", name="Bree")
    gone = await _create(ev4, type="character", name="Gone")
    absorbed = await _create(ev4, type="character", name="Old Mira")
    survivor = await _create(ev4, type="character", name="Mira")
    ctx = await _gm(ev4)
    await apply_change(ev4.db, ctx, {"op": "delete_entity", "entity_id": gone})
    await apply_change(ev4.db, ctx.as_system("merge"), {"op": "merge", "entity_id": absorbed, "survivor_id": survivor})
    await ev4.db.commit()
    quest = await _create(ev4, type="quest", name="Find the bell")
    missing = await gm.get(f"/api/npcs/{MISSING}")
    for eid in (location, gone, absorbed, quest):
        r = await gm.get(f"/api/npcs/{eid}")
        assert (r.status_code, r.content) == (404, missing.content), eid
    assert (await gm.get(f"/api/quests/{location}")).json() == NOT_FOUND
    names = [b["name"] for b in (await gm.get(f"/api/npcs/?campaign_id={ev4.a.campaign_id}")).json()]
    assert names == ["Mira"]


# ── Writes ─────────────────────────────────────────────────────────────────

async def test_gm_create_maps_role_and_status(ev4, db):
    gm = await ev4.actor("gm_owner")
    r = await gm.post("/api/npcs/", json={"campaign_id": str(ev4.a.campaign_id), "name": "Ashen Hand",
                                          "role": "faction", "status": "dead", "notes": "n"})
    assert r.status_code == 201, r.text
    body = r.json()
    entity = await _entity(ev4, uuid.UUID(body["id"]))
    assert (entity.type, entity.kind, entity.status, entity.gm_notes, entity.visibility) == (
        "faction", None, "disbanded", "n", "gm")
    assert (body["role"], body["status"]) == ("faction", "dead")
    assert await _changes(ev4, entity.id) == [("create_entity", None)]
    r = await gm.post("/api/npcs/", json={"campaign_id": str(ev4.a.campaign_id), "name": "Grukk",
                                          "role": "monster"})
    entity = await _entity(ev4, uuid.UUID(r.json()["id"]))
    assert (entity.type, entity.kind, entity.status) == ("character", "creature", "unknown")
    assert (r.json()["role"], r.json()["status"]) == ("monster", "unknown")
    # No legacy row is ever written.
    assert await db.scalar(sa.select(sa.func.count()).select_from(NpcEntry)
                           .where(NpcEntry.campaign_id == ev4.a.campaign_id)) == len(ev4.a.ids["npcs"])


async def test_gm_update_writes_only_what_changes(ev4):
    gm = await ev4.actor("gm_owner")
    npc = await _create(ev4, type="character", name="Aldric", status="missing")
    r = await gm.put(f"/api/npcs/{npc}", json={"name": "Brother Aldric", "role": "npc", "status": "unknown"})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["status"]) == ("Brother Aldric", "unknown")
    assert await _changes(ev4, npc) == [("create_entity", None), ("update_field", "name")]
    assert (await _entity(ev4, npc)).status == "missing"  # unknown in the legacy view: kept
    r = await gm.put(f"/api/npcs/{npc}", json={"role": "pc", "status": "dead", "notes": "gm only"})
    entity = await _entity(ev4, npc)
    assert (entity.kind, entity.status, entity.gm_notes) == ("pc", "deceased", "gm only")
    assert r.json()["role"] == "pc"


async def test_role_change_between_character_and_faction_is_422(ev4):
    gm = await ev4.actor("gm_owner")
    npc = await _create(ev4, type="character", name="Aldric")
    before = await _changes(ev4, npc)
    r = await gm.put(f"/api/npcs/{npc}", json={"name": "New", "role": "faction"})
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    assert await _changes(ev4, npc) == before
    assert (await _entity(ev4, npc)).name == "Aldric"


async def test_player_writes_are_404_and_write_nothing(ev4):
    player = await ev4.actor("player")
    npc = await _create(ev4, type="character", name="Mira")
    await _publish(ev4, npc)  # visible, still not writable
    before = await _changes(ev4, npc)
    for method, url, body in (("PUT", f"/api/npcs/{npc}", {"name": "x"}), ("DELETE", f"/api/npcs/{npc}", None),
                              ("POST", "/api/npcs/", {"name": "x", "campaign_id": str(ev4.a.campaign_id)}),
                              ("POST", f"/api/npcs/{npc}/generate", None)):
        r = await player.request(method, url, json=body)
        assert (r.status_code, r.json()) == (404, NOT_FOUND), (method, url, r.text)
    assert await _changes(ev4, npc) == before


async def test_delete_is_soft(ev4):
    gm = await ev4.actor("gm_owner")
    legacy_id = await world_npc(ev4)
    assert (await gm.delete(f"/api/npcs/{legacy_id}")).status_code == 204
    entity = await _entity(ev4, lw.legacy_entity_id("npc", legacy_id))
    assert entity.deleted_at is not None
    assert (await _changes(ev4, entity.id))[-1] == ("delete_entity", None)
    assert (await gm.get(f"/api/npcs/{legacy_id}")).status_code == 404


async def test_quests_map_and_order(ev4):
    gm = await ev4.actor("gm_owner")
    legacy_id = await world_quest(ev4)
    failed = await _create(ev4, type="quest", name="Lost cause", status="failed")
    done = await _create(ev4, type="quest", name="Rescue", status="completed")
    r = await gm.get(f"/api/quests/?campaign_id={ev4.a.campaign_id}")
    body = r.json()
    assert [b["status"] for b in body] == ["active", "completed", "failed"]
    assert [b["id"] for b in body] == [str(legacy_id), str(done), str(failed)]
    assert all(set(b) == set(QuestGMResponse.model_fields) for b in body)
    r = await gm.put(f"/api/quests/{legacy_id}", json={"status": "completed", "title": "Found"})
    assert (r.json()["status"], r.json()["title"]) == ("completed", "Found")
    entity = await _entity(ev4, lw.legacy_entity_id("quest", legacy_id))
    assert entity.status == "completed" and entity.attributes.get("completed_at")
    r = await gm.post("/api/quests/", json={"campaign_id": str(ev4.a.campaign_id), "title": "Heist"})
    assert r.status_code == 201 and r.json()["status"] == "active", r.text
    player = await ev4.actor("player")
    await _publish(ev4, failed)
    await _publish(ev4, done)
    body = (await player.get(f"/api/quests/?campaign_id={ev4.a.campaign_id}")).json()
    assert [b["id"] for b in body] == [str(done), str(failed)]
    assert all(set(b) == set(QuestPartyResponse.model_fields) for b in body)
    assert await ev4.db.scalar(sa.select(sa.func.count()).select_from(Quest)
                               .where(Quest.campaign_id == ev4.a.campaign_id)) == len(ev4.a.ids["quests"])


# ── Entries ────────────────────────────────────────────────────────────────

async def test_entries_are_the_confirmed_mentions_only(ev4):
    from tests.ev4.probes._support import add_entry

    gm = await ev4.actor("gm_owner")
    legacy_id = await world_npc(ev4)
    entity_id = lw.legacy_entity_id("npc", legacy_id)
    ctx = await _gm(ev4)
    confirmed = [await add_entry(ev4, visibility="party", canary=False) for _ in range(22)]
    suggested = await add_entry(ev4, visibility="party", canary=False)
    named_only = await add_entry(ev4, visibility="party", canary=False)  # no Mention at all
    for entry in confirmed:
        await apply_change(ev4.db, ctx, {"op": "add_mention", "entity_id": entity_id, "journal_id": entry,
                                         "confirmed": True})
    await apply_change(ev4.db, ctx, {"op": "add_mention", "entity_id": entity_id, "journal_id": suggested})
    await ev4.db.commit()
    r = await gm.get(f"/api/npcs/{legacy_id}/entries")
    assert r.status_code == 200, r.text
    ids = [i["id"] for i in r.json()]
    assert len(ids) == 20 and set(ids) <= {str(e) for e in confirmed}
    assert str(suggested) not in ids and str(named_only) not in ids
    assert all("shorthand" in i for i in r.json())


# ── The AI helpers read Entities ───────────────────────────────────────────

async def test_generate_and_extract_read_entities(ev4, monkeypatch):
    from app.api.routes import npcs as npc_routes
    from tests.ev4.probes.retrieval import use_fake_llm

    gm = await ev4.actor("gm_owner")
    await use_fake_llm(ev4, gm)
    legacy_id = await world_npc(ev4)
    await _create(ev4, type="faction", name="Ashen Hand")
    seen = {}

    async def bio(name, role, entries, campaign_name, genre, *, config):
        seen.update(name=name, role=role)
        return "A bio."

    monkeypatch.setattr(npc_routes, "generate_npc_bio", bio)
    r = await gm.post(f"/api/npcs/{legacy_id}/generate")
    assert r.status_code == 200 and r.json() == {"description": "A bio."}, r.text
    assert seen == {"name": "Barnaby", "role": "npc"}

    async def tags(_text):
        return [SimpleNamespace(name=n, tag_type=TagType.character) for n in ("Barnaby", "ashen hand", "Wren")]

    monkeypatch.setattr(npc_routes, "extract_tags", tags)
    r = await gm.post(f"/api/npcs/extract?campaign_id={ev4.a.campaign_id}")
    assert r.status_code == 200 and r.json() == {"suggestions": ["Wren"]}, r.text
