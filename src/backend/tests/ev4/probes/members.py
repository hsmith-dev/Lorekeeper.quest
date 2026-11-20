"""EV-4 probes for api/routes/members.py (E0-Access) and the Role a
collaborate link grants on join (E0-Access.12).

* GET /{campaign_id}/me: the actor's own Role; hidden ≡ missing.
* GET / PATCH / DELETE /{campaign_id}/members…: Owner only. A Player, a
  co-GM, a Player who is GM of Campaign B and a Share Link viewer get the one
  404 for every target (their own member id, another Member's, the Owner's
  user id, another Campaign's member id, a junk id) and with every body
  (promote, demote, `owner`); no Role, epoch or row changes.
* PATCH demotion: the Owner demotes the co-GM while the co-GM holds A's
  events stream; it ends with `access_changed`, their chat sessions in A are
  archived and they now read A as a Player.
* POST /api/share/{token}/join: the new Member gets the link's Role (a
  legacy link with none grants Player).
"""
from __future__ import annotations

import asyncio
import dataclasses
import secrets
import uuid

import sqlalchemy as sa

from tests.ev4.families import assert_hidden_equals_missing, assert_no_canary
from tests.ev4.fixtures import create_user, make_member
from tests.ev4.probes._support import add_chat_session, authenticated, outsider
from tests.ev4.probes.campaigns import _campaign_route
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe
from tests.ev4.report import record_leak

MISSING = "00000000-0000-4000-8000-000000000000"
BASE = "/api/campaigns"
WITH_CO_GM = (*DEFAULT_ACTORS, "co_gm")
BODIES = ({"role": "co_gm"}, {"role": "player"}, {"role": "owner"})


async def _hidden_campaign(ev4) -> uuid.UUID:
    """A Campaign nobody in the actor set owns or belongs to."""
    from app.db.models.campaign import Campaign, Genre

    owner = await create_user(ev4.db, "members_probe_owner")
    cid = uuid.uuid4()
    ev4.db.add(Campaign(id=cid, user_id=owner.id, name="Hidden", genre=Genre.fantasy))
    await ev4.db.commit()
    return cid


async def _member_id(ev4, user_id, campaign_id=None) -> uuid.UUID:
    from app.db.models.campaign_member import CampaignMember

    return (await ev4.db.execute(sa.select(CampaignMember.id).where(
        CampaignMember.campaign_id == (campaign_id or ev4.a.campaign_id),
        CampaignMember.user_id == user_id))).scalar_one()


async def _grants(ev4) -> list[tuple]:
    """Every Member row (id, campaign, user, role, epoch), to show nothing changed."""
    from app.db.models.campaign_member import CampaignMember

    M = CampaignMember
    rows = (await ev4.db.execute(
        sa.select(M.id, M.campaign_id, M.user_id, sa.cast(M.role, sa.Text), M.access_epoch)
        .order_by(M.id).execution_options(populate_existing=True))).all()
    return [tuple(r) for r in rows]


async def _targets(ev4, actor) -> tuple[list[tuple[str, str]], uuid.UUID]:
    """(url, missing url) pairs for every id the actor must not reach, and
    A's victim member id."""
    a = ev4.a.campaign_id
    victim = await _member_id(ev4, (await ev4.make_member("player", label="victim")).id)
    hidden = await outsider(ev4)
    hidden_user = await make_member(ev4.db, role="co_gm", campaign_id=hidden.campaign_id, label="hidden_member")
    hidden_member = await _member_id(ev4, hidden_user.id, hidden.campaign_id)
    missing = f"{BASE}/{MISSING}/members/{MISSING}"
    pairs = [(f"{BASE}/{a}/members/{t}", missing)
             for t in (victim, ev4.a.owner_id, hidden_member, "not-a-uuid", MISSING)]
    # A's Member under another Campaign, and that Campaign's own Member.
    pairs += [(f"{BASE}/{hidden.campaign_id}/members/{victim}", missing),
              (f"{BASE}/{hidden.campaign_id}/members/{hidden_member}", missing)]
    if authenticated(actor):
        pairs.append((f"{BASE}/{a}/members/{await _member_id(ev4, actor.user_id)}", missing))
    if ev4.b is not None:  # cross_gm_player owns B: A's ids under B are still missing there
        b_member = await _member_id(ev4, (await make_member(ev4.db, role="player", campaign_id=ev4.b.campaign_id,
                                                            label="b_member")).id, ev4.b.campaign_id)
        pairs += [(f"{BASE}/{a}/members/{b_member}", missing),
                  (f"{BASE}/{ev4.b.campaign_id}/members/{victim}", f"{BASE}/{ev4.b.campaign_id}/members/{MISSING}")]
    return pairs, victim


@ev4_probe("GET", "/api/campaigns/{campaign_id}/me",
           actors=("anon_share", "anonymous", "player", "co_gm", "cross_gm_player"))
async def probe_my_campaign_role(ev4, actor):
    # The actor's own Role carries no Campaign content.
    r = await actor.get(f"/api/campaigns/{ev4.a.campaign_id}/me")
    assert_no_canary(actor, r)
    # A Campaign the actor is not in answers exactly like one that does not exist.
    hidden = await _hidden_campaign(ev4)
    await assert_hidden_equals_missing(actor, f"/api/campaigns/{hidden}/me", f"/api/campaigns/{MISSING}/me")
    if ev4.b is not None:  # cross_gm_player owns B; an outsider to B would 404 there too
        r = await actor.get(f"/api/campaigns/{ev4.b.campaign_id}/me")
        assert_no_canary(actor, r)


