"""The only publisher (AD-5, E0-Jobs.6): three functions over three channels.

    await publish_job(campaign_id, event)                       # jobs:{campaign_id}
    await publish_campaign_event(campaign_id, "visibility", id)  # campaign:{campaign_id}:events
    await publish_live(live_session_id, msg)                     # live:{live_session_id}:out

    async for event, data in listen_jobs(campaign_id): ...       # the matching subscribers

No feature invents a channel or a polling endpoint, and no module outside
this one publishes or subscribes (tests/test_pubsub.py scans app/ for it).
The one exception is app/access/grants.py: the grant-change channel (AD-13)
is published by app/access and watched by `grant_watch`, which
app/core/sse.py runs through `register_close_watch`.

**Wire format.** Every message is the JSON `{"event": <name>, "data": <data>}`.
The event names are `job` (data: `job_event` fields, see app/jobs/events.py),
`invalidate` (data: `{"domain", "id"}`, `id` null for an unkeyed
invalidation) and `live` (data: the message). The listeners yield
`(event, data)`, which `sse_response` frames as `event: <name>`.

**Throttles** (leading + trailing). A throttled publish goes out at once when
its Valkey key (`SET NX PX`, shared by every process) is free; otherwise the
latest value is kept in this process and one trailing publish goes out when
the window ends (a trailing task on the running loop), so the last value is
never lost. If another process takes the next window first, its publish is
the newer one and this process's trail is dropped unsent. Two throttles:

* `publish_job(..., progress_only=True)`: at most one per Job per
  JOB_PROGRESS_WINDOW_S. A status change (`progress_only=False`, the
  default) is never throttled and drops that Job's pending trailing
  progress (it carries newer state).
* `publish_campaign_event(..., id=None)`: at most one per (Campaign,
  domain) per CAMPAIGN_EVENT_WINDOW_S. Keyed events are not throttled.

A process whose event loop is about to end (the RQ work horse's
`asyncio.run`) calls `await flush_pending()` first: the trailing publishes
go out now instead of being lost with the loop.

**Resync** (E0-Access.11; E0-Jobs.7 and E0-Jobs.9 follow it). There are no
event ids and no replay. A listener started with `announce=True` yields
`("subscribed", {})` once, right after SUBSCRIBE succeeded; every message
published after that point is yielded. A stream route sends it as its first
frame (`event: subscribed`), and a client treats everything it read before
that frame as possibly stale: on every `subscribed` it refetches. Any gap
(reconnect, slow-client cutoff, `access_changed`, a Valkey restart) is
closed the same way: reconnect, `subscribed`, refetch. Without Valkey (or
when SUBSCRIBE fails) no `subscribed` is yielded and the listener ends.

**Failure.** No Valkey client: every publish is a no-op (logged at debug) and
every listener ends at once (logged). A Valkey error, or a publish slower than
PUBLISH_TIMEOUT_S, is logged, never raised. Delivery filtering (who may see
which Job, which ref) is the consuming route's job, never the publisher's.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.core.valkey_client import get_valkey

logger = logging.getLogger(__name__)

PUBLISH_TIMEOUT_S: float = 2
JOB_PROGRESS_WINDOW_S: float = 1
CAMPAIGN_EVENT_WINDOW_S: float = 30
# How long a listener waits on one get_message before looping (it is
# cancellable at any point; this only bounds a single read).
LISTEN_READ_S: float = 1
CLOSE_TIMEOUT_S: float = 2
# A trail re-checks a key that outlived its sleep for at most this long a
# remainder, this many times (timer and PTTL rounding), before giving up.
TRAIL_SETTLE_MS: int = 50
TRAIL_SETTLE_STEPS: int = 5
# Throttle keys in Valkey (no pub/sub: keys only).
THROTTLE_PREFIX = "pubsub_throttle"

# Event names on the wire (and the SSE `event:` field).
JOB_EVENT = "job"
INVALIDATE_EVENT = "invalidate"
LIVE_EVENT = "live"
# Yielded by a listener started with `announce=True`, once, right after its
# SUBSCRIBE succeeded: the resync point (see "Resync" in the docstring).
SUBSCRIBED_EVENT = "subscribed"

# The fields of a `job` event (AD-5).
JOB_EVENT_FIELDS = ("job_id", "kind", "status", "progress", "stage", "eta_seconds", "error_code",
                    "error_message", "result_ref")


# ── The channel registry: exactly three ────────────────────────────────────

def jobs_channel(campaign_id: uuid.UUID | str) -> str:
    return f"jobs:{campaign_id}"


def campaign_events_channel(campaign_id: uuid.UUID | str) -> str:
    return f"campaign:{campaign_id}:events"


def live_channel(live_session_id: uuid.UUID | str) -> str:
    return f"live:{live_session_id}:out"


CHANNELS = {"jobs": jobs_channel, "campaign_events": campaign_events_channel, "live": live_channel}


def _encode(event: str, data: Any) -> str:
    return json.dumps({"event": event, "data": data}, default=str, separators=(",", ":"))


# ── Publishing ─────────────────────────────────────────────────────────────

def _client() -> Any | None:
    try:
        return get_valkey()
    except RuntimeError:
        return None


async def _send(client: Any, channel: str, message: str) -> None:
    try:
        await asyncio.wait_for(client.publish(channel, message), PUBLISH_TIMEOUT_S)
    except Exception:
        logger.warning(json.dumps({"event": "pubsub_publish_failed", "channel": channel}), exc_info=True)


@dataclass
class _Trail:
    channel: str
    message: str
    window_s: float
    task: asyncio.Task | None = None


# Throttle key -> the pending trailing publish (this process).
_TRAILING: dict[str, _Trail] = {}


def _live_trail(key: str) -> _Trail | None:
    """The pending trail for `key` on the running loop; a trail left by
    another (or a closed) loop is dropped."""
    trail = _TRAILING.get(key)
    if trail is None:
        return None
    task = trail.task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if task is None or task.done() or task.get_loop() is not loop:
        _TRAILING.pop(key, None)
        return None
    return trail


def _cancel_trail(key: str) -> None:
    trail = _TRAILING.pop(key, None)
    if trail is not None and trail.task is not None and not trail.task.done():
        try:
            trail.task.cancel()
        except RuntimeError:
            pass  # its loop is closed: nothing left to cancel


async def _acquire(client: Any, key: str, window_s: float) -> bool:
    return bool(await asyncio.wait_for(client.set(key, "1", nx=True, px=max(1, int(window_s * 1000))),
                                       PUBLISH_TIMEOUT_S))


async def _run_trail(key: str, trail: _Trail) -> None:
    """Wait for the window to end, then take the next one and send the
    latest value. When another process took the next window first, its
    publish is newer than this trail, so the trail is dropped unsent (k
    processes never each re-send a window apart)."""
    try:
        client = _client()
        if client is None:
            return
        try:
            ttl_ms = await asyncio.wait_for(client.pttl(key), PUBLISH_TIMEOUT_S)
            if ttl_ms is not None and ttl_ms > 0:
                await asyncio.sleep(ttl_ms / 1000)
            # PTTL is whole milliseconds and a sleep is not exact: the key can
            # outlive the sleep by a little. Wait out that remainder (a short
            # TTL, the same window ending), never a new window another
            # process took (a TTL near the full window).
            for _ in range(TRAIL_SETTLE_STEPS):
                ttl_ms = await asyncio.wait_for(client.pttl(key), PUBLISH_TIMEOUT_S)
                if ttl_ms is None or ttl_ms <= 0 or ttl_ms > TRAIL_SETTLE_MS:
                    break
                await asyncio.sleep(ttl_ms / 1000 + 0.001)
            if not await _acquire(client, key, trail.window_s):
                return  # another process's newer publish holds the window
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(json.dumps({"event": "pubsub_throttle_failed", "channel": trail.channel}),
                           exc_info=True)
            return
        if _TRAILING.get(key) is trail:
            _TRAILING.pop(key, None)
        await _send(client, trail.channel, trail.message)
    finally:
        if _TRAILING.get(key) is trail:
            _TRAILING.pop(key, None)


async def _throttled(client: Any, key: str, window_s: float, channel: str, message: str) -> None:
    try:
        acquired = await _acquire(client, key, window_s)
    except Exception:
        logger.warning(json.dumps({"event": "pubsub_throttle_failed", "channel": channel}), exc_info=True)
        return
    if acquired:
        # A free window: this value is newer than any pending trail.
        _cancel_trail(key)
        await _send(client, channel, message)
        return
    trail = _live_trail(key)
    if trail is not None:
        trail.channel, trail.message = channel, message  # the trailing edge keeps the latest
        return
    trail = _Trail(channel, message, window_s)
    loop = asyncio.get_running_loop()
    # A fresh context: the trail inherits nothing from the publishing code.
    trail.task = loop.create_task(_run_trail(key, trail), context=contextvars.Context())
    _TRAILING[key] = trail


async def flush_pending() -> None:
    """Send this loop's pending trailing publishes now (before the loop
    ends) and drop their tasks. Never raises."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    client = _client()
    for key, trail in list(_TRAILING.items()):
        if trail.task is None or trail.task.get_loop() is not loop:
            continue
        _TRAILING.pop(key, None)
        if not trail.task.done():
            trail.task.cancel()
            if client is not None:
                await _send(client, trail.channel, trail.message)


