import uuid
from datetime import date

import pytest
import pytest_asyncio
import sqlalchemy as sa

from app.db.models.campaign import Campaign
from app.db.models.journal import EMBEDDING_DIM, JournalEntry
from app.db.models.npc import NpcEntry, NpcRole, NpcStatus
from app.db.models.quest import Quest, QuestStatus
from app.db.models.tag import JournalTag, Tag, TagType
from app.db.models.tag_category import TagCategory

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


# --- Exact-field share responses (FR-9(a)) ----------------------------------
# The tests above check that two named fields are absent. These pin the exact
# key set of every read-only share response, so a column added to a model (or
# a field added to an owner schema) can't reach share viewers unnoticed.
# Every row is built with every column filled. _assert_every_column_filled
# catches a nullable column left unset here (a column with an ORM/server
# default is never NULL, so it passes untouched); the exact key sets are what
# catch any new key reaching the response, filled or not.

CANARY = "CANARY-GM-PRIVATE-7f3a"

CAMPAIGN_KEYS = {"id", "name", "genre", "description", "share_kind"}
JOURNAL_LIST_KEYS = {"items", "total", "page", "limit"}
JOURNAL_KEYS = {"id", "campaign_id", "narrative", "session_date", "tags", "created_at"}
TAG_KEYS = {"id", "name", "tag_type", "custom_category"}
TAG_CATEGORY_KEYS = {"id", "name", "campaign_id", "created_at"}
NPC_KEYS = {"id", "campaign_id", "name", "role", "status", "description", "created_at", "updated_at"}
QUEST_KEYS = {"id", "campaign_id", "title", "description", "status", "created_at", "updated_at"}


async def _null_columns(db, model, *where) -> list[str]:
    """Names of the model's table columns that are NULL in the row matched by
    `where`. Checked in SQL (IS NULL) so tsvector/vector columns need no decoding."""
    cols = list(model.__table__.columns)
    row = (await db.execute(sa.select(*[c.is_(None) for c in cols]).where(*where))).one()
    return [c.name for c, is_null in zip(cols, row) if is_null]


async def _assert_every_column_filled(db, model, *where) -> None:
    missing = await _null_columns(db, model, *where)
    assert not missing, f"{model.__name__} columns left unfilled in the test row: {missing}"


