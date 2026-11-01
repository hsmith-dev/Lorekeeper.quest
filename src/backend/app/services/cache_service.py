import json
from app.core.valkey_client import get_valkey

CACHE_TTL = 300  # 5 minutes


async def get_cached(key: str) -> dict | None:
    valkey = get_valkey()
    data = await valkey.get(key)
    return json.loads(data) if data else None


async def set_cached(key: str, value: dict) -> None:
    valkey = get_valkey()
    await valkey.set(key, json.dumps(value), ex=CACHE_TTL)


async def invalidate(key: str) -> None:
    valkey = get_valkey()
    await valkey.delete(key)


def journal_list_key(user_id: str) -> str:
    return f"cache:journals:{user_id}"
