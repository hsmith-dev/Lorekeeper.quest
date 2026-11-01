"""CI-11 (E0-Access.3): for every registered model, the SQL predicate and the
Python Audience agree.

For random rows and a pool of ctxs in Campaign A:

    row ∈ scoped_select(Model, ctx)  iff  row is in A and visible_to(audience_of(row), ctx)

Users and Campaigns A and B are created once per test (flushed, never
committed). Each hypothesis example inserts 1–4 random rows inside a
savepoint and rolls it back, so examples never see each other's rows.

The global models (no campaign_id: derived_sources, data_backfills) are
always_gm and refused by scoped_select, so they have no spec here;
tests/access/test_audience.py covers them. Stored files use test-only
derived types registered by the `file_types` fixture.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings, strategies as st

from app.access import (
    ANON_VIEW, DERIVED_REGISTRY, MEMBER_VIEW, REGISTRY, AnyOf, CampaignContext, as_user, audience_ctx, audience_of,
    ctx_for, register_derived, scoped_select, visible_to,
)
from app.access import registry as reg
from app.db.models import (
    Campaign, CampaignMember, CampaignShareToken, CharacterSheet, CharacterSheetTemplate, ChatSession,
    DataBackfill, DerivedSource, Genre, Job, JournalEntry, JournalTag, NpcEntry, Quest, SessionPlan, ShorthandTerm,
    SourceChunk, SourceDocument, StoredFile, Tag, TagCategory, User,
)
from app.domain.enums import CampaignRole, EntryKind, TagSourceField, Visibility

EXAMPLES = 200
SETTINGS = settings(
    max_examples=EXAMPLES, deadline=None, derandomize=False,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)

AUTHORS = ("owner", "co_gm", "p", "q")
SPARES = 4

campaigns = st.sampled_from(("a", "b"))
visibilities = st.sampled_from(list(Visibility))
kinds = st.sampled_from(list(EntryKind))
authors = st.sampled_from(AUTHORS)
source_fields = st.one_of(st.none(), st.sampled_from(list(TagSourceField)))


# Registered models with no Campaign scope: always_gm, refused by scoped_select.
GLOBAL_MODELS = {DerivedSource, DataBackfill}
CAMPAIGN_MODELS = [m for m in REGISTRY if m not in GLOBAL_MODELS]

# Test-only file types (the `file_types` fixture registers them): one that
# derives from journal entries and an unmodelled kind, one that does not
# derive from journal entries, and one that is never registered.
FILE_TYPES = {"prop_file": ["journal", "prop_unmodelled"], "prop_entity_file": ["prop_entity"]}
file_kinds = st.sampled_from([*FILE_TYPES, "prop_unregistered"])
ref_kinds = st.sampled_from(["journal", "prop_unmodelled", "prop_entity"])
ref_fields = st.sampled_from([None, "narrative", "shorthand", "gm_notes"])


def _uid() -> str:
    return uuid.uuid4().hex


@dataclass
class World:
    users: dict[str, User]
    spares: list[User]
    a: uuid.UUID
    b: uuid.UUID
    templates: dict[uuid.UUID, uuid.UUID]
    world_rows: dict[type, list[Any]]
    ctxs: dict[str, CampaignContext] = field(default_factory=dict)

    def cid(self, which: str | None) -> uuid.UUID | None:
        return None if which is None else (self.a if which == "a" else self.b)


def _user(label: str) -> User:
    return User(email=f"prop-{label}-{_uid()[:12]}@example.com", hashed_password="x", display_name=label,
                access_granted=True, access_source="promo")


@pytest_asyncio.fixture
async def world(db) -> World:
    users = {name: _user(name) for name in AUTHORS}
    spares = [_user(f"spare{i}") for i in range(SPARES)]
    db.add_all([*users.values(), *spares])
    await db.flush()
    a, b = uuid.uuid4(), uuid.uuid4()
    camp_a = Campaign(id=a, user_id=users["owner"].id, name="A", genre=Genre.fantasy)
    camp_b = Campaign(id=b, user_id=users["q"].id, name="B", genre=Genre.fantasy)
    db.add_all([camp_a, camp_b])
    await db.flush()
    members = [
        CampaignMember(campaign_id=a, user_id=users["co_gm"].id, role=CampaignRole.CO_GM),
        CampaignMember(campaign_id=a, user_id=users["p"].id, role=CampaignRole.PLAYER),
        CampaignMember(campaign_id=a, user_id=users["q"].id, role=CampaignRole.PLAYER),
    ]
    templates = {cid: CharacterSheetTemplate(campaign_id=cid, created_by_user_id=users["owner"].id, name="T",
                                             fields=[]) for cid in (a, b)}
    db.add_all([*members, *templates.values()])
    await db.flush()
    w = World(users, spares, a, b, {cid: t.id for cid, t in templates.items()},
              {Campaign: [camp_a, camp_b], CampaignMember: members,
               CharacterSheetTemplate: list(templates.values())})
    owner_ctx = await ctx_for(db, users["owner"].id, a)
    w.ctxs = {
        "owner": owner_ctx,
        "co_gm": await ctx_for(db, users["co_gm"].id, a),
        "p": await ctx_for(db, users["p"].id, a),
        "q": await ctx_for(db, users["q"].id, a),
        "member": audience_ctx(a, MEMBER_VIEW, by=owner_ctx),
        "anon": audience_ctx(a, ANON_VIEW, by=owner_ctx),
        "as_p": audience_ctx(a, as_user(users["p"].id), by=owner_ctx),
    }
    assert [c.role for c in w.ctxs.values()] == ["gm", "gm", "player", "player", "player", "anon", "player"]
    return w


# ── Row specs ──────────────────────────────────────────────────────────────

entry_spec = st.fixed_dictionaries({"campaign": campaigns, "visibility": visibilities, "kind": kinds,
                                    "author": authors})
stored_spec = st.fixed_dictionaries({"campaign": campaigns, "visibility": visibilities, "author": authors})

SPECS = {
    JournalEntry: entry_spec,
    CharacterSheet: stored_spec,
    SessionPlan: stored_spec,
    SourceDocument: stored_spec,
    ShorthandTerm: stored_spec,
    TagCategory: stored_spec,
    ChatSession: st.fixed_dictionaries({"campaign": st.one_of(st.none(), campaigns), "author": authors}),
    SourceChunk: st.fixed_dictionaries({"campaign": campaigns, "doc": stored_spec}),
    JournalTag: st.fixed_dictionaries({"entry": entry_spec, "source_field": source_fields}),
    Tag: st.fixed_dictionaries({"reach": st.lists(
        st.fixed_dictionaries({"entry": entry_spec, "source_field": source_fields}), min_size=0, max_size=3)}),
    NpcEntry: st.fixed_dictionaries({"campaign": campaigns, "author": authors}),
    Quest: st.fixed_dictionaries({"campaign": campaigns, "author": authors}),
    Campaign: st.fixed_dictionaries({"author": authors}),
    CampaignMember: st.fixed_dictionaries({"campaign": campaigns, "spare": st.integers(0, SPARES - 1)}),
    CampaignShareToken: st.fixed_dictionaries({"campaign": campaigns, "author": authors,
                                               "kind": st.sampled_from(("read_only", "collaborate"))}),
    CharacterSheetTemplate: st.fixed_dictionaries({"campaign": campaigns, "author": authors}),
    Job: st.fixed_dictionaries({"campaign": campaigns, "creator": st.one_of(st.none(), authors)}),
    StoredFile: st.fixed_dictionaries({
        "campaign": campaigns, "kind": file_kinds, "stale": st.booleans(),
        "owner": st.one_of(st.none(), authors),
        "sources": st.lists(st.fixed_dictionaries({
            "ref_kind": ref_kinds, "entry": entry_spec, "ref_field": ref_fields, "missing": st.booleans(),
        }), min_size=0, max_size=3),
    }),
}


def test_every_registered_model_has_a_spec():
    assert set(SPECS) == set(CAMPAIGN_MODELS)
    assert set(SPECS) | GLOBAL_MODELS == set(REGISTRY)


def test_global_models_are_the_unscoped_always_gm_ones():
    assert {m for m in REGISTRY if reg.scope_column(m) is None and not isinstance(REGISTRY[m], reg.Derived)} \
        == GLOBAL_MODELS
    assert all(isinstance(REGISTRY[m], reg.AlwaysGM) for m in GLOBAL_MODELS)


@pytest.fixture
def file_types():
    saved = list(DERIVED_REGISTRY)
    for name, derive_from in FILE_TYPES.items():
        register_derived(name, derive_from)
    yield
    DERIVED_REGISTRY[:] = saved


def _rows_strategy(model):
    spec = SPECS[model]
    if model is CampaignMember:  # unique (campaign, user)
        return st.lists(spec, min_size=1, max_size=4, unique_by=lambda s: (s["campaign"], s["spare"]))
    return st.lists(spec, min_size=1, max_size=4)


@dataclass
class Built:
    row: Any
    in_a: bool
    parents: Any = None


async def _entry(db, w: World, s: dict) -> JournalEntry:
    e = JournalEntry(user_id=w.users[s["author"]].id, campaign_id=w.cid(s["campaign"]), shorthand="s",
                     narrative="n", entry_hash=_uid(), kind=s["kind"], visibility=s["visibility"])
    db.add(e)
    await db.flush()
    return e


async def _build(db, w: World, model, s: dict) -> Built:
    """Insert one row (and its parents) for spec `s`; return it with the oracle inputs."""
    uid = w.users[s["author"]].id if "author" in s else None
    cid = w.cid(s.get("campaign")) if "campaign" in s else None
    if model is JournalEntry:
        e = await _entry(db, w, s)
        return Built(e, cid == w.a)
    simple = {
        SessionPlan: lambda: SessionPlan(user_id=uid, campaign_id=cid, title="t", content="c",
                                         visibility=s["visibility"]),
        SourceDocument: lambda: SourceDocument(user_id=uid, campaign_id=cid, title="t", filename="f",
                                               visibility=s["visibility"]),
        ShorthandTerm: lambda: ShorthandTerm(user_id=uid, campaign_id=cid, term="t", meaning="m",
                                             visibility=s["visibility"]),
        TagCategory: lambda: TagCategory(created_by_user_id=uid, campaign_id=cid, name=_uid(),
                                         visibility=s["visibility"]),
        CharacterSheet: lambda: CharacterSheet(created_by_user_id=uid, campaign_id=cid, template_id=w.templates[cid],
                                               name="n", data={}, visibility=s["visibility"]),
        ChatSession: lambda: ChatSession(user_id=uid, campaign_id=cid, title="t", messages=[], message_count=0),
        NpcEntry: lambda: NpcEntry(user_id=uid, campaign_id=cid, name="n"),
        Quest: lambda: Quest(user_id=uid, campaign_id=cid, title="t"),
        Campaign: lambda: Campaign(user_id=uid, name="c", genre=Genre.fantasy),
        CampaignMember: lambda: CampaignMember(campaign_id=cid, user_id=w.spares[s["spare"]].id,
                                               role=CampaignRole.PLAYER),
        CampaignShareToken: lambda: CampaignShareToken(campaign_id=cid, created_by_user_id=uid, token=_uid(),
                                                       kind=s["kind"]),
        CharacterSheetTemplate: lambda: CharacterSheetTemplate(campaign_id=cid, created_by_user_id=uid, name="t",
                                                               fields=[]),
    }
    if model is Job:
        creator = w.users[s["creator"]].id if s["creator"] else None
        job = Job(campaign_id=cid, kind="system.noop", queue="interactive", idempotency_key=_uid(),
                  ctx_kind="user", ctx_user_id=creator, created_by=creator)
        db.add(job)
        await db.flush()
        return Built(job, cid == w.a)
    if model is StoredFile:
        f = StoredFile(id=uuid.uuid4(), campaign_id=cid, kind=s["kind"], storage_key=_uid(),
                       content_type="application/pdf", size=1, sha256="0" * 64, stale=s["stale"],
                       audience_owner_id=w.users[s["owner"]].id if s["owner"] else None)
        db.add(f)
        await db.flush()
        pairs = []
        for src in s["sources"]:
            e = await _entry(db, w, src["entry"])
            ds = DerivedSource(derived_type=f.kind, derived_id=f.id, ref_kind=src["ref_kind"],
                               ref_id=uuid.uuid4() if src["missing"] else e.id, ref_field=src["ref_field"])
            db.add(ds)
            pairs.append((ds, None if src["missing"] else e))
        await db.flush()
        return Built(f, cid == w.a, pairs)
    if model in simple:
        row = simple[model]()
        db.add(row)
        await db.flush()
        in_a = (row.id == w.a) if model is Campaign else (cid == w.a)
        return Built(row, in_a)
    if model is SourceChunk:
        d = s["doc"]
        doc = SourceDocument(user_id=w.users[d["author"]].id, campaign_id=w.cid(d["campaign"]), title="t",
                             filename="f", visibility=d["visibility"])
        db.add(doc)
        await db.flush()
        chunk = SourceChunk(source_document_id=doc.id, user_id=doc.user_id, campaign_id=cid, chunk_index=0,
                            content="c")
        db.add(chunk)
        await db.flush()
        return Built(chunk, cid == w.a and doc.campaign_id == w.a, [doc])
    if model is JournalTag:
        e = await _entry(db, w, s["entry"])
        tag = Tag(name=_uid())
        db.add(tag)
        await db.flush()
        jt = JournalTag(journal_id=e.id, tag_id=tag.id, source_field=s["source_field"])
        db.add(jt)
        await db.flush()
        return Built(jt, e.campaign_id == w.a, [e])
    if model is Tag:
        tag = Tag(name=_uid())
        db.add(tag)
        await db.flush()
        reach = []
        for r in s["reach"]:
            e = await _entry(db, w, r["entry"])
            jt = JournalTag(journal_id=e.id, tag_id=tag.id, source_field=r["source_field"])
            db.add(jt)
            await db.flush()
            if e.campaign_id == w.a:  # the tag's Audience in A: any-of its journal_tags in A
                reach.append(audience_of(jt, parents=[e]))
        return Built(tag, True, reach)
    raise AssertionError(f"no builder for {model.__name__}")  # pragma: no cover


def _pk(model, row):
    if model is JournalTag:
        return (row.journal_id, row.tag_id)
    return row.id


async def _check(db, w: World, model, built: list[Built]) -> None:
    candidates = list(built) + [Built(r, (r.id == w.a) if model is Campaign else (r.campaign_id == w.a))
                                for r in w.world_rows.get(model, [])]
    for name, ctx in w.ctxs.items():
        expected = set()
        for b in candidates:
            aud = audience_of(b.row, parents=b.parents) if b.parents is not None else audience_of(b.row)
            if b.in_a and visible_to(aud, ctx):
                expected.add(_pk(model, b.row))
        got = {_pk(model, r) for r in (await db.execute(scoped_select(model, ctx))).scalars().all()}
        assert got == expected, (
            f"{model.__name__} for ctx {name!r}: SQL-only {got - expected}, Python-only {expected - got}; "
            f"rows: {[(_pk(model, b.row), b.in_a, b.parents) for b in candidates]}"
        )


@pytest.mark.parametrize("model", CAMPAIGN_MODELS, ids=lambda m: m.__tablename__)
@SETTINGS
@given(data=st.data())
async def test_visible_clause_agrees_with_audience_of(db, world, file_types, model, data):
    specs = data.draw(_rows_strategy(model), label="rows")
    sp = await db.begin_nested()
    try:
        built = [await _build(db, world, model, s) for s in specs]
        await _check(db, world, model, built)
    finally:
        await sp.rollback()


def test_anyof_is_used_for_tags_only():
    """A sanity pin on the oracle: only `reached_through` models produce AnyOf."""
    assert isinstance(audience_of(Tag(name="x"), parents=[]), AnyOf)
