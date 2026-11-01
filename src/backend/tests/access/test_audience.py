"""E0-Access.3: the Audience lattice, the AD-12 mapping, the Mention formula,
the registry's shape and derived types. Pure: no database."""
from __future__ import annotations

import itertools
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.access import (
    ALWAYS_GM_FIELDS, ANON_VIEW, DERIVED_REGISTRY, GM_AUDIENCE, MEMBER_VIEW, MEMBERS, PUBLIC, REGISTRY, AnyOf,
    Audience, AudienceLevel, CampaignContext, DerivedType, NotFound, UnregisteredModel, as_user, audience_ctx,
    audience_of, covers, ctx_audience, field_audience, mention_audience, most_restrictive, owner,
    register_derived, scoped_select, scoped_select_multi, stored_audience, visible_clause, visible_to,
)
from app.access import registry as reg
from app.db.models import (
    Campaign, CampaignMember, CampaignShareToken, CharacterSheet, CharacterSheetTemplate, ChatSession, Feedback,
    JournalEntry, JournalTag, NpcEntry, Quest, SessionPlan, ShorthandTerm, SourceChunk, SourceDocument, Tag,
    TagCategory,
)
from app.db.models.journal import JournalEntry as JE

A, B = uuid.uuid4(), uuid.uuid4()
OA, OB = owner(A), owner(B)
ALL = [PUBLIC, MEMBERS, OA, OB, GM_AUDIENCE]


# ── Order ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("row, viewers", [
    (PUBLIC, {PUBLIC, MEMBERS, OA, OB, GM_AUDIENCE}),
    (MEMBERS, {MEMBERS, OA, OB, GM_AUDIENCE}),
    (OA, {OA, GM_AUDIENCE}),
    (GM_AUDIENCE, {GM_AUDIENCE}),
])
def test_covers(row, viewers):
    assert {v for v in ALL if covers(row, v)} == viewers


def test_covers_is_a_partial_order():
    for a in ALL:
        assert covers(a, a)
    for a, b in itertools.product(ALL, ALL):
        if covers(a, b) and covers(b, a):
            assert a == b
    for a, b, c in itertools.product(ALL, ALL, ALL):
        if covers(a, b) and covers(b, c):
            assert covers(a, c)


def test_most_restrictive_is_the_meet():
    assert most_restrictive(OA, OB) == GM_AUDIENCE
    assert most_restrictive(OA, OA) == OA
    assert most_restrictive(PUBLIC, MEMBERS) == MEMBERS
    assert most_restrictive(MEMBERS, OA) == OA
    assert most_restrictive(OA, GM_AUDIENCE) == GM_AUDIENCE
    assert most_restrictive([PUBLIC, OA, MEMBERS]) == OA
    assert most_restrictive(PUBLIC) == PUBLIC
    with pytest.raises(ValueError):
        most_restrictive()
    with pytest.raises(ValueError):
        most_restrictive([])
    # The meet is the greatest lower bound: covered by both inputs' viewers only.
    for a, b in itertools.product(ALL, ALL):
        m = most_restrictive(a, b)
        assert m == most_restrictive(b, a)
        for v in ALL:
            assert covers(m, v) == (covers(a, v) and covers(b, v))


def test_visible_to_and_any_of():
    gm_ctx = SimpleNamespace(audience=GM_AUDIENCE)
    assert visible_to(OA, gm_ctx) and visible_to(OA, OA) and not visible_to(OA, OB)
    assert visible_to(AnyOf([GM_AUDIENCE, OB]), OB)
    assert not visible_to(AnyOf([OA]), OB)
    assert not visible_to(AnyOf(), GM_AUDIENCE), "an empty AnyOf is hidden, even to a GM"
    with pytest.raises(TypeError):
        AnyOf(["public"])