@ev4_probe("GET", "/api/campaigns/{campaign_id}/members", actors=WITH_CO_GM)
async def probe_list_members(ev4, actor):
    await _campaign_route(ev4, actor, "GET", "/members", allowed=False)


@ev4_probe("PATCH", "/api/campaigns/{campaign_id}/members/{member_id}", actors=WITH_CO_GM)
async def probe_change_member_role_escalation(ev4, actor):
    pairs, victim = await _targets(ev4, actor)
    before = await _grants(ev4)
    for url, missing in pairs:
        for body in BODIES:
            await assert_hidden_equals_missing(actor, url, missing, method="PATCH", json=body)
    after = await _grants(ev4)
    if after != before:
        record_leak(f"EV-4 leak: {actor.name} changed a Role through PATCH /members", [str(before), str(after)])
    assert after == before
    # Positive control: the Owner can promote the victim.
    owner = await ev4.actor("gm_owner")
    r = await owner.patch(f"{BASE}/{ev4.a.campaign_id}/members/{victim}", json={"role": "co_gm"})
    assert r.status_code == 200 and r.json()["role"] == "co_gm", r.text


@ev4_probe("PATCH", "/api/campaigns/{campaign_id}/members/{member_id}", actors=("co_gm",))
async def probe_demotion_closes_the_events_stream(ev4, actor):
    from app.access import grants
    from app.core import pubsub
    from app.db.models.chat import ChatSession
    from tests.ev4.probes.events import _channel, _frames

    a = ev4.a.campaign_id
    member = await _member_id(ev4, actor.user_id)
    chat = await add_chat_session(ev4, actor.user_id, [])
    owner = await ev4.actor("gm_owner")
    channels = [pubsub.campaign_events_channel(a), grants.grant_channel(a, member)]
    poll, grants.GRANT_POLL_S = grants.GRANT_POLL_S, 0.05
    try:
        async with _channel(stop_after=10_000) as client:
            request = asyncio.ensure_future(actor.get(f"{BASE}/{a}/events"))

            async def subscribed() -> bool:
                counts = dict(await client.pubsub_numsub(*channels))
                return all(int(counts.get(c, 0)) for c in channels)

            for _ in range(500):
                if request.done() or await subscribed():
                    break
                await asyncio.sleep(0.01)
            assert not request.done(), "the events stream ended before the demotion"
            assert await subscribed(), "the events stream never subscribed"
            r = await owner.patch(f"{BASE}/{a}/members/{member}", json={"role": "player"})
            assert r.status_code == 200 and r.json()["role"] == "player", r.text
            stream = await asyncio.wait_for(request, 15)
    finally:
        grants.GRANT_POLL_S = poll
    assert stream.status_code == 200, stream.text
    assert_no_canary(actor, stream)
    frames = _frames(stream.text)
    if frames[-1:] != [("access_changed", {"detail": "Not found"})]:
        record_leak(f"EV-4 leak: {actor.name}'s events stream outlived their demotion", [stream.text[-300:]])
    assert frames[-1:] == [("access_changed", {"detail": "Not found"})], frames
    archived = (await ev4.db.execute(sa.select(ChatSession.archived_at).where(ChatSession.id == chat)
                                     .execution_options(populate_existing=True))).scalar_one()
    assert archived is not None
    player_now = dataclasses.replace(actor, grants={**actor.grants, a: "player"})
    # Analytics is open to Players (E0-Access.13), so the GM-only check is a tag-category write.
    await assert_hidden_equals_missing(player_now, f"{BASE}/{a}/tag-categories",
                                       f"{BASE}/{MISSING}/tag-categories", method="POST",
                                       json={"name": "demoted-probe"})


@ev4_probe("DELETE", "/api/campaigns/{campaign_id}/members/{member_id}", actors=WITH_CO_GM)
async def probe_remove_member(ev4, actor):
    pairs, _victim = await _targets(ev4, actor)
    before = await _grants(ev4)
    for url, missing in pairs:
        await assert_hidden_equals_missing(actor, url, missing, method="DELETE")
        await assert_hidden_equals_missing(actor, f"{url}?delete_entries=true", f"{missing}?delete_entries=true",
                                           method="DELETE")
    assert await _grants(ev4) == before


async def _collaborate_link(ev4, campaign_id, owner_id, role) -> str:
    from app.db.models.share_token import CampaignShareToken

    token = secrets.token_urlsafe(24)
    ev4.db.add(CampaignShareToken(campaign_id=campaign_id, created_by_user_id=owner_id, token=token,
                                  kind="collaborate", role=role))
    await ev4.db.commit()
    return token


@ev4_probe("POST", "/api/share/{token}/join")
async def probe_join_grants_the_link_role(ev4, actor):
    from app.db.models.campaign import Campaign
    from app.db.models.campaign_member import CampaignMember

    for role, stored in (("co_gm", "co_gm"), ("player", "player"), (None, "player")):
        cid = await _hidden_campaign(ev4)
        owner_id = (await ev4.db.execute(sa.select(Campaign.user_id).where(Campaign.id == cid))).scalar_one()
        token = await _collaborate_link(ev4, cid, owner_id, role)
        r = await actor.post(f"/api/share/{token}/join")
        assert_no_canary(actor, r)
        got = (await ev4.db.execute(sa.select(sa.cast(CampaignMember.role, sa.Text)).where(
            CampaignMember.campaign_id == cid, CampaignMember.user_id == actor.user_id))).scalar_one_or_none()
        if not authenticated(actor):
            assert r.status_code in (401, 403), r.text
            continue
        assert r.status_code == 200 and r.json()["already_member"] is False, r.text
        assert got == stored, (role, got)
