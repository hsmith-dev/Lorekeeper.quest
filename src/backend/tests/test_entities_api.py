"""E0-WorldCore.5: the Entity API's GM behaviour (app/api/routes/entities.py)
and the `entity_field` source resolver.

What a Player may not see is EV-4's (tests/ev4/probes/entities.py,
tests/ev4/test_entity_api_history.py); here the GM (the Owner of the canary
Campaign A) drives every route: create and the duplicate 409, the list
filters and pagination, a multi-field PATCH in one transaction, soft delete,
aliases, Quest steps, history order, revert, and single and bulk Visibility.
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa

from app.access import ctx_for, resolve_sources
from app.db.models.entity import Entity, EntityChange
from app.schemas.sources import SourceKind, SourceRef
from app.services.world_service import apply_change
from tests.ev4.probes._support import MISSING, outsider
from tests.ev4.fixtures import ev4  # noqa: F401  (registers the fixture)

BASE = "/api/entities"


async def _ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


async def _create(gm, ev4, expect: int = 201, **body):
    body.setdefault("type", "character")
    if body["type"] == "character":
        body.setdefault("kind", "npc")
    return await _ok(await gm.post(f"{BASE}/", json={"campaign_id": str(ev4.a.campaign_id), **body}), expect)


async def _history_count(db, entity_id) -> int:
    return (await db.execute(sa.select(sa.func.count()).select_from(EntityChange)
                             .where(EntityChange.entity_id == uuid.UUID(str(entity_id))))).scalar_one()


async def _list(gm, ev4, query: str = "") -> dict:
    return await _ok(await gm.get(f"{BASE}/?campaign_id={ev4.a.campaign_id}{query}"))


# ── Create ─────────────────────────────────────────────────────────────────

async def test_create_returns_the_gm_body(ev4):
    gm = await ev4.actor("gm_owner")
    body = await _create(gm, ev4, name="Mira", description="A sailor", gm_notes="Owes the guild",
                         attributes={"pronouns": "she/her"})
    assert (body["name"], body["visibility"], body["status"], body["kind"]) == ("Mira", "gm", "unknown", "npc")
    assert (body["gm_notes"], body["attributes"]) == ("Owes the guild", {"pronouns": "she/her"})
    assert (body["aliases"], body["steps"], body["mention_count"]) == ([], [], 0)


async def test_create_refuses_a_duplicate_name_of_the_same_type(ev4, db):
    gm = await ev4.actor("gm_owner")
    first = await _create(gm, ev4, name="Brother  Aldric")
    for name in ("aldric", "  ALDRIC ", "The Aldric"):
        r = await gm.post(f"{BASE}/", json={"campaign_id": str(ev4.a.campaign_id), "type": "character",
                                            "kind": "npc", "name": name})
        assert r.status_code == 409, r.text
        assert r.json() == {"detail": "An Entity with this name exists", "code": "duplicate",
                            "existing_id": first["id"]}
    # Another type, a deleted Entity and another Campaign's Entity do not count.
    await _create(gm, ev4, type="location", name="Aldric")
    gone = await _create(gm, ev4, name="Pip")
    await _ok(await gm.delete(f"{BASE}/{gone['id']}"), 204)
    await _create(gm, ev4, name="Pip")
    other = await outsider(ev4)
    other_gm = await ctx_for(db, other.owner_id, other.campaign_id)
    await apply_change(db, other_gm, {"op": "create_entity", "type": "character", "kind": "npc", "name": "Wren"})
    await db.commit()
    await _create(gm, ev4, name="Wren")


async def test_create_validates_its_body(ev4):
    gm = await ev4.actor("gm_owner")
    a = str(ev4.a.campaign_id)
    for bad in ({"type": "character", "kind": "npc", "name": "  "},
                {"type": "character", "kind": "npc", "name": "X", "visibility": "party"},
                {"type": "planet", "name": "X"}):
        assert (await gm.post(f"{BASE}/", json={"campaign_id": a, **bad})).status_code == 422
    r = await gm.post(f"{BASE}/", json={"campaign_id": a, "type": "character", "kind": "npc", "name": "X",
                                        "status": "zombie"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_status", r.text
    r = await gm.post(f"{BASE}/", json={"campaign_id": a, "type": "item", "name": "X",
                                        "attributes": {"holder_entity_id": MISSING}})
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text


# ── List ───────────────────────────────────────────────────────────────────

async def test_list_filters_and_pagination(ev4, db):
    gm = await ev4.actor("gm_owner")
    names = ["bravo", "Alpha", "charlie", "Delta"]
    made = {n: await _create(gm, ev4, name=n) for n in names}
    loc = await _create(gm, ev4, type="location", name="Echo", status="destroyed")
    await _ok(await gm.post(f"{BASE}/{made['charlie']['id']}/visibility", json={"visibility": "party"}))
    await _ok(await gm.patch(f"{BASE}/{made['Delta']['id']}", json={"status": "deceased"}))
    gone = await _create(gm, ev4, name="Foxtrot")
    await _ok(await gm.delete(f"{BASE}/{gone['id']}"), 204)
    absorbed = await _create(gm, ev4, name="Golf")
    ctx = await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)
    await apply_change(db, ctx.as_system("merge"), {"op": "merge", "entity_id": absorbed["id"],
                                                    "survivor_id": made["Alpha"]["id"]})
    await db.commit()

    everything = await _list(gm, ev4)
    assert [i["name"] for i in everything["items"]] == ["Alpha", "bravo", "charlie", "Delta", "Echo"]
    assert everything["total"] == 5 and (everything["limit"], everything["offset"]) == (50, 0)
    assert [i["name"] for i in (await _list(gm, ev4, "&type=location"))["items"]] == ["Echo"]
    assert [i["name"] for i in (await _list(gm, ev4, "&status=deceased"))["items"]] == ["Delta"]
    assert [i["name"] for i in (await _list(gm, ev4, "&visibility=party"))["items"]] == ["charlie"]
    page = await _list(gm, ev4, "&limit=2&offset=1")
    assert ([i["name"] for i in page["items"]], page["total"], page["limit"], page["offset"]) == (
        ["bravo", "charlie"], 5, 2, 1)
    # The merged Entity's name is now an alias of the survivor: q finds the survivor.
    found = await _list(gm, ev4, "&q=golf")
    assert [i["id"] for i in found["items"]] == [made["Alpha"]["id"]]
    assert "Golf" in {a["alias"] for a in found["items"][0]["aliases"]}
    assert (await _list(gm, ev4, "&q=Delta&type=location"))["total"] == 0
    assert [i["id"] for i in (await _list(gm, ev4, "&q=echo&status=destroyed"))["items"]] == [loc["id"]]
    for bad in ("&limit=0", "&limit=201", "&offset=-1", "&type=planet"):
        assert (await gm.get(f"{BASE}/?campaign_id={ev4.a.campaign_id}{bad}")).status_code == 422


# ── Patch and delete ───────────────────────────────────────────────────────

async def test_patch_applies_every_field_in_one_transaction(ev4, db):
    gm = await ev4.actor("gm_owner")
    entity = await _create(gm, ev4, type="quest", name="Find the bell")
    body = await _ok(await gm.patch(f"{BASE}/{entity['id']}", json={
        "name": "Ring the bell", "description": "Loud", "gm_notes": "It is cracked", "status": "completed",
        "attributes": {"reward": "Gold"}}))
    assert (body["name"], body["description"], body["gm_notes"], body["status"]) == (
        "Ring the bell", "Loud", "It is cracked", "completed")
    assert body["attributes"]["reward"] == "Gold" and "completed_at" in body["attributes"]
    rows = await _history_count(db, entity["id"])
    # A failing field writes nothing, not even the fields before it.
    for bad, code in (({"name": "Never", "status": "zombie"}, "invalid_status"),
                      ({"description": "Never", "attributes": {"nope": "x"}}, "invalid")):
        r = await gm.patch(f"{BASE}/{entity['id']}", json=bad)
        assert r.status_code == 422 and r.json()["code"] == code, r.text
    assert await _history_count(db, entity["id"]) == rows
    again = await _ok(await gm.get(f"{BASE}/{entity['id']}"))
    assert (again["name"], again["description"]) == ("Ring the bell", "Loud")
    for bad in ({}, {"visibility": "party"}, {"field_visibility": {"status": "gm"}}, {"name": None}, {"attributes": {}}):
        assert (await gm.patch(f"{BASE}/{entity['id']}", json=bad)).status_code == 422


async def test_delete_is_soft_and_a_deleted_entity_is_409(ev4):
    gm = await ev4.actor("gm_owner")
    entity = await _create(gm, ev4, name="Bell keeper")
    await _ok(await gm.delete(f"{BASE}/{entity['id']}"), 204)
    body = await _ok(await gm.get(f"{BASE}/{entity['id']}"))
    assert body["deleted_at"] is not None
    assert (await _list(gm, ev4))["total"] == 0
    r = await gm.patch(f"{BASE}/{entity['id']}", json={"name": "Back"})
    assert r.status_code == 409 and r.json() == {"detail": "This Entity was deleted", "code": "deleted"}, r.text
    assert (await gm.get(f"{BASE}/{MISSING}")).json() == {"detail": "Not found"}


# ── Aliases and steps ──────────────────────────────────────────────────────

async def test_aliases_add_and_remove(ev4):
    gm = await ev4.actor("gm_owner")
    entity = await _create(gm, ev4, name="Aldric")
    other = await _create(gm, ev4, name="Wren")
    alias = await _ok(await gm.post(f"{BASE}/{entity['id']}/aliases", json={"alias": "  Brother   Al "}), 201)
    assert (alias["alias"], alias["entity_id"]) == ("Brother Al", entity["id"])
    assert [a["alias"] for a in (await _ok(await gm.get(f"{BASE}/{entity['id']}")))["aliases"]] == ["Brother Al"]
    # Another Entity's alias is the 404, and stays.
    r = await gm.delete(f"{BASE}/{other['id']}/aliases/{alias['id']}")
    assert (r.status_code, r.json()) == (404, {"detail": "Not found"})
    await _ok(await gm.delete(f"{BASE}/{entity['id']}/aliases/{alias['id']}"), 204)
    assert (await _ok(await gm.get(f"{BASE}/{entity['id']}")))["aliases"] == []
    assert (await gm.post(f"{BASE}/{entity['id']}/aliases", json={"alias": " "})).status_code == 422


async def test_quest_steps(ev4):
    gm = await ev4.actor("gm_owner")
    quest = await _create(gm, ev4, type="quest", name="Find the bell")
    first = await _ok(await gm.post(f"{BASE}/{quest['id']}/steps", json={"text": "Ask at the inn"}), 201)
    second = await _ok(await gm.post(f"{BASE}/{quest['id']}/steps", json={"text": "Climb the tower"}), 201)
    assert (first["position"], second["position"]) == (0, 1)
    done = await _ok(await gm.patch(f"{BASE}/{quest['id']}/steps/{first['id']}", json={"done": True}))
    assert done["done"] is True and done["done_at"] is not None
    assert [s["text"] for s in (await _ok(await gm.get(f"{BASE}/{quest['id']}")))["steps"]] == [
        "Ask at the inn", "Climb the tower"]
    npc = await _create(gm, ev4, name="Mira")
    r = await gm.post(f"{BASE}/{npc['id']}/steps", json={"text": "Nope"})
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    r = await gm.patch(f"{BASE}/{npc['id']}/steps/{first['id']}", json={"done": False})
    assert (r.status_code, r.json()) == (404, {"detail": "Not found"})
    assert (await gm.patch(f"{BASE}/{quest['id']}/steps/{first['id']}", json={})).status_code == 422


# ── History and revert ─────────────────────────────────────────────────────

async def test_history_is_newest_first_and_paged(ev4):
    gm = await ev4.actor("gm_owner")
    entity = await _create(gm, ev4, name="Mira")
    for name in ("Mira B", "Mira C"):
        await _ok(await gm.patch(f"{BASE}/{entity['id']}", json={"name": name}))
    history = await _ok(await gm.get(f"{BASE}/{entity['id']}/history"))
    assert [(i["op"], i["new_value"] if i["field"] else None) for i in history["items"]] == [
        ("update_field", "Mira C"), ("update_field", "Mira B"), ("create_entity", None)]
    assert history["total"] == 3 and {i["write_visibility"] for i in history["items"]} == {"gm"}
    page = await _ok(await gm.get(f"{BASE}/{entity['id']}/history?limit=1&offset=1"))
    assert [i["new_value"] for i in page["items"]] == ["Mira B"] and page["total"] == 3


async def test_revert_superseded_and_force(ev4):
    gm = await ev4.actor("gm_owner")
    entity = await _create(gm, ev4, name="Mira", description="One")
    await _ok(await gm.patch(f"{BASE}/{entity['id']}", json={"description": "Two"}))
    await _ok(await gm.patch(f"{BASE}/{entity['id']}", json={"description": "Three"}))
    items = (await _ok(await gm.get(f"{BASE}/{entity['id']}/history")))["items"]
    two = next(i for i in items if i["new_value"] == "Two")
    url = f"{BASE}/{entity['id']}/history/{two['id']}/revert"
    r = await gm.post(url, json={})
    assert r.status_code == 409 and r.json()["code"] == "superseded", r.text
    row = await _ok(await gm.post(url, json={"force": True}))
    assert (row["op"], row["reverted_change_id"], row["new_value"]) == ("revert", two["id"], "One")
    assert (await _ok(await gm.get(f"{BASE}/{entity['id']}")))["description"] == "One"
    create = next(i for i in items if i["op"] == "create_entity")
    other = await _create(gm, ev4, name="Wren")
    r = await gm.post(f"{BASE}/{other['id']}/history/{create['id']}/revert", json={})
    assert (r.status_code, r.json()) == (404, {"detail": "Not found"})
    await _ok(await gm.post(f"{BASE}/{entity['id']}/visibility", json={"visibility": "party"}))
    publish = next(i for i in (await _ok(await gm.get(f"{BASE}/{entity['id']}/history")))["items"]
                   if i["field"] == "visibility")
    r = await gm.post(f"{BASE}/{entity['id']}/history/{publish['id']}/revert", json={})
    assert r.status_code == 422 and r.json()["code"] == "not_revertible", r.text


# ── Visibility ─────────────────────────────────────────────────────────────

async def test_single_visibility(ev4):
    gm = await ev4.actor("gm_owner")
    entity = await _create(gm, ev4, name="Mira")
    url = f"{BASE}/{entity['id']}/visibility"
    assert await _ok(await gm.post(url, json={"visibility": "party"})) == {"updated": 1}
    assert await _ok(await gm.post(url, json={"visibility": "gm", "field": "aliases"})) == {"updated": 1}
    body = await _ok(await gm.get(f"{BASE}/{entity['id']}"))
    assert (body["visibility"], body["field_visibility"]) == ("party", {"aliases": "gm"})
    for field, code in (("name", "unknown_field"), ("gm_notes", "always_gm"), ("nope", "unknown_field")):
        r = await gm.post(url, json={"visibility": "gm", "field": field})
        assert r.status_code == 422 and r.json()["code"] == code, (field, r.text)


async def test_bulk_visibility_is_all_or_nothing(ev4, db):
    gm = await ev4.actor("gm_owner")
    a = str(ev4.a.campaign_id)
    ids = [(await _create(gm, ev4, name=f"N{i}"))["id"] for i in range(3)]
    r = await gm.post(f"{BASE}/visibility", json={"campaign_id": a, "entity_ids": ids, "visibility": "party"})
    assert await _ok(r) == {"updated": 3}
    assert (await _list(gm, ev4, "&visibility=party"))["total"] == 3
    r = await gm.post(f"{BASE}/visibility", json={"campaign_id": a, "entity_ids": [*ids, MISSING], "visibility": "gm"})
    assert (r.status_code, r.json()) == (404, {"detail": "Not found"})
    assert (await _list(gm, ev4, "&visibility=party"))["total"] == 3
    too_many = [str(uuid.uuid4()) for _ in range(501)]
    r = await gm.post(f"{BASE}/visibility", json={"campaign_id": a, "entity_ids": too_many, "visibility": "gm"})
    assert r.status_code == 422
    assert (await gm.post(f"{BASE}/visibility", json={"campaign_id": a, "entity_ids": [],
                                                      "visibility": "gm"})).status_code == 422


# ── The entity_field resolver ──────────────────────────────────────────────

async def test_entity_field_resolver(ev4, db):
    gm_ctx = await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)
    player = await ctx_for(db, (await ev4.actor("player")).user_id, ev4.a.campaign_id)

    async def create(**kw):
        return (await apply_change(db, gm_ctx, {"op": "create_entity", **kw})).entity_id

    from app.access import set_visibility
    from app.schemas.sources import RecordRef

    secret_place = await create(type="location", name="Vault")
    mira = await create(type="character", kind="npc", name="Mira", description="A sailor " + "x" * 300,
                        status="alive", attributes={"pronouns": "she/her"})
    item = await create(type="item", name="Bell", attributes={"location_entity_id": str(secret_place),
                                                              "holder_entity_id": str(mira)})
    plain = await create(type="item", name="Cup")  # no location set
    for entity_id in (mira, item, plain):
        await set_visibility(db, gm_ctx, RecordRef(kind="entity", id=entity_id), "party")
    await set_visibility(db, gm_ctx, RecordRef(kind="entity", id=mira, field="status"), "gm")
    await db.commit()

    def ref(entity_id, field):
        return SourceRef(kind=SourceKind.ENTITY_FIELD, id=entity_id, field=field)

    refs = [ref(mira, "description"), ref(mira, "attributes.pronouns"), ref(mira, "status"),
            ref(mira, "gm_notes"), ref(item, "attributes.location_entity_id"), ref(secret_place, "name"),
            ref(item, "attributes"), ref(item, "attributes.holder_entity_id"), ref(mira, "attributes.nope"),
            ref(mira, "field_visibility.status"), ref(plain, "attributes.location_entity_id")]
    shown = {(c.ref.id, c.ref.field): c for c in await resolve_sources(db, refs, player)}
    assert set(shown) == {(mira, "description"), (mira, "attributes.pronouns"), (item, "attributes"),
                          (item, "attributes.holder_entity_id")}
    desc = shown[(mira, "description")]
    assert desc.title == "Mira · Description" and desc.quote.startswith("A sailor") and len(desc.quote) == 200
    assert (shown[(mira, "attributes.pronouns")].title, shown[(mira, "attributes.pronouns")].quote) == (
        "Mira · Pronouns", "she/her")
    # A reference the Player may see is quoted; a hidden one gives no citation at all.
    holder = shown[(item, "attributes.holder_entity_id")]
    assert (holder.title, holder.quote) == ("Bell · Held by", str(mira))
    assert str(secret_place) not in shown[(item, "attributes")].quote
    gm = {(c.ref.id, c.ref.field): c for c in await resolve_sources(db, refs, gm_ctx)}
    # A hidden reference and an unset one answer alike: no citation.
    assert (item, "attributes.location_entity_id") not in shown and (plain, "attributes.location_entity_id") not in shown
    # An unknown attribute key, and an unset one, are dropped for everyone.
    assert set(gm) == {(r.id, r.field) for r in refs} - {(mira, "attributes.nope"),
                                                         (plain, "attributes.location_entity_id")}
    assert gm[(mira, "status")].quote == "alive" and gm[(mira, "status")].title == "Mira · Status"
    assert gm[(item, "attributes.location_entity_id")].quote == str(secret_place)
    assert gm[(item, "attributes")].title == "Bell · Attributes"


async def test_entity_field_resolver_with_attributes_hidden(ev4, db):
    from app.access import set_visibility
    from app.schemas.sources import RecordRef

    gm_ctx = await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)
    player = await ctx_for(db, (await ev4.actor("player")).user_id, ev4.a.campaign_id)
    mira = (await apply_change(db, gm_ctx, {"op": "create_entity", "type": "character", "kind": "npc",
                                            "name": "Mira", "attributes": {"pronouns": "she/her"}})).entity_id
    await set_visibility(db, gm_ctx, RecordRef(kind="entity", id=mira), "party")
    await set_visibility(db, gm_ctx, RecordRef(kind="entity", id=mira, field="attributes"), "gm")
    await db.commit()
    refs = [SourceRef(kind=SourceKind.ENTITY_FIELD, id=mira, field="attributes.pronouns"),
            SourceRef(kind=SourceKind.ENTITY_FIELD, id=mira, field="field_visibility.status")]
    assert await resolve_sources(db, refs, player) == []
    gm = await resolve_sources(db, refs[:1], gm_ctx)
    assert [(c.title, c.quote) for c in gm] == [("Mira · Pronouns", "she/her")]


async def test_mention_count_counts_confirmed_mentions_the_viewer_sees(ev4, db):
    from app.access import set_visibility
    from app.db.models.journal import JournalEntry
    from app.schemas.sources import RecordRef

    gm = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    gm_ctx = await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)
    party_entry = ev4.a.ids["journal_entries"][0]  # the seed's Party entry
    hidden_entry = JournalEntry(id=uuid.uuid4(), user_id=ev4.a.owner_id, campaign_id=ev4.a.campaign_id,
                                shorthand="s", narrative="Mira in the vault.", entry_hash=uuid.uuid4().hex,
                                kind="gm", visibility="gm")
    db.add(hidden_entry)
    await db.flush()
    mira = (await apply_change(db, gm_ctx, {"op": "create_entity", "type": "character", "kind": "npc",
                                            "name": "Mira"})).entity_id
    await set_visibility(db, gm_ctx, RecordRef(kind="entity", id=mira), "party")
    for journal_id, confirmed, span in ((party_entry, True, 0), (party_entry, False, 10), (hidden_entry.id, True, 0)):
        await apply_change(db, gm_ctx, {"op": "add_mention", "entity_id": mira, "journal_id": journal_id,
                                        "confirmed": confirmed, "span_start": span, "span_end": span + 4})
    await db.commit()
    assert (await _ok(await gm.get(f"{BASE}/{mira}")))["mention_count"] == 2
    assert (await _ok(await player.get(f"{BASE}/{mira}")))["mention_count"] == 1
    listed = await _ok(await player.get(f"{BASE}/?campaign_id={ev4.a.campaign_id}"))
    assert [i["mention_count"] for i in listed["items"] if i["id"] == str(mira)] == [1]

# ── Merge (E0-WorldCore.9) ─────────────────────────────────────────────────

async def test_merge_route_preview_and_merge(ev4, db):
    gm = await ev4.actor("gm_owner")
    survivor = await _create(gm, ev4, name="Aldric")
    absorbed = await _create(gm, ev4, name="Brother Aldric Vane")
    await _ok(await gm.post(f"{BASE}/{survivor['id']}/visibility", json={"visibility": "party"}))
    await _ok(await gm.post(f"{BASE}/{absorbed['id']}/aliases", json={"alias": "The Monk"}), 201)
    url = f"{BASE}/{survivor['id']}/merge"
    before = await _history_count(db, absorbed["id"]) + await _history_count(db, survivor["id"])
    preview = await _ok(await gm.post(url, json={"absorbed_id": absorbed["id"], "preview": True}))
    assert preview["change_id"] is None and preview["warning"] == "party_with_gm_only"
    assert preview["downgrades"] and all(set(d) == {"kind", "id", "from", "to"} for d in preview["downgrades"])
    assert preview["aliases"] == ["Brother Aldric Vane", "The Monk"]
    assert (preview["mention_count"], preview["relationships"]) == (0, [])
    assert await _history_count(db, absorbed["id"]) + await _history_count(db, survivor["id"]) == before
    assert (await _ok(await gm.get(f"{BASE}/{absorbed['id']}")))["id"] == absorbed["id"]

    done = await _ok(await gm.post(url, json={"absorbed_id": absorbed["id"]}))
    assert done["change_id"] is not None and done["survivor_id"] == survivor["id"]
    assert done["moved_counts"]["aliases"] == 1 and done["warning"] == "party_with_gm_only"
    assert "aliases" not in done and "mention_count" not in done
    body = await _ok(await gm.get(f"{BASE}/{survivor['id']}"))
    assert sorted(a["alias"] for a in body["aliases"]) == ["Brother Aldric Vane", "The Monk"]
    # The old id answers the survivor's body.
    old = await gm.get(f"{BASE}/{absorbed['id']}")
    assert old.status_code == 200 and old.content == (await gm.get(f"{BASE}/{survivor['id']}")).content
    # The survivor's history includes the absorbed Entity's rows.
    history = await _ok(await gm.get(f"{BASE}/{survivor['id']}/history?limit=200"))
    assert {i["entity_id"] for i in history["items"]} == {survivor["id"], absorbed["id"]}
    assert history["total"] == before + 1
    assert any(i["op"] == "merge" for i in history["items"])


async def test_merge_route_errors_write_nothing(ev4, db):
    gm = await ev4.actor("gm_owner")
    mira = await _create(gm, ev4, name="Mira")
    bell = await _create(gm, ev4, type="item", name="Bell")
    gone = await _create(gm, ev4, name="Gone")
    await _ok(await gm.delete(f"{BASE}/{gone['id']}"), 204)
    absorbed = await _create(gm, ev4, name="Wren")
    await _ok(await gm.post(f"{BASE}/{mira['id']}/merge", json={"absorbed_id": absorbed["id"]}))
    other = await outsider(ev4)
    other_gm = await ctx_for(db, other.owner_id, other.campaign_id)
    foreign = (await apply_change(db, other_gm, {"op": "create_entity", "type": "character", "kind": "npc",
                                                 "name": "Far"})).entity_id
    await db.commit()

    async def total() -> int:
        return (await db.execute(sa.select(sa.func.count()).select_from(EntityChange)
                                 .where(EntityChange.campaign_id == ev4.a.campaign_id))).scalar_one()

    start = await total()
    for target, absorbed_id in ((mira["id"], bell["id"]), (mira["id"], mira["id"])):
        for preview in (False, True):
            r = await gm.post(f"{BASE}/{target}/merge", json={"absorbed_id": absorbed_id, "preview": preview})
            assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    missing = await gm.post(f"{BASE}/{mira['id']}/merge", json={"absorbed_id": MISSING})
    assert (missing.status_code, missing.json()) == (404, {"detail": "Not found"})
    for target, absorbed_id in ((mira["id"], gone["id"]), (mira["id"], absorbed["id"]), (mira["id"], str(foreign)),
                                (absorbed["id"], mira["id"]), (gone["id"], mira["id"]), (MISSING, mira["id"])):
        for preview in (False, True):
            r = await gm.post(f"{BASE}/{target}/merge", json={"absorbed_id": absorbed_id, "preview": preview})
            assert (r.status_code, r.content) == (404, missing.content), (target, absorbed_id, r.text)
    assert (await gm.post(f"{BASE}/{mira['id']}/merge", json={"absorbed_id": "x"})).status_code == 422
    assert (await gm.post(f"{BASE}/{mira['id']}/merge", json={})).status_code == 422
    assert await total() == start


async def test_merge_then_revert_leaves_every_party_body_as_before(ev4, db):
    gm = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    survivor = await _create(gm, ev4, name="Mira")
    absorbed = await _create(gm, ev4, name="Sea Witch")
    for e in (survivor, absorbed):
        await _ok(await gm.post(f"{BASE}/{e['id']}/visibility", json={"visibility": "party"}))
    await _ok(await gm.post(f"{BASE}/{absorbed['id']}/aliases", json={"alias": "Grey Lady"}), 201)
    bell = await _create(gm, ev4, type="item", name="Bell", attributes={"holder_entity_id": absorbed["id"]})
    await _ok(await gm.post(f"{BASE}/{bell['id']}/visibility", json={"visibility": "party"}))
    urls = [f"{BASE}/{survivor['id']}", f"{BASE}/{absorbed['id']}", f"{BASE}/{bell['id']}",
            f"{BASE}/?campaign_id={ev4.a.campaign_id}", f"{BASE}/{survivor['id']}/history"]
    before = [(await player.get(u)).content for u in urls]
    done = await _ok(await gm.post(f"{BASE}/{survivor['id']}/merge", json={"absorbed_id": absorbed["id"]}))
    # A Party absorbed id resolves, for a Player, to the Party survivor's body.
    moved = await player.get(f"{BASE}/{absorbed['id']}")
    assert moved.status_code == 200 and moved.content == (await player.get(f"{BASE}/{survivor['id']}")).content
    assert (await _ok(await gm.get(f"{BASE}/{bell['id']}")))["attributes"]["holder_entity_id"] == survivor["id"]
    revert = await _ok(await gm.post(f"{BASE}/{survivor['id']}/history/{done['change_id']}/revert", json={}))
    assert (revert["op"], revert["reverted_change_id"]) == ("revert", done["change_id"])
    assert [(await player.get(u)).content for u in urls] == before
    assert (await _ok(await gm.get(f"{BASE}/{bell['id']}")))["attributes"]["holder_entity_id"] == absorbed["id"]


async def test_entity_field_citation_follows_a_merge_for_a_gm(ev4, db):
    from app.access import set_visibility
    from app.schemas.sources import RecordRef
    from app.services.world_service import merge_entities

    gm_ctx = await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)
    player = await ctx_for(db, (await ev4.actor("player")).user_id, ev4.a.campaign_id)

    async def create(**kw):
        return (await apply_change(db, gm_ctx, {"op": "create_entity", "type": "character", "kind": "npc",
                                                **kw})).entity_id

    survivor = await create(name="Mira", description="A sailor")
    absorbed = await create(name="Old Mira", description="Old text")
    for e in (survivor, absorbed):
        await set_visibility(db, gm_ctx, RecordRef(kind="entity", id=e), "party")
    await merge_entities(db, gm_ctx, survivor, absorbed)
    await db.commit()
    refs = [SourceRef(kind=SourceKind.ENTITY_FIELD, id=absorbed, field="description")]
    assert [(c.title, c.quote) for c in await resolve_sources(db, refs, gm_ctx)] == [
        ("Mira · Description", "A sailor")]
    assert await resolve_sources(db, refs, player) == []


async def _publish_via(gm, entity, visibility="party"):
    await _ok(await gm.post(f"{BASE}/{entity['id']}/visibility", json={"visibility": visibility}))


async def test_merge_chains_resolve_and_history_spans_them(ev4, db):
    gm = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    a, b, c = [await _create(gm, ev4, name=n) for n in ("Alpha", "Bravo", "Charlie")]
    for e in (a, c):
        await _publish_via(gm, e)  # B stays GM-only
    await _ok(await gm.post(f"{BASE}/{b['id']}/merge", json={"absorbed_id": a["id"]}))
    await _ok(await gm.post(f"{BASE}/{c['id']}/merge", json={"absorbed_id": b["id"]}))
    end = await gm.get(f"{BASE}/{c['id']}")
    assert (await gm.get(f"{BASE}/{a['id']}")).content == end.content
    assert (await gm.get(f"{BASE}/{b['id']}")).content == end.content
    history = await _ok(await gm.get(f"{BASE}/{c['id']}/history?limit=200"))
    assert {i["entity_id"] for i in history["items"]} == {a["id"], b["id"], c["id"]}
    total = sum([await _history_count(db, e["id"]) for e in (a, b, c)])
    assert history["total"] == total == len(history["items"])
    # A Player may not follow the hop from B (stored gm): A answers like a missing id.
    missing = await player.get(f"{BASE}/{MISSING}")
    hidden = await player.get(f"{BASE}/{a['id']}")
    assert (hidden.status_code, hidden.content) == (404, missing.content)


async def test_a_merge_loop_answers_404(ev4, db):
    gm = await ev4.actor("gm_owner")
    x, y = await _create(gm, ev4, name="Xan"), await _create(gm, ev4, name="Yev")
    await db.execute(sa.update(Entity).where(Entity.id == uuid.UUID(x["id"])).values(merged_into_id=uuid.UUID(y["id"])))
    await db.execute(sa.update(Entity).where(Entity.id == uuid.UUID(y["id"])).values(merged_into_id=uuid.UUID(x["id"])))
    await db.commit()
    missing = await gm.get(f"{BASE}/{MISSING}")
    for e in (x, y):
        r = await gm.get(f"{BASE}/{e['id']}")
        assert (r.status_code, r.content) == (404, missing.content)
        assert (await gm.get(f"{BASE}/{e['id']}/history")).status_code == 200  # the family walk ends too


async def test_publishing_an_absorbed_row_does_not_open_its_old_id(ev4, db):
    gm = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    survivor = await _create(gm, ev4, name="Mira")
    absorbed = await _create(gm, ev4, name="Shadow")  # GM-only when merged
    await _publish_via(gm, survivor)
    await _ok(await gm.post(f"{BASE}/{survivor['id']}/merge", json={"absorbed_id": absorbed["id"]}))
    await _publish_via(gm, absorbed)  # the stored column now says party
    missing = await player.get(f"{BASE}/{MISSING}")
    r = await player.get(f"{BASE}/{absorbed['id']}")
    assert (r.status_code, r.content) == (404, missing.content)


async def test_gm_only_into_party_merge_then_revert_leaves_party_bodies_as_before(ev4, db):
    gm = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    survivor = await _create(gm, ev4, name="Mira")
    absorbed = await _create(gm, ev4, name="Shadow")
    await _publish_via(gm, survivor)
    await _ok(await gm.post(f"{BASE}/{absorbed['id']}/aliases", json={"alias": "The Hood"}), 201)
    await _ok(await gm.post(f"{BASE}/{survivor['id']}/aliases", json={"alias": "Little Mira"}), 201)
    urls = [f"{BASE}/{survivor['id']}", f"{BASE}/?campaign_id={ev4.a.campaign_id}",
            f"{BASE}/{survivor['id']}/history"]
    before = [(await player.get(u)).content for u in urls]
    done = await _ok(await gm.post(f"{BASE}/{survivor['id']}/merge", json={"absorbed_id": absorbed["id"]}))
    assert done["warning"] == "party_with_gm_only"
    assert [(await player.get(u)).content for u in urls] == before
    await _ok(await gm.post(f"{BASE}/{survivor['id']}/history/{done['change_id']}/revert", json={}))
    assert [(await player.get(u)).content for u in urls] == before


# ── Wiring: 14 routes, each in nginx's /api/entities/ location (zone api) ───

def test_every_entity_route_is_in_the_api_zone():
    from app.main import app
    from tests.ev4.routes import api_routes, resolve_route

    routes = [r for r in api_routes(app) if r.path.startswith("/api/entities")]
    assert len(routes) == 14, sorted(f"{r.method} {r.path}" for r in routes)
    for route in routes:
        loc = resolve_route(route)
        assert loc is not None and (loc.modifier, loc.uri) == ("", "/api/entities/"), (route, loc)
        limits = [d.args for d in loc.directives if d.name == "limit_req"]
        assert limits and limits[0][0] == "zone=api", (route, limits)
