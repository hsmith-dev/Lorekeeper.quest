"""Cache keys that depend on who is asking (E0-Access.10, AD-13).

    value = await cached_json(ctx, "journals", "list", page, compute=lambda: build(...))

Every key is `cache:{campaign_id}:{generation}:{audience}:{access_epoch}:{domain}:…`,
built only here (tests/access/test_grants.py scans app/ for any other
`cache:` literal). The audience and the grant's epoch are in the key, so a
demoted Member, a member preview and a Share Link never read one another's
values, and a grant change makes the old values unreachable.

`generation` is a per-Campaign counter at `cachegen:{campaign_id}` (outside
the `cache:{campaign_id}:*` pattern). A reader reads it before computing; a
missing one is seeded with `SET NX time_ns()`, so a reset never reuses an old
value. `invalidate_campaign_cache` increments it, then deletes
`cache:{campaign_id}:*`: a value computed before an invalidation is written
under a dead generation (and `cached_json` skips the write when the
generation moved during the compute), so it is never served.

No Valkey client (tests, scripts) means nothing is cached. A Valkey error is
logged and the value computed, never raised.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from app.access.audience import Audience, AudienceLevel
from app.access.context import CampaignContext

logger = logging.getLogger(__name__)

CACHE_TTL_S = 300
CACHE_SCAN_COUNT = 500
KEY_PREFIX = "cache:"
GENERATION_PREFIX = "cachegen:"


def _client() -> Any | None:
    from app.core.valkey_client import get_valkey

    try:
        return get_valkey()
    except RuntimeError:
        return None


def generation_key(campaign_id: uuid.UUID) -> str:
    return f"{GENERATION_PREFIX}{campaign_id}"


def campaign_pattern(campaign_id: uuid.UUID) -> str:
    """The SCAN pattern of every cache key of the Campaign."""
    return f"{KEY_PREFIX}{campaign_id}:*"


def audience_token(audience: Audience) -> str:
    """The key segment of an Audience: `gm`, `members`, `public` or `owner.<uuid>`."""
    if audience.level is AudienceLevel.OWNER:
        return f"owner.{audience.user_id}"
    return audience.level.value


def _escape(value: Any) -> str:
    """`%` and `:` percent-escaped, so ("a:b",) and ("a", "b") never collide."""
    return str(value).replace("%", "%25").replace(":", "%3A")


def cache_key(ctx: CampaignContext, generation: int | str, domain: str, *parts: Any) -> str:
    """`cache:{campaign_id}:{generation}:{audience}:{access_epoch}:{domain}:…`,
    with the domain and parts escaped."""
    if not isinstance(ctx, CampaignContext):
        raise TypeError("cache_key: needs a CampaignContext")
    if not isinstance(domain, str) or not domain:
        raise ValueError("cache_key: domain must be a non-empty string")
    fields = [str(ctx.campaign_id), _escape(generation), audience_token(ctx.audience), str(ctx.access_epoch),
              _escape(domain), *(_escape(p) for p in parts)]
    return KEY_PREFIX + ":".join(fields)


async def cache_generation(client: Any, campaign_id: uuid.UUID) -> str:
    """The Campaign's current generation, seeded with `SET NX time_ns()`
    when missing (first use, or evicted)."""
    key = generation_key(campaign_id)
    value = await client.get(key)
    if value is None:
        await client.set(key, time.time_ns(), nx=True)
        value = await client.get(key)
    return value.decode() if isinstance(value, bytes) else str(value)


async def cached_json(ctx: CampaignContext, domain: str, *parts: Any,
                      compute: Callable[[], Awaitable[Any]], ttl: int = CACHE_TTL_S) -> Any:
    """The cached JSON value for (ctx, domain, *parts), else `await compute()`
    (stored for `ttl` seconds unless an invalidation ran meanwhile)."""
    client = _client()
    if client is None:
        return await compute()
    try:
        generation = await cache_generation(client, ctx.campaign_id)
        key = cache_key(ctx, generation, domain, *parts)
        hit = await client.get(key)
    except Exception:
        logger.warning(json.dumps({"event": "cache_read_failed", "campaign_id": str(ctx.campaign_id)}),
                       exc_info=True)
        return await compute()
    if hit is not None:
        try:
            return json.loads(hit)
        except ValueError:  # corrupt: recompute (and overwrite)
            logger.warning(json.dumps({"event": "cache_read_failed", "campaign_id": str(ctx.campaign_id)}),
                           exc_info=True)
    value = await compute()
    try:
        if await cache_generation(client, ctx.campaign_id) == generation:
            await client.set(key, json.dumps(value), ex=ttl)
    except Exception:
        logger.warning(json.dumps({"event": "cache_write_failed", "campaign_id": str(ctx.campaign_id)}),
                       exc_info=True)
    return value


async def invalidate_campaign_cache(campaign_id: uuid.UUID) -> None:
    """Increment the Campaign's generation, then delete every
    `cache:{campaign_id}:*` key. Never raises."""
    client = _client()
    if client is None:
        return
    try:
        gen = generation_key(campaign_id)
        await client.set(gen, time.time_ns(), nx=True)  # never INCR a missing key from 0
        await client.incr(gen)
        batch: list[str] = []
        async for key in client.scan_iter(match=campaign_pattern(campaign_id), count=CACHE_SCAN_COUNT):
            batch.append(key)
            if len(batch) >= CACHE_SCAN_COUNT:
                await client.unlink(*batch)
                batch = []
        if batch:
            await client.unlink(*batch)
    except Exception:
        logger.warning(json.dumps({"event": "cache_invalidate_failed", "campaign_id": str(campaign_id)}),
                       exc_info=True)
