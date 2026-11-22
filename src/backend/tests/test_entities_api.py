"""E0-WorldCore.5: the Entity API's GM behaviour (app/api/routes/entities.py)
and the `entity_field` source resolver.

What a Player may not see is EV-4's (tests/ev4/probes/entities.py,
tests/ev4/test_entity_api_history.py); here the GM (the Owner of the canary
Campaign A) drives every route: create and the duplicate 409, the list
filters and pagination, a multi-field PATCH in one transaction, soft delete,
aliases, Quest steps, history order, revert, and single and bulk Visibility.
E0-WorldCore.7 adds the Mention routes: the Entity's list (pages, order,
the `confirmed` filter), an entry's list, confirm and remove, and what a
Player gets from them.
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


# ── Mentions (E0-WorldCore.7) ──────────────────────────────────────────────

async def _gm_ctx(ev4, db):
    return await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)


async def _journal(db, ev4, narrative: str = "An entry.", *, session_date=None, visibility: str = "party",
                   kind: str = "gm") -> uuid.UUID:
    from app.db.models.journal import JournalEntry

    entry = JournalEntry(id=uuid.uuid4(), user_id=ev4.a.owner_id, campaign_id=ev4.a.campaign_id, shorthand="s",
                         narrative=narrative, entry_hash=uuid.uuid4().hex, session_date=session_date, kind=kind,
                         visibility=visibility)
    db.add(entry)
    await db.flush()
    return entry.id


async def _new_entity(db, ctx, name: str, *, party: bool = False) -> uuid.UUID:
    from app.access import set_visibility
    from app.schemas.sources import RecordRef

    entity_id = (await apply_change(db, ctx, {"op": "create_entity", "type": "character", "kind": "npc",
                                              "name": name})).entity_id
    if party:
        await set_visibility(db, ctx, RecordRef(kind="entity", id=entity_id), "party")
    return entity_id


async def _add_mention(db, ctx, entity_id, journal_id, **kw) -> uuid.UUID:
    row = await apply_change(db, ctx, {"op": "add_mention", "entity_id": entity_id, "journal_id": journal_id, **kw})
    return uuid.UUID(row.new_value["mention_id"])


async def _mention_history(db, entity_id, op: str) -> int:
    return (await db.execute(sa.select(sa.func.count()).select_from(EntityChange).where(
        EntityChange.entity_id == uuid.UUID(str(entity_id)), EntityChange.op == op))).scalar_one()


async def test_entity_mentions_page_newest_session_first(ev4, db):
    from datetime import date, timedelta

    gm = await ev4.actor("gm_owner")
    ctx = await _gm_ctx(ev4, db)
    mira = await _new_entity(db, ctx, "Mira")
    ids = []
    for i in range(25):
        entry = await _journal(db, ev4, f"Mira, day {i}.", session_date=date(2026, 1, 1) + timedelta(days=i))
        ids.append(await _add_mention(db, ctx, mira, entry, confirmed=i % 2 == 0, quote=f"Mira, day {i}.",
                                      span_start=0, span_end=4))
    await db.commit()
    first = await _ok(await gm.get(f"{BASE}/{mira}/mentions?page=1"))
    second = await _ok(await gm.get(f"{BASE}/{mira}/mentions?page=2"))
    assert (first["total"], first["page"], first["page_size"], len(first["items"])) == (25, 1, 20, 20)
    assert (second["total"], second["page"], len(second["items"])) == (25, 2, 5)
    newest_first = [str(i) for i in reversed(ids)]
    assert [i["id"] for i in first["items"] + second["items"]] == newest_first
    item = first["items"][0]
    assert (item["quote"], item["journal_id"], item["confirmed"], item["origin"]) == (
        "Mira, day 24.", item["journal_id"], True, "manual")
    assert item["entry_title"] == "Journal entry · 2026-01-25"
    assert (item["entity_name"], item["entity_type"]) == ("Mira", "character")
    assert (await gm.get(f"{BASE}/{mira}/mentions?page=0")).status_code == 422
    suggested = await _ok(await gm.get(f"{BASE}/{mira}/mentions?confirmed=false"))
    confirmed = await _ok(await gm.get(f"{BASE}/{mira}/mentions?confirmed=true"))
    assert (suggested["total"], confirmed["total"]) == (12, 13)
    assert all(not i["confirmed"] for i in suggested["items"]) and all(i["confirmed"] for i in confirmed["items"])


async def test_entry_mentions_order_and_deleted_entities(ev4, db):
    gm = await ev4.actor("gm_owner")
    ctx = await _gm_ctx(ev4, db)
    bree, mira, ada = [await _new_entity(db, ctx, n) for n in ("Bree", "Mira", "Ada")]
    gone = await _new_entity(db, ctx, "Gone")
    entry = await _journal(db, ev4, "Mira saw Bree.")
    late = await _add_mention(db, ctx, bree, entry, span_start=9, span_end=13)
    early = await _add_mention(db, ctx, mira, entry, span_start=0, span_end=4)
    unspanned = await _add_mention(db, ctx, ada, entry, confirmed=True)
    await _add_mention(db, ctx, gone, entry, span_start=1, span_end=2)
    await apply_change(db, ctx, {"op": "delete_entity", "entity_id": gone})
    await db.commit()
    body = await _ok(await gm.get(f"{BASE}/mentions?journal_id={entry}"))
    assert [i["id"] for i in body["items"]] == [str(early), str(late), str(unspanned)]
    assert [(i["entity_name"], i["entity_type"]) for i in body["items"]] == [
        ("Mira", "character"), ("Bree", "character"), ("Ada", "character")]
    assert {i["entry_title"] for i in body["items"]} == {"Journal entry"}
    assert (await gm.get(f"{BASE}/mentions?journal_id={MISSING}")).status_code == 404
    assert (await gm.get(f"{BASE}/mentions")).status_code == 422


async def test_confirm_mention(ev4, db):
    from app.db.models.entity import EntityMention

    gm = await ev4.actor("gm_owner")
    ctx = await _gm_ctx(ev4, db)
    mira, bree = await _new_entity(db, ctx, "Mira"), await _new_entity(db, ctx, "Bree")
    entry = await _journal(db, ev4, "Mira and Bree.")
    mention = await _add_mention(db, ctx, mira, entry, quote="Mira and Bree.", origin="migration")
    bree_mention = await _add_mention(db, ctx, bree, entry)
    await db.commit()
    before = (await _ok(await gm.get(f"{BASE}/{mira}")))["mention_count"]
    # Another Entity's Mention is the 404.
    assert (await gm.post(f"{BASE}/{mira}/mentions/{bree_mention}/confirm")).status_code == 404
    body = await _ok(await gm.post(f"{BASE}/{mira}/mentions/{mention}/confirm"))
    assert (body["id"], body["confirmed"], body["origin"], body["entity_name"]) == (
        str(mention), True, "migration", "Mira")
    assert await _mention_history(db, mira, "confirm_mention") == 1
    assert (await _ok(await gm.get(f"{BASE}/{mira}")))["mention_count"] == before + 1
    # Again: the earlier change (no new row).
    await _ok(await gm.post(f"{BASE}/{mira}/mentions/{mention}/confirm"))
    assert await _mention_history(db, mira, "confirm_mention") == 1
    # Confirmed by something other than a change (a migration row): 422 invalid.
    stray = EntityMention(campaign_id=ev4.a.campaign_id, journal_id=entry, entity_id=bree, source_field="narrative",
                          origin="migration", confirmed=True)
    db.add(stray)
    await db.commit()
    r = await gm.post(f"{BASE}/{bree}/mentions/{stray.id}/confirm")
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    # A deleted Entity's Mention is 409.
    await apply_change(db, ctx, {"op": "delete_entity", "entity_id": bree})
    await db.commit()
    r = await gm.post(f"{BASE}/{bree}/mentions/{bree_mention}/confirm")
    assert r.status_code == 409 and r.json()["code"] == "deleted", r.text


async def test_remove_mention(ev4, db):
    from app.db.models.entity import EntityMention

    gm = await ev4.actor("gm_owner")
    ctx = await _gm_ctx(ev4, db)
    mira, bree = await _new_entity(db, ctx, "Mira"), await _new_entity(db, ctx, "Bree")
    entry = await _journal(db, ev4, "Mira and Bree.")
    mention = await _add_mention(db, ctx, mira, entry)
    bree_mention = await _add_mention(db, ctx, bree, entry)
    await db.commit()
    assert (await gm.delete(f"{BASE}/{mira}/mentions/{bree_mention}")).status_code == 404
    await _ok(await gm.delete(f"{BASE}/{mira}/mentions/{mention}"), 204)
    gone = (await db.execute(sa.select(EntityMention).where(EntityMention.id == mention))).scalar_one_or_none()
    assert gone is None
    assert await _mention_history(db, mira, "remove_mention") == 1
    assert (await gm.delete(f"{BASE}/{mira}/mentions/{mention}")).status_code == 404
    listed = await _ok(await gm.get(f"{BASE}/{mira}/mentions"))
    assert listed["items"] == [] and listed["total"] == 0


async def test_remove_lowers_mention_count_and_confirm_updates_the_list(ev4, db):
    gm = await ev4.actor("gm_owner")
    ctx = await _gm_ctx(ev4, db)
    mira = await _new_entity(db, ctx, "Mira")
    entry = await _journal(db, ev4, "Mira ran.")
    mention = await _add_mention(db, ctx, mira, entry)
    await db.commit()
    await _ok(await gm.post(f"{BASE}/{mira}/mentions/{mention}/confirm"))
    listed = await _ok(await gm.get(f"{BASE}/{mira}/mentions?confirmed=true"))
    assert [i["id"] for i in listed["items"]] == [str(mention)]
    assert (await _ok(await gm.get(f"{BASE}/{mira}")))["mention_count"] == 1
    await _ok(await gm.delete(f"{BASE}/{mira}/mentions/{mention}"), 204)
    assert (await _ok(await gm.get(f"{BASE}/{mira}")))["mention_count"] == 0


async def test_player_entry_titles_and_entryless_mentions(ev4, db):
    from datetime import date

    from app.db.models.journal import JournalEntry

    gm = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    ctx = await _gm_ctx(ev4, db)
    mira = await _new_entity(db, ctx, "Mira", party=True)
    mine = await _journal(db, ev4, "Mira at camp.", session_date=date(2026, 2, 2), kind="player")
    gm_entry = await _journal(db, ev4, "Mira at sea.", session_date=date(2026, 2, 1))
    on_player = await _add_mention(db, ctx, mira, mine, confirmed=True)
    on_gm = await _add_mention(db, ctx, mira, gm_entry, confirmed=True)
    doomed_entry = await _journal(db, ev4, "Mira, gone.", session_date=date(2026, 2, 3))
    orphan = await _add_mention(db, ctx, mira, doomed_entry, confirmed=True)
    await db.commit()
    # The entry goes away under the Mention (journal_id SET NULL).
    await db.execute(sa.delete(JournalEntry).where(JournalEntry.id == doomed_entry))
    await db.commit()
    body = await _ok(await gm.get(f"{BASE}/{mira}/mentions"))
    assert [i["id"] for i in body["items"]] == [str(on_player), str(on_gm), str(orphan)] and body["total"] == 3
    titles = {i["id"]: i["entry_title"] for i in body["items"]}
    assert titles[str(on_player)] == "Player journal · 2026-02-02"
    assert titles[str(on_gm)] == "Journal entry · 2026-02-01"
    assert titles[str(orphan)] is None and body["items"][2]["journal_id"] is None
    seen = await _ok(await player.get(f"{BASE}/{mira}/mentions"))
    assert str(orphan) not in {i["id"] for i in seen["items"]}


async def test_a_player_sees_confirmed_allowed_mentions_only(ev4, db):
    gm_ctx = await _gm_ctx(ev4, db)
    player = await ev4.actor("player")
    mira = await _new_entity(db, gm_ctx, "Mira", party=True)
    secret = await _new_entity(db, gm_ctx, "Secret")
    party_entry = await _journal(db, ev4, "Mira sailed.")
    other_entry = await _journal(db, ev4, "Mira again.")
    hidden_entry = await _journal(db, ev4, "Mira in the vault.", visibility="gm")
    shown = await _add_mention(db, gm_ctx, mira, party_entry, confirmed=True, quote="Mira sailed.")
    await _add_mention(db, gm_ctx, mira, other_entry)  # suggested
    await _add_mention(db, gm_ctx, mira, other_entry, confirmed=True, source_field="shorthand")
    await _add_mention(db, gm_ctx, mira, hidden_entry, confirmed=True)
    await _add_mention(db, gm_ctx, secret, party_entry, confirmed=True)
    await db.commit()
    body = await _ok(await player.get(f"{BASE}/{mira}/mentions"))
    assert [i["id"] for i in body["items"]] == [str(shown)] and body["total"] == 1
    assert "origin" not in body["items"][0] and "source_field" not in body["items"][0]
    assert await _ok(await player.get(f"{BASE}/{mira}/mentions?confirmed=false")) == {
        "items": [], "total": 0, "page": 1, "page_size": 20}
    entry_list = await _ok(await player.get(f"{BASE}/mentions?journal_id={party_entry}"))
    assert [i["id"] for i in entry_list["items"]] == [str(shown)]
    assert (await _ok(await player.get(f"{BASE}/mentions?journal_id={other_entry}")))["items"] == []
    assert (await player.get(f"{BASE}/mentions?journal_id={hidden_entry}")).status_code == 404
    assert (await player.get(f"{BASE}/{secret}/mentions")).status_code == 404
    assert (await _ok(await player.get(f"{BASE}/{mira}")))["mention_count"] == 1
    # Writes: the uniform 404, nothing written.
    for method, url in (("POST", f"{BASE}/{mira}/mentions/{shown}/confirm"),
                        ("DELETE", f"{BASE}/{mira}/mentions/{shown}")):
        assert (await player.request(method, url)).status_code == 404
    assert await _mention_history(db, mira, "remove_mention") == 0


# ── Wiring: 17 routes + the E0-WorldCore.6 old-link resolver, each in nginx's /api/entities/ location (zone api) ───

def test_every_entity_route_is_in_the_api_zone():
    from app.main import app
    from tests.ev4.routes import api_routes, resolve_route

    routes = [r for r in api_routes(app) if r.path.startswith("/api/entities")]
    assert len(routes) == 18, sorted(f"{r.method} {r.path}" for r in routes)
    for route in routes:
        loc = resolve_route(route)
        assert loc is not None and (loc.modifier, loc.uri) == ("", "/api/entities/"), (route, loc)
        limits = [d.args for d in loc.directives if d.name == "limit_req"]
        assert limits and limits[0][0] == "zone=api", (route, limits)