async def _publish(channel: str, event: str, data: Any, *, throttle: tuple[str, float] | None = None) -> None:
    client = _client()
    if client is None:
        logger.debug("pubsub publish skipped: no Valkey client", extra={"channel": channel})
        return
    try:
        message = _encode(event, data)
    except (TypeError, ValueError):
        logger.warning(json.dumps({"event": "pubsub_encode_failed", "channel": channel}), exc_info=True)
        return
    if throttle is None:
        await _send(client, channel, message)
    else:
        await _throttled(client, throttle[0], throttle[1], channel, message)


async def publish_job(campaign_id: uuid.UUID | str, event: dict[str, Any], *, progress_only: bool = False) -> None:
    """Publish a `job` event on `jobs:{campaign_id}`. `event` holds the
    JOB_EVENT_FIELDS (other keys are dropped, missing ones are null). A
    progress-only event is throttled per Job (JOB_PROGRESS_WINDOW_S); a
    status change never is, and cancels the Job's pending trailing progress.
    Call it after commit, with the committed row (app/jobs/events.py)."""
    data = {name: event.get(name) for name in JOB_EVENT_FIELDS}
    if data["job_id"] is not None:
        data["job_id"] = str(data["job_id"])
    key = f"{THROTTLE_PREFIX}:job:{data['job_id']}"
    if progress_only and data["job_id"] is not None:
        await _publish(jobs_channel(campaign_id), JOB_EVENT, data, throttle=(key, JOB_PROGRESS_WINDOW_S))
        return
    _cancel_trail(key)
    await _publish(jobs_channel(campaign_id), JOB_EVENT, data)


