"""E0-LLM.2: the Redis priority gate (app/core/llm_gate.py).

Every gate test runs twice: against fakeredis (in process, Lua via lupa) and
against a real Redis-compatible server when REDIS_TEST_URL is set (Valkey in
CI). Each test gets its own key prefix and deletes its keys afterwards. Waits
are short (poll 10 ms) so no test takes more than a couple of seconds.
"""

import asyncio
import logging
import os
import time
import uuid

import fakeredis
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core import llm_gate
from app.core.errors import LLMBusy
from app.core.llm_gate import GateClass, LLMGate, class_for_queue

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL")


@pytest_asyncio.fixture(params=["fake", "real"])
async def redis(request):
    if request.param == "fake":
        client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    else:
        if not REDIS_TEST_URL:
            pytest.skip("REDIS_TEST_URL not set")
        client = aioredis.from_url(REDIS_TEST_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def make_gate(redis):
    gates: list[LLMGate] = []

    def make(**kwargs) -> LLMGate:
        kwargs.setdefault("capacity", 1)
        kwargs.setdefault("wait_s", 2)
        kwargs.setdefault("poll_s", 0.01)
        gate = LLMGate(redis, key_prefix=f"test_llm_gate:{uuid.uuid4().hex}", **kwargs)
        gates.append(gate)
        return gate

    yield make
    for gate in gates:
        await redis.delete(*gate.keys)


async def wait_until(cond, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        if await cond():
            return
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


def waiters_at_least(gate: LLMGate, n: int):
    async def cond():
        return await gate.redis.zcard(gate.waiters_key) >= n
    return cond


async def enqueue(gate: LLMGate, cls, **kwargs) -> asyncio.Task:
    """Start an acquire and wait until it is actually in the waiter queue."""
    before = await gate.redis.zcard(gate.waiters_key)
    task = asyncio.create_task(gate.acquire(cls, **kwargs))
    await wait_until(waiters_at_least(gate, before + 1))
    return task


async def test_free_slot_granted_with_ttl(make_gate):
    now = [1_700_000_000_000]
    gate = make_gate(clock=lambda: now[0])
    slot = await gate.acquire(GateClass.gm_interactive)
    try:
        holders = await gate.redis.zrange(gate.holders_key, 0, -1, withscores=True)
        assert len(holders) == 1
        assert holders[0][1] == now[0] + 30_000
        assert await gate.redis.zcard(gate.waiters_key) == 0
    finally:
        await slot.release()
    assert await gate.redis.zcard(gate.holders_key) == 0


async def test_priority_order(make_gate):
    gate = make_gate()
    current = await gate.acquire(GateClass.job_onsave)
    tasks = [
        await enqueue(gate, GateClass.job_backfill),
        await enqueue(gate, GateClass.gm_interactive),
        await enqueue(gate, GateClass.live_recap),
    ]
    pending = set(tasks)
    order = []
    for _ in range(3):
        await current.release()
        done, pending = await asyncio.wait(pending, timeout=1, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == 1
        current = done.pop().result()
        order.append(current.gate_class)
    await current.release()
    assert order == [GateClass.live_recap, GateClass.gm_interactive, GateClass.job_backfill]


async def test_fifo_within_class(make_gate):
    gate = make_gate()
    current = await gate.acquire(GateClass.gm_interactive)
    a = await enqueue(gate, GateClass.job_onsave)
    b = await enqueue(gate, GateClass.job_onsave)
    c = await enqueue(gate, GateClass.job_onsave)
    names = {a: "a", b: "b", c: "c"}
    pending = {a, b, c}
    order = []
    for _ in range(3):
        await current.release()
        done, pending = await asyncio.wait(pending, timeout=1, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == 1
        task = done.pop()
        order.append(names[task])
        current = task.result()
    await current.release()
    assert order == ["a", "b", "c"]


async def test_capacity_two(make_gate):
    gate = make_gate(capacity=2)
    tasks = [asyncio.create_task(gate.acquire(GateClass.gm_interactive)) for _ in range(3)]
    done, pending = await asyncio.wait(tasks, timeout=0.3)
    assert len(done) == 2 and len(pending) == 1
    assert await gate.redis.zcard(gate.holders_key) == 2
    first = done.pop()
    await first.result().release()
    done2, _ = await asyncio.wait(pending, timeout=1)
    assert len(done2) == 1
    for t in [*done, *done2]:
        await t.result().release()


async def test_timeout_raises_busy_and_removes_waiter(make_gate):
    gate = make_gate()
    holder = await gate.acquire(GateClass.live_recap)
    try:
        started = time.monotonic()
        with pytest.raises(LLMBusy) as exc:
            await gate.acquire(GateClass.gm_interactive, wait_s=0.2)
        assert 0.15 <= time.monotonic() - started < 1.0
        assert exc.value.code == "llm_busy" and exc.value.status_code == 503
        assert await gate.redis.zcard(gate.waiters_key) == 0
        assert await gate.redis.zcard(gate.seen_key) == 0
    finally:
        await holder.release()


async def test_job_deadline_contextvar(make_gate):
    gate = make_gate(wait_s=60)
    holder = await gate.acquire(GateClass.live_recap)
    token = llm_gate.current_deadline.set(time.monotonic() + 0.3)
    try:
        started = time.monotonic()
        with pytest.raises(LLMBusy):
            await gate.acquire(GateClass.job_backfill)
        assert 0.25 <= time.monotonic() - started < 1.5
    finally:
        llm_gate.current_deadline.reset(token)
        await holder.release()


async def test_dead_holder_recovered_after_ttl(make_gate):
    now = [1_700_000_000_000]
    gate = make_gate(clock=lambda: now[0], renew_every_s=100)
    dead = await gate.acquire(GateClass.job_backfill)
    dead._renewal.cancel()  # the "crashed" holder never renews
    with pytest.raises(LLMBusy):
        await gate.acquire(GateClass.live_recap, wait_s=0)
    now[0] += 30_001
    slot = await gate.acquire(GateClass.live_recap, wait_s=0)
    holders = await gate.redis.zrange(gate.holders_key, 0, -1)
    assert holders == [slot._token]
    await slot.release()
    await dead.release()


async def test_renewal_keeps_holder(make_gate):
    gate = make_gate(holder_ttl_s=0.3, renew_every_s=0.05)
    holder = await gate.acquire(GateClass.job_backfill)
    try:
        await asyncio.sleep(0.6)  # twice the TTL
        assert await gate.redis.zscore(gate.holders_key, holder._token) is not None
        with pytest.raises(LLMBusy):
            await gate.acquire(GateClass.live_recap, wait_s=0.1)
    finally:
        await holder.release()
    slot = await gate.acquire(GateClass.live_recap, wait_s=0.5)
    await slot.release()


async def test_dead_waiter_purged(make_gate):
    gate = make_gate()
    now_ms = int(time.time() * 1000)
    ghost = "live_recap:00000000000000000001:deadbeef"
    # A live_recap waiter whose process died 10 s ago: top priority, never polls.
    await gate.redis.zadd(gate.waiters_key, {ghost: now_ms - 10_000})
    await gate.redis.zadd(gate.seen_key, {ghost: now_ms - 10_000})
    slot = await gate.acquire(GateClass.job_backfill, wait_s=0.5)
    assert await gate.redis.zscore(gate.waiters_key, ghost) is None
    assert await gate.redis.zscore(gate.seen_key, ghost) is None
    await slot.release()


async def test_cancel_while_waiting_removes_waiter(make_gate):
    gate = make_gate()
    holder = await gate.acquire(GateClass.live_recap)
    try:
        task = await enqueue(gate, GateClass.gm_interactive, wait_s=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await gate.redis.zcard(gate.waiters_key) == 0
        assert await gate.redis.zcard(gate.seen_key) == 0
    finally:
        await holder.release()


@pytest.mark.parametrize("failure", ["cancel", "redis_error"])
async def test_failure_after_server_side_grant_leaves_no_holder(make_gate, failure):
    # The Lua grant has run in Redis, but the caller never sees the reply
    # (cancelled, or the connection dropped): the token must not stay behind
    # in holders, where nothing renews or releases it for the 30 s TTL.
    gate = make_gate()
    script = gate._acquire_script
    granted = asyncio.Event()

    async def grant_then_fail(**kwargs):
        await script(**kwargs)
        granted.set()
        if failure == "redis_error":
            raise RedisConnectionError("connection lost after the reply was sent")
        await asyncio.Event().wait()  # cancelled here

    gate._acquire_script = grant_then_fail
    task = asyncio.create_task(gate.acquire(GateClass.gm_interactive))
    await asyncio.wait_for(granted.wait(), 1)
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RedisConnectionError):
            await task
    assert await gate.redis.zcard(gate.holders_key) == 0
    gate._acquire_script = script
    slot = await gate.acquire(GateClass.live_recap, wait_s=0)
    await slot.release()


async def test_release_is_idempotent_and_stops_renewal(make_gate):
    gate = make_gate(renew_every_s=0.01)
    slot = await gate.acquire(GateClass.gm_interactive)
    renewal = slot._renewal
    await slot.release()
    await slot.release()
    await asyncio.sleep(0.05)
    assert renewal.cancelled() or renewal.done()
    assert await gate.redis.zcard(gate.holders_key) == 0


async def test_release_completes_when_caller_cancelled(make_gate):
    gate = make_gate()
    slot = await gate.acquire(GateClass.gm_interactive)
    task = asyncio.create_task(slot.release())
    await asyncio.sleep(0)  # release() is now awaiting Redis
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    async def freed():
        return await gate.redis.zcard(gate.holders_key) == 0

    await wait_until(freed)


async def test_snapshot_counts(make_gate):
    gate = make_gate()
    holder = await gate.acquire(GateClass.gm_interactive)
    t1 = await enqueue(gate, GateClass.job_backfill)
    t2 = await enqueue(gate, GateClass.job_backfill)
    t3 = await enqueue(gate, GateClass.live_recap)
    try:
        assert await gate.snapshot() == {
            "capacity": 1,
            "holders": {"gm_interactive": 1},
            "waiters": {"job_backfill": 2, "live_recap": 1},
        }
    finally:
        for t in (t1, t2, t3):
            t.cancel()
        await asyncio.gather(t1, t2, t3, return_exceptions=True)
        await holder.release()


# --- module helpers (shared gate) ------------------------------------------


@pytest.fixture
def shared_gate(make_gate, monkeypatch):
    gate = make_gate()
    monkeypatch.setattr(llm_gate, "get_gate", lambda: gate)
    return gate


async def test_reentrant_slot(shared_gate):
    gate = shared_gate
    async with llm_gate.llm_slot(GateClass.job_onsave) as outer:
        assert not outer.is_noop
        async with llm_gate.llm_slot(GateClass.live_recap) as inner:  # would deadlock at capacity 1
            assert inner.is_noop
            assert (await llm_gate.acquire()).is_noop
            assert await gate.redis.zcard(gate.holders_key) == 1
    assert await gate.redis.zcard(gate.holders_key) == 0
    async with llm_gate.llm_slot() as again:  # held flag was reset on exit
        assert not again.is_noop


async def test_module_acquire_coerces_str_and_defaults(shared_gate):
    slot = await llm_gate.acquire("live_recap")
    assert slot.gate_class is GateClass.live_recap
    await slot.release()

    slot = await llm_gate.acquire()
    assert slot.gate_class is GateClass.gm_interactive
    await slot.release()

    token = llm_gate.current_class.set(GateClass.job_backfill)
    try:
        slot = await llm_gate.acquire()
        assert slot.gate_class is GateClass.job_backfill
        await slot.release()
    finally:
        llm_gate.current_class.reset(token)

    with pytest.raises(ValueError):
        await llm_gate.acquire("not_a_class")


async def test_module_snapshot(shared_gate):
    async with llm_gate.llm_slot(GateClass.player_interactive):
        snap = await llm_gate.snapshot()
    assert snap == {"capacity": 1, "holders": {"player_interactive": 1}, "waiters": {}}


def test_class_for_queue():
    assert class_for_queue("onsave") is GateClass.job_onsave
    assert class_for_queue("backfill") is GateClass.job_backfill
    assert class_for_queue("interactive") is GateClass.gm_interactive
    with pytest.raises(ValueError):
        class_for_queue("nightly")


def test_priority_order_of_classes():
    ranked = sorted(GateClass, key=llm_gate.PRIORITY.__getitem__)
    assert ranked == [
        GateClass.live_recap,
        GateClass.gm_interactive,
        GateClass.player_interactive,
        GateClass.job_onsave,
        GateClass.job_backfill,
    ]


async def test_fail_open_when_redis_uninitialised(monkeypatch, caplog):
    def boom():
        raise RuntimeError("Redis not initialized")

    monkeypatch.setattr(llm_gate, "get_redis", boom)
    monkeypatch.setattr(llm_gate, "_gate", None)
    with caplog.at_level(logging.WARNING, logger="app.core.llm_gate"):
        async with llm_gate.llm_slot(GateClass.live_recap) as slot:
            assert slot.is_noop
    assert "llm_gate_unavailable" in caplog.text


async def test_fail_open_on_redis_error(monkeypatch, caplog):
    class BrokenGate:
        async def acquire(self, cls, *, wait_s=None):
            raise RedisConnectionError("connection refused")

    monkeypatch.setattr(llm_gate, "get_gate", lambda: BrokenGate())
    with caplog.at_level(logging.WARNING, logger="app.core.llm_gate"):
        slot = await llm_gate.acquire(GateClass.gm_interactive)
    assert slot.is_noop
    await slot.release()
    assert "llm_gate_unavailable" in caplog.text


def test_get_gate_rebuilt_when_client_changes(monkeypatch):
    r1 = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    r2 = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    current = [r1]
    monkeypatch.setattr(llm_gate, "get_redis", lambda: current[0])
    monkeypatch.setattr(llm_gate, "_gate", None)
    g1 = llm_gate.get_gate()
    assert llm_gate.get_gate() is g1 and g1.redis is r1
    current[0] = r2
    g2 = llm_gate.get_gate()
    assert g2 is not g1 and g2.redis is r2