def test_audience_shape():
    with pytest.raises(ValueError):
        Audience(AudienceLevel.OWNER)
    with pytest.raises(ValueError):
        Audience(AudienceLevel.GM, A)
    assert repr(OA) == f"Owner({A})" and repr(PUBLIC) == "Public"


# ── AD-12 mapping ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("vis, kind, expected", [
    ("party", "gm", PUBLIC),
    ("party", None, PUBLIC),
    ("party", "player", MEMBERS),
    ("private", "gm", OA),
    ("private", "player", OA),
    ("private", None, OA),
    ("gm", "gm", GM_AUDIENCE),
    ("gm", "player", GM_AUDIENCE),
    ("gm", None, GM_AUDIENCE),
])
def test_stored_audience(vis, kind, expected):
    assert stored_audience(vis, A, kind) == expected


def test_stored_audience_rejects_unknown_values():
    with pytest.raises(ValueError):
        stored_audience("secret", A)
    with pytest.raises(ValueError):
        stored_audience("party", A, "npc")
    assert stored_audience("private", None) == GM_AUDIENCE


def test_ctx_audiences():
    assert ctx_audience("gm", A) == GM_AUDIENCE
    assert ctx_audience("player", A) == OA
    assert ctx_audience("anon", None) == PUBLIC


# ── Field rule and the Mention formula ─────────────────────────────────────

def test_field_audience():
    assert {"shorthand", "gm_notes", "voice_notes"} <= ALWAYS_GM_FIELDS
    assert field_audience("shorthand") == GM_AUDIENCE
    assert field_audience("gm_notes") == GM_AUDIENCE
    for f in ("narrative", "manual", None):
        assert field_audience(f) == PUBLIC


@pytest.mark.parametrize("entry, entity, source_field, floor, expected", [
    (PUBLIC, PUBLIC, "narrative", None, PUBLIC),
    (PUBLIC, PUBLIC, "shorthand", None, GM_AUDIENCE),
    (PUBLIC, PUBLIC, "gm_notes", None, GM_AUDIENCE),
    (MEMBERS, PUBLIC, "narrative", None, MEMBERS),
    (PUBLIC, OA, "narrative", None, OA),
    (OA, OB, "narrative", None, GM_AUDIENCE),
    (PUBLIC, PUBLIC, None, MEMBERS, MEMBERS),
    (PUBLIC, MEMBERS, "narrative", OA, OA),
    (PUBLIC, PUBLIC, "narrative", GM_AUDIENCE, GM_AUDIENCE),
])
def test_mention_audience(entry, entity, source_field, floor, expected):
    assert mention_audience(entry, entity, source_field, floor) == expected


# ── Registry shape ─────────────────────────────────────────────────────────

def test_every_current_table_is_registered_as_the_story_says():
    expect = {
        JournalEntry: reg.Stored, CharacterSheet: reg.Stored, SessionPlan: reg.Stored, SourceDocument: reg.Stored,
        ShorthandTerm: reg.Stored, TagCategory: reg.Stored, ChatSession: reg.Stored,
        SourceChunk: reg.Derived, JournalTag: reg.Derived, Tag: reg.Derived,
        NpcEntry: reg.AlwaysGM, Quest: reg.AlwaysGM,
        Campaign: reg.Membership, CampaignMember: reg.Membership, CampaignShareToken: reg.Membership,
        CharacterSheetTemplate: reg.Membership,
    }
    assert {m: type(r) for m, r in REGISTRY.items()} == expect
    assert REGISTRY[JournalEntry].kind_field == "kind"
    assert REGISTRY[ChatSession].column is None and REGISTRY[ChatSession].owner_field == "user_id"
    assert REGISTRY[CharacterSheet].owner_field == REGISTRY[TagCategory].owner_field == "created_by_user_id"
    assert REGISTRY[JournalTag].field == "source_field"
    assert {m: REGISTRY[m].audience for m in (Campaign, CampaignMember, CampaignShareToken,
                                             CharacterSheetTemplate)} == {
        Campaign: PUBLIC, CampaignMember: MEMBERS, CampaignShareToken: GM_AUDIENCE, CharacterSheetTemplate: PUBLIC}
    assert reg.gm_fields(JournalEntry) == ("shorthand",)
    assert reg.gm_fields(NpcEntry) == reg.gm_fields(Quest) == ("notes",)
    assert "feedback" in reg.UNSCOPED


