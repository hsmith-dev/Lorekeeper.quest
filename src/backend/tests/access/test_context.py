"""E0-Access.2: CampaignContext, require_campaign(_for), ctx_for, role_map and
scoped_select_multi, against the story's I/O matrix.

Route-level checks run on a throwaway FastAPI app (not app.main.app, so the
EV-4 route census is untouched) whose get_db is the test session.
"""
from __future__ import annotations

import dataclasses
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.access import (
    Audience, AudienceLevel, CampaignContext, NotFound, SystemReason, ctx_audience, ctx_for, ctx_role, display_role,
    meets, not_found, require_campaign, require_campaign_for, role_map, scoped_select_multi,
)
from app.db.models.campaign import Campaign, Genre
from app.db.models.journal import JournalEntry
from app.db.session import get_db
from app.domain.enums import CampaignRole
from tests.ev4.fixtures import bearer, create_user, make_member

NOT_FOUND = {"detail": "Not found"}
RANDOM = "00000000-0000-4000-8000-000000000000"


# ── Pure policy (no database) ───────────────────────────────────────────────

def _ctx(role="gm", is_owner=False, **over) -> CampaignContext:
    uid = over.pop("user_id", uuid.uuid4())
    if role == "anon":
        over.setdefault("read_only", True)  # an anon ctx is always a reduced ctx
    return CampaignContext(campaign_id=over.pop("campaign_id", uuid.uuid4()), user_id=uid, role=role,
                           is_owner=is_owner, audience=ctx_audience(role, uid), **over)


def test_ctx_role_maps_stored_roles():
    assert ctx_role(CampaignRole.CO_GM) == "gm"
    assert ctx_role("co_gm") == "gm"
    assert ctx_role(CampaignRole.PLAYER) == "player"
    with pytest.raises(ValueError):
        ctx_role("owner")


@pytest.mark.parametrize("ctx_kwargs, allowed", [
    (dict(role="gm", is_owner=True), {"player", "gm", "owner"}),
    (dict(role="gm"), {"player", "gm"}),
    (dict(role="player"), {"player"}),
    (dict(role="anon", user_id=None), set()),
])
def test_meets_orders_player_gm_owner(ctx_kwargs, allowed):
    ctx = _ctx(**ctx_kwargs)
    assert {r for r in ("player", "gm", "owner") if meets(ctx, r)} == allowed


def test_min_role_is_validated():
    with pytest.raises(ValueError):
        require_campaign("admin")
    with pytest.raises(ValueError):
        require_campaign_for(JournalEntry, "journal_id", "co_gm")
    with pytest.raises(ValueError):
        meets(_ctx(), "anon")
    with pytest.raises(TypeError):
        require_campaign_for(object, "x", "player")


def test_display_role():
    assert display_role(_ctx("gm", True)) == "Owner"
    assert display_role(_ctx("gm")) == "Co-GM"
    assert display_role(_ctx("player")) == "Player"


def test_not_found_raises_itself():
    with pytest.raises(NotFound) as exc:
        not_found()
    assert exc.value.status_code == 404 and exc.value.detail == "Not found"
    with pytest.raises(NotFound):
        raise not_found()


def test_ctx_is_frozen_and_validated():
    ctx = _ctx("player")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.role = "gm"  # type: ignore[misc]
    with pytest.raises(ValueError):
        _ctx("co_gm")
    with pytest.raises(ValueError):
        _ctx("player", is_owner=True)
    assert ctx.audience == Audience(AudienceLevel.OWNER, ctx.user_id)
    assert _ctx("gm").audience.level is AudienceLevel.GM
    assert ctx_audience("anon", None).level is AudienceLevel.PUBLIC


@pytest.mark.parametrize("reason", ["entry_deleted", "merge", SystemReason.MERGE])
def test_as_system(reason):
    ctx = _ctx("player", grant_id=uuid.uuid4(), access_epoch=4)
    sys_ctx = ctx.as_system(reason)
    assert sys_ctx.role == "gm" and sys_ctx.actor == "system" and sys_ctx.is_system
    assert sys_ctx.system_reason == SystemReason(reason)
    assert (sys_ctx.campaign_id, sys_ctx.user_id) == (ctx.campaign_id, ctx.user_id)
    assert sys_ctx.audience.level is AudienceLevel.GM
    assert ctx.actor == "user" and ctx.system_reason is None, "the original ctx is unchanged"


