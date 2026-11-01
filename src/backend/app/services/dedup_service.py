import uuid

from app.core.valkey_client import get_valkey

DEDUP_TTL = 86400  # 24 hours


def _key(campaign_id: uuid.UUID | str, user_id: uuid.UUID | str, entry_hash: str) -> str:
    # Per (Campaign, author), like the DB's uq_journal_entries_campaign_user_entry_hash
    # (AR-17): the same notes saved by someone else, or in another Campaign,
    # are not a duplicate, and a 409 never reveals another author's entry.
    return f"dedup:{campaign_id}:{user_id}:{entry_hash}"


async def check_hash(campaign_id: uuid.UUID | str, user_id: uuid.UUID | str, entry_hash: str) -> bool:
    valkey = get_valkey()
    return await valkey.exists(_key(campaign_id, user_id, entry_hash)) == 1


async def store_hash(campaign_id: uuid.UUID | str, user_id: uuid.UUID | str, entry_hash: str) -> None:
    valkey = get_valkey()
    await valkey.set(_key(campaign_id, user_id, entry_hash), "1", ex=DEDUP_TTL)
