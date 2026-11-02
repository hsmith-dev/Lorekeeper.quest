"""E0-WorldCore.2: the F3-world registrations, on transient rows (no DB).

CI-11 (test_registry_property.py) proves SQL and Python agree on random
rows; these pin what the Python side says for the cases the AC names: the
Visibility floor, an edge narrowed by both endpoints, the binding Mention
formula, the entity_changes field rule, and an Entity's Party rendering of
hidden fields (AD-13).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from sqlalchemy.orm.attributes import set_committed_value

from app.access import (
    GM_AUDIENCE, PUBLIC, REGISTRY, CampaignContext, NotFound, audience_of, check_create, mention_audience, owner,
    project,
)
from app.access import registry as reg
from app.db.models import (
    Entity, EntityAlias, EntityChange, EntityMention, EntityRelationship, JournalEntry, QuestStep, RelationshipType,
)
from app.schemas.entities import EntityGMResponse, EntityPartyResponse

CID = uuid.uuid4()
AUTHOR, PLAYER = uuid.uuid4(), uuid.uuid4()
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

GM_CTX = CampaignContext(campaign_id=CID, user_id=AUTHOR, role="gm", is_owner=True, audience=GM_AUDIENCE)
PLAYER_CTX = CampaignContext(campaign_id=CID, user_id=PLAYER, role="player", is_owner=False, audience=owner(PLAYER))


def entity(visibility: str = "party", field_visibility: dict | None = None, type_: str = "character",
           **kw) -> Entity:
    defaults = {"kind": "npc" if type_ == "character" else None,
                "status": {"character": "alive", "quest": "completed"}.get(type_, "active")}
    defaults.update(kw)
    return Entity(id=uuid.uuid4(), campaign_id=CID, type=type_, name="Aldric",
                  visibility=visibility, field_visibility=field_visibility or {}, created_by_user_id=AUTHOR,
                  created_at=NOW, updated_at=NOW, **defaults)


def entry(visibility: str = "party", kind: str = "gm") -> JournalEntry:
    return JournalEntry(id=uuid.uuid4(), campaign_id=CID, user_id=AUTHOR, visibility=visibility, kind=kind)


def test_registrations_match_the_ac():
    assert isinstance(REGISTRY[Entity], reg.Stored) and REGISTRY[Entity].owner_field == "created_by_user_id"
    assert REGISTRY[Entity].field_visibility == "field_visibility" and REGISTRY[Entity].gm_fields == ("gm_notes",)
    edges = REGISTRY[EntityRelationship]
    assert isinstance(edges, reg.Stored) and edges.owner_field is None and edges.floor == "visibility_floor"
    assert [link.fk for link in edges.narrowed_by] == ["source_entity_id", "target_entity_id"]
    assert REGISTRY[RelationshipType] == reg.membership(PUBLIC)
    assert REGISTRY[EntityAlias].floor == "visibility_floor"
    assert [link.model for link in REGISTRY[QuestStep].derive_from] == [Entity]
    mention = REGISTRY[EntityMention]
    assert [link.model for link in mention.derive_from] == [JournalEntry, Entity]
    assert (mention.field, mention.floor) == ("source_field", "visibility_floor")
    assert REGISTRY[EntityChange].field_rule == reg.FIELD_RULE_PARENT_FIELD


def test_registration_options_are_validated():
    with pytest.raises(ValueError):
        reg.stored(column=None, owner_field=None)
    with pytest.raises(ValueError):
        reg.derived([reg.parent(Entity, "entity_id")], field_rule="nope")
    with pytest.raises(ValueError):
        reg.derived([reg.parent(Entity, "entity_id")], field_rule=reg.FIELD_RULE_PARENT_FIELD)  # no field


# ── Floors ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("floor, expected", [(None, PUBLIC), ("party", PUBLIC), ("gm", GM_AUDIENCE),
                                             ("private", GM_AUDIENCE)])
def test_alias_floor_narrows_a_party_entity(floor, expected):
    alias = EntityAlias(campaign_id=CID, alias="Al", normalized_alias="al", visibility_floor=floor)
    assert audience_of(alias, parents=[entity("party")]) == expected


def test_alias_and_step_follow_their_entity():
    assert audience_of(EntityAlias(visibility_floor=None), parents=[entity("gm")]) == GM_AUDIENCE
    assert audience_of(QuestStep(position=0, text="go"), parents=[entity("party", type_="quest")]) == PUBLIC
    assert audience_of(QuestStep(position=0, text="go"), parents=[entity("private", type_="quest")]) == owner(AUTHOR)


# ── Relationships: stored, narrowed by both endpoints ──────────────────────

@pytest.mark.parametrize("edge_vis, floor, src, tgt, expected", [
    ("party", None, "party", "party", PUBLIC),
    ("party", None, "party", "gm", GM_AUDIENCE),    # a Party edge never reveals a GM-only Entity
    ("party", None, "gm", "party", GM_AUDIENCE),
    ("party", "gm", "party", "party", GM_AUDIENCE),  # the merge floor
    ("gm", None, "party", "party", GM_AUDIENCE),
    ("private", None, "party", "party", GM_AUDIENCE),  # an edge has no author: private is nobody's
    ("party", None, "private", "party", owner(AUTHOR)),
])
def test_edge_is_never_wider_than_an_endpoint(edge_vis, floor, src, tgt, expected):
    edge = EntityRelationship(campaign_id=CID, visibility=edge_vis, visibility_floor=floor)
    assert audience_of(edge, parents=[entity(src), entity(tgt)]) == expected


def test_edge_needs_its_endpoints():
    edge = EntityRelationship(campaign_id=CID, visibility="party")
    with pytest.raises(ValueError):
        audience_of(edge)  # the endpoint relationships are not loaded
    assert audience_of(edge, parents=[None, entity("party")]) == GM_AUDIENCE


# ── Mentions: most_restrictive(entry, entity, field_aud(source_field), floor) ──

@pytest.mark.parametrize("entry_vis, entity_vis, source_field, floor", [
    ("party", "party", "narrative", None),
    ("party", "party", "shorthand", None),
    ("party", "party", "gm_notes", None),
    ("party", "party", "narrative", "gm"),
    ("gm", "party", "narrative", None),
    ("party", "gm", "narrative", None),
    ("private", "party", "narrative", None),
])
def test_mention_audience_is_the_binding_formula(entry_vis, entity_vis, source_field, floor):
    e, ent = entry(entry_vis), entity(entity_vis)
    m = EntityMention(campaign_id=CID, source_field=source_field, origin="manual", visibility_floor=floor)
    floor_aud = None if floor is None else GM_AUDIENCE
    assert audience_of(m, parents=[e, ent]) == mention_audience(audience_of(e), audience_of(ent), source_field,
                                                                floor_aud)


def test_mention_from_the_shorthand_or_gm_notes_never_reaches_a_player():
    for source_field in ("shorthand", "gm_notes"):
        m = EntityMention(campaign_id=CID, source_field=source_field, origin="extraction")
        assert audience_of(m, parents=[entry("party"), entity("party")]) == GM_AUDIENCE


def test_orphan_mention_is_gm():
    m = EntityMention(campaign_id=CID, source_field="narrative", origin="migration")
    assert audience_of(m, parents=[None, entity("party")]) == GM_AUDIENCE


# ── entity_changes: the Entity, narrowed by the changed field ──────────────

@pytest.mark.parametrize("field, field_visibility, expected", [
    (None, {}, GM_AUDIENCE),  # a whole-row snapshot may hold gm_notes
    ("status", {}, PUBLIC),
    ("description", {"description": "party"}, PUBLIC),
    ("description", {"description": "gm"}, GM_AUDIENCE),
    ("description", {"description": "private"}, owner(AUTHOR)),
    ("description", {"description": "bogus"}, GM_AUDIENCE),  # fail closed
    ("attributes.region", {"attributes.region": "gm"}, GM_AUDIENCE),
    ("attributes.region", {"attributes": "gm"}, GM_AUDIENCE),  # the whole map hidden
    ("attributes.region", {"attributes": "private"}, owner(AUTHOR)),
    ("attributes", {"attributes": "gm"}, GM_AUDIENCE),
    ("gm_notes.x", {}, GM_AUDIENCE),
    ("status", {"description": "gm"}, PUBLIC),
    ("gm_notes", {}, GM_AUDIENCE),
    ("field_visibility", {}, GM_AUDIENCE),
    ("field_visibility.status", {}, GM_AUDIENCE),
    ("visibility_floor", {}, GM_AUDIENCE),
])
def test_change_field_rule(field, field_visibility, expected):
    change = EntityChange(campaign_id=CID, op="update_field", field=field)
    assert audience_of(change, parents=[entity("party", field_visibility)]) == expected


@pytest.mark.parametrize("op, expected", [("migrated", PUBLIC), ("create_entity", GM_AUDIENCE),
                                          ("merge", GM_AUDIENCE), ("delete_entity", GM_AUDIENCE)])
def test_change_without_a_field_is_gm_unless_migrated(op, expected):
    change = EntityChange(campaign_id=CID, op=op, field=None, new_value={"gm_notes": "secret"})
    assert audience_of(change, parents=[entity("party")]) == expected


def test_change_of_a_gm_entity_is_gm():
    change = EntityChange(campaign_id=CID, op="migrated", field=None)
    assert audience_of(change, parents=[entity("gm")]) == GM_AUDIENCE


def test_change_field_rule_needs_the_entity_row():
    change = EntityChange(campaign_id=CID, op="update_field", field="status")
    with pytest.raises(ValueError):
        audience_of(change, parents=[PUBLIC])


# ── Entity Party rendering: hidden renders as unset (AD-13) ────────────────

def test_party_projection_renders_hidden_fields_as_unset():
    loc = entity("party", {"status": "gm", "description": "gm", "attributes.region": "gm", "attributes.stale": "gm",
                           "name": "party"}, type_="location", status="destroyed", description="Ruined keep",
                 attributes={"region": "North", "kind": "dungeon", "stale": 1}, gm_notes="secret")
    body = project(loc, PLAYER_CTX)
    assert isinstance(body, EntityPartyResponse)
    assert body.status == "unknown" and body.description is None
    assert body.attributes == {"kind": "dungeon"}
    assert body.name == "Aldric"
    assert "gm_notes" not in body.model_dump() and "field_visibility" not in body.model_dump()
    assert loc.attributes == {"region": "North", "kind": "dungeon", "stale": 1}  # the row is not mutated

    gm = project(loc, GM_CTX)
    assert isinstance(gm, EntityGMResponse)
    assert (gm.status, gm.description, gm.gm_notes) == ("destroyed", "Ruined keep", "secret")
    assert gm.attributes == {"region": "North", "kind": "dungeon", "stale": 1}


def test_hidden_quest_status_renders_as_active():
    quest = entity("party", {"status": "gm"}, type_="quest", attributes={"completed_at": "2026-01-01T00:00:00Z"})
    body = project(quest, PLAYER_CTX)
    assert body.status == "active"
    assert "completed_at" not in body.attributes  # it would give the status away
    assert project(quest, GM_CTX).attributes == {"completed_at": "2026-01-01T00:00:00Z"}


def test_hidden_required_field_is_left_as_is():
    # `name` is never hidden; a field_visibility entry for it must not 500 the Party schema.
    npc = entity("party", {"name": "gm", "kind": "gm"})
    body = project(npc, PLAYER_CTX)
    assert (body.name, body.kind) == ("Aldric", "npc")


def test_field_shown_to_its_owner_only():
    sheet = entity("party", {"description": "private"}, description="Mine")
    assert project(sheet, PLAYER_CTX).description is None
    author_ctx = CampaignContext(campaign_id=CID, user_id=AUTHOR, role="player", is_owner=False,
                                 audience=owner(AUTHOR))
    assert project(sheet, author_ctx).description == "Mine"


# ── check_create: the floor and the endpoints narrow a create too ──────────

def _edge(src: Entity | None, tgt: Entity | None, visibility: str = "party", floor: str | None = None):
    edge = EntityRelationship(campaign_id=CID, visibility=visibility, visibility_floor=floor)
    if src is not None or tgt is not None:
        set_committed_value(edge, "source_entity", src)
        set_committed_value(edge, "target_entity", tgt)
    return edge


def test_check_create_counts_floor_and_endpoints(monkeypatch):
    # check_create ends with can_write (E0-Access.6), which refuses any
    # Player create but their own Player Journal entry:
    with pytest.raises(NotFound):
        check_create(_edge(entity("party"), entity("party")), PLAYER_CTX)
    # The visibility half on its own (write gate off for this test):
    from app.access import projection
    monkeypatch.setattr(projection, "can_write", lambda ctx, obj: None)
    check_create(_edge(entity("party"), entity("party")), PLAYER_CTX)  # visible: allowed
    with pytest.raises(NotFound):
        check_create(_edge(entity("party"), entity("gm")), PLAYER_CTX)
    with pytest.raises(NotFound):
        check_create(_edge(entity("party"), entity("party"), floor="gm"), PLAYER_CTX)
    check_create(_edge(entity("party"), entity("gm"), floor="gm"), GM_CTX)
    with pytest.raises(ValueError):
        check_create(_edge(None, None), PLAYER_CTX)  # endpoints not loaded


def test_gm_only_entity_is_not_found_for_a_player():
    with pytest.raises(NotFound):
        project(entity("gm"), PLAYER_CTX)


# ── E0-WorldCore.3: deleted / merged Entities, register_writer ─────────────

@pytest.mark.parametrize("gone", [{"deleted_at": NOW}, {"merged_into_id": uuid.uuid4()}])
def test_a_deleted_or_merged_entity_is_gm_only(gone):
    assert REGISTRY[Entity].gm_when == ("deleted_at", "merged_into_id")
    e = entity("party", **gone)
    assert audience_of(e) == GM_AUDIENCE
    alias = EntityAlias(campaign_id=CID, alias="Al", normalized_alias="al")
    assert audience_of(alias, parents=[e]) == GM_AUDIENCE
    with pytest.raises(NotFound):
        check_create(e, PLAYER_CTX)
    with pytest.raises(NotFound):
        project(e, PLAYER_CTX)
    assert audience_of(entity("party")) == PUBLIC


def test_gm_when_needs_column_names():
    with pytest.raises(ValueError):
        reg.stored(gm_when=("",))
    with pytest.raises(ValueError):
        reg.stored(column=None, gm_when=("deleted_at",))


def test_register_writer(monkeypatch):
    from app.db.models import NpcEntry, SessionPlan

    monkeypatch.setitem(REGISTRY, SessionPlan, reg.stored())

    def writer(db, ctx, row, field, value):  # pragma: no cover - never called
        return None

    assert reg.register_writer(SessionPlan, writer).writer is writer
    assert REGISTRY[SessionPlan].writer is writer
    assert reg.register_writer(SessionPlan, writer).writer is writer  # the same one: a no-op
    with pytest.raises(ValueError):
        reg.register_writer(SessionPlan, lambda *a: None)
    with pytest.raises(ValueError):
        reg.register_writer(NpcEntry, writer)  # always_gm
    monkeypatch.setitem(REGISTRY, SessionPlan, reg.stored())
    with pytest.raises(TypeError):
        reg.register_writer(SessionPlan, "not callable")