def test_unregistered_model_raises():
    ctx = audience_ctx(A, ANON_VIEW, by=_gm(A))
    with pytest.raises(UnregisteredModel):
        scoped_select(Feedback, ctx)
    with pytest.raises(UnregisteredModel):
        visible_clause(Feedback, ctx)
    with pytest.raises(UnregisteredModel):
        audience_of(Feedback(message="x"))
    with pytest.raises(UnregisteredModel):
        scoped_select_multi(Feedback, {A: "gm"})


def test_completeness_check_fails_on_an_unregistered_campaign_table(monkeypatch):
    monkeypatch.delitem(reg.REGISTRY, SessionPlan)
    with pytest.raises(RuntimeError, match="session_plans"):
        reg._check_complete()
    monkeypatch.setitem(reg.REGISTRY, SessionPlan, reg.stored())
    monkeypatch.delitem(reg.REGISTRY, Tag)
    with pytest.raises(RuntimeError, match="tags"):
        reg._check_complete()
    monkeypatch.setitem(reg.REGISTRY, Tag, reg.derived([reg.reached_through(JournalTag, "tag_id")]))
    monkeypatch.setitem(reg.UNSCOPED, "session_plans", "both")
    with pytest.raises(RuntimeError, match="both registered and UNSCOPED"):
        reg._check_complete()


def test_registration_constructors_validate():
    with pytest.raises(ValueError):
        reg.derived([])
    with pytest.raises(ValueError):
        reg.derived([reg.parent(JE, "journal_id"), reg.reached_through(JournalTag, "tag_id")])
    with pytest.raises(ValueError):
        reg.membership(OA)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _gm(cid) -> CampaignContext:
    return CampaignContext(campaign_id=cid, user_id=uuid.uuid4(), role="gm", is_owner=True, audience=GM_AUDIENCE)


def _player(cid, uid=A) -> CampaignContext:
    return CampaignContext(campaign_id=cid, user_id=uid, role="player", is_owner=False, audience=owner(uid))


def test_visible_clause_sql_per_ctx_class():
    cid = uuid.uuid4()
    gm, player = _gm(cid), _player(cid)
    anon, member = audience_ctx(cid, ANON_VIEW, by=gm), audience_ctx(cid, MEMBER_VIEW, by=gm)
    sql = _sql(scoped_select(JournalEntry, gm))
    assert "journal_entries.campaign_id" in sql and "visibility" not in sql.split("WHERE", 1)[1]
    sql = _sql(scoped_select(JournalEntry, player))
    assert "'private'" in sql and str(A) in sql
    sql = _sql(scoped_select(JournalEntry, member))
    assert "'party'" in sql and "'private'" not in sql and "kind" not in sql.split("WHERE", 1)[1]
    sql = _sql(scoped_select(JournalEntry, anon))
    assert "'party'" in sql and "journal_entries.kind = 'gm'" in sql
    # Membership / always_gm compile to constants.
    assert _sql(scoped_select(NpcEntry, player)).rstrip().lower().endswith("false")
    assert "false" not in _sql(scoped_select(Campaign, anon)).lower()
    assert _sql(scoped_select(CampaignShareToken, player)).rstrip().lower().endswith("false")
    # Tags have no campaign column: scoped through journal_tags -> journal_entries.
    sql = _sql(scoped_select(Tag, player))
    assert "EXISTS" in sql and f"journal_entries.campaign_id = '{cid}'" in sql and "source_field" in sql


# ── audience_ctx ───────────────────────────────────────────────────────────

