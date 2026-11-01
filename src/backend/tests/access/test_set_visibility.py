"""E0-Access.9: set_visibility, the only Visibility writer.

Who may change Visibility (a writable GM user ctx only, every other ctx the
one 404), which refs are valid, the always-GM 422s, the field paths, the
registry `writer` slot, the order of work (write, stale markers, commit,
listeners, cache invalidation), rollback, and the bulk route.
"""
from __future__ import annotations

import fnmatch
import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy import event

import app.access.visibility as vis
from app.access import (
    ANON_VIEW, MEMBER_VIEW, PREVIEW_HEADER, REGISTRY, NotFound, VisibilityError, audience_ctx, ctx_for,
    mark_dependents_stale, register_visibility_kind, scoped_get, set_visibility, set_visibility_many, stored,
)
from app.db.models import CharacterSheet, JournalEntry
from app.db.models.session_plan import SessionPlan
from app.domain.enums import Visibility
from app.schemas.journal import JournalGMResponse
from app.schemas.sources import RecordRef, SourceKind, SourceRef
from app.schemas.visibility import VISIBILITY_KINDS
from tests.ev4.fixtures import ev4, mint_canary  # noqa: F401  (ev4 registers the fixture)

NOT_FOUND = {"detail": "Not found"}
ALWAYS_GM = {"detail": "This is always GM-only", "code": "always_gm"}
MISSING = uuid.UUID("00000000-0000-4000-8000-000000000000")


# ── Helpers ────────────────────────────────────────────────────────────────

async def _entry(db, campaign_id, author, *, visibility="party", kind="gm") -> JournalEntry:
    e = JournalEntry(user_id=author, campaign_id=campaign_id, shorthand="s", narrative=f"Plain {uuid.uuid4().hex}",
                     entry_hash=uuid.uuid4().hex, session_date=date(2026, 5, 1), visibility=visibility, kind=kind)
    db.add(e)
    await db.flush()
    return e


async def _plan(db, campaign_id, author, *, visibility="party") -> SessionPlan:
    p = SessionPlan(user_id=author, campaign_id=campaign_id, title="Plan", content="c", visibility=visibility)
    db.add(p)
    await db.flush()
    return p


async def _stored_visibility(db, model, row_id) -> str:
    return (await db.execute(sa.select(model.visibility).where(model.id == row_id))).scalar_one()


@pytest.fixture
async def gm(ev4, db):
    return await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)


@pytest.fixture
def recorder(monkeypatch):
    """No other marker or listener; records the order of work."""
    calls: list = []

    async def marker(db, ref):
        calls.append(("marker", ref))

    async def listener(campaign_id, refs, ctx):
        calls.append(("listener", campaign_id, tuple(refs), ctx.user_id))

    async def cache(campaign_id):
        calls.append(("cache", campaign_id))

    monkeypatch.setattr(vis, "_STALE_MARKERS", [marker])
    monkeypatch.setattr(vis, "_LISTENERS", [listener])
    monkeypatch.setattr(vis, "invalidate_campaign_cache", cache)
    return calls


def _watch(db, calls: list) -> None:
    """Record a flushed Visibility change as "write" and the commit as "commit"."""
    sync = db.sync_session

    def after_flush(session, ctx):
        if any(isinstance(o, (JournalEntry, SessionPlan)) for o in session.dirty):
            calls.append(("write",))

    def before_commit(session):
        if not session.in_nested_transaction():  # a savepoint release is not the commit
            calls.append(("commit",))

    event.listen(sync, "after_flush", after_flush)
    event.listen(sync, "before_commit", before_commit)


# ── The single writer ──────────────────────────────────────────────────────

