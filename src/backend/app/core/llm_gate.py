"""One priority gate in front of the local LLM (AD-2, E0-LLM.2).

The platform's own Ollama serves one request at a time on the Reference Box
(OLLAMA_NUM_PARALLEL=1). Without a gate, whichever call arrives first wins, so
a background Job can sit in front of a live Rolling Recap or a GM's question.
This module is a Valkey (Redis-protocol) priority semaphore every platform-LLM
call goes through:

    async with llm_slot(GateClass.job_backfill):
        ...  # at most `capacity` of these run at once, across all workers

Classes, highest priority first: live_recap, gm_interactive,
player_interactive, job_onsave, job_backfill. Within a class it is first in,
first out. A running call is never preempted; priority only decides who goes
next.

Redis layout (keys only, no pub/sub — the pub/sub budget is three channels):

- `<prefix>:holders`        ZSET token -> expiry (ms). A holder renews every
  `renew_every_s`; a crashed holder simply stops renewing and its entry is
  purged once it expires, so its slot comes back on its own.
- `<prefix>:waiters`        ZSET token -> priority * 10**13 + arrival_ms.
  Lowest score is next. Equal scores fall back to the member string, and the
  token embeds a nanosecond timestamp, so same-millisecond arrivals in one
  class stay in order.
- `<prefix>:waiters_seen`   ZSET token -> last poll (ms). A waiter whose
  process died stops polling and is purged after `waiter_stale_s`; without
  this it would sit at the head of the queue forever.

One Lua script does purge + enqueue + grant atomically; waiters poll it every
`poll_s`, re-submitting their original score, so a waiter that was briefly
purged (a stalled event loop) gets its old place back.

Behaviour callers rely on:

- Reentrant: inside a held slot (this task's context) a nested acquire is a
  no-op, so wrapping several provider calls in one `llm_slot` never deadlocks
  at capacity 1.
- Wait budget: explicit `wait_s`, else `current_deadline` (a time.monotonic()
  deadline the Jobs wrapper sets from the Job's remaining timeout), else
  settings.llm_gate_wait_s. Running out raises errors.LLMBusy (503 llm_busy).
- Fails open: if Redis is not initialised or errors, the call runs ungated
  with a warning. Ollama still serialises requests itself, so losing the gate
  loses ordering, never correctness — and it must not block AI features.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from enum import StrEnum

from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import LLMBusy
from app.core.valkey_client import get_valkey

logger = logging.getLogger(__name__)


class GateClass(StrEnum):
    live_recap = "live_recap"
    gm_interactive = "gm_interactive"
    player_interactive = "player_interactive"
    job_onsave = "job_onsave"
    job_backfill = "job_backfill"


# Lower number = served first.
PRIORITY: dict[GateClass, int] = {
    GateClass.live_recap: 0,
    GateClass.gm_interactive: 1,
    GateClass.player_interactive: 2,
    GateClass.job_onsave: 3,
    GateClass.job_backfill: 4,
}

_PRIORITY_STRIDE = 10**13  # > any ms timestamp this century, < 2**53 / 5

# The class a call uses when it doesn't name one. Routes default to
# gm_interactive; the Jobs wrapper sets its queue's class here.
current_class: contextvars.ContextVar[GateClass] = contextvars.ContextVar(
    "llm_gate_current_class", default=GateClass.gm_interactive
)
# time.monotonic() deadline for gate waits in this context (Jobs: the Job's
# remaining timeout_s). None = use settings.llm_gate_wait_s.
current_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "llm_gate_current_deadline", default=None
)
# True while this context holds a slot — what makes nested acquires no-ops.
_held: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_gate_held", default=False)

_QUEUE_CLASSES = {
    "onsave": GateClass.job_onsave,
    "backfill": GateClass.job_backfill,
    "interactive": GateClass.gm_interactive,
}


def class_for_queue(queue: str) -> GateClass:
    """Gate class for an E0-Jobs queue name."""
    try:
        return _QUEUE_CLASSES[queue]
    except KeyError:
        raise ValueError(f"unknown job queue {queue!r}; expected one of {sorted(_QUEUE_CLASSES)}") from None


def _coerce(cls: GateClass | str | None) -> GateClass:
    if cls is None:
        return current_class.get()
    return GateClass(cls)  # ValueError for an unknown name


def _log(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, json.dumps({"event": event, **fields}))


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


# KEYS: holders, waiters, seen
# ARGV: token, score, now_ms, capacity, holder_ttl_ms, waiter_stale_ms
# Returns 1 when granted (token is now a holder), 0 when still queued.
_ACQUIRE_LUA = """
local holders, waiters, seen = KEYS[1], KEYS[2], KEYS[3]
local token = ARGV[1]
local now = tonumber(ARGV[3])
local capacity = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local stale = tonumber(ARGV[6])