def test_audience_ctx_from_gm():
    cid = uuid.uuid4()
    gm = CampaignContext(campaign_id=cid, user_id=A, role="gm", is_owner=False, audience=GM_AUDIENCE,
                         grant_id=uuid.uuid4(), access_epoch=7)
    anon = audience_ctx(cid, ANON_VIEW, by=gm)
    assert (anon.role, anon.user_id, anon.audience, anon.read_only) == ("anon", None, PUBLIC, True)
    member = audience_ctx(cid, MEMBER_VIEW, by=gm)
    assert (member.role, member.user_id, member.audience, member.read_only) == ("player", None, MEMBERS, True)
    other = audience_ctx(cid, as_user(B), by=gm)
    assert (other.role, other.user_id, other.audience, other.read_only) == ("player", B, OB, True)
    for c in (anon, member, other):
        assert c.is_owner is False and c.grant_id is None and c.access_epoch == 7 and c.campaign_id == cid
        assert c.actor == "user"
    assert audience_ctx(str(cid), as_user(str(B)), by=gm) == other


def test_audience_ctx_from_player_and_anon():
    cid = uuid.uuid4()
    p = _player(cid, A)
    assert audience_ctx(cid, ANON_VIEW, by=p).audience == PUBLIC
    assert audience_ctx(cid, MEMBER_VIEW, by=p).audience == MEMBERS
    me = audience_ctx(cid, as_user(A), by=p)
    assert me.audience == OA and me.read_only
    with pytest.raises(NotFound):
        audience_ctx(cid, as_user(B), by=p)
    anon = audience_ctx(cid, ANON_VIEW, by=p)
    assert audience_ctx(cid, ANON_VIEW, by=anon).audience == PUBLIC
    with pytest.raises(NotFound):
        audience_ctx(cid, MEMBER_VIEW, by=anon)
    with pytest.raises(NotFound):
        audience_ctx(cid, as_user(A), by=anon)
    member = audience_ctx(cid, MEMBER_VIEW, by=p)
    with pytest.raises(NotFound):
        audience_ctx(cid, as_user(A), by=member)
    # Another Campaign, or junk.
    with pytest.raises(NotFound):
        audience_ctx(uuid.uuid4(), ANON_VIEW, by=_gm(cid))
    with pytest.raises(NotFound):
        audience_ctx("not-a-uuid", ANON_VIEW, by=_gm(cid))
    with pytest.raises(ValueError):
        audience_ctx(cid, "gm", by=_gm(cid))
    with pytest.raises(ValueError):
        as_user("nope")


def test_reduced_ctx_rules():
    cid = uuid.uuid4()
    with pytest.raises(ValueError):  # anon must be read-only
        CampaignContext(campaign_id=cid, user_id=None, role="anon", is_owner=False, audience=PUBLIC)
    with pytest.raises(ValueError):  # member view must be read-only
        CampaignContext(campaign_id=cid, user_id=None, role="player", is_owner=False, audience=MEMBERS)
    with pytest.raises(ValueError):  # a Player reads as themself
        CampaignContext(campaign_id=cid, user_id=A, role="player", is_owner=False, audience=OB)
    with pytest.raises(ValueError):  # a GM reads everything
        CampaignContext(campaign_id=cid, user_id=A, role="gm", is_owner=False, audience=MEMBERS)
    with pytest.raises(ValueError):  # anon has no user
        CampaignContext(campaign_id=cid, user_id=A, role="anon", is_owner=False, audience=PUBLIC, read_only=True)
    reduced = audience_ctx(cid, as_user(A), by=_gm(cid))
    with pytest.raises(ValueError):  # a reduced ctx is never raised to a system ctx
        reduced.as_system("merge")


# ── Derived types (DERIVED_REGISTRY, RC-8) ─────────────────────────────────

