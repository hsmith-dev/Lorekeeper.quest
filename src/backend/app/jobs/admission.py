"""Admission: which claimed Job may run now (AD-5, E0-Jobs.5).

The worker wrapper (app/jobs/worker.py) calls `admit` after the rights check
and before the handler. A Job that is not admitted goes back to `queued`
(its attempt not used up) with a short delay, and is pushed again when due
through the delayed set below. Two rules, checked in this order:

* Live Sessions. While `lease:live` exists (a Live Session holds it, E4), a
  kind whose `resources` intersect LIVE_BLOCKED and that is not `live_safe`
  waits LIVE_WAIT_S ("Paused for the Live Session"). `hold(name, ttl_s)`
  sets `lease:<name>` (refreshing it; holds are shared, not exclusive),
  `renew(name)` sets it again with the TTL its last `hold` stored, and
  `release(name)` deletes it. So two Live Sessions share `lease:live`: one
  `release` lifts it until the other's next `renew`.
* Heavy models. A kind whose `resources` include any of LEASED_RESOURCES
  takes `res:<resource>` for each (SET NX, value = the Job id, TTL = RQ's
  timeout for the kind; one already holding this Job's id, left by a killed
  attempt, is taken again, so a killed work horse's lease lapses no later than
  RQ's own kill). Any one taken by another Job: the ones this Job took are
  given back and it waits RESOURCE_WAIT_S ("Waiting for the model").
  Leases are released compare-and-delete after the outcome is written, so a
  Job never deletes another Job's lease. `llm` is not leased here: E0-LLM's
  `llm_slot` (app/core/llm_gate.py) serialises it.

Leases and holds live on the process-wide Valkey client
(app.core.valkey_client), like the LLM gate. Valkey not initialised or
failing: admission fails open (everything is admitted, with a warning), and a
hold, renew or release is a logged no-op.

The delayed set (`lorekeeper:jobs:delayed`, a ZSET scored by due time) is on
RQ's connection (app.jobs.outbox), since it is transport: `defer_push` adds a
deferred Job, and every non-burst worker's reaper thread runs
`drain_delayed` every second, pushing what is due once (with a distinct RQ
id). The reaper's `next_run_at` re-push is the backstop. Under JOBS_EAGER
nothing is pushed: the row stays `queued`.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.valkey_client import get_valkey
from app.domain.enums import JobQueue
from app.jobs import outbox
from app.jobs.registry import JobKind

logger = logging.getLogger(__name__)

# Resources serialised by a lease here (one Job per resource at a time).
LEASED_RESOURCES: frozenset[str] = frozenset({"nli", "stt", "tts", "ocr", "cpu_heavy"})
# Resources a Live Session keeps off the box (unless the kind is live_safe).
LIVE_BLOCKED: frozenset[str] = frozenset({"llm", "nli", "tts", "cpu_heavy"})

LIVE = "live"
LIVE_TTL_S = 90
RESOURCE_WAIT_S = 5
LIVE_WAIT_S = 15
WAITING_STAGE = "Waiting for the model"
PAUSED_STAGE = "Paused for the Live Session"

RESOURCE_KEY_PREFIX = "res:"
HOLD_KEY_PREFIX = "lease:"
# name -> the TTL its last `hold` asked for (what `renew` uses).
HOLD_TTLS_KEY = "lorekeeper:holds:ttl"
DELAYED_KEY = "lorekeeper:jobs:delayed"
DRAIN_BATCH = 500

_UNAVAILABLE = (RuntimeError, RedisError, OSError)

# Delete the key only while it still holds this Job's id.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


# ── Named holds ────────────────────────────────────────────────────────────

def _hold_key(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("hold: name must be a non-empty str")
    return f"{HOLD_KEY_PREFIX}{name}"


async def hold(name: str, ttl_s: int = LIVE_TTL_S) -> bool:
    """Set `lease:<name>` for `ttl_s` seconds (refreshing it if already set;
    not exclusive). False, logged, when Valkey is unavailable."""
    key = _hold_key(name)
    if isinstance(ttl_s, bool) or not isinstance(ttl_s, int) or ttl_s <= 0:
        raise ValueError(f"hold: ttl_s must be a positive int, got {ttl_s!r}")
    try:
        client = get_valkey()
        await client.hset(HOLD_TTLS_KEY, name, ttl_s)
        await client.set(key, "1", ex=ttl_s)
    except _UNAVAILABLE:
        logger.warning("admission: hold %r not set (Valkey unavailable)", name, exc_info=True)
        return False
    return True


async def renew(name: str) -> bool:
    """Set `lease:<name>` again with the TTL its last `hold` stored. False
    when it was never held, or Valkey is unavailable."""
    key = _hold_key(name)
    try:
        client = get_valkey()
        ttl = _text(await client.hget(HOLD_TTLS_KEY, name))
        if ttl is None:
            return False
        await client.set(key, "1", ex=int(ttl))
    except _UNAVAILABLE:
        logger.warning("admission: hold %r not renewed (Valkey unavailable)", name, exc_info=True)
        return False
    return True


async def release(name: str) -> None:
    """Delete `lease:<name>` (a later `renew` sets it again)."""
    key = _hold_key(name)
    try:
        await get_valkey().delete(key)
    except _UNAVAILABLE:
        logger.warning("admission: hold %r not released (Valkey unavailable)", name, exc_info=True)


async def is_held(name: str) -> bool:
    """Whether `lease:<name>` exists. False (fail open) when Valkey is
    unavailable."""
    key = _hold_key(name)
    try:
        return bool(await get_valkey().exists(key))
    except _UNAVAILABLE:
        logger.warning("admission: cannot read hold %r (Valkey unavailable); admitting", name, exc_info=True)
        return False


# ── Resource leases ────────────────────────────────────────────────────────

def leased(kind: JobKind) -> list[str]:
    """The resources of `kind` that take a lease here, sorted."""
    return sorted(kind.resources & LEASED_RESOURCES)


async def acquire_resources(job_id: uuid.UUID, kind: JobKind) -> list[str] | None:
    """Take `res:<r>` for every leased resource of `kind`; the ones taken, or
    None when another Job holds one (nothing stays taken). Fails open ([])."""
    wanted = leased(kind)
    if not wanted:
        return []
    taken: list[str] = []
    try:
        client = get_valkey()
        ttl = outbox.rq_timeout(kind.name)
        for resource in wanted:
            key = f"{RESOURCE_KEY_PREFIX}{resource}"
            if not await client.set(key, str(job_id), nx=True, ex=ttl):
                # This Job's own lease (left by a killed attempt, the Job
                # requeued) is taken again, not waited out.
                if _text(await client.get(key)) != str(job_id):
                    await release_resources(job_id, taken)
                    return None
                await client.set(key, str(job_id), ex=ttl)
            taken.append(resource)
    except _UNAVAILABLE:
        logger.warning("admission: resource leases unavailable (Valkey); admitting", exc_info=True)
        # A SET may have landed server-side before the client raised.
        await release_resources(job_id, wanted)
        return []
    return taken


async def release_resources(job_id: uuid.UUID, resources: list[str] | tuple[str, ...]) -> None:
    """Delete each `res:<r>` that still holds `job_id` (never another Job's)."""
    if not resources:
        return
    try:
        client = get_valkey()
        for resource in resources:
            await client.eval(_RELEASE_LUA, 1, f"{RESOURCE_KEY_PREFIX}{resource}", str(job_id))
    except _UNAVAILABLE:
        logger.warning("admission: resource leases not released (Valkey); they lapse with their TTL",
                       exc_info=True)


# ── Admission ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Deferral:
    """Not admitted: wait `delay_s`, showing `stage`."""
    delay_s: int
    stage: str


async def admit(job_id: uuid.UUID, kind: JobKind) -> list[str] | Deferral:
    """The leases taken (release them with `release_resources` after the
    outcome is written), or a Deferral. Live Sessions are checked first."""
    if not kind.live_safe and kind.resources & LIVE_BLOCKED and await is_held(LIVE):
        return Deferral(LIVE_WAIT_S, PAUSED_STAGE)
    taken = await acquire_resources(job_id, kind)
    if taken is None:
        return Deferral(RESOURCE_WAIT_S, WAITING_STAGE)
    return taken


# ── The delayed set ────────────────────────────────────────────────────────

def _member(job_id: uuid.UUID, queue: JobQueue | str, kind: str) -> str:
    return f"{job_id}|{JobQueue(queue).value}|{kind}"


def defer_push(job_id: uuid.UUID, queue: JobQueue | str, kind: str, due: datetime,
               connection: Any = None) -> None:
    """Push `job_id` again at `due` (through the delayed set). Sync (redis-py):
    call it off the event loop. Nothing under JOBS_EAGER."""
    if get_settings().jobs_eager:
        return
    conn = connection if connection is not None else outbox.get_connection()
    conn.zadd(DELAYED_KEY, {_member(job_id, queue, kind): due.timestamp()})


def drain_delayed(connection: Any, now: float | None = None) -> list[uuid.UUID]:
    """Push every delayed Job that is due, once each (a member is pushed by
    whichever worker removes it), with a distinct RQ id. A failed push puts
    the member back and stops the drain. Sync."""
    now = time.time() if now is None else now
    pushed: list[uuid.UUID] = []
    due = connection.zrangebyscore(DELAYED_KEY, "-inf", now, start=0, num=DRAIN_BATCH, withscores=True)
    for raw, score in due:
        member = _text(raw)
        if not connection.zrem(DELAYED_KEY, raw):
            continue  # another worker took it
        try:
            job_text, queue, kind = member.split("|", 2)
            job_id = uuid.UUID(job_text)
            JobQueue(queue)
        except ValueError:
            logger.warning("admission: dropped a malformed delayed entry %r", member)
            continue
        try:
            outbox.push(job_id, queue, kind, connection, rq_id=outbox.distinct_rq_id(job_id))
        except Exception:
            connection.zadd(DELAYED_KEY, {raw: score})
            logger.warning("admission: delayed push failed; retried next drain", exc_info=True,
                           extra={"job_id": str(job_id), "kind": kind})
            break
        pushed.append(job_id)
    return pushed


__all__ = [
    "DELAYED_KEY", "LEASED_RESOURCES", "LIVE", "LIVE_BLOCKED", "LIVE_TTL_S", "LIVE_WAIT_S", "PAUSED_STAGE",
    "RESOURCE_WAIT_S", "WAITING_STAGE", "Deferral", "acquire_resources", "admit", "defer_push",
    "drain_delayed", "hold", "is_held", "leased", "release", "release_resources", "renew",
]
