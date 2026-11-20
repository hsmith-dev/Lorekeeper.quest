"""E0-Access.6: Players are locked out of GM authoring and AI routes, and
write rules are enforced.

* `access.can_write` / `may_write`: the unit matrix (Role, reduced ctxs,
  other Campaigns, the two Player rules);
* GM-only routes refuse a Player with the missing-Campaign 404 before any LLM
  config is resolved or any usage is metered, and write no row;
* a Player may tag, untag and delete their own `kind=player` entry only;
* the fail-closed account gate (`account_gate`, `PARTY_READ`);
* joining with a Player link needs no paid account, a Co-GM link does.
"""
from __future__ import annotations

import inspect
import secrets
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from starlette.requests import Request

from app.access import (
    ANON_VIEW, GM, MEMBER_VIEW, PLAYER, CampaignContext, NotFound, SystemReason, as_user, audience_ctx, can_write,
    check_create, ctx_audience, may_write,
)
from app.api.deps import PARTY_READ, account_gate, is_party_read
from app.db.models import Campaign, CharacterSheet, JournalEntry, JournalTag, NpcEntry, Tag
from app.db.models.campaign_member import CampaignMember
from app.db.models.share_token import CampaignShareToken
from app.domain.enums import CampaignRole
from tests.ev4.fixtures import bearer, create_user, ev4, make_member  # noqa: F401  (ev4 registers the fixture)

NOT_FOUND = {"detail": "Not found"}
NOT_FOUND_BYTES = b'{"detail":"Not found"}'
MISSING = "00000000-0000-4000-8000-000000000000"


# ── can_write: the unit matrix ─────────────────────────────────────────────

A = uuid.uuid4()
OTHER = uuid.uuid4()
GM_USER = uuid.uuid4()
P_USER = uuid.uuid4()
Q_USER = uuid.uuid4()


def _ctx(role: str, user_id: uuid.UUID, campaign_id: uuid.UUID = A, *, owner: bool = False) -> CampaignContext:
    return CampaignContext(campaign_id=campaign_id, user_id=user_id, role=role, is_owner=owner,
                           audience=ctx_audience(role, user_id))


GM_CTX = _ctx(GM, GM_USER, owner=True)
CO_GM_CTX = _ctx(GM, uuid.uuid4())
P_CTX = _ctx(PLAYER, P_USER)


def _entry(*, author=P_USER, kind="player", campaign_id=A) -> JournalEntry:
    return JournalEntry(id=uuid.uuid4(), user_id=author, campaign_id=campaign_id, shorthand="s", narrative="n",
                        entry_hash="h", kind=kind, visibility="party")


def _sheet(campaign_id=A, pc_entity_id=None) -> CharacterSheet:
    return CharacterSheet(id=uuid.uuid4(), campaign_id=campaign_id, template_id=uuid.uuid4(),
                          created_by_user_id=P_USER, name="Pip", data={}, pc_entity_id=pc_entity_id)


def _npc(campaign_id=A) -> NpcEntry:
    return NpcEntry(id=uuid.uuid4(), user_id=P_USER, campaign_id=campaign_id, name="Barnaby")


