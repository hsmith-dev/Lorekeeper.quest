"""EV-4 probes for grant changes (E0-Access.10).

A grant change applies on the very next chunk and the very next request:

* POST /api/chat/stream: the actor's grant in Campaign A changes mid-stream
  (a co-GM is demoted to Player, a Player is removed). No delta after the
  change reaches them, the stream ends with `error {"detail":"Not found"}`,
  and their next request answers per the new grant: a removed actor gets
  the one 404 of a missing Campaign, a demoted one Party-only content.
* DELETE /api/campaigns/{id}/members/{member_id}: after the Owner removes
  the actor, their still-valid JWT reads every Campaign route of A exactly
  like a missing Campaign.
* DELETE /api/campaigns/{id}/share/{token_id}: after the Owner revokes A's
  Share Link, every share URL of it answers like an unknown token.

No Valkey runs in the suite, so the stream closes through grant_watch's poll
(shortened here); tests/access/test_grants.py covers the `access:` message.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ev4.families import assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import MISSING, UNKNOWN_TOKEN, assert_same_answer, authenticated, outsider
from tests.ev4.probes.retrieval import fake_embeddings, index_seeded, use_fake_llm
from tests.ev4.registry import ev4_probe
from tests.ev4.report import record_leak

BASE = "/api/campaigns"
MEMBERS = ("player", "co_gm", "cross_gm_player")
AFTER = "AFTER-THE-GRANT-CHANGE"


@contextmanager
def _scripted_stream(during):
    """llm_provider.stream_messages yields one delta, runs `during()`, then
    would yield AFTER ten seconds later; grant_watch polls every 50 ms."""
    from app.access import grants
    from app.services import llm_provider

    state = {"closed": False}

    async def fake(messages, config=None, **kwargs):
        try:
            yield "Before the change. "
            await during()
            await asyncio.sleep(10)
            yield AFTER
        finally:
            state["closed"] = True

    real, poll = llm_provider.stream_messages, grants.GRANT_POLL_S
    llm_provider.stream_messages, grants.GRANT_POLL_S = fake, 0.05
    try:
        yield state
    finally:
        llm_provider.stream_messages, grants.GRANT_POLL_S = real, poll


async def _grant(ev4, actor):
    from app.db.models.campaign_member import CampaignMember

    return (await ev4.db.execute(sa.select(CampaignMember.id).where(
        CampaignMember.campaign_id == ev4.a.campaign_id, CampaignMember.user_id == actor.user_id))).scalar_one()


async def _in_own_session(ev4, fn) -> None:
    async with AsyncSession(bind=ev4.db.bind, expire_on_commit=False) as s:
        await fn(s)
        await s.commit()


def _events(text: str) -> list[str]:
    return [block.split("\n", 1)[0].removeprefix("event: ") for block in text.strip().split("\n\n") if block]


async def _gone_from_a(ev4, actor) -> None:
    """Every Campaign route of A answers the removed actor like a missing Campaign."""
    a = ev4.a.campaign_id
    for path in ("", "/me", "/tag-categories"):
        await assert_hidden_equals_missing(actor, f"{BASE}/{a}{path}", f"{BASE}/{MISSING}{path}")


@ev4_probe("POST", "/api/chat/stream", actors=("anon_share", "player", "co_gm", "cross_gm_player"))
async def probe_chat_stream_closes_on_grant_change(ev4, actor):
    from app.access import change_member_role, remove_member
    from app.db.models.campaign_member import CampaignMember

    a = ev4.a.campaign_id
    body = {"message": "What happened at the Drowsy Dragon?", "campaign_id": str(a)}
    if not authenticated(actor):
        # No account: no stream, and A answers exactly like a missing Campaign.
        assert_same_answer(actor, await actor.post("/api/chat/stream", json=body),
                                 await actor.post("/api/chat/stream", json={**body, "campaign_id": MISSING}),
                                 "chat stream Campaign")
        return
    grant = await _grant(ev4, actor)
    demote = actor.name == "co_gm"

    async def change():
        async def fn(s):
            member = await s.get(CampaignMember, grant)
            if demote:
                await change_member_role(s, member, "player")
            else:
                await remove_member(s, member)
        await _in_own_session(ev4, fn)

    await use_fake_llm(ev4, actor)
    with fake_embeddings():
        await index_seeded(ev4)
        with _scripted_stream(change) as state:
            r = await asyncio.wait_for(actor.post("/api/chat/stream", json=body), 10)
        assert_no_canary(actor, r)
        events = _events(r.text)
        last = r.text.strip().rsplit("\n\n", 1)[-1]
        if AFTER in r.text or events[-1:] != ["error"] or json.loads(last.split("data: ", 1)[1]) != {
                "detail": "Not found"}:
            record_leak(f"EV-4 leak: {actor.name}'s stream kept going after their grant changed", [r.text[-300:]])
        assert state["closed"], "the upstream stream was not closed"
        if demote:
            # Now a Player of A: the next stream is Party-only (judged as a Player).
            player_now = dataclasses.replace(actor, grants={**actor.grants, a: "player"})
            r = await player_now.post("/api/chat/stream", json=body)
            assert r.status_code == 200, r.text
            assert_no_canary(player_now, r)
            await assert_hidden_equals_missing(player_now, f"{BASE}/{a}/analytics", f"{BASE}/{MISSING}/analytics")
        else:
            await _gone_from_a(ev4, actor)
            assert_same_answer(actor, await actor.post("/api/chat/stream", json=body),
                               await actor.post("/api/chat/stream", json={**body, "campaign_id": MISSING}),
                               "chat stream Campaign after removal")


@ev4_probe("DELETE", "/api/campaigns/{campaign_id}/members/{member_id}", actors=("anon_share",) + MEMBERS)
async def probe_removed_member_jwt(ev4, actor):
    if not authenticated(actor):
        hidden = await outsider(ev4)
        await assert_hidden_equals_missing(actor, f"{BASE}/{hidden.campaign_id}", f"{BASE}/{MISSING}")
        return
    owner = await ev4.actor("gm_owner")
    r = await owner.delete(f"{BASE}/{ev4.a.campaign_id}/members/{await _grant(ev4, actor)}")
    assert r.status_code == 204, r.text
    await _gone_from_a(ev4, actor)  # the JWT is still valid; the grant is not


@ev4_probe("DELETE", "/api/campaigns/{campaign_id}/share/{token_id}", actors=("anon_share", "player", "co_gm"))
async def probe_revoked_share_link(ev4, actor):
    from app.db.models.share_token import CampaignShareToken

    token = ev4.a.share_token
    r = await actor.get(f"/api/share/{token}")
    assert r.status_code == 200, r.text  # live before the revocation
    token_id = (await ev4.db.execute(
        sa.select(CampaignShareToken.id).where(CampaignShareToken.token == token))).scalar_one()
    owner = await ev4.actor("gm_owner")
    r = await owner.delete(f"{BASE}/{ev4.a.campaign_id}/share/{token_id}")
    assert r.status_code == 204, r.text
    for suffix in ("", "/journals", "/npcs", "/quests"):
        await assert_hidden_equals_missing(actor, f"/api/share/{token}{suffix}", f"/api/share/{UNKNOWN_TOKEN}{suffix}")
