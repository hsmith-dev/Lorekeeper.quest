"""EV-4 probes for api/routes/entities.py (E0-WorldCore.5).

Campaign A gets, through `world_service.apply_change` and `set_visibility`:
a GM-only Character whose name, description, gm_notes, alias and history are
canaries; a Party Character with the default status (the control) whose
gm_notes are a canary and which gains a Party-visible edit; a Party
Character whose real status is hidden (it must read like the control's
unset status); a Party Quest with a step; and a Party Item that was then
deleted. Another Campaign (an outsider's) holds a Party Entity with canaries.

For a non-GM, the GM-only, the deleted, the outsider's and a missing Entity
answer exactly alike on every item route; the list and its `total` show
exactly the Party Entities and do not move when the GM writes something
GM-only; a hidden status renders as the unset one. A Player reaches no write
route (each answers like a missing Entity or Campaign and writes nothing),
whatever the target. A GM (the Owner, a Co-GM) writes. A Share Link holder
sends no bearer token here, so every route refuses it (401), with no canary.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from tests.ev4.families import (
    assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_hidden_field_equals_unset,
    assert_no_canary,
)
from tests.ev4.fixtures import mint_canary
from tests.ev4.probes._support import (
    MISSING, assert_same_answer, authenticated, is_gm_of_a, outsider, row_count,
)
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe
from tests.ev4.report import note_family_call, record_leak

BASE = "/api/entities"
WRITERS = (*DEFAULT_ACTORS, "co_gm")


@dataclass
class World:
    gm: object
    secret: uuid.UUID          # GM-only, canaries everywhere
    secret_alias: uuid.UUID
    secret_change: uuid.UUID
    party: uuid.UUID           # Party, default status: the unset control
    party_alias: uuid.UUID
    party_change: uuid.UUID    # a Party-visible edit (attributes.goals)
    hidden_status: uuid.UUID   # Party, real status deceased, status hidden
    quest: uuid.UUID           # Party Quest
    step: uuid.UUID
    gone: uuid.UUID            # Party, then deleted
    other: uuid.UUID           # an outsider Campaign's Party Entity
    other_campaign: uuid.UUID

    @property
    def hidden(self) -> list[uuid.UUID]:
        return [self.secret, self.gone, self.other]


async def _create(db, ctx, **kw) -> uuid.UUID:
    from app.services.world_service import apply_change

    return (await apply_change(db, ctx, {"op": "create_entity", **kw})).entity_id


async def _publish(db, ctx, entity_id, field=None, value="party") -> None:
    from app.access import set_visibility
    from app.schemas.sources import RecordRef

    await set_visibility(db, ctx, RecordRef(kind="entity", id=entity_id, field=field), value)


async def _world(ev4) -> World:
    from app.access import ctx_for
    from app.services.world_service import apply_change

    db, a = ev4.db, ev4.a.campaign_id
    gm = await ctx_for(db, ev4.a.owner_id, a)

    def c(kind: str) -> str:
        return mint_canary(kind, a).token

    secret = await _create(db, gm, type="character", kind="npc", name=c("XENTNAME"), description=c("XENTDESC"),
                           gm_notes=c("XENTNOTES"))
    secret_alias = await apply_change(db, gm, {"op": "add_alias", "entity_id": secret, "alias": c("XENTALIAS")})
    secret_change = await apply_change(db, gm, {"op": "update_field", "entity_id": secret, "field": "description",
                                                "value": c("XENTEDIT")})
    party = await _create(db, gm, type="character", kind="npc", name="Mira Party", gm_notes=c("XENTPNOTES"))
    hidden_status = await _create(db, gm, type="character", kind="npc", name="Quiet One", status="deceased")
    quest = await _create(db, gm, type="quest", name="Find the bell")
    gone = await _create(db, gm, type="item", name="Old Bell", description=c("XENTGONE"))
    for entity_id in (party, hidden_status, quest, gone):
        await _publish(db, gm, entity_id)
    await _publish(db, gm, hidden_status, "status", "gm")
    party_alias = await apply_change(db, gm, {"op": "add_alias", "entity_id": party, "alias": "Little Mira"})
    party_change = await apply_change(db, gm, {"op": "update_field", "entity_id": party, "field": "attributes.goals",
                                               "value": "Find the bell"})
    step = await apply_change(db, gm, {"op": "add_quest_step", "entity_id": quest, "text": "Ask at the inn"})
    await apply_change(db, gm, {"op": "delete_entity", "entity_id": gone})
    await db.commit()

    seeded = await outsider(ev4)
    other_gm = await ctx_for(db, seeded.owner_id, seeded.campaign_id)
    other = await _create(db, other_gm, type="character", kind="npc",
                          name=mint_canary("XENTOTHER", seeded.campaign_id).token)
    await _publish(db, other_gm, other)
    await db.commit()

    from app.db.models.entity import EntityAlias
    from sqlalchemy import select

    async def alias_id(entity_id) -> uuid.UUID:
        return (await db.execute(select(EntityAlias.id).where(EntityAlias.entity_id == entity_id))).scalars().first()

    return World(gm=gm, secret=secret, secret_alias=await alias_id(secret), secret_change=secret_change.id,
                 party=party, party_alias=await alias_id(party), party_change=party_change.id,
                 hidden_status=hidden_status, quest=quest, step=uuid.UUID(step.new_value["step_id"]), gone=gone,
                 other=other, other_campaign=seeded.campaign_id)


async def _gm_only_write(ev4, w: World) -> None:
    """Something only a GM may see: a GM-only Entity and a gm_notes edit."""
    from app.services.world_service import apply_change

    await _create(ev4.db, w.gm, type="character", kind="npc", name=f"Mira {mint_canary('XENTNEW', ev4.a.campaign_id).token}")
    await apply_change(ev4.db, w.gm, {"op": "update_field", "entity_id": w.party, "field": "gm_notes",
                                      "value": mint_canary("XENTNOTES2", ev4.a.campaign_id).token})
    await ev4.db.commit()


async def _history_rows(ev4) -> int:
    from app.db.models.entity import EntityChange

    return await row_count(ev4, EntityChange, EntityChange.campaign_id == ev4.a.campaign_id)


def _ids(response) -> set[str]:
    body = response.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    return {i["id"] for i in items}


async def _ladder(ev4, url: str) -> None:
    """Members see the same Party ids, a subset of the GM's; the Share Link
    holder (no bearer token on this API) is refused, with no canary."""
    note_family_call()
    anon = await ev4.actor("anon_share")
    r = await anon.get(url)
    assert_no_canary(anon, r)
    assert r.status_code in (401, 403), r.text
    ids = {}
    for name in ("player", "player_2", "gm_owner"):
        actor = await ev4.actor(name)
        r = await actor.get(url)
        assert_no_canary(actor, r)
        assert r.status_code == 200, r.text
        ids[name] = _ids(r)
    if not (ids["player"] == ids["player_2"] and ids["player"] <= ids["gm_owner"]):
        record_leak("EV-4 leak: the Entity audience ladder is broken",
                    [f"{k}: {sorted(v)}" for k, v in ids.items()])


async def _refused(ev4, actor, method: str, url: str, missing_url: str, **kwargs) -> None:
    """A non-GM's write answers like the missing target and writes no history."""
    before = await _history_rows(ev4)
    await assert_hidden_equals_missing(actor, url, missing_url, method=method, **kwargs)
    assert await _history_rows(ev4) == before, f"{actor.name}: {method} {url} wrote something"