async def test_gm_hides_a_party_entry_and_gets_the_gm_body(db, ev4, gm, recorder):
    a = ev4.a.campaign_id
    entry = await _entry(db, a, ev4.a.owner_id)
    player = await ctx_for(db, (await ev4.actor("player")).user_id, a)
    await db.commit()
    assert (await scoped_get(db, JournalEntry, player, entry.id)).id == entry.id

    body = await set_visibility(db, gm, RecordRef(kind="journal", id=entry.id), Visibility.GM)
    assert isinstance(body, JournalGMResponse) and body.id == entry.id and body.shorthand == "s"
    ref = RecordRef(kind="journal", id=entry.id)
    assert recorder == [("marker", ref)]
    await db.commit()
    assert recorder[1:] == [("listener", a, (ref,), gm.user_id), ("cache", a)]
    assert await _stored_visibility(db, JournalEntry, entry.id) == Visibility.GM
    with pytest.raises(NotFound):
        await scoped_get(db, JournalEntry, player, entry.id)


async def test_order_is_write_marker_commit_listener_cache(db, ev4, gm, recorder):
    a = ev4.a.campaign_id
    entries = [await _entry(db, a, ev4.a.owner_id) for _ in range(2)]
    await db.commit()
    _watch(db, recorder)
    refs = [RecordRef(kind="journal", id=e.id) for e in entries]
    assert await set_visibility_many(db, gm, refs, "gm") == 2
    await db.commit()
    kinds = [c[0] for c in recorder]
    assert kinds == ["write", "marker", "write", "marker", "commit", "listener", "cache"], recorder
    assert recorder[-2] == ("listener", a, tuple(refs), gm.user_id)  # once per Campaign, every ref


async def test_with_no_marker_or_listener_the_change_still_commits(db, ev4, gm, monkeypatch):
    monkeypatch.setattr(vis, "_STALE_MARKERS", [])
    monkeypatch.setattr(vis, "_LISTENERS", [])
    plan = await _plan(db, ev4.a.campaign_id, ev4.a.owner_id)
    await db.commit()
    await set_visibility(db, gm, RecordRef(kind="session_plan", id=plan.id), "private")
    await db.commit()
    assert await _stored_visibility(db, SessionPlan, plan.id) == Visibility.PRIVATE


async def test_a_source_ref_works_and_a_mapping_too(db, ev4, gm, recorder):
    a = ev4.a.campaign_id
    entry = await _entry(db, a, ev4.a.owner_id)
    await db.commit()
    await set_visibility(db, gm, SourceRef(kind=SourceKind.JOURNAL, id=entry.id), Visibility.GM)
    await set_visibility(db, gm, {"kind": "journal", "id": str(entry.id)}, Visibility.PARTY)
    await db.commit()
    assert await _stored_visibility(db, JournalEntry, entry.id) == Visibility.PARTY


async def test_mark_dependents_stale_runs_markers_in_order_in_the_transaction(db, monkeypatch):
    seen = []
    monkeypatch.setattr(vis, "_STALE_MARKERS", [])
    first = vis.register_stale_marker(lambda db_, ref: seen.append(("first", ref)))

    async def second(db_, ref):
        assert db_ is db
        seen.append(("second", ref))

    vis.register_stale_marker(second)
    vis.register_stale_marker(first)  # a no-op
    refs = [RecordRef(kind="journal", id=uuid.uuid4()), RecordRef(kind="journal", id=uuid.uuid4())]
    await mark_dependents_stale(db, refs)
    assert seen == [("first", refs[0]), ("second", refs[0]), ("first", refs[1]), ("second", refs[1])]


# ── The writer slot ────────────────────────────────────────────────────────

async def test_a_registered_writer_is_called_instead_of_the_column(db, ev4, gm, monkeypatch, recorder):
    calls = []

    async def writer(db_, ctx, row, field, value):
        calls.append((ctx.user_id, row.id, field, value))

    monkeypatch.setitem(REGISTRY, SessionPlan, stored(writer=writer))
    plan = await _plan(db, ev4.a.campaign_id, ev4.a.owner_id)
    await db.commit()
    body = await set_visibility(db, gm, RecordRef(kind="session_plan", id=plan.id), Visibility.GM)
    assert body.id == plan.id
    await db.commit()
    assert calls == [(gm.user_id, plan.id, "visibility", Visibility.GM)]
    assert await _stored_visibility(db, SessionPlan, plan.id) == Visibility.PARTY  # not written directly
    assert [c[0] for c in recorder] == ["marker", "listener", "cache"]