def _cases():
    """(label, ctx, row, may write)."""
    own = _entry()
    reduced = [
        ("preview", audience_ctx(A, MEMBER_VIEW, by=GM_CTX)),
        ("anon", audience_ctx(A, ANON_VIEW, by=GM_CTX)),
        ("as_user(player)", audience_ctx(A, as_user(P_USER), by=GM_CTX)),
        ("player's member view", audience_ctx(A, MEMBER_VIEW, by=P_CTX)),
    ]
    out = [
        # gm (Owner, Co-GM, system): any row of the Campaign.
        ("owner: player entry", GM_CTX, own, True),
        ("owner: gm entry", GM_CTX, _entry(author=GM_USER, kind="gm"), True),
        ("co_gm: sheet", CO_GM_CTX, _sheet(), True),
        ("co_gm: npc", CO_GM_CTX, _npc(), True),
        ("owner: the Campaign", GM_CTX, Campaign(id=A, user_id=GM_USER, name="A"), True),
        # A global Tag (shared across Campaigns) is unscoped: refused (fail closed).
        ("owner: a global tag", GM_CTX, Tag(name="Bree"), False),
        ("owner: a journal_tags link", GM_CTX, JournalTag(journal_id=own.id, tag_id=uuid.uuid4()), True),
        ("system", GM_CTX.as_system(SystemReason.ENTRY_DELETED), _entry(author=GM_USER, kind="gm"), True),
        # ... never a row of another Campaign.
        ("owner: other Campaign's entry", GM_CTX, _entry(campaign_id=OTHER), False),
        ("owner: other Campaign", GM_CTX, Campaign(id=OTHER, user_id=GM_USER, name="B"), False),
        ("co_gm: other Campaign's sheet", CO_GM_CTX, _sheet(campaign_id=OTHER), False),
        # player: own kind=player entries only.
        ("player: own player entry", P_CTX, own, True),
        ("player: own gm-kind entry", P_CTX, _entry(kind="gm"), False),
        ("player: another player's entry", P_CTX, _entry(author=Q_USER), False),
        ("player: the GM's entry", P_CTX, _entry(author=GM_USER, kind="gm"), False),
        ("player: own player entry, other Campaign", P_CTX, _entry(campaign_id=OTHER), False),
        # ... and their own linked PC's sheet: no `entities` until F3-world.
        ("player: sheet", P_CTX, _sheet(), False),
        ("player: sheet with a pc_entity_id", P_CTX, _sheet(pc_entity_id=uuid.uuid4()), False),
        ("player: npc", P_CTX, _npc(), False),
        ("player: the Campaign", P_CTX, Campaign(id=A, user_id=GM_USER, name="A"), False),
        ("player: a tag", P_CTX, Tag(name="Bree"), False),
    ]
    # A reduced ctx writes nothing, not even what its user could otherwise write.
    for label, ctx in reduced:
        out.append((f"{label}: own player entry", ctx, own, False))
        out.append((f"{label}: npc", ctx, _npc(), False))
    return out


@pytest.mark.parametrize("label, ctx, row, allowed", _cases(), ids=[c[0] for c in _cases()])
def test_can_write_matrix(label, ctx, row, allowed):
    assert may_write(ctx, row) is allowed, label
    if allowed:
        assert can_write(ctx, row) is None
    else:
        with pytest.raises(NotFound) as exc:
            can_write(ctx, row)
        assert (exc.value.status_code, exc.value.detail) == (404, "Not found")


def test_check_create_ends_with_can_write():
    # Visible to the Player (party, Members) but not theirs to write.
    with pytest.raises(NotFound):
        check_create(_entry(author=Q_USER), P_CTX)
    check_create(_entry(), P_CTX)
    with pytest.raises(NotFound):
        check_create(_entry(), audience_ctx(A, as_user(P_USER), by=GM_CTX))
    check_create(_npc(), CO_GM_CTX)
    with pytest.raises(NotFound):
        check_create(_npc(), audience_ctx(A, MEMBER_VIEW, by=GM_CTX))


# ── GM-only routes: 404 before any LLM config or meter ─────────────────────

@pytest.fixture
def llm_spy(monkeypatch):
    """Records every LLM-config resolution and every meter call."""
    from app.api.deps import get_user_llm_config
    from app.api.routes import journals as journal_routes, session_plans as plan_routes
    from app.main import app
    from app.services import llm_config_service

    calls: list[str] = []

    async def resolve(*_args, **_kwargs):
        calls.append("config")
        raise AssertionError("an LLM config was resolved for a refused request")

    async def meter(*_args, **_kwargs):
        calls.append("meter")

    async def resolve_dependency():
        return await resolve()

    monkeypatch.setattr(journal_routes, "get_user_llm_config", resolve)
    monkeypatch.setattr(plan_routes, "get_user_llm_config", resolve)
    monkeypatch.setattr(llm_config_service, "meter", meter)
    app.dependency_overrides[get_user_llm_config] = resolve_dependency
    yield calls
    app.dependency_overrides.pop(get_user_llm_config, None)


