"""The one way to return server-sent events (AD-5, E0-Jobs.6).

    @router.get("/stream")
    async def stream(ctx: CampaignContext = Depends(require_campaign), db=Depends(get_db)):
        return sse_response(listen_jobs(ctx.campaign_id), ctx=ctx, bind=db.bind)

`gen` is an async iterator of `(event, data)` pairs (what the app/core/pubsub
listeners yield) or of ready frames (`format_event`). The response:

* has `Content-Type: text/event-stream`, `Cache-Control: no-cache` and
  `X-Accel-Buffering: no` (nginx must not buffer it);
* sends `event: ping` every SSE_PING_S;
* stands on the ctx's grant: the registered close watch (app/access
  registers `grant_watch` at import: app.core may not import app.access)
  runs for the whole stream. When it fires, the stream sends
  `event: access_changed` `{"detail": "Not found"}` and ends, within
  WATCH_CLOSE_S. The watch also fires on an upgrade: the client reconnects
  once and stops on 401/404. A watch that fired because its poll could not
  run (`poll_failed`), or that raised, ends the stream without that event
  (fail closed, but a transient DB error must not look like revocation);
* bounds memory for a slow client: a pump task pulls `gen` into a queue of
  at most SSE_QUEUE_MAX frames with `put_nowait`; a full queue ends the
  stream (the client reconnects and refetches). A send blocked longer than
  SEND_TIMEOUT_S ends it too;
* cleans up on every exit (end of `gen`, watch, overflow, client
  disconnect): the pump and the watch are cancelled and `gen` closed, so the
  listener's Valkey subscription and the watch's go, bounded by
  CLEANUP_TIMEOUT_S.

With no close watch registered (app.access never imported) `sse_response`
raises RuntimeError: no stream without the revocation check.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Send

logger = logging.getLogger(__name__)

SSE_PING_S: float = 15
SSE_QUEUE_MAX: int = 256
SEND_TIMEOUT_S: float = 10
# The stream ends within this long of the close watch firing.
WATCH_CLOSE_S: float = 2
CLEANUP_TIMEOUT_S: float = 2

PING_EVENT = "ping"
ACCESS_CHANGED_EVENT = "access_changed"
NOT_FOUND = {"detail": "Not found"}
# Watch results that end the stream without `access_changed`.
SILENT_REASONS = frozenset({"poll_failed"})

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

Watch = Callable[..., Awaitable[Any]]
Check = Callable[[Any], None]

_close_watch: tuple[Watch, Check | None] | None = None


def register_close_watch(watch: Watch, *, check: Check | None = None) -> None:
    """Install the watch every stream runs: `await watch(ctx, bind=bind)`
    returns (with a reason) when the ctx's access changed. `check(ctx)`, run
    when the response is built, raises for a ctx the watch cannot watch.
    Registering the same watch again is a no-op; a different one raises
    ValueError."""
    global _close_watch
    if _close_watch is not None and _close_watch[0] is not watch:
        raise ValueError("register_close_watch: a different close watch is already registered")
    _close_watch = (watch, check)


def format_event(event: str, data: Any = None) -> str:
    """One SSE frame: `event: <event>` and `data: <json>` (a str is sent as
    is, one `data:` line per line), ended by a blank line."""
    if not isinstance(event, str) or not event or any(c in event for c in "\r\n:"):
        raise ValueError(f"format_event: bad event name {event!r}")
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, default=str, separators=(",", ":"))
    lines = [f"event: {event}"] + [f"data: {line}" for line in payload.splitlines() or [""]]
    return "\n".join(lines) + "\n\n"


PING_FRAME = format_event(PING_EVENT, {})


def _frame(item: Any) -> str:
    if isinstance(item, str):
        if not item.endswith("\n\n"):
            raise ValueError("sse_response: a str item must be a whole frame (format_event)")
        return item
    if isinstance(item, tuple) and len(item) == 2:
        return format_event(item[0], item[1])
    raise TypeError(f"sse_response: expected (event, data) or a frame, got {type(item).__name__}")


_END = object()


async def _settle(task: asyncio.Future | None) -> None:
    """Cancel `task` and wait for it to finish (its finally blocks run)."""
    if task is None:
        return
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:  # noqa: BLE001 - cancelled or failed: either way it is over
        pass


class SSEResponse(StreamingResponse):
    """A StreamingResponse whose `stream_response` runs the pump, the ping
    timer, the close watch and the bounded send. Build it with `sse_response`."""

    media_type = "text/event-stream"

    def __init__(self, gen: AsyncIterator[Any], *, watch: Callable[[], Awaitable[Any]],
                 headers: Mapping[str, str] | None = None) -> None:
        fixed = {name.lower() for name in SSE_HEADERS}
        merged = {name: value for name, value in (headers or {}).items() if name.lower() not in fixed}
        merged.update(SSE_HEADERS)
        super().__init__(gen, headers=merged, media_type=self.media_type)
        self._watch_factory = watch
        self.overflowed = False

    async def _pump(self, queue: asyncio.Queue) -> None:
        try:
            async for item in self.body_iterator:
                try:
                    frame = _frame(item)
                except (TypeError, ValueError):
                    logger.warning(json.dumps({"event": "sse_bad_item"}), exc_info=True)
                    continue
                try:
                    queue.put_nowait(frame)
                except asyncio.QueueFull:
                    self.overflowed = True
                    logger.warning(json.dumps({"event": "sse_queue_full", "max": SSE_QUEUE_MAX}))
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(json.dumps({"event": "sse_stream_failed"}), exc_info=True)
        try:
            queue.put_nowait(_END)
        except asyncio.QueueFull:
            self.overflowed = True

    async def _send_frame(self, send: Send, frame: str, watch: asyncio.Future | None, timeout: float) -> bool:
        """Send one frame, racing the watch. False when the send did not
        finish within `timeout` or the watch fired while it was blocked."""
        sending = asyncio.ensure_future(send({"type": "http.response.body", "body": frame.encode(self.charset),
                                              "more_body": True}))
        waiting = {sending} if watch is None or watch.done() else {sending, watch}
        await asyncio.wait(waiting, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if not sending.done():
            await _settle(sending)
            logger.info(json.dumps({"event": "sse_send_aborted"}))
            return False
        sending.result()  # a send error (client gone) propagates
        return True

    def _watch_ended_silently(self, watch: asyncio.Future) -> bool:
        if watch.cancelled():
            return True
        error = watch.exception()
        if error is not None:
            logger.warning(json.dumps({"event": "sse_watch_failed"}), exc_info=error)
            return True
        return watch.result() in SILENT_REASONS

    async def stream_response(self, send: Send) -> None:
        await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        queue: asyncio.Queue = asyncio.Queue(maxsize=SSE_QUEUE_MAX)
        watch = asyncio.ensure_future(self._watch_factory())
        pump = asyncio.ensure_future(self._pump(queue))
        getter: asyncio.Future | None = None
        aborted = False
        try:
            next_ping = time.monotonic() + SSE_PING_S
            while True:
                if self.overflowed:
                    break
                if watch.done():
                    if not self._watch_ended_silently(watch):
                        aborted = not await self._send_frame(
                            send, format_event(ACCESS_CHANGED_EVENT, NOT_FOUND), None, WATCH_CLOSE_S / 2)
                    break
                if getter is None:
                    getter = asyncio.ensure_future(queue.get())
                timeout = max(0.0, next_ping - time.monotonic())
                await asyncio.wait({getter, watch}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                if watch.done():
                    continue  # handled at the top; a frame that arrived with it is dropped
                if getter.done():
                    frame, getter = getter.result(), None
                    if frame is _END or self.overflowed:
                        break
                else:
                    frame, next_ping = PING_FRAME, time.monotonic() + SSE_PING_S
                if not await self._send_frame(send, frame, watch, SEND_TIMEOUT_S):
                    aborted = True
                    break
            if not aborted:
                with anyio.move_on_after(WATCH_CLOSE_S / 2):
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            # Also on a client disconnect (this task cancelled by the base
            # class's task group): shielded, bounded.
            with anyio.move_on_after(CLEANUP_TIMEOUT_S, shield=True):
                for task in (getter, pump, watch):
                    await _settle(task)
                aclose = getattr(self.body_iterator, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:
                        logger.warning(json.dumps({"event": "sse_close_failed"}), exc_info=True)


def sse_response(gen: AsyncIterator[Any], *, ctx: Any, bind: Any = None,
                 headers: Mapping[str, str] | None = None) -> SSEResponse:
    """Return `gen` as an SSE stream that closes when `ctx`'s access
    changes (see the module docstring). `bind` is the engine the watch polls
    on (default: the app engine). RuntimeError when no close watch is
    registered; the watch's check raises for a ctx it cannot watch."""
    if _close_watch is None:
        raise RuntimeError("sse_response: no close watch registered (import app.access)")
    watch, check = _close_watch
    if ctx is None:
        raise ValueError("sse_response: a stream needs the ctx it stands on")
    if check is not None:
        check(ctx)

    def start() -> Awaitable[Any]:
        return watch(ctx, bind=bind)

    return SSEResponse(gen, watch=start, headers=headers)


__all__ = [
    "ACCESS_CHANGED_EVENT", "PING_EVENT", "SEND_TIMEOUT_S", "SSEResponse", "SSE_HEADERS", "SSE_PING_S",
    "SSE_QUEUE_MAX", "WATCH_CLOSE_S", "format_event", "register_close_watch", "sse_response",
]
