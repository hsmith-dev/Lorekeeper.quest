"""EV-4 probes for the Campaign events stream (E0-Access.11).

GET /api/campaigns/{campaign_id}/events: an actor's stream of Campaign A's
invalidations. Hidden rows are added to A (a GM Entity, a GM journal
entry), plus a visible Entity. On a live fakeredis channel the probe then
publishes keyed and unkeyed invalidations for hidden rows, an always-GM
domain (`npcs`), an unknown domain, junk, a broadcast `visibility` keyed with
a hidden id, and finally a visible marker. Only a GM of A may receive a
hidden id or a GM-only domain. A Player, a GM previewing as a member and a
Player who is GM of Campaign B must receive exactly `visibility` (no id)
and the visible marker (the positive control: the stream does deliver).
No-account actors and hidden Campaigns answer exactly like a missing one.

The ASGI test client returns a response only once its body is complete, so
the probe ends the stream itself: the listener stops after the messages it
published (no other code path changes).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager

import fakeredis

from tests.ev4.families import assert_no_canary
from tests.ev4.fixtures import mint_canary
from tests.ev4.probes._support import (
    MISSING, add_entry, assert_same_answer, authenticated, is_gm_of_a, outsider, previewing,
)
from tests.ev4.registry import ev4_probe
from tests.ev4.report import record_leak

PATH = "/api/campaigns/{cid}/events"


@asynccontextmanager
async def _channel(stop_after: int):
    """A fakeredis Valkey for the app, and the events listener ending after
    `stop_after` channel messages."""
    from app.access import events as access_events
    from app.core import pubsub, valkey_client

    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    previous = valkey_client.set_valkey(client)
    real = pubsub.listen_campaign_events

    def bounded(campaign_id, *, announce=False):
        async def gen():
            seen = 0
            async for item in real(campaign_id, announce=announce):
                yield item
                if item[0] != pubsub.SUBSCRIBED_EVENT:
                    seen += 1
                    if seen >= stop_after:
                        return
        return gen()

    access_events.pubsub.listen_campaign_events = bounded
    try:
        yield client
    finally:
        access_events.pubsub.listen_campaign_events = real
        valkey_client.set_valkey(previous)
        pubsub._TRAILING.clear()
        await client.aclose()


async def _add_entity(ev4, visibility: str) -> uuid.UUID:
    from app.db.models import Entity

    cid = ev4.a.campaign_id
    row = Entity(id=uuid.uuid4(), campaign_id=cid, type="character", kind="npc", status="alive",
                 name=mint_canary("XENTITY", cid).token if visibility == "gm" else f"Visible {uuid.uuid4().hex[:6]}",
                 visibility=visibility, field_visibility={}, created_by_user_id=ev4.a.owner_id)
    ev4.db.add(row)
    await ev4.db.commit()
    return row.id


def _frames(text: str) -> list[tuple[str, object]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln]
        if not lines or not lines[0].startswith("event: "):
            continue
        data = "\n".join(ln[len("data: "):] for ln in lines[1:] if ln.startswith("data: "))
        out.append((lines[0][len("event: "):], json.loads(data) if data else None))
    return out


async def _stream(ev4, actor) -> tuple[object, list, dict]:
    from app.core import pubsub

    a = ev4.a.campaign_id
    hidden_entity = await _add_entity(ev4, "gm")
    visible_entity = await _add_entity(ev4, "party")
    hidden_entry = await add_entry(ev4, visibility="gm")
    hidden = {"entity": str(hidden_entity), "entry": str(hidden_entry)}
    marker = {"domain": "entities", "id": str(visible_entity)}
    messages = [
        {"domain": "entities", "id": hidden["entity"]},
        {"domain": "journal", "id": hidden["entry"]},
        {"domain": "entities", "id": None},
        {"domain": "npcs", "id": None},
        {"domain": "npcs", "id": str(ev4.a.ids["npcs"][0])},
        {"domain": "gm_secrets", "id": hidden["entity"]},
        {"domain": "visibility", "id": hidden["entity"]},
        {"domain": "entities", "id": hidden["entity"], "name": "leak"},
        marker,
    ]
    channel = pubsub.campaign_events_channel(a)
    async with _channel(stop_after=len(messages)) as client:
        request = asyncio.ensure_future(actor.get(PATH.format(cid=a)))

        async def subscribed() -> bool:
            result = await client.pubsub_numsub(channel)
            return bool(result and int(result[0][1]))

        for _ in range(500):
            if request.done() or await subscribed():
                break
            await asyncio.sleep(0.01)
        if not request.done():
            for data in messages:
                await client.publish(channel, json.dumps({"event": "invalidate", "data": data}))
        r = await asyncio.wait_for(request, 15)
    return r, _frames(r.text) if r.status_code == 200 else [], {"hidden": hidden, "marker": marker}


@ev4_probe("GET", "/api/campaigns/{campaign_id}/events",
           actors=("anon_share", "anonymous", "player", "co_gm", "cross_gm_player"))
async def probe_campaign_events(ev4, actor):
    a = ev4.a.campaign_id
    if not authenticated(actor):
        assert_same_answer(actor, await actor.get(PATH.format(cid=a)), await actor.get(PATH.format(cid=MISSING)),
                           "events of a Campaign without an account")
        return
    # A Campaign the actor has no grant in answers like a missing one.
    other = await outsider(ev4)
    assert_same_answer(actor, await actor.get(PATH.format(cid=other.campaign_id)),
                       await actor.get(PATH.format(cid=MISSING)), "events of a hidden Campaign")

    viewers = [actor, previewing(actor)] if is_gm_of_a(ev4, actor) else [actor]
    for viewer in viewers:
        r, frames, ids = await _stream(ev4, viewer)
        assert r.status_code == 200, r.text
        assert r.headers.get("x-accel-buffering") == "no"
        assert_no_canary(viewer, r)
        assert frames[:1] == [("subscribed", {})], frames
        invalidations = [data for event, data in frames if event == "invalidate"]
        if viewer.grants.get(a) == "gm":
            # Positive control: a GM gets the hidden keys (and still no junk keys).
            assert {"domain": "entities", "id": ids["hidden"]["entity"]} in invalidations, invalidations
            assert all(set(d) == {"domain", "id"} for d in invalidations)
            continue
        expected = [{"domain": "entities", "id": None}, {"domain": "visibility", "id": None}, ids["marker"]]
        leaked = [d for d in invalidations if d not in expected]
        if leaked or any(v in r.text for v in ids["hidden"].values()):
            record_leak(f"EV-4 leak: {viewer.name} received an invalidation about a hidden record", [r.text[-400:]])
        assert invalidations == expected, invalidations