@pytest_asyncio.fixture
async def fully_filled_share(client, db, promo_code):
    """A read-only shared campaign whose journal entry, NPC, quest and tags
    (one built-in, one custom-category) have every column set."""
    r = await client.post("/api/auth/register", json={
        "email": f"gm_{uuid.uuid4().hex[:8]}@example.com", "password": "password123",
        "display_name": "GM", "promo_code": promo_code,
    })
    assert r.status_code in (200, 201), r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    user_id = uuid.UUID(r.json()["user_id"])

    camp = await client.post("/api/campaigns/", json={
        "name": "Fully Filled Campaign", "genre": "fantasy", "description": "Player-facing blurb.",
    }, headers=headers)
    assert camp.status_code == 201, camp.text
    campaign_id = uuid.UUID(camp.json()["id"])

    # Tags are global and unique on (name, tag_type); committed rows persist
    # across tests, so names get a per-run suffix.
    suffix = uuid.uuid4().hex[:8]
    category = TagCategory(campaign_id=campaign_id, created_by_user_id=user_id, name=f"Deity {suffix}")
    db.add(category)
    await db.flush()
    builtin_tag = Tag(name=f"Barnaby {suffix}", tag_type=TagType.character)
    custom_tag = Tag(name=f"Pelor {suffix}", custom_category_id=category.id)
    entry = JournalEntry(
        user_id=user_id, campaign_id=campaign_id,
        shorthand=CANARY, narrative="The party arrived at the Drowsy Dragon at dusk.",
        entry_hash=uuid.uuid4().hex, session_date=date(2026, 10, 31),
        embedding=[0.1] * EMBEDDING_DIM, tags=[builtin_tag, custom_tag],
    )
    npc = NpcEntry(
        user_id=user_id, campaign_id=campaign_id, name="Barnaby", role=NpcRole.npc,
        status=NpcStatus.alive, description="A jovial innkeeper.", notes=CANARY,
    )
    quest = Quest(
        user_id=user_id, campaign_id=campaign_id, title="Find the missing caravan",
        description="Merchants vanished on the north road.", status=QuestStatus.active, notes=CANARY,
    )
    db.add_all([builtin_tag, custom_tag, entry, npc, quest])
    await db.flush()
    # The app maintains narrative_tsv with raw SQL (journal_service), not via the ORM.
    await db.execute(
        sa.text("UPDATE journal_entries SET narrative_tsv = to_tsvector('english', narrative) WHERE id = :id"),
        {"id": entry.id},
    )
    await db.commit()

    await _assert_every_column_filled(db, Campaign, Campaign.id == campaign_id)
    await _assert_every_column_filled(db, TagCategory, TagCategory.id == category.id)
    await _assert_every_column_filled(db, JournalEntry, JournalEntry.id == entry.id)
    await _assert_every_column_filled(db, NpcEntry, NpcEntry.id == npc.id)
    await _assert_every_column_filled(db, Quest, Quest.id == quest.id)
    for tag in (builtin_tag, custom_tag):
        await _assert_every_column_filled(
            db, JournalTag, JournalTag.journal_id == entry.id, JournalTag.tag_id == tag.id,
        )
    # A tag sets exactly one of tag_type / custom_category_id, so each tag
    # leaves exactly that one column NULL; every other column must be set.
    assert await _null_columns(db, Tag, Tag.id == builtin_tag.id) == ["custom_category_id"]
    assert await _null_columns(db, Tag, Tag.id == custom_tag.id) == ["tag_type"]

    share = await client.post(f"/api/campaigns/{campaign_id}/share", json={"kind": "read_only"}, headers=headers)
    assert share.status_code == 201, share.text
    return {"token": share.json()["token"], "entry_id": entry.id}


def _assert_public_journal(item: dict) -> None:
    assert set(item) == JOURNAL_KEYS
    assert len(item["tags"]) == 2
    for tag in item["tags"]:
        assert set(tag) == TAG_KEYS
    builtin = [t for t in item["tags"] if t["custom_category"] is None]
    custom = [t for t in item["tags"] if t["custom_category"] is not None]
    assert len(builtin) == 1 and len(custom) == 1
    assert builtin[0]["tag_type"] == "character"
    assert custom[0]["tag_type"] is None
    assert set(custom[0]["custom_category"]) == TAG_CATEGORY_KEYS


@pytest.mark.asyncio
async def test_shared_campaign_metadata_exact_keys(client, fully_filled_share):
    r = await client.get(f"/api/share/{fully_filled_share['token']}")
    assert r.status_code == 200
    assert set(r.json()) == CAMPAIGN_KEYS
    assert CANARY not in r.text


@pytest.mark.asyncio
async def test_shared_journals_exact_keys(client, fully_filled_share):
    token = fully_filled_share["token"]

    listing = await client.get(f"/api/share/{token}/journals")
    assert listing.status_code == 200
    body = listing.json()
    assert set(body) == JOURNAL_LIST_KEYS
    assert len(body["items"]) == 1
    _assert_public_journal(body["items"][0])
    assert CANARY not in listing.text

    detail = await client.get(f"/api/share/{token}/journals/{fully_filled_share['entry_id']}")
    assert detail.status_code == 200
    _assert_public_journal(detail.json())
    assert CANARY not in detail.text


@pytest.mark.asyncio
async def test_shared_npcs_and_quests_exact_keys(client, fully_filled_share):
    token = fully_filled_share["token"]

    npcs = await client.get(f"/api/share/{token}/npcs")
    assert npcs.status_code == 200
    assert len(npcs.json()) == 1
    assert set(npcs.json()[0]) == NPC_KEYS
    assert CANARY not in npcs.text

    quests = await client.get(f"/api/share/{token}/quests")
    assert quests.status_code == 200
    assert len(quests.json()) == 1
    assert set(quests.json()[0]) == QUEST_KEYS
    assert CANARY not in quests.text