@pytest.fixture
def derived_registry():
    saved = list(DERIVED_REGISTRY)
    yield DERIVED_REGISTRY
    DERIVED_REGISTRY[:] = saved


def test_derived_registry_starts_empty():
    assert DERIVED_REGISTRY == []


def _src(kind, aud):
    return SimpleNamespace(ref_kind=kind, audience=aud)


def test_non_file_derived_type_is_most_restrictive_of_its_sources(derived_registry):
    derived_registry.append({"derived_type": "live_recap", "derive_from": ["live_segment"]})
    recap = SimpleNamespace(derived_type="live_recap",
                            derived_sources=[_src("live_segment", PUBLIC), _src("live_segment", MEMBERS)])
    assert audience_of(recap) == MEMBERS
    recap.derived_sources.append(_src("live_segment", OA))
    assert audience_of(recap) == OA
    recap.derived_sources.append(_src("live_segment", OB))
    assert audience_of(recap) == GM_AUDIENCE
    # Sources given explicitly, as Audiences, or as registered rows.
    assert audience_of(recap, parents=[PUBLIC]) == PUBLIC
    plan = SessionPlan(user_id=A, campaign_id=uuid.uuid4(), title="t", content="c", visibility="party")
    assert audience_of(recap, parents=[{"ref_kind": "live_segment", "ref": plan}]) == PUBLIC


def test_derived_type_with_no_sources_is_gm(derived_registry):
    register_derived("dummy_file", ["source_document"])
    assert isinstance(derived_registry[-1], DerivedType)
    assert audience_of(SimpleNamespace(derived_type="dummy_file", derived_sources=[])) == GM_AUDIENCE


def test_derived_type_unknown_ref_kind_or_type(derived_registry):
    register_derived("dummy_recap", ["live_segment"])
    bad = SimpleNamespace(derived_type="dummy_recap", derived_sources=[_src("journal_entry", PUBLIC)])
    with pytest.raises(ValueError, match="journal_entry"):
        audience_of(bad)
    with pytest.raises(ValueError):
        audience_of(SimpleNamespace(derived_type="never_registered", derived_sources=[]))
    with pytest.raises(ValueError):
        register_derived("dummy_recap", ["live_segment"])
    with pytest.raises(ValueError):
        register_derived("empty", [])


# ── audience_of on registered rows (no DB) ─────────────────────────────────

def test_audience_of_rows():
    cid = uuid.uuid4()
    entry = JournalEntry(user_id=A, campaign_id=cid, shorthand="s", narrative="n", entry_hash="h",
                         kind="player", visibility="party")
    assert audience_of(entry) == MEMBERS
    assert audience_of(ChatSession(user_id=A, campaign_id=cid, title="t")) == OA
    assert audience_of(NpcEntry(user_id=A, campaign_id=cid, name="n")) == GM_AUDIENCE
    assert audience_of(Campaign(user_id=A, name="c")) == PUBLIC
    jt = JournalTag(journal_id=uuid.uuid4(), tag_id=uuid.uuid4(), source_field="shorthand")
    assert audience_of(jt, parents=[PUBLIC]) == GM_AUDIENCE
    jt.source_field = None
    assert audience_of(jt, parents=[entry]) == MEMBERS
    with pytest.raises(ValueError):
        audience_of(jt)  # no relationship to the entry: parents= is required
    tag = Tag(name="x")
    assert audience_of(tag, parents=[MEMBERS, GM_AUDIENCE]) == AnyOf([MEMBERS, GM_AUDIENCE])
    assert audience_of(tag, parents=[]) == AnyOf()
    doc = SourceDocument(user_id=A, campaign_id=cid, title="t", filename="f", visibility="gm")
    chunk = SourceChunk(user_id=A, campaign_id=cid, chunk_index=0, content="c")
    chunk.document = doc
    assert audience_of(chunk) == GM_AUDIENCE
    assert audience_of(chunk, parents=[PUBLIC]) == PUBLIC