# ── Reads ──────────────────────────────────────────────────────────────────

@ev4_probe("GET", "/api/entities/")
async def probe_list_entities(ev4, actor):
    w = await _world(ev4)
    a = ev4.a.campaign_id
    await assert_hidden_equals_missing(actor, f"{BASE}/?campaign_id={w.other_campaign}",
                                       f"{BASE}/?campaign_id={MISSING}")
    url = f"{BASE}/?campaign_id={a}"
    if not authenticated(actor):
        r = await actor.get(url)
        assert_no_canary(actor, r)
        assert r.status_code in (401, 403), r.text
        return
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    assert _ids(r) == {str(w.party), str(w.hidden_status), str(w.quest)}, r.text
    assert r.json()["total"] == 3
    # A hidden status matches only as the unset one.
    hidden = await actor.get(f"{url}&status=deceased")
    assert_no_canary(actor, hidden)
    assert hidden.json()["total"] == 0, hidden.text
    unknown = await actor.get(f"{url}&status=unknown")
    assert_no_canary(actor, unknown)
    assert _ids(unknown) == {str(w.party), str(w.hidden_status)} and unknown.json()["total"] == 2, unknown.text
    # The stored Visibility is not a Player's filter (the Party schema has none): ignored.
    for value in ("gm", "party", "private"):
        filtered = await actor.get(f"{url}&visibility={value}")
        assert_no_canary(actor, filtered)
        assert filtered.content == r.content, (value, filtered.text)
    await assert_counts_and_ranking_unchanged(
        actor, [url, f"{url}&q=Mira", f"{url}&type=character", f"{url}&status=unknown"],
        lambda: _gm_only_write(ev4, w))
    await _ladder(ev4, url)