def _gm_routes():
    """(method, url template with {cid} / {npc} / {quest}, payload): payload
    is a callable taking the Campaign id (a body naming it), a fixed JSON
    body, or None."""
    def body(**kw):
        return lambda cid: {**kw, "campaign_id": cid}

    return [
        ("POST", "/api/journals/generate-draft", body(notes="met the innkeeper")),
        ("POST", "/api/journals/generate", body(notes="n", entry_hash=uuid.uuid4().hex)),
        ("POST", "/api/journals/generate", body(notes="n", entry_hash=uuid.uuid4().hex, narrative="Done.")),
        ("POST", "/api/journals/summarize-session", body(transcript="We went to the inn.")),
        ("POST", "/api/journals/recap", body()),
        ("POST", "/api/journals/autocomplete", body(text="The party met")),
        ("POST", "/api/session-plans/generate", body(focus="the inn")),
        ("POST", "/api/session-plans/", body(title="Plan", content="c")),
        ("POST", "/api/npcs/", body(name="Spy")),
        ("POST", "/api/quests/", body(title="Heist")),
        ("POST", "/api/shorthand/", body(term="bbeg", meaning="big bad")),
        ("POST", "/api/journals/reindex?campaign_id={cid}", None),
        ("POST", "/api/npcs/extract?campaign_id={cid}", None),
        ("POST", "/api/quests/suggest?campaign_id={cid}", None),
        ("POST", "/api/campaigns/{cid}/tag-categories", {"name": "Deity"}),
        ("POST", "/api/npcs/{npc}/generate", None),
        ("POST", "/api/quests/{quest}/generate", None),
        ("PUT", "/api/npcs/{npc}", {"name": "Renamed"}),
        ("DELETE", "/api/quests/{quest}", None),
    ]


async def test_player_gm_routes_are_404_before_llm_config_or_meter(client, db, ev4, llm_spy):
    from app.db.models.npc import NpcEntry as Npc
    from app.db.models.quest import Quest
    from app.db.models.session_plan import SessionPlan
    from app.db.models.shorthand import ShorthandTerm

    a = str(ev4.a.campaign_id)
    npc, quest = str(ev4.a.ids["npcs"][0]), str(ev4.a.ids["quests"][0])
    player = await ev4.actor("player")
    counted = (JournalEntry, Npc, Quest, SessionPlan, ShorthandTerm)

    async def counts():
        return [await db.scalar(sa.select(sa.func.count()).select_from(m).where(m.campaign_id == ev4.a.campaign_id))
                for m in counted]

    before = await counts()
    for method, url, payload in _gm_routes():
        def call(cid, row_npc=npc, row_quest=quest):
            target = url.format(cid=cid, npc=row_npc, quest=row_quest)
            kw = {}
            if callable(payload):
                kw["json"] = payload(cid)
            elif payload is not None:
                kw["json"] = payload
            return client.request(method, target, headers=player.headers, **kw)

        r = await call(a)
        missing = await (call(MISSING, MISSING, MISSING))
        assert (r.status_code, r.content) == (404, NOT_FOUND_BYTES), f"{method} {url}: {r.text}"
        assert (missing.status_code, missing.content) == (404, NOT_FOUND_BYTES), f"{method} {url} (missing)"
    assert llm_spy == []
    assert await counts() == before


async def test_co_gm_still_reaches_the_gm_routes(client, ev4, monkeypatch):
    from app.api.routes import journals as journal_routes
    from app.services import journal_service
    from tests.ev4.probes.retrieval import use_fake_llm

    async def no_dup(*_args):
        return False

    async def noop(*_args):
        return None

    monkeypatch.setattr(journal_routes, "check_hash", no_dup)
    monkeypatch.setattr(journal_service, "store_hash", noop)
    monkeypatch.setattr(journal_service, "extract_tags", lambda _text: [])
    monkeypatch.setattr(journal_service.embedding_service, "embed", lambda _text: None)
    a = str(ev4.a.campaign_id)
    co_gm = await ev4.actor("co_gm")
    await use_fake_llm(ev4, co_gm)
    for url, body in (("/api/journals/generate-draft", {"notes": "met the innkeeper"}),
                      ("/api/journals/summarize-session", {"transcript": "We went to the inn."}),
                      ("/api/journals/recap", {}),
                      ("/api/journals/generate", {"notes": "n", "entry_hash": uuid.uuid4().hex,
                                                  "narrative": "Done."})):
        r = await client.post(url, json={**body, "campaign_id": a}, headers=co_gm.headers)
        assert r.status_code in (200, 201), f"{url}: {r.text}"