async def publish_campaign_event(campaign_id: uuid.UUID | str, domain: str, id: uuid.UUID | str | None) -> None:  # noqa: A002
    """Publish an invalidation `{domain, id}` on `campaign:{campaign_id}:events`.
    `id=None` (a downgrade or delete: an unkeyed invalidation of the domain)
    goes out at most once per (Campaign, domain) per CAMPAIGN_EVENT_WINDOW_S,
    with one trailing publish so the last one is never lost."""
    if not isinstance(domain, str) or not domain:
        raise ValueError("publish_campaign_event: domain must be a non-empty string")
    data = {"domain": domain, "id": None if id is None else str(id)}
    channel = campaign_events_channel(campaign_id)
    if id is None:
        key = f"{THROTTLE_PREFIX}:campaign:{campaign_id}:{domain}"
        await _publish(channel, INVALIDATE_EVENT, data, throttle=(key, CAMPAIGN_EVENT_WINDOW_S))
        return
    await _publish(channel, INVALIDATE_EVENT, data)


async def publish_live(live_session_id: uuid.UUID | str, msg: Any) -> None:
    """Publish a Live Session message on `live:{live_session_id}:out`."""
    await _publish(live_channel(live_session_id), LIVE_EVENT, msg)


# ── Subscribing ────────────────────────────────────────────────────────────