@pytest.mark.parametrize("reason", ["delete", "MERGE", "", None, "owner"])
def test_as_system_rejects_other_reasons(reason):
    with pytest.raises(ValueError):
        _ctx().as_system(reason)


def test_system_ctx_only_via_as_system_shape():
    """A system ctx can't be assembled by hand with a missing reason, a
    non-GM role or no user, and as_system refuses anon and system ctxs."""
    with pytest.raises(ValueError):
        _ctx("gm", actor="system")  # no system_reason
    with pytest.raises(ValueError):
        _ctx("gm", system_reason=SystemReason.MERGE)  # reason on a user ctx
    with pytest.raises(ValueError):
        _ctx("player", actor="system", system_reason=SystemReason.MERGE)
    with pytest.raises(ValueError):
        _ctx("gm", actor="robot")
    with pytest.raises(ValueError):
        _ctx("anon", user_id=None).as_system("merge")
    with pytest.raises(ValueError):
        _ctx("gm").as_system("merge").as_system("merge")


def test_dependencies_are_memoized():
    assert require_campaign("gm") is require_campaign("gm")
    assert require_campaign("gm") is not require_campaign("owner")
    assert require_campaign_for(JournalEntry, "journal_id", "player") is require_campaign_for(
        JournalEntry, "journal_id", "player")


def test_scoped_select_multi_empty_map_selects_nothing():
    from sqlalchemy.dialects import postgresql

    sql = str(scoped_select_multi(JournalEntry, {}).compile(dialect=postgresql.dialect()))
    assert sql.rstrip().lower().endswith("where false"), sql
    with pytest.raises(TypeError):
        scoped_select_multi(object, {uuid.uuid4(): "gm"})


def test_api_deps_reexports_the_same_identity_objects():
    from app.access import identity
    from app.api import deps
    assert deps.get_current_user is identity.get_current_user
    assert deps.bearer_scheme is identity.bearer_scheme


# ── Database fixtures ──────────────────────────────────────────────────────

async def _campaign(db, owner, name="C") -> uuid.UUID:
    cid = uuid.uuid4()
    db.add(Campaign(id=cid, user_id=owner.id, name=name, genre=Genre.fantasy))
    await db.commit()
    return cid


async def _entry(db, author, campaign_id) -> uuid.UUID:
    eid = uuid.uuid4()
    db.add(JournalEntry(id=eid, user_id=author.id, campaign_id=campaign_id, shorthand="s", narrative="n",
                        entry_hash=uuid.uuid4().hex))
    await db.commit()
    return eid


async def _member_id(db, campaign_id, user_id) -> uuid.UUID:
    return (await db.execute(sa.text(
        "SELECT id FROM campaign_members WHERE campaign_id = :c AND user_id = :u"), {"c": campaign_id, "u": user_id}
    )).scalar_one()


@dataclasses.dataclass
class World:
    owner: object
    co_gm: object
    player: object
    outsider: object
    a: uuid.UUID
    b: uuid.UUID          # owned by `player` (cross-Campaign)
    c: uuid.UUID          # nobody of interest
    co_gm_grant: uuid.UUID


@pytest_asyncio.fixture
async def world(db) -> World:
    owner = await create_user(db, "owner")
    player = await create_user(db, "player")
    outsider = await create_user(db, "outsider")
    a = await _campaign(db, owner, "A")
    b = await _campaign(db, player, "B")
    c = await _campaign(db, outsider, "C")
    co_gm = await make_member(db, role="co_gm", campaign_id=a, label="co_gm")
    await make_member(db, role="player", campaign_id=a, user=player)
    grant = await _member_id(db, a, co_gm.id)
    # Raw SQL, like make_member: no CampaignMember is in the identity map yet,
    # so ctx_for reads the committed values.
    await db.execute(sa.text("UPDATE campaign_members SET access_epoch = 3 WHERE id = :id"), {"id": grant})
    await db.commit()
    return World(owner, co_gm, player, outsider, a, b, c, grant)


# ── ctx_for (I/O matrix) ───────────────────────────────────────────────────

async def test_owner_ctx(db, world):
    ctx = await ctx_for(db, world.owner.id, world.a)
    assert (ctx.role, ctx.is_owner, ctx.grant_id, ctx.access_epoch) == ("gm", True, None, 0)
    assert ctx.campaign_id == world.a and ctx.user_id == world.owner.id and ctx.actor == "user"


async def test_co_gm_ctx(db, world):
    ctx = await ctx_for(db, world.co_gm, world.a)
    assert (ctx.role, ctx.is_owner, ctx.grant_id, ctx.access_epoch) == ("gm", False, world.co_gm_grant, 3)
    assert meets(ctx, "gm") and not meets(ctx, "owner")