# ── Player Journal writes: own kind=player entries only ────────────────────

async def test_player_tags_untags_and_deletes_only_their_own_player_entries(client, db, ev4):
    a = ev4.a.campaign_id
    player = await ev4.actor("player")
    other = await ev4.make_member("player", label="other")

    def entry(author, kind="player", visibility="party"):
        e = JournalEntry(user_id=author, campaign_id=a, shorthand="s", narrative=f"n {uuid.uuid4().hex}",
                         entry_hash=uuid.uuid4().hex, kind=kind, visibility=visibility)
        db.add(e)
        return e

    own, own_private = entry(player.user_id), entry(player.user_id, visibility="private")
    own_gm_kind, others, gms = entry(player.user_id, kind="gm"), entry(other.id), entry(ev4.a.owner_id, kind="gm")
    hidden = entry(other.id, visibility="private")
    await db.commit()
    body = {"name": f"Bree {uuid.uuid4().hex[:6]}", "tag_type": "location"}

    for e in (own_gm_kind, others, gms, hidden):
        for method, url, kw in (("POST", f"/api/journals/{e.id}/tags", {"json": body}),
                                ("DELETE", f"/api/journals/{e.id}/tags/{MISSING}", {}),
                                ("DELETE", f"/api/journals/{e.id}", {})):
            r = await client.request(method, url, headers=player.headers, **kw)
            missing = await client.request(method, url.replace(str(e.id), MISSING), headers=player.headers, **kw)
            assert (r.status_code, r.content) == (missing.status_code, missing.content) == (404, NOT_FOUND_BYTES)
        assert await db.scalar(sa.select(sa.func.count()).where(JournalEntry.id == e.id)) == 1
        assert await db.scalar(sa.select(sa.func.count()).where(JournalTag.journal_id == e.id)) == 0

    for e in (own, own_private):
        r = await client.post(f"/api/journals/{e.id}/tags", json=body, headers=player.headers)
        assert r.status_code == 201, r.text
        tag_id = r.json()["id"]
        r = await client.delete(f"/api/journals/{e.id}/tags/{tag_id}", headers=player.headers)
        assert r.status_code == 204, r.text
        assert (await client.delete(f"/api/journals/{e.id}", headers=player.headers)).status_code == 204
        assert await db.scalar(sa.select(sa.func.count()).where(JournalEntry.id == e.id)) == 0


# ── STOPGAP until E7 (owner decision 2026-11-01): a Player's own sheets ───

async def _sheets(db, ev4):
    """A sheet by the Player, one by another Player, one by the Owner (all
    Party, so the Player can see each)."""
    a = ev4.a.campaign_id
    player = await ev4.actor("player")
    other = await ev4.make_member("player", label="sheet-other")
    template_id = ev4.a.ids["character_sheet_templates"][0]

    def sheet(author):
        s = CharacterSheet(campaign_id=a, template_id=template_id, created_by_user_id=author,
                           name=f"Pc {uuid.uuid4().hex[:6]}", data={}, visibility="party")
        db.add(s)
        return s

    own, others, gms = sheet(player.user_id), sheet(other.id), sheet(ev4.a.owner_id)
    await db.commit()
    return player, own, others, gms


async def test_player_edits_only_their_own_sheets(client, db, ev4):
    player, own, others, gms = await _sheets(db, ev4)
    for s in (others, gms):
        for method, kw in (("PATCH", {"json": {"name": "Mine now"}}), ("DELETE", {})):
            r = await client.request(method, f"/api/character-sheets/{s.id}", headers=player.headers, **kw)
            missing = await client.request(method, f"/api/character-sheets/{MISSING}", headers=player.headers, **kw)
            assert (r.status_code, r.content) == (missing.status_code, missing.content) == (404, NOT_FOUND_BYTES)
        assert await db.scalar(sa.select(sa.func.count()).where(CharacterSheet.id == s.id,
                                                                 CharacterSheet.name != "Mine now")) == 1
    r = await client.patch(f"/api/character-sheets/{own.id}", json={"name": "Pippa"}, headers=player.headers)
    assert r.status_code == 200 and r.json()["name"] == "Pippa", r.text
    # Creates and templates stay GM-only.
    a = str(ev4.a.campaign_id)
    template_id = str(ev4.a.ids["character_sheet_templates"][0])
    r = await client.post("/api/character-sheets/", headers=player.headers,
                          json={"campaign_id": a, "template_id": template_id, "name": "New", "data": {}})
    assert (r.status_code, r.content) == (404, NOT_FOUND_BYTES)
    r = await client.patch(f"/api/character-sheets/templates/{template_id}", json={"name": "X"},
                           headers=player.headers)
    assert (r.status_code, r.content) == (404, NOT_FOUND_BYTES)
    assert (await client.delete(f"/api/character-sheets/{own.id}", headers=player.headers)).status_code == 204
    assert await db.scalar(sa.select(sa.func.count()).where(CharacterSheet.id == own.id)) == 0