async def test_field_visibility_assigns_a_new_dict_and_tells_the_writer_the_path(db, ev4, gm, monkeypatch):
    a = ev4.a.campaign_id
    sheet = CharacterSheet(campaign_id=a, template_id=ev4.a.ids["character_sheet_templates"][0],
                           created_by_user_id=ev4.a.owner_id, name="Sheet", data={"hp": "party"})
    db.add(sheet)
    await db.commit()
    before = sheet.data
    monkeypatch.setitem(REGISTRY, CharacterSheet, stored(owner_field="created_by_user_id", field_visibility="data"))
    await set_visibility(db, gm, RecordRef(kind="character_sheet", id=sheet.id, field="name"), Visibility.GM)
    await db.commit()
    stored_data = (await db.execute(sa.select(CharacterSheet.data).where(CharacterSheet.id == sheet.id))).scalar_one()
    assert stored_data == {"hp": "party", "name": "gm"} and before == {"hp": "party"}
    assert await _stored_visibility(db, CharacterSheet, sheet.id) == Visibility.PARTY  # the row is unchanged

    paths = []
    monkeypatch.setitem(REGISTRY, CharacterSheet, stored(
        owner_field="created_by_user_id", field_visibility="data",
        writer=lambda db_, ctx, row, field, value: paths.append(field)))
    await set_visibility(db, gm, RecordRef(kind="character_sheet", id=sheet.id), "gm", field="name")
    assert paths == ["field_visibility.name"]


def test_field_path_resolution():
    cols = {"id", "visibility", "visibility_floor", "title", "field_visibility", "gm_notes", "secret"}
    with_fields = stored(field_visibility="field_visibility", gm_fields=("secret",))
    plain = stored()
    assert vis.field_path(cols, with_fields, None) == "visibility"
    assert vis.field_path(cols, with_fields, "visibility") == "visibility"
    assert vis.field_path(cols, with_fields, "visibility_floor") == "visibility_floor"
    assert vis.field_path(cols, plain, "visibility_floor") == "visibility_floor"
    assert vis.field_path(cols, with_fields, "title") == "field_visibility.title"
    for field in ("gm_notes", "shorthand", "voice_notes", "secret"):
        with pytest.raises(VisibilityError) as err:
            vis.field_path(cols, with_fields, field)
        assert err.value.code == "always_gm"
    with pytest.raises(VisibilityError) as err:
        vis.field_path(cols, plain, "title")
    assert err.value.code == "no_field_visibility"
    with pytest.raises(VisibilityError) as err:
        vis.field_path(cols - {"visibility_floor"}, plain, "visibility_floor")
    assert err.value.code == "no_field_visibility"
    for field in ("nope", "field_visibility"):
        with pytest.raises(VisibilityError) as err:
            vis.field_path(cols, with_fields, field)
        assert err.value.code == "unknown_field"


# ── Denials ────────────────────────────────────────────────────────────────