async def test_player_ctx_and_cross_campaign(db, world):
    in_a = await ctx_for(db, world.player.id, world.a)
    in_b = await ctx_for(db, world.player.id, world.b)
    assert (in_a.role, in_a.is_owner) == ("player", False)
    assert (in_b.role, in_b.is_owner, in_b.grant_id) == ("gm", True, None)
    assert in_a.grant_id == await _member_id(db, world.a, world.player.id)


@pytest.mark.parametrize("who, where", [("outsider", "a"), ("player", "c"), ("owner", "random"), ("owner", "junk")])
async def test_ctx_for_not_found(db, world, who, where):
    campaign_id = {"a": world.a, "c": world.c, "random": uuid.UUID(RANDOM), "junk": "not-a-uuid"}[where]
    with pytest.raises(NotFound):
        await ctx_for(db, getattr(world, who).id, campaign_id)


async def test_ctx_for_after_removal(db, world):
    await db.execute(sa.text("DELETE FROM campaign_members WHERE id = :id"), {"id": world.co_gm_grant})
    await db.commit()
    with pytest.raises(NotFound):
        await ctx_for(db, world.co_gm.id, world.a)


async def test_ctx_for_sees_a_grant_change_in_the_same_session(db, world):
    """A long-lived (worker) session gets the grant as it is now."""
    before = await ctx_for(db, world.co_gm.id, world.a)
    assert before.role == "gm" and before.access_epoch == 3
    await db.execute(sa.text("UPDATE campaign_members SET role = 'player', access_epoch = 9 WHERE id = :id"),
                     {"id": world.co_gm_grant})
    after = await ctx_for(db, world.co_gm.id, world.a)
    assert after.role == "player" and after.access_epoch == 9 and after.grant_id == world.co_gm_grant


# ── role_map / scoped_select_multi ─────────────────────────────────────────

async def test_role_map_and_scoped_select_multi(db, world):
    rows = {cid: await _entry(db, world.outsider, cid) for cid in (world.a, world.b, world.c)}
    roles = await role_map(db, world.player)
    assert roles == {world.a: "player", world.b: "gm"}
    assert await role_map(db, world.player.id) == roles
    got = set((await db.execute(scoped_select_multi(JournalEntry, roles))).scalars())
    assert {e.id for e in got} == {rows[world.a], rows[world.b]}
    assert (await db.execute(scoped_select_multi(JournalEntry, {}))).scalars().all() == []
    assert await role_map(db, world.co_gm) == {world.a: "gm"}
    assert await role_map(db, world.owner) == {world.a: "gm"}


async def test_deprecated_wrappers(db, world):
    import app.api.deps as deps
    from app.api.deps import get_campaign_with_access

    # E0-Access.5 deleted accessible_campaign_ids (role_map replaces it).
    assert not hasattr(deps, "accessible_campaign_ids")
    assert (await get_campaign_with_access(db, world.a, world.player)).id == world.a
    assert (await get_campaign_with_access(db, world.a, world.owner, require_owner=True)).id == world.a
    with pytest.raises(NotFound):
        await get_campaign_with_access(db, world.a, world.co_gm, require_owner=True)
    with pytest.raises(NotFound):
        await get_campaign_with_access(db, world.a, world.outsider)
    with pytest.raises(NotFound):
        await get_campaign_with_access(db, uuid.UUID(RANDOM), world.owner)


# ── Request dependencies on a throwaway app ────────────────────────────────

def _ctx_json(ctx: CampaignContext) -> dict:
    return {"campaign_id": str(ctx.campaign_id), "role": ctx.role, "is_owner": ctx.is_owner,
            "grant_id": str(ctx.grant_id) if ctx.grant_id else None, "access_epoch": ctx.access_epoch,
            "actor": ctx.actor, "system_reason": ctx.system_reason}