async def test_sheet_stopgap_is_refused_to_reduced_ctxs(client, db, ev4):
    """Preview and audience ctxs never pass, even on the viewer's own sheet;
    a transient sheet (a create) never matches the stopgap."""
    player, own, _, _ = await _sheets(db, ev4)
    row = await db.get(CharacterSheet, own.id)
    p_ctx = _ctx(PLAYER, player.user_id, ev4.a.campaign_id)
    assert may_write(p_ctx, row)
    assert not may_write(audience_ctx(ev4.a.campaign_id, as_user(player.user_id), by=p_ctx), row)
    assert not may_write(audience_ctx(ev4.a.campaign_id, ANON_VIEW, by=p_ctx), row)
    new = CharacterSheet(campaign_id=ev4.a.campaign_id, template_id=row.template_id,
                         created_by_user_id=player.user_id, name="New", data={})
    assert not may_write(p_ctx, new)
    co_gm = await ev4.actor("co_gm")
    r = await client.patch(f"/api/character-sheets/{own.id}", json={"name": "Preview"},
                           headers={**co_gm.headers, "X-Lorekeeper-Preview": "member"})
    assert (r.status_code, r.content) == (404, NOT_FOUND_BYTES)


async def test_sheet_stopgap_removes_cleanly(client, db, ev4, monkeypatch):
    """E7 deletes SHEET_AUTHOR_STOPGAP: with it off a Player edits no sheet
    (the uniform 404) and GMs are unchanged."""
    from app.access import write

    player, own, _, _ = await _sheets(db, ev4)
    monkeypatch.setattr(write, "SHEET_AUTHOR_STOPGAP", False)
    r = await client.patch(f"/api/character-sheets/{own.id}", json={"name": "Nope"}, headers=player.headers)
    missing = await client.patch(f"/api/character-sheets/{MISSING}", json={"name": "Nope"}, headers=player.headers)
    assert (r.status_code, r.content) == (missing.status_code, missing.content) == (404, NOT_FOUND_BYTES)
    co_gm = await ev4.actor("co_gm")
    r = await client.patch(f"/api/character-sheets/{own.id}", json={"name": "GM edit"}, headers=co_gm.headers)
    assert r.status_code == 200, r.text


async def test_a_previewing_gm_writes_nothing(client, db, ev4):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    preview = {**owner.headers, "X-Lorekeeper-Preview": "member"}
    entry = ev4.a.ids["journal_entries"][0]
    sheet = ev4.a.ids["character_sheets"][0]
    for method, url, kw in (("DELETE", f"/api/journals/{entry}", {}),
                            ("POST", f"/api/journals/{entry}/tags", {"json": {"name": "Bree"}}),
                            ("PATCH", f"/api/character-sheets/{sheet}", {"json": {"name": "Renamed"}}),
                            ("POST", "/api/npcs/", {"json": {"name": "Spy", "campaign_id": str(a)}}),
                            ("PATCH", f"/api/campaigns/{a}", {"json": {"name": "Renamed"}})):
        r = await client.request(method, url, headers=preview, **kw)
        assert (r.status_code, r.content) == (404, NOT_FOUND_BYTES), f"{method} {url}"
    assert await db.scalar(sa.select(sa.func.count()).where(JournalEntry.id == entry)) == 1
    assert (await db.get(Campaign, a, populate_existing=True)).name != "Renamed"


