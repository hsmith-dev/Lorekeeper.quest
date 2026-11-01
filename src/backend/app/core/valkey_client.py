"""The process-wide client for the Valkey server (compose service `valkey`).

Valkey is Redis-compatible, so this is a redis-py client over a redis:// URL;
only the server changed. Key names (`llm_gate:*`, `cache:*`, `dedup:*`) are
unchanged.
"""

import redis.asyncio as aioredis
from app.core.config import get_settings

_valkey: aioredis.Redis | None = None


async def init_valkey() -> None:
    global _valkey
    settings = get_settings()
    _valkey = aioredis.from_url(settings.valkey_url, decode_responses=True)


async def close_valkey() -> None:
    if _valkey:
        await _valkey.aclose()


def get_valkey() -> aioredis.Redis:
    if _valkey is None:
        raise RuntimeError("Valkey not initialized")
    return _valkey