def _toy_app(db) -> FastAPI:
    toy = FastAPI()

    for min_role in ("player", "gm", "owner"):
        def make(m):
            async def item(ctx: CampaignContext = Depends(require_campaign(m))):
                return _ctx_json(ctx)

            async def collection(ctx: CampaignContext = Depends(require_campaign(m))):
                return _ctx_json(ctx)
            return item, collection
        item, collection = make(min_role)
        toy.add_api_route(f"/c/{{campaign_id}}/{min_role}", item)
        toy.add_api_route(f"/things/{min_role}", collection)

    async def journal(ctx: CampaignContext = Depends(require_campaign_for(JournalEntry, "journal_id", "player"))):
        return _ctx_json(ctx)

    async def journal_gm(ctx: CampaignContext = Depends(require_campaign_for(JournalEntry, "journal_id", "gm"))):
        return _ctx_json(ctx)

    toy.add_api_route("/journals/{journal_id}", journal)
    # Wiring bug: the route has no {journal_id}.
    toy.add_api_route("/miswired/{entry_id}", journal)
    toy.add_api_route("/journals/{journal_id}/gm", journal_gm)
    toy.dependency_overrides[get_db] = lambda: db
    return toy


@pytest_asyncio.fixture
async def toy(db):
    async with AsyncClient(transport=ASGITransport(app=_toy_app(db)), base_url="http://toy") as c:
        yield c


async def _assert_same_as_random(toy, user, url: str, random_url: str):
    denied = await toy.get(url, headers=bearer(user))
    missing = await toy.get(random_url, headers=bearer(user))
    assert denied.status_code == missing.status_code == 404, (denied.text, missing.text)
    assert denied.json() == missing.json() == NOT_FOUND
    assert denied.content == missing.content


@pytest.mark.parametrize("who, allowed", [
    ("owner", {"player", "gm", "owner"}),
    ("co_gm", {"player", "gm"}),
    ("player", {"player"}),
    ("outsider", set()),
])
async def test_require_campaign_path_param(toy, world, who, allowed):
    user = getattr(world, who)
    for min_role in ("player", "gm", "owner"):
        url = f"/c/{world.a}/{min_role}"
        if min_role in allowed:
            r = await toy.get(url, headers=bearer(user))
            assert r.status_code == 200, r.text
            assert r.json()["campaign_id"] == str(world.a) and r.json()["actor"] == "user"
            assert r.json()["system_reason"] is None
        else:
            await _assert_same_as_random(toy, user, url, f"/c/{RANDOM}/{min_role}")


async def test_require_campaign_query_param_and_cross_campaign(toy, world):
    h = bearer(world.player)
    r = await toy.get("/things/gm", params={"campaign_id": str(world.b)}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "gm" and r.json()["is_owner"] is True
    r = await toy.get("/things/player", params={"campaign_id": str(world.a)}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "player"
    # GM in B is nothing in A.
    denied = await toy.get("/things/gm", params={"campaign_id": str(world.a)}, headers=h)
    missing = await toy.get("/things/gm", params={"campaign_id": RANDOM}, headers=h)
    junk = await toy.get("/things/gm", params={"campaign_id": "nope"}, headers=h)
    assert denied.status_code == missing.status_code == junk.status_code == 404
    assert denied.content == missing.content == junk.content
    assert denied.json() == NOT_FOUND


async def test_require_campaign_co_gm_fields(toy, world):
    r = await toy.get(f"/c/{world.a}/gm", headers=bearer(world.co_gm))
    assert r.json() == {"campaign_id": str(world.a), "role": "gm", "is_owner": False,
                        "grant_id": str(world.co_gm_grant), "access_epoch": 3, "actor": "user",
                        "system_reason": None}


async def test_require_campaign_needs_auth(toy, world):
    r = await toy.get(f"/c/{world.a}/player")
    assert r.status_code in (401, 403)


async def test_require_campaign_for(toy, db, world):
    in_a = await _entry(db, world.owner, world.a)
    in_c = await _entry(db, world.outsider, world.c)
    r = await toy.get(f"/journals/{in_a}", headers=bearer(world.player))
    assert r.status_code == 200 and r.json()["campaign_id"] == str(world.a) and r.json()["role"] == "player"
    r = await toy.get(f"/journals/{in_a}/gm", headers=bearer(world.co_gm))
    assert r.status_code == 200 and r.json()["role"] == "gm"
    missing = await toy.get(f"/journals/{RANDOM}", headers=bearer(world.player))
    for url in (f"/journals/{in_a}/gm", f"/journals/{in_c}", "/journals/not-a-uuid"):
        r = await toy.get(url, headers=bearer(world.player))
        assert r.status_code == 404 and r.content == missing.content, url
    assert missing.json() == NOT_FOUND


async def test_require_campaign_for_miswired_route_fails_loudly(toy, db, world):
    in_a = await _entry(db, world.owner, world.a)
    with pytest.raises(RuntimeError, match="journal_id"):
        await toy.get(f"/miswired/{in_a}", headers=bearer(world.player))
