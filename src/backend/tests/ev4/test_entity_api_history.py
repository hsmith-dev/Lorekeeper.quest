"""EV-4 (E0-WorldCore.5): what the Entity API shows a Player of history,
aliases and Entity references, over HTTP.

  * History written before an Entity was published stays GM-only after it is
    published (owner decision round 4: `entity_changes.write_visibility`).
  * History written while a field was hidden stays GM-only after the field
    is shown again.
  * A hidden `aliases` field: the body shows `[]`, the alias rows are absent
    from every read (list, item, search) and so is their history.
  * An ENTITY_REF naming a GM-only Entity: the attribute is absent and the
    history values are null; the id appears nowhere in the Player's bodies.
  * After the F3-world copy, a Player's list of a Campaign with only migrated
    (GM-only) Entities is byte-identical to an empty Campaign's.

Every GM step goes through the routes too (the gm_owner actor); the GM's
bodies are the positive control.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from app.db.models.campaign import Campaign, Genre
from tests.ev4.families import _headers, assert_no_canary
from tests.ev4.fixtures import create_user, mint_canary

BASE = "/api/entities"
BACKEND_DIR = Path(__file__).resolve().parents[2]


async def _gm_player(ev4):
    return await ev4.actor("gm_owner"), await ev4.actor("player")


async def _create(gm, ev4, **body) -> str:
    r = await gm.post(f"{BASE}/", json={"campaign_id": str(ev4.a.campaign_id), **body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


async def _publish(gm, entity_id, field=None, visibility="party"):
    body = {"visibility": visibility} | ({"field": field} if field else {})
    await _ok(await gm.post(f"{BASE}/{entity_id}/visibility", json=body))


async def _history(actor, entity_id) -> dict:
    return await _ok(await actor.get(f"{BASE}/{entity_id}/history"))


async def test_pre_publish_history_stays_gm_only(ev4):
    gm, player = await _gm_player(ev4)
    canary = mint_canary("XWC5DRAFT", ev4.a.campaign_id).token
    entity_id = await _create(gm, ev4, type="character", kind="npc", name="Mira")
    await _ok(await gm.patch(f"{BASE}/{entity_id}", json={"description": canary}))
    await _ok(await gm.patch(f"{BASE}/{entity_id}", json={"description": "A sailor"}))
    await _publish(gm, entity_id)
    await _ok(await gm.patch(f"{BASE}/{entity_id}", json={"name": "Mira Vale"}))

    r = await player.get(f"{BASE}/{entity_id}/history")
    assert_no_canary(player, r)
    items = (await _ok(r))["items"]
    assert [(i["op"], i["field"], i["old_value"], i["new_value"]) for i in items] == [
        ("update_field", "name", "Mira", "Mira Vale")], items
    assert (await _ok(r))["total"] == 1
    gm_items = (await _history(gm, entity_id))["items"]
    assert canary in str(gm_items)
    assert {i["write_visibility"] for i in gm_items} == {"gm", "party"}
    assert [i["field"] for i in gm_items if i["write_visibility"] == "party"] == ["name"]


async def test_history_written_while_a_field_was_hidden_stays_hidden(ev4):
    gm, player = await _gm_player(ev4)
    canary = mint_canary("XWC5HIDDEN", ev4.a.campaign_id).token
    entity_id = await _create(gm, ev4, type="location", name="Harbor", description="Quiet")
    await _publish(gm, entity_id)
    await _publish(gm, entity_id, "description", "gm")
    await _ok(await gm.patch(f"{BASE}/{entity_id}", json={"description": canary}))
    await _ok(await gm.patch(f"{BASE}/{entity_id}", json={"description": "Busy"}))
    await _publish(gm, entity_id, "description", "party")

    body = await _ok(await player.get(f"{BASE}/{entity_id}"))
    assert body["description"] == "Busy"  # the field itself is shown again
    r = await player.get(f"{BASE}/{entity_id}/history")
    assert_no_canary(player, r)
    assert canary not in r.text
    assert [i for i in (await _ok(r))["items"] if i["field"] == "description"] == []
    assert canary in str(await _history(gm, entity_id))


async def test_hidden_aliases_are_absent_everywhere(ev4):
    gm, player = await _gm_player(ev4)
    a = ev4.a.campaign_id
    canary = mint_canary("XWC5ALIAS", a).token
    entity_id = await _create(gm, ev4, type="character", kind="npc", name="Aldric")
    await _publish(gm, entity_id)
    await _ok(await gm.post(f"{BASE}/{entity_id}/aliases", json={"alias": "Greyhawk"}), 201)
    await _publish(gm, entity_id, "aliases", "gm")
    await _ok(await gm.post(f"{BASE}/{entity_id}/aliases", json={"alias": canary}), 201)

    for url in (f"{BASE}/{entity_id}", f"{BASE}/?campaign_id={a}", f"{BASE}/{entity_id}/history",
                f"{BASE}/?campaign_id={a}&q=Greyhawk"):
        r = await player.get(url)
        assert_no_canary(player, r)
        assert r.status_code == 200 and "Greyhawk" not in r.text, (url, r.text)
    assert (await _ok(await player.get(f"{BASE}/{entity_id}")))["aliases"] == []
    items = (await _ok(await player.get(f"{BASE}/?campaign_id={a}")))["items"]
    assert [(i["id"], i["aliases"]) for i in items] == [(entity_id, [])]
    assert (await _ok(await player.get(f"{BASE}/?campaign_id={a}&q=Greyhawk")))["total"] == 0
    assert [i for i in (await _history(player, entity_id))["items"] if i["field"] == "aliases"] == []
    # The GM control.
    assert {x["alias"] for x in (await _ok(await gm.get(f"{BASE}/{entity_id}")))["aliases"]} == {"Greyhawk", canary}
    assert (await _ok(await gm.get(f"{BASE}/?campaign_id={a}&q=Greyhawk")))["total"] == 1


async def test_a_hidden_entity_ref_is_never_named(ev4):
    gm, player = await _gm_player(ev4)
    a = ev4.a.campaign_id
    location = await _create(gm, ev4, type="location", name=mint_canary("XWC5LOC", a).token)
    seen = await _create(gm, ev4, type="character", kind="npc", name="Giver")
    quest = await _create(gm, ev4, type="quest", name="Find the bell")
    await _publish(gm, quest)
    await _publish(gm, seen)
    await _ok(await gm.patch(f"{BASE}/{quest}", json={"attributes": {
        "location_entity_id": location, "giver_entity_id": seen}}))

    body = await _ok(await player.get(f"{BASE}/{quest}"))
    assert "location_entity_id" not in body["attributes"]
    assert body["attributes"]["giver_entity_id"] == seen  # a visible reference stays
    history = await _history(player, quest)
    by_field = {i["field"]: i for i in history["items"]}
    assert (by_field["attributes.location_entity_id"]["old_value"],
            by_field["attributes.location_entity_id"]["new_value"]) == (None, None)
    assert by_field["attributes.giver_entity_id"]["new_value"] == seen
    for url in (f"{BASE}/{quest}", f"{BASE}/{quest}/history", f"{BASE}/?campaign_id={a}",
                f"{BASE}/?campaign_id={a}&q=bell"):
        r = await player.get(url)
        assert_no_canary(player, r)
        assert r.status_code == 200 and location not in r.text, (url, r.text)
    # The GM control.
    assert (await _ok(await gm.get(f"{BASE}/{quest}")))["attributes"]["location_entity_id"] == location
    assert location in str(await _history(gm, quest))


def _f3_world():
    spec = importlib.util.spec_from_file_location(
        "f3_world_revision_wc5", BACKEND_DIR / "migrations" / "versions" / "03c0b504f1d1_f3_world_entities_legacy_copy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_post_upgrade_player_list_is_the_empty_list(ev4, db):
    f3_world = _f3_world()
    await db.run_sync(lambda session: f3_world.apply_data_steps(session.connection()))
    await db.commit()
    player = await ev4.actor("player")
    gm = await ev4.actor("gm_owner")
    a = ev4.a.campaign_id
    # The control: the GM sees the migrated (GM-only) Entities.
    assert (await _ok(await gm.get(f"{BASE}/?campaign_id={a}")))["total"] == len(ev4.a.ids["npcs"]) + len(
        ev4.a.ids["quests"])
    owner = await create_user(db, "empty-owner")
    empty = Campaign(user_id=owner.id, name="Empty", genre=Genre.fantasy)
    db.add(empty)
    await db.commit()
    await ev4.make_member("player", campaign_id=empty.id, user=await _user(db, player.user_id))

    migrated = await player.get(f"{BASE}/?campaign_id={a}")
    nothing = await player.get(f"{BASE}/?campaign_id={empty.id}")
    assert_no_canary(player, migrated)
    assert migrated.status_code == nothing.status_code == 200
    assert migrated.content == nothing.content == b'{"items":[],"total":0,"limit":50,"offset":0}'
    assert _headers(migrated) == _headers(nothing)
    for npc_or_quest in await _migrated_ids(db, a):
        r = await player.get(f"{BASE}/{npc_or_quest}")
        missing = await player.get(f"{BASE}/00000000-0000-4000-8000-000000000000")
        assert (r.status_code, r.content) == (missing.status_code, missing.content) == (
            404, b'{"detail":"Not found"}')


async def _user(db, user_id):
    from app.db.models.user import User

    return await db.get(User, user_id)


async def _migrated_ids(db, campaign_id) -> list[str]:
    import sqlalchemy as sa

    from app.db.models.entity import Entity

    return [str(i) for i in (await db.execute(sa.select(Entity.id).where(Entity.campaign_id == campaign_id)))
            .scalars().all()]