@ev4_probe("GET", "/api/entities/{entity_id}")
async def probe_get_entity(ev4, actor):
    w = await _world(ev4)
    for entity_id in w.hidden:
        await assert_hidden_equals_missing(actor, f"{BASE}/{entity_id}", f"{BASE}/{MISSING}")
    await assert_hidden_equals_missing(actor, f"{BASE}/not-a-uuid", f"{BASE}/{MISSING}")
    if not authenticated(actor):
        return
    r = await actor.get(f"{BASE}/{w.party}")
    assert_no_canary(actor, r)
    assert r.status_code == 200 and "gm_notes" not in r.json(), r.text
    assert [a["alias"] for a in r.json()["aliases"]] == ["Little Mira"]
    # A hidden status renders exactly like the control's unset one.
    await assert_hidden_field_equals_unset(actor, f"{BASE}/{w.hidden_status}", "status",
                                           unset_url=f"{BASE}/{w.party}")
    await assert_counts_and_ranking_unchanged(actor, f"{BASE}/{w.party}", lambda: _gm_only_write(ev4, w))
    # Privacy first: GM-only edits (gm_notes, hiding a field, editing it while
    # hidden) leave the Party body byte-identical; no timestamp dates them.
    await assert_counts_and_ranking_unchanged(
        actor, [f"{BASE}/{w.party}", f"{BASE}/?campaign_id={ev4.a.campaign_id}"],
        lambda: _hidden_edits(ev4, w), ignore=())


async def _hidden_edits(ev4, w: World) -> None:
    from app.services.world_service import apply_change

    await apply_change(ev4.db, w.gm, {"op": "update_field", "entity_id": w.party, "field": "gm_notes",
                                      "value": mint_canary("XENTNOTES3", ev4.a.campaign_id).token})
    await _publish(ev4.db, w.gm, w.party, "description", "gm")
    await apply_change(ev4.db, w.gm, {"op": "update_field", "entity_id": w.party, "field": "description",
                                      "value": mint_canary("XENTHIDDEN", ev4.a.campaign_id).token})
    await ev4.db.commit()


@ev4_probe("GET", "/api/entities/{entity_id}/history")
async def probe_entity_history(ev4, actor):
    w = await _world(ev4)
    for entity_id in w.hidden:
        await assert_hidden_equals_missing(actor, f"{BASE}/{entity_id}/history", f"{BASE}/{MISSING}/history")
    if not authenticated(actor):
        return
    url = f"{BASE}/{w.party}/history"
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    # Only what was written while the Party could see it: the alias and the goals edit.
    assert {(i["op"], i["field"]) for i in r.json()["items"]} == {("add_alias", "aliases"),
                                                                ("update_field", "attributes.goals")}, r.text
    await assert_counts_and_ranking_unchanged(actor, url, lambda: _gm_only_write(ev4, w))


# ── Writes ─────────────────────────────────────────────────────────────────

