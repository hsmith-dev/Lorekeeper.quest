import json
from app.core.redis_client import get_redis

CACHE_TTL = 300  # 5 minutes


async def get_cached(key: str) -> dict | None:
    redis = get_redis()
    data = await redis.get(key)
    return json.loads(data) if data else None


async def set_cached(key: str, value: dict) -> None:
    redis = get_redis()
    await redis.set(key, json.dumps(value), ex=CACHE_TTL)


async def invalidate(key: str) -> None:
    redis = get_redis()
    await redis.delete(key)


def journal_list_key(user_id: str) -> str:
    return f"cache:journals:{user_id}"
