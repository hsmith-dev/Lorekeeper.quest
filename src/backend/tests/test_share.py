import uuid

import pytest

from app.db.models.journal import JournalEntry

# Read-only share links are anonymous and player-facing. They must never
# return GM-private fields: NPC/quest `notes` and journal `shorthand` (the
# GM's raw session notes). See app/schemas/share.py (Public* schemas).

GM_SECRET = "GM-ONLY: the innkeeper is the lich in disguise"


async def _owner_with_shared_campaign(client, db, promo_code, kind="read_only"):
    r = await client.post("/api/auth/register", json={
        "email": f"gm_{uuid.uuid4().hex[:8]}@example.com", "password": "password123",
        "display_name": "GM", "promo_code": promo_code,
    })
    assert r.status_code in (200, 201), r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    camp = await client.post("/api/campaigns/", json={"name": "Shared Campaign", "genre": "fantasy"}, headers=headers)
    assert camp.status_code == 201, camp.text
    campaign_id = camp.json()["id"]

    npc = await client.post("/api/npcs/", json={
        "name": "Barnaby", "description": "A jovial innkeeper.", "notes": GM_SECRET, "campaign_id": campaign_id,
    }, headers=headers)
    assert npc.status_code == 201, npc.text

    quest = await client.post("/api/quests/", json={
        "title": "Find the missing caravan", "description": "Merchants vanished on the north road.",
        "notes": GM_SECRET, "campaign_id": campaign_id,
    }, headers=headers)
    assert quest.status_code == 201, quest.text

    # Inserted directly: the /journals/generate path runs spaCy + embeddings,
    # which this test doesn't need. user_id is the campaign owner.
    entry = JournalEntry(
        user_id=uuid.UUID(r.json()["user_id"]), campaign_id=uuid.UUID(campaign_id),
        shorthand=GM_SECRET, narrative="The party arrived at the Drowsy Dragon at dusk.",
        entry_hash=uuid.uuid4().hex,
    )
    db.add(entry)
    await db.commit()

    share = await client.post(f"/api/campaigns/{campaign_id}/share", json={"kind": kind}, headers=headers)
    assert share.status_code == 201, share.text
    return share.json()["token"], entry.id


@pytest.mark.asyncio
async def test_shared_npcs_and_quests_omit_gm_notes(client, db, promo_code):
    token, _ = await _owner_with_shared_campaign(client, db, promo_code)

    npcs = await client.get(f"/api/share/{token}/npcs")
    assert npcs.status_code == 200
    assert len(npcs.json()) == 1
    assert npcs.json()[0]["description"] == "A jovial innkeeper."
    assert "notes" not in npcs.json()[0]
    assert GM_SECRET not in npcs.text

    quests = await client.get(f"/api/share/{token}/quests")
    assert quests.status_code == 200
    assert len(quests.json()) == 1
    assert quests.json()[0]["description"] == "Merchants vanished on the north road."
    assert "notes" not in quests.json()[0]
    assert GM_SECRET not in quests.text


@pytest.mark.asyncio
async def test_shared_journals_omit_shorthand(client, db, promo_code):
    token, entry_id = await _owner_with_shared_campaign(client, db, promo_code)

    listing = await client.get(f"/api/share/{token}/journals")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["narrative"].startswith("The party arrived")
    assert "shorthand" not in items[0]
    assert GM_SECRET not in listing.text

    detail = await client.get(f"/api/share/{token}/journals/{entry_id}")
    assert detail.status_code == 200
    assert "shorthand" not in detail.json()
    assert GM_SECRET not in detail.text


@pytest.mark.asyncio
async def test_collaborate_token_cannot_read_content(client, db, promo_code):
    # A collaborate link only previews metadata until redeemed via /join.
    token, _ = await _owner_with_shared_campaign(client, db, promo_code, kind="collaborate")
    meta = await client.get(f"/api/share/{token}")
    assert meta.status_code == 200
    assert meta.json()["share_kind"] == "collaborate"
    for path in ("journals", "npcs", "quests"):
        r = await client.get(f"/api/share/{token}/{path}")
        assert r.status_code == 404