async def test_every_ctx_but_a_writable_gm_gets_not_found(db, ev4, gm, recorder):
    a = ev4.a.campaign_id
    entry = await _entry(db, a, ev4.a.owner_id)
    await db.commit()
    player = await ctx_for(db, (await ev4.actor("player")).user_id, a)
    co_gm = await ctx_for(db, (await ev4.actor("co_gm")).user_id, a)
    denied = [player, audience_ctx(a, ANON_VIEW, by=gm), audience_ctx(a, MEMBER_VIEW, by=gm),
              gm.as_system("merge")]
    ref = RecordRef(kind="journal", id=entry.id)
    for ctx in denied:
        with pytest.raises(NotFound):
            await set_visibility(db, ctx, ref, "gm")
        with pytest.raises(NotFound):
            await set_visibility_many(db, ctx, [ref], "gm")
        # Even a ref that would be 422 for a GM is the one 404.
        with pytest.raises(NotFound):
            await set_visibility(db, ctx, RecordRef(kind="npc", id=ev4.a.ids["npcs"][0]), "gm")
    assert recorder == []
    await set_visibility(db, co_gm, ref, "gm")  # a Co-GM may
    await db.commit()
    assert await _stored_visibility(db, JournalEntry, entry.id) == Visibility.GM


async def test_missing_other_campaign_wrong_kind_and_unknown_kind_are_not_found(db, ev4, gm, recorder):
    a = ev4.a.campaign_id
    other = await ev4.actor("cross_gm_player")  # owns Campaign B
    b_entry = await _entry(db, ev4.b.campaign_id, other.user_id)
    gm_kind = await _entry(db, a, ev4.a.owner_id)
    player_kind = await _entry(db, a, (await ev4.actor("player")).user_id, kind="player", visibility="private")
    await db.commit()
    for ref in (RecordRef(kind="journal", id=MISSING), RecordRef(kind="journal", id=b_entry.id),
                RecordRef(kind="player_journal", id=gm_kind.id), RecordRef(kind="journal", id=player_kind.id),
                RecordRef(kind="no_such_kind", id=gm_kind.id), RecordRef(kind="session_plan", id=gm_kind.id)):
        with pytest.raises(NotFound):
            await set_visibility(db, gm, ref, "gm")
    assert recorder == []
    await set_visibility(db, gm, RecordRef(kind="player_journal", id=player_kind.id), "party")
    await db.commit()
    assert await _stored_visibility(db, JournalEntry, player_kind.id) == Visibility.PARTY
    assert await _stored_visibility(db, JournalEntry, b_entry.id) == Visibility.PARTY


async def test_always_gm_models_and_fields_are_422(db, ev4, gm):
    entry = await _entry(db, ev4.a.campaign_id, ev4.a.owner_id)
    await db.commit()
    for ref in (RecordRef(kind="npc", id=ev4.a.ids["npcs"][0]), RecordRef(kind="quest", id=ev4.a.ids["quests"][0]),
                RecordRef(kind="journal", id=entry.id, field="shorthand"),
                RecordRef(kind="journal", id=entry.id, field="gm_notes")):
        with pytest.raises(VisibilityError) as err:
            await set_visibility(db, gm, ref, "party")
        assert (err.value.status_code, err.value.code, err.value.detail) == (422, "always_gm", "This is always GM-only")
    with pytest.raises(VisibilityError) as err:
        await set_visibility(db, gm, RecordRef(kind="journal", id=entry.id), "gm", field="narrative")
    assert err.value.code == "no_field_visibility"


def test_kinds_are_registered_for_the_schema_and_cannot_be_rebound():
    assert {"journal", "player_journal", "session_plan", "npc", "quest"} <= set(vis.visibility_kinds())
    assert set(vis.visibility_kinds()) <= VISIBILITY_KINDS
    assert register_visibility_kind("session_plan", SessionPlan) is vis._KINDS["session_plan"]  # no-op
    with pytest.raises(ValueError):
        register_visibility_kind("session_plan", JournalEntry)


def test_bulk_dedupes_on_the_write_target_not_the_raw_ref():
    a, b = uuid.uuid4(), uuid.uuid4()
    refs = [RecordRef(kind="journal", id=a), RecordRef(kind="journal", id=a, field="visibility"),
            SourceRef(kind=SourceKind.JOURNAL, id=a), SourceRef(kind=SourceKind.JOURNAL, id=a, span=(0, 3)),
            {"kind": "journal", "id": str(a)}, RecordRef(kind="journal", id=b)]
    assert [(r.kind, r.id) for r in vis.dedupe_targets(refs)] == [("journal", a), ("journal", b)]
    with pytest.raises(VisibilityError):
        vis.dedupe_targets([RecordRef(kind="journal", id=a, field="shorthand")])