redis.call('ZREMRANGEBYSCORE', holders, '-inf', now)
local dead = redis.call('ZRANGEBYSCORE', seen, '-inf', now - stale)
for _, t in ipairs(dead) do
  redis.call('ZREM', waiters, t)
  redis.call('ZREM', seen, t)
end

if redis.call('ZSCORE', holders, token) then
  return 1
end

redis.call('ZADD', waiters, ARGV[2], token)
redis.call('ZADD', seen, now, token)

local free = capacity - redis.call('ZCARD', holders)
if free > 0 then
  local rank = redis.call('ZRANK', waiters, token)
  if rank and rank < free then
    redis.call('ZREM', waiters, token)
    redis.call('ZREM', seen, token)
    redis.call('ZADD', holders, now + ttl, token)
    return 1
  end
end
return 0
"""

# KEYS: holders. ARGV: token, new_expiry_ms. 1 = renewed, 0 = no longer held.
_RENEW_LUA = """
if redis.call('ZSCORE', KEYS[1], ARGV[1]) then
  redis.call('ZADD', KEYS[1], ARGV[2], ARGV[1])
  return 1
end
return 0
"""


# Strong refs for shielded cleanup tasks, so they can't be garbage collected
# while the cancelled caller has stopped awaiting them.
_cleanup_tasks: set[asyncio.Task] = set()


async def _shielded(coro) -> None:
    """Run coro to completion even if the awaiting task is cancelled (the
    caller still sees its CancelledError)."""
    task = asyncio.ensure_future(coro)
    _cleanup_tasks.add(task)
    task.add_done_callback(_cleanup_tasks.discard)
    await asyncio.shield(task)


class Slot:
    """A granted slot. `release()` is idempotent and safe to call from a
    `finally`; `held()` marks the current context as holding it so nested
    acquires are no-ops. A Slot with no gate is the no-op slot used for BYOK,
    fail-open and reentrant acquires."""

    def __init__(self, gate: LLMGate | None = None, token: str | None = None, cls: GateClass | None = None):
        self._gate = gate
        self._token = token
        self.gate_class = cls
        self._renewal: asyncio.Task | None = None
        self._released = gate is None

    @property
    def is_noop(self) -> bool:
        return self._gate is None

    def _start_renewal(self) -> None:
        if self._gate is not None:
            self._renewal = asyncio.create_task(self._gate._renew_loop(self._token))

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._renewal is not None:
            self._renewal.cancel()
            self._renewal = None
        assert self._gate is not None and self._token is not None
        # Shielded: a cancelled caller (SSE client disconnect under an anyio
        # cancel scope) must not abort the removal and leave the holder
        # lingering until its TTL.
        await _shielded(self._gate._release(self._token))

    @contextmanager
    def held(self) -> Iterator[Slot]:
        reset = _held.set(True)
        try:
            yield self
        finally:
            try:
                _held.reset(reset)
            except ValueError:
                # Closed from another context (e.g. an SSE generator finalised
                # by a different task): nothing of ours left to restore.
                pass


class LLMGate:
    def __init__(
        self,
        redis,
        *,
        capacity: int,
        wait_s: float,
        key_prefix: str = "llm_gate",
        holder_ttl_s: float = 30,
        renew_every_s: float = 10,
        poll_s: float = 0.1,
        waiter_stale_s: float = 5,
        clock: Callable[[], int] = _wall_ms,
    ):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.redis = redis
        self.capacity = capacity
        self.wait_s = wait_s
        self.key_prefix = key_prefix
        self.holders_key = f"{key_prefix}:holders"
        self.waiters_key = f"{key_prefix}:waiters"
        self.seen_key = f"{key_prefix}:waiters_seen"
        self.holder_ttl_ms = int(holder_ttl_s * 1000)
        self.renew_every_s = renew_every_s
        self.poll_s = poll_s
        self.waiter_stale_ms = int(waiter_stale_s * 1000)
        self.clock = clock
        self._acquire_script = redis.register_script(_ACQUIRE_LUA)
        self._renew_script = redis.register_script(_RENEW_LUA)

    @property
    def keys(self) -> list[str]:
        return [self.holders_key, self.waiters_key, self.seen_key]

    def _budget(self, wait_s: float | None) -> float:
        if wait_s is not None:
            return max(0.0, wait_s)
        deadline = current_deadline.get()
        if deadline is not None:
            return max(0.0, deadline - time.monotonic())
        return self.wait_s

    async def acquire(self, cls: GateClass | str, *, wait_s: float | None = None) -> Slot:
        """Queue for a slot and return it once granted, or raise LLMBusy when
        the wait budget runs out. Cancellation while waiting removes the
        waiter entry and propagates."""
        cls = GateClass(cls)
        token = f"{cls}:{time.time_ns():020d}:{secrets.token_hex(4)}"
        score = PRIORITY[cls] * _PRIORITY_STRIDE + self.clock()
        budget = self._budget(wait_s)
        started = time.monotonic()
        deadline = started + budget
        polls = 0
        try:
            while True:
                granted = await self._acquire_script(
                    keys=self.keys,
                    args=[token, score, self.clock(), self.capacity, self.holder_ttl_ms, self.waiter_stale_ms],
                )
                if int(granted) == 1:
                    break
                polls += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    await self._discard_quietly(token)
                    _log("llm_gate_busy", logging.WARNING, gate_class=str(cls),
                         waited_ms=int((time.monotonic() - started) * 1000))
                    raise LLMBusy("The AI model is busy right now. Please try again in a moment.")
                await asyncio.sleep(min(self.poll_s, remaining))
        except (asyncio.CancelledError, RedisError, OSError):
            # The Lua grant may already have run server-side, so remove the
            # token from holders too, or it would be an orphan with no renewal.
            await self._discard_quietly(token)
            raise
        if polls:
            _log("llm_gate_granted", gate_class=str(cls), waited_ms=int((time.monotonic() - started) * 1000))
        slot = Slot(self, token, cls)
        slot._start_renewal()
        return slot

    async def _discard_quietly(self, token: str) -> None:
        """Remove token from all three keys, shielded from cancellation;
        errors are logged and swallowed (the stale-waiter purge and holder
        TTL clean up after us anyway)."""
        await _shielded(self._release(token))

    async def _release(self, token: str) -> None:
        try:
            pipe = self.redis.pipeline(transaction=True)
            for key in self.keys:
                pipe.zrem(key, token)
            await pipe.execute()
        except Exception as exc:  # holder TTL frees the slot if this fails
            _log("llm_gate_release_failed", logging.WARNING, error=type(exc).__name__)

    async def _renew_loop(self, token: str) -> None:
        while True:
            await asyncio.sleep(self.renew_every_s)
            try:
                ok = await self._renew_script(keys=[self.holders_key], args=[token, self.clock() + self.holder_ttl_ms])
            except Exception as exc:
                _log("llm_gate_renew_failed", logging.WARNING, error=type(exc).__name__)
                continue
            if not int(ok):
                # Expired and purged (e.g. the loop stalled past the TTL).
                # Re-adding could exceed capacity; the call just finishes ungated.
                _log("llm_gate_slot_lost", logging.WARNING, gate_class=token.split(":", 1)[0])
                return

    async def snapshot(self) -> dict:
        now = self.clock()
        holders = await self.redis.zrangebyscore(self.holders_key, f"({now}", "+inf")
        waiters = await self.redis.zrange(self.waiters_key, 0, -1)
        return {
            "capacity": self.capacity,
            "holders": _count_by_class(holders),
            "waiters": _count_by_class(waiters),
        }


def _count_by_class(tokens) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tokens:
        t = t.decode() if isinstance(t, bytes) else t
        cls = t.split(":", 1)[0]
        counts[cls] = counts.get(cls, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Process-wide gate

_gate: LLMGate | None = None


def get_gate() -> LLMGate:
    """The shared gate, built from the app's Valkey client and settings. Raises
    RuntimeError when Valkey isn't initialised. Rebuilt if the client changes
    (tests, or a reconnect that replaced it)."""
    global _gate
    redis = get_valkey()
    if _gate is None or _gate.redis is not redis:
        s = get_settings()
        _gate = LLMGate(redis, capacity=s.llm_gate_capacity, wait_s=s.llm_gate_wait_s)
    return _gate


async def acquire(cls: GateClass | str | None = None, *, wait_s: float | None = None) -> Slot:
    """Acquire a slot on the shared gate. A no-op Slot when this context
    already holds one, or when Valkey is unavailable (fail open)."""
    gate_class = _coerce(cls)
    if _held.get():
        return Slot()
    # Must not block AI features: without Valkey, run ungated (Ollama still
    # serialises requests; only the ordering is lost).
    try:
        gate = get_gate()
    except RuntimeError as exc:  # Valkey not initialised
        _log("llm_gate_unavailable", logging.WARNING, gate_class=str(gate_class), error=type(exc).__name__)
        return Slot()
    try:
        return await gate.acquire(gate_class, wait_s=wait_s)
    except (RedisError, OSError) as exc:
        _log("llm_gate_unavailable", logging.WARNING, gate_class=str(gate_class), error=type(exc).__name__)
        return Slot()


@asynccontextmanager
async def llm_slot(cls: GateClass | str | None = None, *, wait_s: float | None = None) -> AsyncIterator[Slot]:
    """`async with llm_slot(cls):` — hold a local-LLM slot for the block."""
    slot = await acquire(cls, wait_s=wait_s)
    try:
        with slot.held():
            yield slot
    finally:
        await slot.release()


async def snapshot() -> dict:
    return await get_gate().snapshot()