@ev4_probe("POST", "/api/entities/", actors=WRITERS)
async def probe_create_entity(ev4, actor):
    from app.db.models.entity import Entity

    w = await _world(ev4)
    a = ev4.a.campaign_id
    body = {"type": "character", "kind": "npc", "name": "Pip"}
    assert_same_answer(actor, await actor.post(f"{BASE}/", json={**body, "campaign_id": str(w.other_campaign)}),
                       await actor.post(f"{BASE}/", json={**body, "campaign_id": MISSING}), "Campaign")
    before = await row_count(ev4, Entity, Entity.campaign_id == a)
    r = await actor.post(f"{BASE}/", json={**body, "campaign_id": str(a)})
    if is_gm_of_a(ev4, actor):
        assert_no_canary(actor, r)
        assert r.status_code == 201, r.text
        again = await actor.post(f"{BASE}/", json={**body, "name": " pip ", "campaign_id": str(a)})
        assert again.status_code == 409 and again.json()["existing_id"] == r.json()["id"], again.text
        return
    missing = await actor.post(f"{BASE}/", json={**body, "campaign_id": MISSING})
    assert_same_answer(actor, r, missing, "Entity create")
    # A duplicate of a hidden name is refused like any create, never a 409.
    dup = await actor.post(f"{BASE}/", json={"type": "character", "kind": "npc", "name": "Quiet One",
                                             "campaign_id": str(a)})
    assert_same_answer(actor, dup, missing, "Entity create (duplicate)")
    assert await row_count(ev4, Entity, Entity.campaign_id == a) == before


@ev4_probe("POST", "/api/entities/visibility", actors=WRITERS)
async def probe_bulk_entity_visibility(ev4, actor):
    from app.db.models.entity import Entity

    w = await _world(ev4)
    a = str(ev4.a.campaign_id)

    def body(campaign_id, *ids, visibility="party"):
        return {"campaign_id": str(campaign_id), "entity_ids": [str(i) for i in ids], "visibility": visibility}

    assert_same_answer(actor, await actor.post(f"{BASE}/visibility", json=body(w.other_campaign, w.other)),
                       await actor.post(f"{BASE}/visibility", json=body(MISSING, w.other)),
                       "bulk visibility in another Campaign")
    if is_gm_of_a(ev4, actor):
        r = await actor.post(f"{BASE}/visibility", json=body(a, w.party, w.quest, visibility="gm"))
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json() == {"updated": 2}, r.text
        # All-or-nothing: another Campaign's id is the missing-row 404 and nothing changes.
        assert_same_answer(actor, await actor.post(f"{BASE}/visibility", json=body(a, w.hidden_status, w.other)),
                           await actor.post(f"{BASE}/visibility", json=body(a, w.hidden_status, MISSING)),
                           "an Entity of another Campaign")
        assert await row_count(ev4, Entity, Entity.id == w.hidden_status, Entity.visibility == "party") == 1
        return
    before = await _history_rows(ev4)
    for ids in ((w.secret,), (w.party,)):
        assert_same_answer(actor, await actor.post(f"{BASE}/visibility", json=body(a, *ids)),
                           await actor.post(f"{BASE}/visibility", json=body(MISSING, *ids)), "bulk visibility")
    assert await _history_rows(ev4) == before
    assert await row_count(ev4, Entity, Entity.id == w.secret, Entity.visibility == "gm") == 1


@ev4_probe("PATCH", "/api/entities/{entity_id}", actors=WRITERS)
async def probe_update_entity(ev4, actor):
    from app.db.models.entity import Entity

    w = await _world(ev4)
    patch = {"name": "Renamed"}
    await assert_hidden_equals_missing(actor, f"{BASE}/{w.other}", f"{BASE}/{MISSING}", method="PATCH", json=patch)
    if is_gm_of_a(ev4, actor):
        r = await actor.patch(f"{BASE}/{w.party}", json={"name": "Mira Vale", "attributes": {"goals": "Rest"}})
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json()["name"] == "Mira Vale", r.text
        return
    for entity_id in (*w.hidden, w.party):
        await _refused(ev4, actor, "PATCH", f"{BASE}/{entity_id}", f"{BASE}/{MISSING}", json=patch)
    assert await row_count(ev4, Entity, Entity.name == "Renamed") == 0


