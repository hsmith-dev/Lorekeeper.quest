"""E0-Access.3: the Audience lattice, the AD-12 mapping, the Mention formula,
the registry's shape and derived types; E0-Jobs.1: the jobs owner rule, the
stored_files `derived_from_sources` class and the global always_gm models.
Pure: no database."""
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
    Campaign, CampaignMember, CampaignShareToken, CharacterSheet, CharacterSheetTemplate, ChatSession,
    DataBackfill, DerivedSource, Feedback, Job, JournalEntry, JournalTag, NpcEntry, Quest, SessionPlan,
    ShorthandTerm, SourceChunk, SourceDocument, StoredFile, Tag, TagCategory,
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
        Job: reg.AlwaysGM, StoredFile: reg.DerivedFromSources, DerivedSource: reg.AlwaysGM,
        DataBackfill: reg.AlwaysGM,
    }
    assert {m: type(r) for m, r in REGISTRY.items()} == expect
    assert REGISTRY[Job].owner_field == "created_by"
    assert REGISTRY[DerivedSource].owner_field is REGISTRY[DataBackfill].owner_field is None
    assert REGISTRY[NpcEntry].owner_field is None
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


@pytest.mark.parametrize("args", [
    (AnyOf([PUBLIC]),),               # first position, not only later ones
    (AnyOf([PUBLIC]), PUBLIC),
    (PUBLIC, AnyOf([PUBLIC])),
    ("public",),                      # a bare str is not iterated char by char
    ([PUBLIC, "gm"],),
    ([AnyOf([GM_AUDIENCE])],),
    (None,),
    (3,),
])
def test_most_restrictive_rejects_non_audiences(args):
    with pytest.raises(TypeError):
        most_restrictive(*args)


@pytest.mark.parametrize("entry, error", [
    ({"derived_type": "bad_str", "derive_from": "live_segment"}, TypeError),
    ({"derived_type": "no_from"}, ValueError),
    ({"derive_from": ["live_segment"]}, ValueError),
    ({"derived_type": "empty_list", "derive_from": []}, ValueError),
    ({"derived_type": "bad_kind", "derive_from": [3]}, TypeError),
    ({"derived_type": "", "derive_from": ["x"]}, TypeError),
    ("not-an-entry", TypeError),
])
def test_malformed_derived_registry_entries_fail_clearly(derived_registry, entry, error):
    derived_registry.append(entry)
    with pytest.raises(error):
        audience_of(SimpleNamespace(derived_type="anything", derived_sources=[]))


def test_register_derived_rejects_a_bare_str(derived_registry):
    with pytest.raises(TypeError):
        register_derived("recap", "live_segment")
    with pytest.raises(TypeError):
        register_derived("recap", [None])
    assert derived_registry == []


# ── E0-Jobs.1: jobs, stored_files and the global always_gm models ───────────

def test_job_owner_rule():
    cid = uuid.uuid4()
    assert audience_of(Job(campaign_id=cid, created_by=A)) == OA
    assert audience_of(Job(campaign_id=cid, created_by=None)) == GM_AUDIENCE
    gm, p = _gm(cid), _player(cid, A)
    assert _sql(scoped_select(Job, gm)).rstrip().endswith(f"jobs.campaign_id = '{cid}'")
    assert f"jobs.created_by = '{A}'" in _sql(scoped_select(Job, p))
    for reduced in (audience_ctx(cid, MEMBER_VIEW, by=gm), audience_ctx(cid, ANON_VIEW, by=gm)):
        assert _sql(scoped_select(Job, reduced)).rstrip().lower().endswith("false")


@pytest.mark.parametrize("model", [DerivedSource, DataBackfill])
def test_global_always_gm_models_are_refused_by_scoped_select(model):
    cid = uuid.uuid4()
    assert reg.scope_column(model) is None
    for ctx in (_gm(cid), _player(cid)):
        with pytest.raises(UnregisteredModel, match="no Campaign scope"):
            scoped_select(model, ctx)
    with pytest.raises(TypeError):
        scoped_select_multi(model, {cid: "gm"})
    row = DerivedSource(derived_type="x", derived_id=A, ref_kind="journal", ref_id=B) if model is DerivedSource \
        else DataBackfill(name="suggested_mentions_v1")
    assert audience_of(row) == GM_AUDIENCE


