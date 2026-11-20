"""E0-Access.12: the Members API (list / change Role / remove) and the Role
a Share Link carries (create, list, join).

The spec's I/O matrix: the list shape (the Owner row first with
`member_id: null`); promote, demote (chat sessions archived, NPC chats
included; entries stay and become GM-editable only) and same-Role PATCHes
with their epoch bump and after-commit publish; every escalation and junk
id is the byte-identical 404; bad bodies are 422 for the Owner and still
404 for anyone else; share links store and list `role` / `expires_at`; join
grants the link's Role.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from app.access import grants
from app.core import pubsub
from app.db.models import Entity, JournalEntry
from app.db.models.campaign import Campaign, Genre
from app.db.models.campaign_member import CampaignMember
from app.db.models.chat import ChatSession
from app.db.models.share_token import CampaignShareToken
from app.domain.enums import CampaignRole
from tests.ev4.fixtures import bearer, create_user, ev4, make_member  # noqa: F401  (ev4 registers the fixture)

NOT_FOUND = {"detail": "Not found"}
MISSING = "00000000-0000-4000-8000-000000000000"
MEMBER_KEYS = {"member_id", "user_id", "display_name", "role", "joined_at"}


@pytest.fixture
def published(monkeypatch):
    """Every after-commit grant publish as ("grant", campaign, grant) and
    Campaign event as ("event", campaign, domain)."""
    calls: list[tuple] = []

    async def grant(campaign_id, grant_id):
        calls.append(("grant", campaign_id, grant_id))

    async def event(campaign_id, domain, id=None):  # noqa: A002
        calls.append(("event", campaign_id, domain))

    monkeypatch.setattr(grants, "publish_grant_change", grant)
    monkeypatch.setattr(pubsub, "publish_campaign_event", event)
    return calls


async def _row(db, member_id) -> CampaignMember:
    return (await db.execute(sa.select(CampaignMember).where(CampaignMember.id == member_id)
                             .execution_options(populate_existing=True))).scalar_one()


async def _member_id(db, campaign_id, user_id) -> uuid.UUID:
    return await db.scalar(sa.select(CampaignMember.id).where(
        CampaignMember.campaign_id == campaign_id, CampaignMember.user_id == user_id))


async def _snapshot(db) -> list[tuple]:
    M = CampaignMember
    return [tuple(r) for r in (await db.execute(
        sa.select(M.id, sa.cast(M.role, sa.Text), M.access_epoch).order_by(M.id)
        .execution_options(populate_existing=True))).all()]


def _url(campaign_id, member_id="") -> str:
    return f"/api/campaigns/{campaign_id}/members" + (f"/{member_id}" if member_id != "" else "")


# ── List ───────────────────────────────────────────────────────────────────

async def test_list_is_the_owner_then_members_by_joined_at(client, db, ev4):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    co_gm = await ev4.actor("co_gm")
    r = await client.get(_url(a), headers=owner.headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert all(set(row) == MEMBER_KEYS for row in rows)
    created_at = await db.scalar(sa.select(Campaign.created_at).where(Campaign.id == a))
    assert rows[0]["member_id"] is None and rows[0]["role"] == "owner"
    assert rows[0]["user_id"] == str(ev4.a.owner_id) and rows[0]["display_name"] == "EV4 gm_owner"
    assert datetime.fromisoformat(rows[0]["joined_at"]) == created_at
    assert [(row["user_id"], row["role"]) for row in rows[1:]] == [
        (str(player.user_id), "player"), (str(co_gm.user_id), "co_gm")]
    assert rows[1]["member_id"] == str(await _member_id(db, a, player.user_id))
    assert "email" not in r.text and "@example.com" not in r.text


# ── Change Role ────────────────────────────────────────────────────────────

async def test_promote_bumps_the_epoch_and_publishes(client, db, ev4, published):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    mid = await _member_id(db, a, player.user_id)
    r = await client.patch(_url(a, mid), json={"role": "co_gm"}, headers=owner.headers)
    assert r.status_code == 200, r.text
    assert r.json() == {**r.json(), "member_id": str(mid), "user_id": str(player.user_id), "role": "co_gm"}
    assert set(r.json()) == MEMBER_KEYS
    row = await _row(db, mid)
    assert (row.role, row.access_epoch) == (CampaignRole.CO_GM, 1)
    assert published == [("grant", a, mid), ("event", a, "role")]
    me = await client.get(f"/api/campaigns/{a}/me", headers=player.headers)
    assert me.json()["display_role"] == "Co-GM"


async def test_same_role_changes_nothing(client, db, ev4, published):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    co_gm = await ev4.actor("co_gm")
    mid = await _member_id(db, a, co_gm.user_id)
    r = await client.patch(_url(a, mid), json={"role": "co_gm"}, headers=owner.headers)
    assert r.status_code == 200 and r.json()["role"] == "co_gm", r.text
    assert (await _row(db, mid)).access_epoch == 0
    assert published == []


async def test_demotion_archives_chats_and_keeps_entries_gm_only(client, db, ev4, published):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    co_gm = await ev4.actor("co_gm")
    mid = await _member_id(db, a, co_gm.user_id)
    npc = Entity(id=uuid.uuid4(), campaign_id=a, type="character", kind="npc", status="alive", name="Barnaby",
                 visibility="party", field_visibility={}, created_by_user_id=ev4.a.owner_id)
    db.add(npc)
    await db.flush()
    already = datetime(2026, 1, 1, tzinfo=timezone.utc)
    other = await create_user(db, "other_campaign_owner")
    elsewhere = Campaign(id=uuid.uuid4(), user_id=other.id, name="Elsewhere", genre=Genre.fantasy)
    db.add(elsewhere)
    await db.flush()
    chats = {
        "plain": ChatSession(user_id=co_gm.user_id, campaign_id=a, title="Plain"),
        "npc": ChatSession(user_id=co_gm.user_id, campaign_id=a, title="NPC", npc_entity_id=npc.id),
        "archived": ChatSession(user_id=co_gm.user_id, campaign_id=a, title="Old", archived_at=already),
        "no_campaign": ChatSession(user_id=co_gm.user_id, campaign_id=None, title="Free"),
        "elsewhere": ChatSession(user_id=co_gm.user_id, campaign_id=elsewhere.id, title="Elsewhere"),
        "owner": ChatSession(user_id=ev4.a.owner_id, campaign_id=a, title="Owner's"),
    }
    db.add_all(chats.values())
    entry = JournalEntry(user_id=co_gm.user_id, campaign_id=a, shorthand="s", narrative="The co-GM wrote this.",
                         entry_hash=uuid.uuid4().hex, kind="gm", visibility="party")
    db.add(entry)
    await db.commit()

    r = await client.patch(_url(a, mid), json={"role": "player"}, headers=owner.headers)
    assert r.status_code == 200 and r.json()["role"] == "player", r.text
    row = await _row(db, mid)
    assert (row.role, row.access_epoch) == (CampaignRole.PLAYER, 1)
    assert published == [("grant", a, mid), ("event", a, "role")]

    archived = dict((await db.execute(
        sa.select(ChatSession.id, ChatSession.archived_at).where(ChatSession.id.in_([c.id for c in chats.values()]))
        .execution_options(populate_existing=True))).all())
    assert archived[chats["plain"].id] is not None and archived[chats["npc"].id] is not None
    assert archived[chats["archived"].id] == already
    for untouched in ("no_campaign", "elsewhere", "owner"):
        assert archived[chats[untouched].id] is None, untouched

    stored = (await db.execute(sa.select(JournalEntry.kind, JournalEntry.visibility).where(
        JournalEntry.id == entry.id).execution_options(populate_existing=True))).one()
    assert tuple(stored) == ("gm", "party")
    # Now a Player: their gm-kind entry is GM-editable only.
    r = await client.delete(f"/api/journals/{entry.id}", headers=co_gm.headers)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    assert await db.scalar(sa.select(sa.func.count()).where(JournalEntry.id == entry.id)) == 1
    assert (await client.delete(f"/api/journals/{entry.id}", headers=owner.headers)).status_code == 204


async def test_a_promotion_archives_nothing(client, db, ev4):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    chat = ChatSession(user_id=player.user_id, campaign_id=a, title="Mine")
    db.add(chat)
    await db.commit()
    r = await client.patch(_url(a, await _member_id(db, a, player.user_id)), json={"role": "co_gm"},
                           headers=owner.headers)
    assert r.status_code == 200
    await db.refresh(chat)
    assert chat.archived_at is None


async def test_removing_a_co_gm_archives_their_chats(client, db, ev4):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    co_gm = await ev4.actor("co_gm")
    mine = ChatSession(user_id=co_gm.user_id, campaign_id=a, title="GM context")
    free = ChatSession(user_id=co_gm.user_id, campaign_id=None, title="Free")
    db.add_all([mine, free])
    await db.commit()
    r = await client.delete(_url(a, await _member_id(db, a, co_gm.user_id)), headers=owner.headers)
    assert r.status_code == 204, r.text
    archived = dict((await db.execute(
        sa.select(ChatSession.id, ChatSession.archived_at).where(ChatSession.id.in_([mine.id, free.id]))
        .execution_options(populate_existing=True))).all())
    assert archived[mine.id] is not None and archived[free.id] is None


@pytest.fixture
def gated(monkeypatch):
    """The platform gated (no open-access mode), whatever the DB row says."""
    from app.services import app_config_service

    async def closed(_db):
        return False

    monkeypatch.setattr(app_config_service, "is_open_access", closed)


async def test_promoting_needs_an_active_account(client, db, ev4, gated, published):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    unpaid = await create_user(db, "unpaid_member")
    unpaid.access_granted = False
    await db.commit()
    await make_member(db, role="player", campaign_id=a, user=unpaid)
    mid = await _member_id(db, a, unpaid.id)
    r = await client.patch(_url(a, mid), json={"role": "co_gm"}, headers=owner.headers)
    assert (r.status_code, r.json()) == (409, {"detail": "They need an active account to be a Co-GM."})
    row = await _row(db, mid)
    assert (row.role, row.access_epoch) == (CampaignRole.PLAYER, 0)
    assert published == []
    paid = await ev4.actor("player")
    r = await client.patch(_url(a, await _member_id(db, a, paid.user_id)), json={"role": "co_gm"},
                           headers=owner.headers)
    assert r.status_code == 200 and r.json()["role"] == "co_gm", r.text


# ── Escalation and bad bodies ──────────────────────────────────────────────

async def test_every_escalation_is_the_one_404(client, db, ev4, published):
    a = ev4.a.campaign_id
    player, co_gm, cross = await ev4.actor("player"), await ev4.actor("co_gm"), await ev4.actor("cross_gm_player")
    b = ev4.b.campaign_id
    b_member = await make_member(db, role="player", campaign_id=b, label="b_member")
    b_mid = await _member_id(db, b, b_member.id)
    ids = {who.name: await _member_id(db, a, who.user_id) for who in (player, co_gm, cross)}
    before = await _snapshot(db)
    missing = await client.patch(_url(MISSING, MISSING), json={"role": "co_gm"}, headers=player.headers)
    assert (missing.status_code, missing.json()) == (404, NOT_FOUND)
    for who in (player, co_gm, cross):
        for target in (*ids.values(), ev4.a.owner_id, b_mid, MISSING, "not-a-uuid"):
            for body in ({"role": "co_gm"}, {"role": "player"}, {"role": "owner"}, {"role": "gm"}):
                r = await client.patch(_url(a, target), json=body, headers=who.headers)
                assert (r.status_code, r.content) == (404, missing.content), (who.name, target, body, r.text)
            for query in ("", "?delete_entries=true"):
                r = await client.delete(_url(a, target) + query, headers=who.headers)
                assert (r.status_code, r.content) == (404, missing.content), (who.name, target, r.text)
            r = await client.get(_url(a), headers=who.headers)
            assert (r.status_code, r.content) == (404, missing.content)
    # cross owns B: A's Member under B, and the Owner's user id under B, are missing ones.
    for target in (ids["player"], ev4.a.owner_id, MISSING, "not-a-uuid"):
        r = await client.patch(_url(b, target), json={"role": "co_gm"}, headers=cross.headers)
        assert (r.status_code, r.content) == (404, missing.content), target
    # The Owner of A: B's Member, the Owner's own user id and junk are missing.
    owner = await ev4.actor("gm_owner")
    for target in (b_mid, ev4.a.owner_id, MISSING, "not-a-uuid"):
        r = await client.patch(_url(a, target), json={"role": "co_gm"}, headers=owner.headers)
        assert (r.status_code, r.content) == (404, missing.content), target
        r = await client.delete(_url(a, target), headers=owner.headers)
        assert (r.status_code, r.content) == (404, missing.content), target
    assert await _snapshot(db) == before
    assert published == []


@pytest.mark.parametrize("body", [{"role": "owner"}, {"role": "gm"}, {"role": None}, {}, {"role": "CO_GM"}])
async def test_a_bad_body_is_422_for_the_owner_only(client, db, ev4, body):
    a = ev4.a.campaign_id
    owner, co_gm = await ev4.actor("gm_owner"), await ev4.actor("co_gm")
    mid = await _member_id(db, a, (await ev4.actor("player")).user_id)
    r = await client.patch(_url(a, mid), json=body, headers=owner.headers)
    assert r.status_code == 422, r.text
    r = await client.patch(_url(a, mid), json=body, headers=co_gm.headers)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    assert (await _row(db, mid)).role == CampaignRole.PLAYER


async def test_remove_moved_with_its_paths(client, db, ev4, published):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    player = await ev4.actor("player")
    mid = await _member_id(db, a, player.user_id)
    r = await client.delete(_url(a, mid), headers=owner.headers)
    assert r.status_code == 204, r.text
    assert await db.scalar(sa.select(sa.func.count()).where(CampaignMember.id == mid)) == 0
    assert published == [("grant", a, mid), ("event", a, "role")]
    r = await client.delete(_url(a, mid), headers=owner.headers)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


# ── Share Links: Role and expiry ───────────────────────────────────────────

async def test_share_links_store_and_list_role_and_expiry(client, db, ev4):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    url = f"/api/campaigns/{a}/share"
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0)
    made = {}
    for name, body, role in (("collab_default", {"kind": "collaborate"}, "player"),
                             ("collab_co_gm", {"kind": "collaborate", "role": "co_gm", "expires_at": soon.isoformat()},
                              "co_gm"),
                             ("collab_player", {"kind": "collaborate", "role": "player"}, "player"),
                             ("read_only", {"kind": "read_only", "expires_at": soon.isoformat()}, None)):
        r = await client.post(url, json=body, headers=owner.headers)
        assert r.status_code == 201, r.text
        assert r.json()["role"] == role, name
        made[name] = r.json()
        stored = await db.scalar(sa.select(sa.cast(CampaignShareToken.role, sa.Text)).where(
            CampaignShareToken.id == uuid.UUID(r.json()["id"])))
        assert stored == role
    assert datetime.fromisoformat(made["collab_co_gm"]["expires_at"]) == soon
    assert made["collab_default"]["expires_at"] is None
    listed = {t["id"]: t for t in (await client.get(url, headers=owner.headers)).json()}
    for token in made.values():
        assert {k: listed[token["id"]][k] for k in ("role", "expires_at", "kind")} == \
            {k: token[k] for k in ("role", "expires_at", "kind")}


@pytest.mark.parametrize("body", [
    {"kind": "read_only", "role": "player"},
    {"kind": "read_only", "role": "co_gm"},
    {"kind": "collaborate", "role": "owner"},
    {"kind": "collaborate", "expires_at": "2020-01-01T00:00:00Z"},
    {"kind": "read_only", "expires_at": "2020-01-01T00:00:00+00:00"},
    {"kind": "collaborate", "expires_at": "not-a-date"},
])
async def test_bad_share_bodies_are_422(client, db, ev4, body):
    a = ev4.a.campaign_id
    owner = await ev4.actor("gm_owner")
    before = await db.scalar(sa.select(sa.func.count()).select_from(CampaignShareToken).where(
        CampaignShareToken.campaign_id == a))
    r = await client.post(f"/api/campaigns/{a}/share", json=body, headers=owner.headers)
    assert r.status_code == 422, r.text
    assert await db.scalar(sa.select(sa.func.count()).select_from(CampaignShareToken).where(
        CampaignShareToken.campaign_id == a)) == before


async def test_naive_expires_at_is_utc(client, ev4):
    owner = await ev4.actor("gm_owner")
    url = f"/api/campaigns/{ev4.a.campaign_id}/share"
    r = await client.post(url, json={"kind": "collaborate", "expires_at": "2030-01-01T12:00:00"}, headers=owner.headers)
    assert r.status_code == 201, r.text
    assert datetime.fromisoformat(r.json()["expires_at"]) == datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    r = await client.post(url, json={"kind": "read_only", "expires_at": "2020-01-01T00:00:00"}, headers=owner.headers)
    assert r.status_code == 422, r.text


async def test_expires_at_now_is_422(client, ev4):
    owner = await ev4.actor("gm_owner")
    body = {"kind": "collaborate", "expires_at": datetime.now(timezone.utc).isoformat()}
    r = await client.post(f"/api/campaigns/{ev4.a.campaign_id}/share", json=body, headers=owner.headers)
    assert r.status_code == 422, r.text


# ── Join grants the link's Role ────────────────────────────────────────────

async def _link(db, ev4, role, *, revoked=False, expired=False) -> str:
    token = secrets.token_urlsafe(24)
    db.add(CampaignShareToken(
        campaign_id=ev4.a.campaign_id, created_by_user_id=ev4.a.owner_id, token=token, kind="collaborate",
        role=role, revoked=revoked,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1) if expired else None))
    await db.commit()
    return token


@pytest.mark.parametrize("role, stored", [(CampaignRole.CO_GM, "co_gm"), (CampaignRole.PLAYER, "player"),
                                          (None, "player")])
async def test_join_grants_the_link_role(client, db, ev4, role, stored):
    user = await create_user(db, "joiner")
    r = await client.post(f"/api/share/{await _link(db, ev4, role)}/join", headers=bearer(user))
    assert r.status_code == 200 and r.json()["already_member"] is False, r.text
    got = await db.scalar(sa.select(sa.cast(CampaignMember.role, sa.Text)).where(
        CampaignMember.campaign_id == ev4.a.campaign_id, CampaignMember.user_id == user.id))
    assert got == stored
    me = (await client.get(f"/api/campaigns/{ev4.a.campaign_id}/me", headers=bearer(user))).json()
    assert me["display_role"] == ("Co-GM" if stored == "co_gm" else "Player")


async def test_expired_or_revoked_links_join_nothing(client, db, ev4):
    user = await create_user(db, "late_joiner")
    unknown = await client.post("/api/share/no-such-token/join", headers=bearer(user))
    assert (unknown.status_code, unknown.json()) == (404, NOT_FOUND)
    for token in (await _link(db, ev4, CampaignRole.CO_GM, revoked=True),
                  await _link(db, ev4, CampaignRole.PLAYER, expired=True)):
        r = await client.post(f"/api/share/{token}/join", headers=bearer(user))
        assert (r.status_code, r.content) == (404, unknown.content)
    assert await db.scalar(sa.select(sa.func.count()).select_from(CampaignMember).where(
        CampaignMember.user_id == user.id)) == 0