@ev4_probe("DELETE", "/api/entities/{entity_id}", actors=WRITERS)
async def probe_delete_entity(ev4, actor):
    from app.db.models.entity import Entity

    w = await _world(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/{w.other}", f"{BASE}/{MISSING}", method="DELETE")
    if is_gm_of_a(ev4, actor):
        r = await actor.delete(f"{BASE}/{w.party}")
        assert_no_canary(actor, r)
        assert r.status_code == 204, r.text
        assert await row_count(ev4, Entity, Entity.id == w.party, Entity.deleted_at.is_not(None)) == 1
        return
    for entity_id in (*w.hidden, w.party):
        await _refused(ev4, actor, "DELETE", f"{BASE}/{entity_id}", f"{BASE}/{MISSING}")
    assert await row_count(ev4, Entity, Entity.id == w.party, Entity.deleted_at.is_(None)) == 1


@ev4_probe("POST", "/api/entities/{entity_id}/aliases", actors=WRITERS)
async def probe_add_alias(ev4, actor):
    w = await _world(ev4)
    body = {"alias": "The Vale"}
    await assert_hidden_equals_missing(actor, f"{BASE}/{w.other}/aliases", f"{BASE}/{MISSING}/aliases",
                                       method="POST", json=body)
    if is_gm_of_a(ev4, actor):
        r = await actor.post(f"{BASE}/{w.party}/aliases", json=body)
        assert_no_canary(actor, r)
        assert r.status_code == 201 and r.json()["alias"] == "The Vale", r.text
        return
    for entity_id in (*w.hidden, w.party):
        await _refused(ev4, actor, "POST", f"{BASE}/{entity_id}/aliases", f"{BASE}/{MISSING}/aliases", json=body)


@ev4_probe("DELETE", "/api/entities/{entity_id}/aliases/{alias_id}", actors=WRITERS)
async def probe_remove_alias(ev4, actor):
    w = await _world(ev4)
    missing = f"{BASE}/{MISSING}/aliases/{MISSING}"
    if is_gm_of_a(ev4, actor):
        # Another Entity's alias is the 404.
        await assert_hidden_equals_missing(actor, f"{BASE}/{w.party}/aliases/{w.secret_alias}",
                                           f"{BASE}/{w.party}/aliases/{MISSING}", method="DELETE")
        r = await actor.delete(f"{BASE}/{w.party}/aliases/{w.party_alias}")
        assert_no_canary(actor, r)
        assert r.status_code == 204, r.text
        return
    for entity_id, alias_id in ((w.secret, w.secret_alias), (w.party, w.party_alias)):
        await _refused(ev4, actor, "DELETE", f"{BASE}/{entity_id}/aliases/{alias_id}", missing)


@ev4_probe("POST", "/api/entities/{entity_id}/steps", actors=WRITERS)
async def probe_add_step(ev4, actor):
    w = await _world(ev4)
    body = {"text": "Ring the bell"}
    await assert_hidden_equals_missing(actor, f"{BASE}/{w.other}/steps", f"{BASE}/{MISSING}/steps",
                                       method="POST", json=body)
    if is_gm_of_a(ev4, actor):
        r = await actor.post(f"{BASE}/{w.quest}/steps", json=body)
        assert_no_canary(actor, r)
        assert r.status_code == 201 and r.json()["text"] == "Ring the bell", r.text
        return
    for entity_id in (w.secret, w.quest):
        await _refused(ev4, actor, "POST", f"{BASE}/{entity_id}/steps", f"{BASE}/{MISSING}/steps", json=body)


@ev4_probe("PATCH", "/api/entities/{entity_id}/steps/{step_id}", actors=WRITERS)
async def probe_update_step(ev4, actor):
    w = await _world(ev4)
    body = {"done": True}
    missing = f"{BASE}/{MISSING}/steps/{MISSING}"
    if is_gm_of_a(ev4, actor):
        # A step of another Entity is the 404.
        await assert_hidden_equals_missing(actor, f"{BASE}/{w.party}/steps/{w.step}",
                                           f"{BASE}/{w.party}/steps/{MISSING}", method="PATCH", json=body)
        r = await actor.patch(f"{BASE}/{w.quest}/steps/{w.step}", json=body)
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json()["done"] is True, r.text
        return
    await _refused(ev4, actor, "PATCH", f"{BASE}/{w.quest}/steps/{w.step}", missing, json=body)


@ev4_probe("POST", "/api/entities/{entity_id}/history/{change_id}/revert", actors=WRITERS)
async def probe_revert_change(ev4, actor):
    w = await _world(ev4)
    missing = f"{BASE}/{MISSING}/history/{MISSING}/revert"
    if is_gm_of_a(ev4, actor):
        # A change of another Entity is the 404.
        await assert_hidden_equals_missing(actor, f"{BASE}/{w.party}/history/{w.secret_change}/revert",
                                           f"{BASE}/{w.party}/history/{MISSING}/revert", method="POST", json={})
        r = await actor.post(f"{BASE}/{w.party}/history/{w.party_change}/revert", json={})
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json()["op"] == "revert", r.text
        return
    for entity_id, change_id in ((w.secret, w.secret_change), (w.party, w.party_change)):
        await _refused(ev4, actor, "POST", f"{BASE}/{entity_id}/history/{change_id}/revert", missing, json={})


@ev4_probe("POST", "/api/entities/{entity_id}/visibility", actors=WRITERS)
async def probe_entity_visibility(ev4, actor):
    from app.db.models.entity import Entity

    w = await _world(ev4)
    body = {"visibility": "party"}
    await assert_hidden_equals_missing(actor, f"{BASE}/{w.other}/visibility", f"{BASE}/{MISSING}/visibility",
                                       method="POST", json=body)
    if is_gm_of_a(ev4, actor):
        r = await actor.post(f"{BASE}/{w.party}/visibility", json={"visibility": "gm", "field": "aliases"})
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json() == {"updated": 1}, r.text
        bad = await actor.post(f"{BASE}/{w.party}/visibility", json={"visibility": "party", "field": "gm_notes"})
        assert bad.status_code == 422 and bad.json()["code"] == "always_gm", bad.text
        return
    for entity_id in (w.secret, w.party):
        await _refused(ev4, actor, "POST", f"{BASE}/{entity_id}/visibility", f"{BASE}/{MISSING}/visibility",
                       json=body)
    assert await row_count(ev4, Entity, Entity.id == w.secret, Entity.visibility == "gm") == 1


# ── Merge (E0-WorldCore.9) ─────────────────────────────────────────────────

async def _merge_material(ev4, w: World) -> None:
    """The GM-only `secret` also gets a confirmed Mention in the seed's Party
    entry and an edge to a Party Entity (its note a canary), so a merge into
    the Party `party` moves an alias, a Mention and a Relationship."""
    from app.db.models.entity import RelationshipType
    from app.services.world_service import apply_change

    db, a = ev4.db, ev4.a.campaign_id
    rt = RelationshipType(campaign_id=a, key=f"ev4_merge_{uuid.uuid4().hex[:6]}", label="Ally of",
                          inverse_label="Ally of")
    db.add(rt)
    await db.flush()
    await apply_change(db, w.gm, {"op": "add_mention", "entity_id": w.secret,
                                  "journal_id": ev4.a.ids["journal_entries"][0], "confirmed": True})
    await apply_change(db, w.gm, {"op": "add_relationship", "entity_id": w.secret, "target_entity_id": w.hidden_status,
                                  "relationship_type_id": rt.id, "note": mint_canary("XENTEDGE", a).token})
    await db.commit()


async def _gm_merges(ev4, w: World) -> None:
    from app.services.world_service import merge_entities

    await merge_entities(ev4.db, w.gm, w.party, w.secret)
    await ev4.db.commit()


async def _rows_on(ev4, actor, entity_id) -> dict[str, list[str]] | None:
    """The alias, Mention and edge ids on `entity_id` the actor's ctx can see
    (None for an actor with no ctx in Campaign A)."""
    import sqlalchemy as sa

    from app.access import NotFound, ctx_for, scoped_select
    from app.db.models.entity import EntityAlias, EntityMention, EntityRelationship

    if not authenticated(actor):
        return None
    try:
        ctx = await ctx_for(ev4.db, actor.user_id, ev4.a.campaign_id)
    except NotFound:
        return None
    out = {}
    for name, model, where in (
            ("aliases", EntityAlias, EntityAlias.entity_id == entity_id),
            ("mentions", EntityMention, EntityMention.entity_id == entity_id),
            ("relationships", EntityRelationship, sa.or_(EntityRelationship.source_entity_id == entity_id,
                                                         EntityRelationship.target_entity_id == entity_id))):
        rows = (await ev4.db.execute(scoped_select(model, ctx).where(where)
                                     .execution_options(populate_existing=True))).scalars().all()
        out[name] = sorted(str(r.id) for r in rows)
    return out


@ev4_probe("POST", "/api/entities/{entity_id}/merge", actors=WRITERS)
async def probe_merge_entities(ev4, actor):
    """A non-GM is refused like a missing Entity and nothing is written. The
    downgrade probe: after a GM merges the GM-only Entity into the Party one,
    a Player sees none of the moved aliases, Mentions or edges (no canary, the
    bodies and counts do not move), and the absorbed id answers like a
    missing one."""
    from app.db.models.entity import Entity

    w = await _world(ev4)
    await _merge_material(ev4, w)
    a = ev4.a.campaign_id
    body = {"absorbed_id": str(w.secret)}
    # Another Campaign's Entity, as the survivor, answers like a missing one.
    await assert_hidden_equals_missing(actor, f"{BASE}/{w.other}/merge", f"{BASE}/{MISSING}/merge", method="POST",
                                       json={"absorbed_id": str(w.party)})
    if is_gm_of_a(ev4, actor):
        # ... and as the absorbed one.
        assert_same_answer(actor, await actor.post(f"{BASE}/{w.party}/merge", json={"absorbed_id": str(w.other)}),
                           await actor.post(f"{BASE}/{w.party}/merge", json={"absorbed_id": MISSING}),
                           "merge of another Campaign's Entity")
        before = await _history_rows(ev4)
        preview = await actor.post(f"{BASE}/{w.party}/merge", json={**body, "preview": True})
        assert_no_canary(actor, preview)
        assert preview.status_code == 200, preview.text
        assert preview.json()["warning"] == "party_with_gm_only" and {
            d["kind"] for d in preview.json()["downgrades"]} == {"alias", "mention", "relationship"}, preview.text
        assert await _history_rows(ev4) == before
        r = await actor.post(f"{BASE}/{w.party}/merge", json=body)
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json()["change_id"], r.text
        old = await actor.get(f"{BASE}/{w.secret}")
        assert old.status_code == 200 and old.json()["id"] == str(w.party), old.text
        return
    for target, absorbed in ((w.party, w.secret), (w.secret, w.party), (w.party, w.hidden_status)):
        for preview in (False, True):
            await _refused(ev4, actor, "POST", f"{BASE}/{target}/merge", f"{BASE}/{MISSING}/merge",
                           json={"absorbed_id": str(absorbed), "preview": preview})
    assert await row_count(ev4, Entity, Entity.campaign_id == a, Entity.merged_into_id.is_not(None)) == 0

    # The downgrade probe.
    seen = await _rows_on(ev4, actor, w.party)
    if authenticated(actor):
        urls = [f"{BASE}/{w.party}", f"{BASE}/?campaign_id={a}", f"{BASE}/?campaign_id={a}&q=Mira",
                f"{BASE}/{w.party}/history", f"{BASE}/{w.hidden_status}"]
        await assert_counts_and_ranking_unchanged(actor, urls, lambda: _gm_merges(ev4, w), ignore=())
        for url in urls:
            assert_no_canary(actor, await actor.get(url))
    else:
        await _gm_merges(ev4, w)
    assert await row_count(ev4, Entity, Entity.id == w.secret, Entity.merged_into_id == w.party) == 1
    if await _rows_on(ev4, actor, w.party) != seen:
        record_leak("EV-4 leak: a merge of a GM-only Entity widened what the Party sees",
                    [f"{actor.name}: before {seen} after {await _rows_on(ev4, actor, w.party)}"])
    # The hidden absorbed id answers like a missing one.
    await assert_hidden_equals_missing(actor, f"{BASE}/{w.secret}", f"{BASE}/{MISSING}")
    await assert_hidden_equals_missing(actor, f"{BASE}/{w.secret}/history", f"{BASE}/{MISSING}/history")