# ── The account gate ───────────────────────────────────────────────────────

@pytest.fixture
def gated(monkeypatch):
    """The platform gated (no open-access mode), whatever the DB row says."""
    from app.services import app_config_service

    async def closed(_db):
        return False

    monkeypatch.setattr(app_config_service, "is_open_access", closed)


def _gate_request(method: str, route) -> Request:
    scope = {"type": "http", "method": method, "path": "/api/x", "headers": []}
    if route is not None:
        scope["route"] = route
    return Request(scope)


@pytest.mark.parametrize("method, extra, gated_through", [
    ("GET", PARTY_READ, False),
    ("HEAD", PARTY_READ, False),
    ("POST", PARTY_READ, True),       # a mis-marked write still pays
    ("GET", None, True),              # not marked: gated (fail-closed)
    ("GET", {"x-other": True}, True),
])
async def test_account_gate_unit(db, gated, method, extra, gated_through):
    # A user with no Campaign is GM nowhere, so only the route decides.
    unpaid = SimpleNamespace(id=uuid.uuid4(), access_granted=False)
    route = SimpleNamespace(openapi_extra=extra)
    if gated_through:
        with pytest.raises(HTTPException) as exc:
            await account_gate(_gate_request(method, route), unpaid, db)
        assert exc.value.status_code == 402 and exc.value.headers == {"X-Gate-Reason": "account-gate"}
    else:
        assert await account_gate(_gate_request(method, route), unpaid, db) is unpaid
    paid = SimpleNamespace(id=uuid.uuid4(), access_granted=True)
    assert await account_gate(_gate_request(method, route), paid, db) is paid


async def test_account_gate_without_a_matched_route_is_gated(db, gated):
    with pytest.raises(HTTPException) as exc:
        await account_gate(_gate_request("GET", None), SimpleNamespace(id=uuid.uuid4(), access_granted=False), db)
    assert exc.value.status_code == 402


PARTY_READ_ROUTES = {
    "GET /api/campaigns/", "GET /api/campaigns/{campaign_id}", "GET /api/campaigns/{campaign_id}/tag-categories",
    "GET /api/campaigns/{campaign_id}/me", "GET /api/journals/", "GET /api/journals/{journal_id}", "GET /api/tags/",
    "GET /api/chat/sessions", "GET /api/chat/sessions/{session_id}", "GET /api/npcs/", "GET /api/npcs/{npc_id}",
    "GET /api/npcs/{npc_id}/entries", "GET /api/quests/", "GET /api/quests/{quest_id}",
    "GET /api/quests/{quest_id}/entries", "GET /api/sources/", "GET /api/session-plans/",
    "GET /api/session-plans/{plan_id}", "GET /api/shorthand/", "GET /api/character-sheets/templates",
    "GET /api/character-sheets/", "GET /api/character-sheets/{sheet_id}",
}