def test_no_create_or_update_schema_declares_a_visibility_column():
    """Routes apply an Update body with `setattr(row, field, value)` loops: a
    Visibility field on one would write the column outside set_visibility.
    No Create schema declares one either today (a create keeps its default),
    so both are checked."""
    import importlib
    import inspect
    import pkgutil

    from pydantic import BaseModel

    import app.schemas

    columns = {"visibility", "visibility_floor", "field_visibility"}
    assert vis._KINDS  # every kind's model is written only through set_visibility
    checked, offenders = 0, []
    for info in pkgutil.walk_packages(app.schemas.__path__, "app.schemas."):
        module = importlib.import_module(info.name)
        for name, obj in vars(module).items():
            if not (inspect.isclass(obj) and issubclass(obj, BaseModel) and obj.__module__ == module.__name__):
                continue
            if not (name.endswith("Update") or name.endswith("Create")):
                continue
            checked += 1
            bad = columns & set(obj.model_fields)
            if bad:
                offenders.append(f"{module.__name__}.{name}: {sorted(bad)}")
    assert checked, "found no Create/Update schemas to check"
    assert not offenders, offenders


# ── Rollback ───────────────────────────────────────────────────────────────

async def test_bulk_is_all_or_nothing(db, ev4, gm, recorder):
    a = ev4.a.campaign_id
    entries = [await _entry(db, a, ev4.a.owner_id) for _ in range(2)]
    await db.commit()
    ids = [e.id for e in entries]  # rows expire on rollback; keep the ids
    refs = [RecordRef(kind="journal", id=i) for i in ids]
    with pytest.raises(NotFound):
        await set_visibility_many(db, gm, [*refs, RecordRef(kind="journal", id=MISSING)], "gm")
    with pytest.raises(VisibilityError):
        await set_visibility_many(db, gm, [*refs, RecordRef(kind="npc", id=ev4.a.ids["npcs"][0])], "gm")
    await db.commit()
    for entry_id in ids:
        assert await _stored_visibility(db, JournalEntry, entry_id) == Visibility.PARTY
    assert [c[0] for c in recorder if c[0] != "marker"] == []  # nothing dispatched for the failed savepoint


async def test_rollback_discards_listeners_and_cache(db, ev4, gm, recorder):
    entry = await _entry(db, ev4.a.campaign_id, ev4.a.owner_id)
    await db.commit()
    entry_id = entry.id  # rows expire on rollback
    await set_visibility(db, gm, RecordRef(kind="journal", id=entry_id), "gm")
    await db.rollback()
    await db.commit()
    assert [c[0] for c in recorder] == ["marker"]
    assert await _stored_visibility(db, JournalEntry, entry_id) == Visibility.PARTY


async def test_a_rolled_back_savepoint_drops_only_its_changes(db, ev4, gm, recorder):
    a = ev4.a.campaign_id
    kept, dropped = await _entry(db, a, ev4.a.owner_id), await _entry(db, a, ev4.a.owner_id)
    await db.commit()
    kept_id, dropped_id = kept.id, dropped.id  # rows expire on rollback
    await set_visibility(db, gm, RecordRef(kind="journal", id=kept_id), "gm")
    savepoint = await db.begin_nested()
    await set_visibility(db, gm, RecordRef(kind="journal", id=dropped_id), "gm")
    await savepoint.rollback()
    await db.commit()
    listened = [c for c in recorder if c[0] == "listener"]
    assert listened == [("listener", a, (RecordRef(kind="journal", id=kept_id),), gm.user_id)]
    assert await _stored_visibility(db, JournalEntry, dropped_id) == Visibility.PARTY