def test_completeness_check_accepts_only_always_gm_without_a_campaign_scope(monkeypatch):
    reg._check_complete()
    monkeypatch.setitem(reg.REGISTRY, DataBackfill, reg.stored())
    with pytest.raises(RuntimeError, match="DataBackfill has no Campaign scope"):
        reg._check_complete()
    monkeypatch.setitem(reg.REGISTRY, DataBackfill, reg.membership(PUBLIC))
    with pytest.raises(RuntimeError, match="DataBackfill"):
        reg._check_complete()


@pytest.fixture
def file_types(derived_registry):
    register_derived("test_file", ["journal", "test_unmodelled"])
    register_derived("test_entity_file", ["test_entity"])
    return derived_registry


CID = uuid.uuid4()


def _file(kind="test_file", *, stale=False, owner_id=None, campaign_id=CID) -> StoredFile:
    return StoredFile(id=uuid.uuid4(), campaign_id=campaign_id, kind=kind, storage_key="k", content_type="t",
                      size=1, sha256="0" * 64, stale=stale, audience_owner_id=owner_id)


def _entry(vis="party", kind="gm", author=A, campaign_id=CID) -> JournalEntry:
    return JournalEntry(id=uuid.uuid4(), user_id=author, campaign_id=campaign_id, shorthand="s", narrative="n",
                        entry_hash="h", kind=kind, visibility=vis)


def _pair(f, ref, *, ref_kind="journal", ref_field=None, ref_id=None):
    ds = DerivedSource(derived_type=f.kind, derived_id=f.id, ref_kind=ref_kind,
                       ref_id=ref_id or (ref.id if ref is not None else uuid.uuid4()), ref_field=ref_field)
    return (ds, ref)


def test_file_audience_matrix(file_types):
    f = _file()
    party, private_a, gm_entry = _entry(), _entry("private"), _entry("gm")
    # every source visible: the most restrictive of them
    assert audience_of(f, parents=[_pair(f, party)]) == PUBLIC
    assert audience_of(f, parents=[_pair(f, party), _pair(f, private_a)]) == OA
    assert audience_of(f, parents=[_pair(f, party), _pair(f, _entry(kind="player"))]) == MEMBERS
    # one hidden source hides it
    assert audience_of(f, parents=[_pair(f, party), _pair(f, gm_entry)]) == GM_AUDIENCE
    # no sources
    assert audience_of(f, parents=[]) == GM_AUDIENCE
    # unknown / unmodelled / disallowed ref_kind, missing or foreign source row
    assert audience_of(f, parents=[_pair(f, party, ref_kind="nope")]) == GM_AUDIENCE
    assert audience_of(f, parents=[_pair(f, party, ref_kind="test_unmodelled")]) == GM_AUDIENCE
    ef = _file("test_entity_file")
    assert audience_of(ef, parents=[_pair(ef, party)]) == GM_AUDIENCE
    assert audience_of(f, parents=[_pair(f, None)]) == GM_AUDIENCE
    assert audience_of(f, parents=[_pair(f, _entry(campaign_id=uuid.uuid4()))]) == GM_AUDIENCE
    assert audience_of(f, parents=[_pair(f, party, ref_id=uuid.uuid4())]) == GM_AUDIENCE
    # a GM ref_field
    assert audience_of(f, parents=[_pair(f, party, ref_field="shorthand")]) == GM_AUDIENCE
    assert audience_of(f, parents=[_pair(f, party, ref_field="narrative")]) == PUBLIC
    # stale; unregistered kind
    stale = _file(stale=True)
    assert audience_of(stale, parents=[_pair(stale, party)]) == GM_AUDIENCE
    unreg = _file("never_registered")
    assert audience_of(unreg, parents=[_pair(unreg, party)]) == GM_AUDIENCE
    # audience_owner_id: self, or another owner
    mine = _file(owner_id=A)
    assert audience_of(mine, parents=[_pair(mine, party)]) == OA
    assert audience_of(mine, parents=[_pair(mine, _entry("private", author=B))]) == GM_AUDIENCE