def _deps(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _deps(dep)


def test_party_read_routes_are_safe_reads_with_no_hosted_ai():
    from fastapi.routing import APIRoute

    from app.api.deps import get_user_llm_config
    from app.main import app

    marked = {}
    for route in app.routes:
        if isinstance(route, APIRoute) and is_party_read(route):
            for method in route.methods:
                marked[f"{method} {route.path}"] = route
    assert set(marked) == PARTY_READ_ROUTES
    for key, route in marked.items():
        assert key.split()[0] in ("GET", "HEAD"), key
        assert get_user_llm_config not in set(_deps(route.dependant)), f"{key} resolves an LLM config"
        # Several AI routes resolve the config inline, not as a dependency.
        source = inspect.getsource(inspect.unwrap(route.endpoint))
        assert "get_user_llm_config" not in source and "llm_config_service" not in source, key


async def _unpaid_player(db, ev4):
    user = await create_user(db, "unpaid")
    user.access_granted = False
    await db.commit()
    await make_member(db, role="player", campaign_id=ev4.a.campaign_id, user=user)
    return user


async def test_unpaid_player_reads_the_party_but_not_ai_routes(client, db, ev4, gated):
    a = ev4.a.campaign_id
    user = await _unpaid_player(db, ev4)
    headers = bearer(user)
    for url in (f"/api/journals/?campaign_id={a}", "/api/campaigns/", f"/api/campaigns/{a}",
                f"/api/campaigns/{a}/me", f"/api/tags/?campaign_id={a}", f"/api/journals/{ev4.a.ids['journal_entries'][0]}",
                f"/api/character-sheets/?campaign_id={a}", "/api/chat/sessions"):
        r = await client.get(url, headers=headers)
        assert r.status_code == 200, f"{url}: {r.status_code} {r.text}"
    for url, body in (("/api/chat/", {"message": "Who is the lich?", "campaign_id": str(a)}),
                      ("/api/journals/generate-draft", {"notes": "n", "campaign_id": str(a)})):
        r = await client.post(url, json=body, headers=headers)
        assert r.status_code == 402 and r.headers.get("X-Gate-Reason") == "account-gate", f"{url}: {r.text}"
    # A non-Party read stays gated too (analytics is GM-only, but the gate answers first).
    r = await client.get(f"/api/campaigns/{a}/analytics", headers=headers)
    assert r.status_code == 402


async def test_unpaid_gm_is_gated_on_party_reads(client, db, ev4, gated):
    """The PARTY_READ exemption is for Players only: an unpaid Owner, and an
    unpaid user who is Player in A but Owner of another Campaign, both get
    the 402 on a Party read (they would read GM projections for free)."""
    from app.db.models.campaign import Genre
    from app.db.models.user import User

    owner = await db.get(User, ev4.a.owner_id)
    owner.access_granted = False
    await db.commit()
    r = await client.get(f"/api/journals/?campaign_id={ev4.a.campaign_id}", headers=bearer(owner))
    assert r.status_code == 402 and r.headers.get("X-Gate-Reason") == "account-gate", r.text

    mixed = await _unpaid_player(db, ev4)
    db.add(Campaign(id=uuid.uuid4(), user_id=mixed.id, name="Mine", genre=Genre.fantasy))
    await db.commit()
    r = await client.get(f"/api/journals/?campaign_id={ev4.a.campaign_id}", headers=bearer(mixed))
    assert r.status_code == 402 and r.headers.get("X-Gate-Reason") == "account-gate", r.text


# ── Join: a Player link needs no paid account ──────────────────────────────

async def _link(db, ev4, role, *, revoked=False) -> str:
    token = secrets.token_urlsafe(24)
    db.add(CampaignShareToken(campaign_id=ev4.a.campaign_id, created_by_user_id=ev4.a.owner_id, token=token,
                              kind="collaborate", role=role, revoked=revoked))
    await db.commit()
    return token


async def _members(db, ev4, user) -> int:
    return await db.scalar(sa.select(sa.func.count()).select_from(CampaignMember).where(
        CampaignMember.campaign_id == ev4.a.campaign_id, CampaignMember.user_id == user.id))


@pytest.mark.parametrize("role", [None, CampaignRole.PLAYER])
async def test_unpaid_user_redeems_a_player_link(client, db, ev4, gated, role):
    user = await create_user(db, "unpaid_join")
    user.access_granted = False
    await db.commit()
    r = await client.post(f"/api/share/{await _link(db, ev4, role)}/join", headers=bearer(user))
    assert r.status_code == 200 and r.json()["already_member"] is False, r.text
    assert await _members(db, ev4, user) == 1


async def test_co_gm_link_needs_a_paid_account(client, db, ev4, gated):
    unpaid = await create_user(db, "unpaid_cogm")
    unpaid.access_granted = False
    await db.commit()
    token = await _link(db, ev4, CampaignRole.CO_GM)
    r = await client.post(f"/api/share/{token}/join", headers=bearer(unpaid))
    assert r.status_code == 402 and r.headers.get("X-Gate-Reason") == "account-gate", r.text
    assert await _members(db, ev4, unpaid) == 0
    # A revoked link is the 404, before the account is checked.
    revoked = await _link(db, ev4, CampaignRole.CO_GM, revoked=True)
    r = await client.post(f"/api/share/{revoked}/join", headers=bearer(unpaid))
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    paid = await create_user(db, "paid_cogm")
    r = await client.post(f"/api/share/{token}/join", headers=bearer(paid))
    assert r.status_code == 200, r.text
    assert await _members(db, ev4, paid) == 1
