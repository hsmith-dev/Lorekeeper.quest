"""EV-4 probes for api/routes/entity_legacy.py, the old-link resolver
(E0-WorldCore.6): `GET /api/entities/legacy/{npc|quest}/{legacy_id}`.

Campaign A: the seeded NPC and Quest as GM-only Entities (F3 ids); a
published NPC Entity (legacy id L1); a published NPC merged into a published
survivor (L2) and one merged into a GM-only survivor (L3); a deleted
published NPC (L4). An outsider Campaign's published NPC (L5).

For a non-GM of A: GM-only, deleted, merged (a merged-away Entity is GM-only,
so a non-GM never follows a merge), the other kind, another Campaign's, an
unknown `legacy_type` and a missing id all answer like a missing id; the
published one resolves to its Entity. A GM of A resolves every live one, and
a merged one to its survivor.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from tests.ev4.families import assert_hidden_equals_missing, assert_no_canary
from tests.ev4.fixtures import mint_canary
from tests.ev4.probes._support import MISSING, authenticated, is_gm_of_a, outsider, publish, world_npc, world_quest
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

BASE = "/api/entities/legacy"


@dataclass
class Links:
    npc: uuid.UUID            # seeded NPC, GM-only
    quest: uuid.UUID          # seeded Quest, GM-only
    shown: uuid.UUID          # published
    shown_entity: uuid.UUID
    merged: uuid.UUID         # published, merged into a published survivor
    survivor: uuid.UUID
    merged_hidden: uuid.UUID  # published, merged into a GM-only survivor
    deleted: uuid.UUID        # published, then deleted
    other: uuid.UUID          # another Campaign's published NPC


async def _npc(ev4, gm, legacy_id: uuid.UUID, *, name: str | None = None, seeded=None) -> uuid.UUID:
    from app.domain import legacy_world as lw
    from app.services.world_service import apply_change

    seeded = seeded or ev4.a
    entity_id = lw.legacy_entity_id("npc", legacy_id)
    await apply_change(ev4.db, gm, {"op": "create_entity", "entity_id": entity_id, "legacy_npc_id": legacy_id,
                                    "type": "character", "kind": "npc",
                                    "name": name or mint_canary("XLEGACY", seeded.campaign_id).token})
    await ev4.db.commit()
    return entity_id


async def _links(ev4) -> Links:
    from app.access import ctx_for
    from app.services.world_service import apply_change

    db, a = ev4.db, ev4.a.campaign_id
    gm = await ctx_for(db, ev4.a.owner_id, a)
    npc, quest = await world_npc(ev4), await world_quest(ev4)
    shown, merged, merged_hidden, deleted = (uuid.uuid4() for _ in range(4))
    shown_entity = await _npc(ev4, gm, shown, name="Mira")
    merged_entity = await _npc(ev4, gm, merged, name="Old Mira")
    hidden_absorbed = await _npc(ev4, gm, merged_hidden, name="Other Mira")
    deleted_entity = await _npc(ev4, gm, deleted, name="Gone Mira")
    survivor = (await apply_change(db, gm, {"op": "create_entity", "type": "character", "kind": "npc",
                                            "name": "Mira the Elder"})).entity_id
    hidden_survivor = (await apply_change(db, gm, {"op": "create_entity", "type": "character", "kind": "npc",
                                                   "name": mint_canary("XSURVIVOR", a).token})).entity_id
    await db.commit()
    for eid in (shown_entity, merged_entity, hidden_absorbed, deleted_entity, survivor):
        await publish(ev4, eid)
    await apply_change(db, gm.as_system("merge"), {"op": "merge", "entity_id": merged_entity, "survivor_id": survivor})
    await apply_change(db, gm.as_system("merge"), {"op": "merge", "entity_id": hidden_absorbed,
                                                   "survivor_id": hidden_survivor})
    await apply_change(db, gm, {"op": "delete_entity", "entity_id": deleted_entity})
    await db.commit()

    seeded = await outsider(ev4)
    other = uuid.uuid4()
    other_gm = await ctx_for(db, seeded.owner_id, seeded.campaign_id)
    await publish(ev4, await _npc(ev4, other_gm, other, seeded=seeded), seeded=seeded)
    return Links(npc=npc, quest=quest, shown=shown, shown_entity=shown_entity, merged=merged, survivor=survivor,
                 merged_hidden=merged_hidden, deleted=deleted, other=other)


@ev4_probe("GET", "/api/entities/legacy/{legacy_type}/{legacy_id}", actors=(*DEFAULT_ACTORS, "player_2", "co_gm"))
async def probe_resolve_legacy_link(ev4, actor):
    links = await _links(ev4)
    missing = f"{BASE}/npc/{MISSING}"
    gm = is_gm_of_a(ev4, actor)

    async def resolves(url: str, entity_id: uuid.UUID, entity_type: str) -> None:
        r = await actor.get(url)
        assert_no_canary(actor, r)
        if r.status_code != 200 or r.json() != {"entity_id": str(entity_id), "type": entity_type}:
            raise AssertionError(f"{actor.name}: {url} -> {r.status_code} {r.text[:200]}")

    # Always hidden from this actor: another Campaign's, the other kind, an
    # unknown type, a non-UUID, a deleted one.
    always = [f"{BASE}/npc/{links.other}", f"{BASE}/quest/{links.npc}", f"{BASE}/npc/{links.quest}",
              f"{BASE}/item/{links.npc}", f"{BASE}/npc/not-a-uuid", f"{BASE}/npc/{links.deleted}"]
    for url in always:
        await assert_hidden_equals_missing(actor, url, missing)
    if gm:
        from app.domain import legacy_world as lw

        await resolves(f"{BASE}/npc/{links.npc}", lw.legacy_entity_id("npc", links.npc), "character")
        await resolves(f"{BASE}/quest/{links.quest}", lw.legacy_entity_id("quest", links.quest), "quest")
        await resolves(f"{BASE}/npc/{links.shown}", links.shown_entity, "character")
        await resolves(f"{BASE}/npc/{links.shown_entity}", links.shown_entity, "character")  # an Entity id
        await resolves(f"{BASE}/npc/{links.merged}", links.survivor, "character")
        r = await actor.get(f"{BASE}/npc/{links.merged_hidden}")
        assert r.status_code == 200, r.text  # the GM sees the GM-only survivor
        return
    # GM-only, and merged (a merged-away Entity is GM-only): like missing.
    for url in (f"{BASE}/npc/{links.npc}", f"{BASE}/quest/{links.quest}", f"{BASE}/npc/{links.merged}",
                f"{BASE}/npc/{links.merged_hidden}"):
        await assert_hidden_equals_missing(actor, url, missing)
    if not authenticated(actor):
        return
    # The audience ladder: every Member resolves the published link, to the same Entity.
    await resolves(f"{BASE}/npc/{links.shown}", links.shown_entity, "character")
    # An Entity id (the legacy lists show newer Entities under it) resolves alike.
    await resolves(f"{BASE}/npc/{links.shown_entity}", links.shown_entity, "character")
