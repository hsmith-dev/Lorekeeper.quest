"""EV-4 probes for api/routes/members.py (E0-Access)."""
from __future__ import annotations

import uuid

from tests.ev4.families import assert_hidden_equals_missing, assert_no_canary
from tests.ev4.fixtures import create_user
from tests.ev4.registry import ev4_probe

MISSING = "00000000-0000-4000-8000-000000000000"


async def _hidden_campaign(ev4) -> uuid.UUID:
    """A Campaign nobody in the actor set owns or belongs to."""
    from app.db.models.campaign import Campaign, Genre

    owner = await create_user(ev4.db, "members_probe_owner")
    cid = uuid.uuid4()
    ev4.db.add(Campaign(id=cid, user_id=owner.id, name="Hidden", genre=Genre.fantasy))
    await ev4.db.commit()
    return cid


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