async def _close(pubsub: Any | None) -> None:
    if pubsub is None:
        return
    for step in ("unsubscribe", "aclose"):
        try:
            await asyncio.wait_for(getattr(pubsub, step)(), CLOSE_TIMEOUT_S)
        except Exception:
            pass


def _decode(channel: str, raw: Any) -> tuple[str, Any] | None:
    try:
        if isinstance(raw, bytes):
            raw = raw.decode()
        message = json.loads(raw)
        event = message["event"]
        if not isinstance(event, str) or not event:
            raise ValueError("no event name")
        return event, message.get("data")
    except Exception:
        logger.warning(json.dumps({"event": "pubsub_bad_message", "channel": channel}))
        return None


async def _confirmed(pubsub: Any, channel: str) -> bool:
    """Wait (at most PUBLISH_TIMEOUT_S) for the server's `subscribe` reply."""
    deadline = asyncio.get_running_loop().time() + PUBLISH_TIMEOUT_S
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            logger.warning(json.dumps({"event": "pubsub_subscribe_unconfirmed", "channel": channel}))
            return False
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=False, timeout=min(remaining, LISTEN_READ_S))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(json.dumps({"event": "pubsub_subscribe_failed", "channel": channel}), exc_info=True)
            return False
        if message is not None and message.get("type") == "subscribe":
            return True


async def _listen(channel: str, announce: bool = False) -> AsyncIterator[tuple[str, Any]]:
    """Yield `(event, data)` for each message on `channel`. Subscribes on the
    first iteration; unsubscribes and closes when the generator is closed or
    cancelled. With `announce`, first yields `(SUBSCRIBED_EVENT, {})` once the
    subscription is live. Ends (logged) without Valkey or on a Valkey error; a
    message that is not our JSON is skipped (logged)."""
    client = _client()
    if client is None:
        logger.warning(json.dumps({"event": "pubsub_listen_skipped", "channel": channel, "reason": "no_valkey"}))
        return
    pubsub = None
    try:
        try:
            pubsub = client.pubsub()
            await asyncio.wait_for(pubsub.subscribe(channel), PUBLISH_TIMEOUT_S)
        except Exception:
            logger.warning(json.dumps({"event": "pubsub_subscribe_failed", "channel": channel}), exc_info=True)
            return
        if announce:
            # Only once the server confirmed the SUBSCRIBE: a message published
            # after the confirmation is delivered, so a refetch started after
            # `subscribed` misses nothing.
            if not await _confirmed(pubsub, channel):
                return
            yield SUBSCRIBED_EVENT, {}
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=LISTEN_READ_S)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(json.dumps({"event": "pubsub_listen_failed", "channel": channel}), exc_info=True)
                return
            if message is None or message.get("type") != "message":
                continue
            decoded = _decode(channel, message.get("data"))
            if decoded is not None:
                yield decoded
    finally:
        await _close(pubsub)


def listen_jobs(campaign_id: uuid.UUID | str, *, announce: bool = False) -> AsyncIterator[tuple[str, Any]]:
    """The `job` events of one Campaign (unfiltered: the route filters)."""
    return _listen(jobs_channel(campaign_id), announce)


def listen_campaign_events(campaign_id: uuid.UUID | str, *, announce: bool = False) -> AsyncIterator[tuple[str, Any]]:
    """The `invalidate` events of one Campaign (unfiltered: the route filters)."""
    return _listen(campaign_events_channel(campaign_id), announce)


def listen_live(live_session_id: uuid.UUID | str, *, announce: bool = False) -> AsyncIterator[tuple[str, Any]]:
    """The `live` messages of one Live Session."""
    return _listen(live_channel(live_session_id), announce)


__all__ = [
    "CAMPAIGN_EVENT_WINDOW_S", "CHANNELS", "INVALIDATE_EVENT", "JOB_EVENT", "JOB_EVENT_FIELDS",
    "JOB_PROGRESS_WINDOW_S", "LIVE_EVENT", "PUBLISH_TIMEOUT_S", "SUBSCRIBED_EVENT", "campaign_events_channel", "flush_pending",
    "jobs_channel", "listen_campaign_events", "listen_jobs", "listen_live", "live_channel", "publish_campaign_event",
    "publish_job", "publish_live",
]