def test_file_audience_needs_its_own_source_pairs(file_types):
    f, other = _file(), _file()
    with pytest.raises(ValueError, match="parents"):
        audience_of(f)
    with pytest.raises(ValueError, match="not a source"):
        audience_of(f, parents=[_pair(other, _entry())])
    with pytest.raises(TypeError):
        audience_of(f, parents=[_entry()])


def test_file_visible_clause_sql(file_types):
    gm, p = _gm(CID), _player(CID, A)
    assert "derived_sources" not in _sql(scoped_select(StoredFile, gm))
    sql = _sql(scoped_select(StoredFile, p))
    assert "NOT stored_files.stale" in sql
    assert "stored_files.kind IN ('test_file', 'test_entity_file')" in sql
    assert f"stored_files.audience_owner_id = '{A}'" in sql
    assert "ds.ref_kind = 'journal'" in sql and "test_unmodelled" not in sql
    assert f"journal_entries.campaign_id = '{CID}'" in sql and "'shorthand'" in sql
    member = _sql(scoped_select(StoredFile, audience_ctx(CID, MEMBER_VIEW, by=gm)))
    assert "stored_files.audience_owner_id IS NULL" in member and str(A) not in member


def test_register_source_kind(monkeypatch):
    monkeypatch.setattr(reg, "SOURCE_KIND_MODELS", dict(reg.SOURCE_KIND_MODELS))
    assert reg.SOURCE_KIND_MODELS == {"journal": JournalEntry}
    reg.register_source_kind("session_plan", SessionPlan)
    assert reg.SOURCE_KIND_MODELS["session_plan"] is SessionPlan
    with pytest.raises(ValueError, match="already"):
        reg.register_source_kind("journal", JournalEntry)
    for ref_kind, derived_model in (("tag", Tag), ("chunk", SourceChunk), ("journal_tag", JournalTag)):
        with pytest.raises(ValueError, match="derived"):  # its Audience needs its parents
            reg.register_source_kind(ref_kind, derived_model)
    with pytest.raises(ValueError):
        reg.register_source_kind("file", StoredFile)
    with pytest.raises(ValueError):
        reg.register_source_kind("backfill", DataBackfill)  # global
    with pytest.raises(UnregisteredModel):
        reg.register_source_kind("feedback", Feedback)
    with pytest.raises(TypeError):
        reg.register_source_kind("", JournalEntry)


def test_file_source_model_gm_fields_narrow_in_sql_and_python(monkeypatch, file_types):
    # A source model with its own GM-only field ("content", not an always-GM field).
    monkeypatch.setitem(reg.REGISTRY, SessionPlan, reg.stored(gm_fields=("content",)))
    monkeypatch.setattr(reg, "SOURCE_KIND_MODELS", dict(reg.SOURCE_KIND_MODELS))
    reg.register_source_kind("plan", SessionPlan)
    register_derived("test_plan_file", ["plan", "journal"])
    f = _file("test_plan_file")
    plan = SessionPlan(id=uuid.uuid4(), user_id=A, campaign_id=CID, title="t", content="c", visibility="party")
    assert audience_of(f, parents=[_pair(f, plan, ref_kind="plan", ref_field="title")]) == PUBLIC
    assert audience_of(f, parents=[_pair(f, plan, ref_kind="plan", ref_field="content")]) == GM_AUDIENCE
    assert audience_of(f, parents=[_pair(f, plan, ref_kind="plan", ref_field="shorthand")]) == GM_AUDIENCE
    # "content" is GM only for the plan branch, not for journal sources.
    assert audience_of(f, parents=[_pair(f, _entry(), ref_field="content")]) == PUBLIC
    sql = _sql(scoped_select(StoredFile, _player(CID, A)))
    journal_branch = sql.split("ds.ref_kind = 'journal'")[1].split("ds.ref_kind = 'plan'")[0]
    plan_branch = sql.split("ds.ref_kind = 'plan'")[1]
    assert "ds.ref_field NOT IN ('gm_notes', 'shorthand', 'voice_notes')" in journal_branch
    assert "ds.ref_field NOT IN ('content', 'gm_notes', 'shorthand', 'voice_notes')" in plan_branch
