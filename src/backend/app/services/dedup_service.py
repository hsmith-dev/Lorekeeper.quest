from app.core.redis_client import get_redis

DEDUP_TTL = 86400  # 24 hours


async def check_hash(entry_hash: str) -> bool:
    redis = get_redis()
    return await redis.exists(f"dedup:{entry_hash}") == 1


async def store_hash(entry_hash: str) -> None:
    redis = get_redis()
    await redis.set(f"dedup:{entry_hash}", "1", ex=DEDUP_TTL)
