import uuid

from app.core.valkey_client import get_valkey

DEDUP_TTL = 86400  # 24 hours


def _key(campaign_id: uuid.UUID | str, user_id: uuid.UUID | str, entry_hash: str) -> str:
    # Per (Campaign, author), like ix_journal_entries_campaign_user_entry_hash
    # (AR-17). Never decides a 409 (E0-Journal.2): it cannot tell an entry the
    # writer can see from a hidden one; journal_service.visible_duplicate does.
    return f"dedup:{campaign_id}:{user_id}:{entry_hash}"


async def check_hash(campaign_id: uuid.UUID | str, user_id: uuid.UUID | str, entry_hash: str) -> bool:
    valkey = get_valkey()
    return await valkey.exists(_key(campaign_id, user_id, entry_hash)) == 1


async def store_hash(campaign_id: uuid.UUID | str, user_id: uuid.UUID | str, entry_hash: str) -> None:
    valkey = get_valkey()
    await valkey.set(_key(campaign_id, user_id, entry_hash), "1", ex=DEDUP_TTL)


async def drop_hash(campaign_id: uuid.UUID | str, user_id: uuid.UUID | str, entry_hash: str) -> None:
    """Forget a hash (its entry was deleted, or edited to other notes)."""
    valkey = get_valkey()
    await valkey.delete(_key(campaign_id, user_id, entry_hash))