async def test_a_failing_listener_is_logged_and_the_cache_still_goes(db, ev4, gm, monkeypatch, caplog):
    seen = []

    def bad(campaign_id, refs, ctx):
        raise RuntimeError("boom")

    async def cache(campaign_id):
        seen.append(campaign_id)

    monkeypatch.setattr(vis, "_STALE_MARKERS", [])
    monkeypatch.setattr(vis, "_LISTENERS", [bad])
    monkeypatch.setattr(vis, "invalidate_campaign_cache", cache)
    entry = await _entry(db, ev4.a.campaign_id, ev4.a.owner_id)
    await db.commit()
    await set_visibility(db, gm, RecordRef(kind="journal", id=entry.id), "gm")
    await db.commit()  # does not raise
    assert seen == [ev4.a.campaign_id]
    assert "visibility_listener_failed" in caplog.text


# ── Cache invalidation ─────────────────────────────────────────────────────

class _FakeValkey:
    def __init__(self, keys, fail=False):
        self.keys = set(keys)
        self.fail = fail

    async def scan_iter(self, match, count):
        if self.fail:
            raise ConnectionError("down")
        for key in sorted(self.keys):
            if fnmatch.fnmatchcase(key, match):
                yield key

    async def unlink(self, *keys):
        self.keys -= set(keys)


async def test_invalidate_deletes_only_that_campaigns_keys(monkeypatch, caplog):
    from app.core import valkey_client

    cid, other = uuid.uuid4(), uuid.uuid4()
    fake = _FakeValkey({f"cache:{cid}:journals:gm:0", f"cache:{cid}:x", f"cache:{other}:x", "llm_gate:x"})
    monkeypatch.setattr(valkey_client, "_valkey", fake)
    await vis.invalidate_campaign_cache(cid)
    assert fake.keys == {f"cache:{other}:x", "llm_gate:x"}
    monkeypatch.setattr(valkey_client, "_valkey", _FakeValkey({f"cache:{cid}:x"}, fail=True))
    await vis.invalidate_campaign_cache(cid)  # logged, not raised
    assert "visibility_cache_invalidate_failed" in caplog.text
    monkeypatch.setattr(valkey_client, "_valkey", None)
    await vis.invalidate_campaign_cache(cid)  # no client: nothing cached


# ── The bulk route ─────────────────────────────────────────────────────────

def _url(campaign_id) -> str:
    return f"/api/campaigns/{campaign_id}/visibility"


def _items(*rows, kind="journal", **extra):
    return [{"kind": kind, "id": str(r), **extra} for r in rows]


