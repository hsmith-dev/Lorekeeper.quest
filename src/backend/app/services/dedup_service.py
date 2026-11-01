from app.core.valkey_client import get_valkey

DEDUP_TTL = 86400  # 24 hours


async def check_hash(entry_hash: str) -> bool:
    valkey = get_valkey()
    return await valkey.exists(f"dedup:{entry_hash}") == 1


async def store_hash(entry_hash: str) -> None:
    valkey = get_valkey()
    await valkey.set(f"dedup:{entry_hash}", "1", ex=DEDUP_TTL)