async def test_route_sets_every_item_and_counts_duplicates_once(client, db, ev4, recorder):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    entries = [await _entry(db, a, ev4.a.owner_id) for _ in range(3)]
    await db.commit()
    ids = [e.id for e in entries]
    r = await client.post(_url(a), json={"items": _items(*ids, ids[0]), "value": "gm"}, headers=owner.headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": 3}
    for i in ids:
        assert await _stored_visibility(db, JournalEntry, i) == Visibility.GM
    assert [c[0] for c in recorder] == ["marker"] * 3 + ["listener", "cache"]
    co_gm = await ev4.actor("co_gm")
    r = await client.post(_url(a), json={"items": _items(ids[0]), "value": "party"}, headers=co_gm.headers)
    assert r.json() == {"updated": 1}


async def test_route_404_and_422_roll_back_every_item(client, db, ev4, recorder):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    other = await ev4.actor("cross_gm_player")
    entry = await _entry(db, a, ev4.a.owner_id)
    b_entry = await _entry(db, ev4.b.campaign_id, other.user_id)
    plan = await _plan(db, a, ev4.a.owner_id)
    await db.commit()
    entry_id, plan_id, b_id = entry.id, plan.id, b_entry.id  # rows expire when the route rolls back
    cases = [
        (_items(entry_id, MISSING), 404, NOT_FOUND),
        (_items(entry_id, b_id), 404, NOT_FOUND),
        (_items(entry_id) + _items(entry_id, kind="player_journal"), 404, NOT_FOUND),
        (_items(entry_id) + _items(ev4.a.ids["npcs"][0], kind="npc"), 422, ALWAYS_GM),
        (_items(entry_id) + _items(ev4.a.ids["quests"][0], kind="quest"), 422, ALWAYS_GM),
        (_items(entry_id, field="shorthand"), 422, ALWAYS_GM),
        (_items(entry_id, field="gm_notes"), 422, ALWAYS_GM),
        (_items(entry_id) + _items(plan_id, kind="session_plan", field="title"), 422,
         {"detail": "This record has no field-level visibility", "code": "no_field_visibility"}),
    ]
    for items, status, body in cases:
        r = await client.post(_url(a), json={"items": items, "value": "gm"}, headers=owner.headers)
        assert (r.status_code, r.json()) == (status, body), (items, r.text)
    assert await _stored_visibility(db, JournalEntry, entry_id) == Visibility.PARTY
    assert await _stored_visibility(db, SessionPlan, plan_id) == Visibility.PARTY
    assert [c for c in recorder if c[0] != "marker"] == []


async def test_route_validation_is_422(client, db, ev4):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    entry = ev4.a.ids["journal_entries"][0]
    for body in ({"items": [], "value": "gm"},
                 {"items": _items(*[uuid.uuid4() for _ in range(501)]), "value": "gm"},
                 {"items": _items(entry, kind="no_such_kind"), "value": "gm"},
                 {"items": _items(entry), "value": "secret"},
                 {"items": _items(entry)}):
        r = await client.post(_url(a), json=body, headers=owner.headers)
        assert r.status_code == 422, (body, r.text)
    assert await _stored_visibility(db, JournalEntry, entry) == Visibility.PARTY


async def test_route_is_the_one_404_for_players_preview_and_outsiders(client, db, ev4):
    a = ev4.a.campaign_id
    entry = ev4.a.ids["journal_entries"][0]
    body = {"items": _items(entry), "value": "gm"}
    owner = await ev4.actor("gm_owner")
    for actor_name in ("player", "cross_gm_player"):
        actor = await ev4.actor(actor_name)
        r = await client.post(_url(a), json=body, headers=actor.headers)
        assert (r.status_code, r.json()) == (404, NOT_FOUND)
    r = await client.post(_url(a), json=body, headers={**owner.headers, PREVIEW_HEADER: "member"})
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    r = await client.post(_url(MISSING), json=body, headers=owner.headers)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    # A Player's invalid body is still the 404 (the Role is checked first).
    player = await ev4.actor("player")
    r = await client.post(_url(a), json={"items": [], "value": "gm"}, headers=player.headers)
    assert r.status_code == 404
    r = await client.post(_url(a), json=body)
    assert r.status_code in (401, 403)
    assert await _stored_visibility(db, JournalEntry, entry) == Visibility.PARTY


async def test_downgrade_applies_on_the_next_player_read(client, db, ev4):
    a = ev4.a.campaign_id
    owner, player = await ev4.actor("gm_owner"), await ev4.actor("player")
    entry = await _entry(db, a, ev4.a.owner_id)
    await db.commit()
    assert (await client.get(f"/api/journals/{entry.id}", headers=player.headers)).status_code == 200
    r = await client.post(_url(a), json={"items": _items(entry.id), "value": "gm"}, headers=owner.headers)
    assert r.json() == {"updated": 1}
    assert (await client.get(f"/api/journals/{entry.id}", headers=player.headers)).json() == NOT_FOUND
    listed = (await client.get(f"/api/journals/?campaign_id={a}&limit=100", headers=player.headers)).json()
    assert str(entry.id) not in {i["id"] for i in listed["items"]}
    assert (await client.get(f"/api/journals/{entry.id}", headers=owner.headers)).status_code == 200
