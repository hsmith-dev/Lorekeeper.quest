"""EV-4 probes for api/routes/jobs.py (E0-Jobs.7).

Job rows are written directly in Campaign A (kind `system.noop`): GM Jobs
started by the Owner carry a canary in `stage`, so a Player who reads one is
caught by `assert_no_canary`. Each authenticated actor also gets Jobs they
started themselves (the positive control). A `result_ref` naming a GM-only
journal entry, with an extra canary key, must reach a non-GM as null; one
naming a Party entry must reach them as exactly `{"kind", "id"}`.

  * GET /{job_id}: a GM Job, another Campaign's Job and a malformed id
    answer exactly like a missing id for every non-GM of A (and in preview);
  * GET /?campaign_id=: a Player lists only their own Jobs, and
    `queue_position` counts only Jobs they can see (two hidden GM Jobs sit
    ahead of theirs in the same queue); a hidden Campaign is a missing one;
  * POST /{job_id}/retry and /cancel: a hidden Job (failed, queued, running)
    answers like a missing id and is left untouched (never a 409 that would
    reveal its state); the actor's own Job does change;
  * GET /stream: only the actor's own `job` events reach a Player (and none
    the member view), `result_ref` filtered; nginx streams the route
    unbuffered in the generic zone.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import fakeredis

from tests.ev4 import nginx
from tests.ev4.families import assert_hidden_equals_missing, assert_no_canary
from tests.ev4.fixtures import mint_canary
from tests.ev4.probes._support import (
    MISSING, add_entry, assert_same_answer, authenticated, is_gm_of_a, outsider, previewing,
)
from tests.ev4.registry import ev4_probe
from tests.ev4.report import note_family_call, record_leak

ACTORS = ("anon_share", "anonymous", "player", "co_gm", "cross_gm_player")
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _job(ev4, *, starter, status: str = "queued", campaign_id=None, canary: bool = False,
               result_ref=None, offset_s: int = 0, ctx_kind: str = "gm"):
    from app.db.models import Job

    cid = campaign_id or ev4.a.campaign_id
    now = datetime.now(timezone.utc)
    terminal = status in ("done", "failed", "cancelled")
    row = Job(id=uuid.uuid4(), campaign_id=cid, kind="system.noop", queue="interactive", status=status,
              payload={}, idempotency_key=f"ev4-jobs:{uuid.uuid4().hex}", ctx_kind=ctx_kind, ctx_user_id=starter,
              created_by=starter, access_epoch=0, attempts=3 if status == "failed" else 0,
              stage=mint_canary("XJOB", cid).token if canary else "Working",
              error_code="internal" if status == "failed" else None,
              result_ref=result_ref, created_at=_T0 + timedelta(seconds=offset_s) if status == "queued" else now,
              finished_at=now if terminal else None,
              started_at=now if status in ("running", "done", "failed") else None)
    ev4.db.add(row)
    await ev4.db.commit()
    return row.id


async def _status(ev4, job_id) -> str:
    from app.db.models import Job

    await ev4.db.commit()  # a fresh snapshot
    row = await ev4.db.get(Job, job_id, populate_existing=True)
    return str(getattr(row.status, "value", row.status))


def _role(ev4, actor) -> str:
    """The ctx_kind a Job the actor starts in A stores (the worker's rights
    check compares it with their Role when the Job runs)."""
    return "gm" if is_gm_of_a(ev4, actor) else "player"


def _detail(job_id) -> str:
    return f"/api/jobs/{job_id}"


async def _refs(ev4) -> dict:
    hidden_entry = await add_entry(ev4, visibility="gm")
    party_entry = await add_entry(ev4, visibility="party", canary=False)
    leak = mint_canary("XREF", ev4.a.campaign_id).token
    return {
        "hidden": {"kind": "journal", "id": str(hidden_entry), "note": leak},
        "visible": {"kind": "journal", "id": str(party_entry), "note": leak},
        "visible_out": {"kind": "journal", "id": str(party_entry)},
        "leak": leak,
    }


async def _hidden_jobs(ev4) -> dict:
    """GM Jobs of A (by the Owner) in every state, and another Campaign's."""
    owner = ev4.a.owner_id
    other = await outsider(ev4)
    return {
        "queued": await _job(ev4, starter=owner, canary=True, offset_s=1),
        "running": await _job(ev4, starter=owner, status="running", canary=True),
        "failed": await _job(ev4, starter=owner, status="failed", canary=True),
        "done": await _job(ev4, starter=owner, status="done", canary=True),
        "elsewhere": await _job(ev4, starter=other.owner_id, status="failed", canary=True,
                                campaign_id=other.campaign_id),
        "other_campaign": other.campaign_id,
    }


# ── GET /api/jobs/{job_id} ─────────────────────────────────────────────────

@ev4_probe("GET", "/api/jobs/{job_id}", actors=ACTORS)
async def probe_job_detail(ev4, actor):
    refs = await _refs(ev4)
    hidden = await _hidden_jobs(ev4)
    missing = _detail(MISSING)
    await assert_hidden_equals_missing(actor, _detail(hidden["elsewhere"]), missing)
    await assert_hidden_equals_missing(actor, _detail("not-a-uuid"), missing)

    if is_gm_of_a(ev4, actor):
        r = await actor.get(_detail(hidden["done"]))
        assert r.status_code == 200, r.text
        assert_no_canary(actor, r)
        gm_ref = await _job(ev4, starter=ev4.a.owner_id, status="done", result_ref=refs["hidden"])
        assert (await actor.get(_detail(gm_ref))).json()["result_ref"] == refs["hidden"]  # raw for a GM
        preview = previewing(actor)
        for state in ("queued", "running", "failed", "done"):
            await assert_hidden_equals_missing(preview, _detail(hidden[state]), missing)
        await assert_hidden_equals_missing(preview, _detail(gm_ref), missing)
        return

    for state in ("queued", "running", "failed", "done"):
        await assert_hidden_equals_missing(actor, _detail(hidden[state]), missing)
    if not authenticated(actor):
        return

    own_hidden_ref = await _job(ev4, starter=actor.user_id, ctx_kind=_role(ev4, actor), status="done", result_ref=refs["hidden"])
    own_visible_ref = await _job(ev4, starter=actor.user_id, ctx_kind=_role(ev4, actor), status="done", result_ref=refs["visible"])
    r1, r2 = await actor.get(_detail(own_hidden_ref)), await actor.get(_detail(own_visible_ref))
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert_no_canary(actor, r1)
    assert_no_canary(actor, r2)
    if r1.json()["result_ref"] is not None or r2.json()["result_ref"] != refs["visible_out"]:
        record_leak(f"EV-4 leak: {actor.name} received a Job result_ref they may not see",
                    [r1.text[:300], r2.text[:300]])


# ── GET /api/jobs/ ─────────────────────────────────────────────────────────

def _list(cid) -> str:
    return f"/api/jobs/?campaign_id={cid}"


@ev4_probe("GET", "/api/jobs/", actors=ACTORS)
async def probe_job_list(ev4, actor):
    a = ev4.a.campaign_id
    refs = await _refs(ev4)
    hidden = await _hidden_jobs(ev4)
    hidden_ahead = await _job(ev4, starter=ev4.a.owner_id, canary=True, offset_s=2)
    if not authenticated(actor):
        assert_same_answer(actor, await actor.get(_list(a)), await actor.get(_list(MISSING)),
                           "Job list of a Campaign without an account")
        return
    assert_same_answer(actor, await actor.get(_list(hidden["other_campaign"])), await actor.get(_list(MISSING)),
                       "Job list of a hidden Campaign")

    own_first = await _job(ev4, starter=actor.user_id, ctx_kind=_role(ev4, actor), offset_s=3, result_ref=refs["hidden"])
    own_second = await _job(ev4, starter=actor.user_id, ctx_kind=_role(ev4, actor), offset_s=4)
    r = await actor.get(_list(a))
    assert r.status_code == 200, r.text
    assert_no_canary(actor, r)
    jobs = {j["id"]: j for j in r.json()["jobs"]}

    if is_gm_of_a(ev4, actor):
        # Positive control: a GM sees every Job of A, and counts them all.
        assert {str(hidden["queued"]), str(hidden_ahead), str(own_first)} <= set(jobs), jobs
        assert jobs[str(own_second)]["queue_position"] >= 3
        preview = previewing(actor)
        rp = await preview.get(_list(a))
        assert rp.status_code == 200, rp.text
        assert_no_canary(preview, rp)
        if rp.json()["jobs"]:
            record_leak(f"EV-4 leak: {actor.name} in preview listed Jobs", [rp.text[:300]])
        return

    problems = []
    if set(jobs) != {str(own_first), str(own_second)}:
        problems.append(f"listed {sorted(set(jobs))}, own {[str(own_first), str(own_second)]}")
    else:
        if jobs[str(own_first)]["queue_position"] != 0 or jobs[str(own_second)]["queue_position"] != 1:
            problems.append(f"queue_position counts hidden Jobs: {jobs}")
        if jobs[str(own_first)]["result_ref"] is not None:
            problems.append("a hidden result_ref was listed")
    if problems:
        record_leak(f"EV-4 leak: {actor.name}'s Job list reveals hidden Jobs", problems)


# ── POST /api/jobs/{job_id}/retry and /cancel ──────────────────────────────

async def _probe_write(ev4, actor, action: str, hidden_states: tuple[str, ...], own_status: str,
                       expect_status: int, expect_row: str):
    hidden = await _hidden_jobs(ev4)
    missing = f"/api/jobs/{MISSING}/{action}"
    before = {state: await _status(ev4, hidden[state]) for state in hidden_states}

    async def hidden_post(viewer, state):
        await assert_hidden_equals_missing(viewer, f"/api/jobs/{hidden[state]}/{action}", missing, method="POST")

    await assert_hidden_equals_missing(actor, f"/api/jobs/{hidden['elsewhere']}/{action}", missing, method="POST")
    await assert_hidden_equals_missing(actor, f"/api/jobs/not-a-uuid/{action}", missing, method="POST")

    if is_gm_of_a(ev4, actor):
        preview = previewing(actor)
        for state in hidden_states:
            await hidden_post(preview, state)
    else:
        for state in hidden_states:
            await hidden_post(actor, state)
    changed = [s for s in hidden_states if await _status(ev4, hidden[s]) != before[s]]
    if changed:
        record_leak(f"EV-4 leak: {actor.name} changed a Job they cannot see ({action})", changed)
    if await _status(ev4, hidden["elsewhere"]) != "failed":
        record_leak(f"EV-4 leak: {actor.name} changed another Campaign's Job ({action})", [])
    if not authenticated(actor):
        return

    # Positive control: the actor's own Job.
    own = await _job(ev4, starter=actor.user_id, ctx_kind=_role(ev4, actor), status=own_status)
    r = await actor.post(f"/api/jobs/{own}/{action}")
    note_family_call()
    assert_no_canary(actor, r)
    assert r.status_code == expect_status, r.text
    assert await _status(ev4, own) in expect_row, (action, await _status(ev4, own))


@ev4_probe("POST", "/api/jobs/{job_id}/retry", actors=ACTORS)
async def probe_job_retry(ev4, actor):
    # JOBS_EAGER runs the retried noop at once: queued, then done.
    await _probe_write(ev4, actor, "retry", ("failed", "queued", "running", "done"), "failed", 202,
                       ("queued", "done"))


@ev4_probe("POST", "/api/jobs/{job_id}/cancel", actors=ACTORS)
async def probe_job_cancel(ev4, actor):
    await _probe_write(ev4, actor, "cancel", ("queued", "running", "failed", "done"), "queued", 200,
                       ("cancelled",))


# ── GET /api/jobs/stream ───────────────────────────────────────────────────

STREAM = "/api/jobs/stream?campaign_id={cid}"


@asynccontextmanager
async def _channel(stop_after: int):
    """A fakeredis Valkey for the app, and the jobs listener ending after
    `stop_after` channel messages (the ASGI client needs the body to end)."""
    from app.access import jobs as access_jobs
    from app.core import pubsub, valkey_client

    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    previous = valkey_client.set_valkey(client)
    real = pubsub.listen_jobs

    def bounded(campaign_id, *, announce=False):
        async def gen():
            seen = 0
            async for item in real(campaign_id, announce=announce):
                yield item
                if item[0] != pubsub.SUBSCRIBED_EVENT:
                    seen += 1
                    if seen >= stop_after:
                        return
        return gen()

    access_jobs.pubsub.listen_jobs = bounded
    try:
        yield client
    finally:
        access_jobs.pubsub.listen_jobs = real
        valkey_client.set_valkey(previous)
        pubsub._TRAILING.clear()
        await client.aclose()


def _frames(text: str) -> list[tuple[str, object]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln]
        if not lines or not lines[0].startswith("event: "):
            continue
        data = "\n".join(ln[len("data: "):] for ln in lines[1:] if ln.startswith("data: "))
        out.append((lines[0][len("event: "):], json.loads(data) if data else None))
    return out


def _event(job_id, stage="Working", result_ref=None, **extra) -> dict:
    return {"job_id": str(job_id), "kind": "system.noop", "status": "running", "progress": 0.5, "stage": stage,
            "eta_seconds": 10, "error_code": None, "error_message": None, "result_ref": result_ref, **extra}


async def _stream(ev4, viewer, messages: list) -> tuple[object, list]:
    from app.core import pubsub

    a = ev4.a.campaign_id
    channel = pubsub.jobs_channel(a)
    # A message that is not our JSON is skipped by the listener: not counted.
    async with _channel(stop_after=sum(not isinstance(m, str) for m in messages)) as client:
        request = asyncio.ensure_future(viewer.get(STREAM.format(cid=a)))

        async def subscribed() -> bool:
            result = await client.pubsub_numsub(channel)
            return bool(result and int(result[0][1]))

        for _ in range(500):
            if request.done() or await subscribed():
                break
            await asyncio.sleep(0.01)
        if not request.done():
            for message in messages:
                await client.publish(channel, message if isinstance(message, str) else json.dumps(message))
        r = await asyncio.wait_for(request, 15)
    return r, _frames(r.text) if r.status_code == 200 else []


def _assert_streaming_location() -> None:
    note_family_call()
    loc = nginx.https_locations().resolve("/api/jobs/stream")
    directives = {d.name: d.args for d in loc.directives} if loc is not None else {}
    if (loc is None or loc.uri != "/api/jobs/stream" or directives.get("proxy_buffering") != ["off"]
            or (directives.get("limit_req") or [""])[0] != "zone=api"):
        record_leak("EV-4: /api/jobs/stream is not an unbuffered generic-zone nginx location",
                    [f"resolved to {loc!r} with {directives}"])


@ev4_probe("GET", "/api/jobs/stream", actors=ACTORS)
async def probe_job_stream(ev4, actor):
    a = ev4.a.campaign_id
    _assert_streaming_location()
    if not authenticated(actor):
        assert_same_answer(actor, await actor.get(STREAM.format(cid=a)), await actor.get(STREAM.format(cid=MISSING)),
                           "Job stream of a Campaign without an account")
        return
    refs = await _refs(ev4)
    hidden = await _hidden_jobs(ev4)
    assert_same_answer(actor, await actor.get(STREAM.format(cid=hidden["other_campaign"])),
                       await actor.get(STREAM.format(cid=MISSING)), "Job stream of a hidden Campaign")

    own = await _job(ev4, starter=actor.user_id, ctx_kind=_role(ev4, actor), status="running")
    gm_stage = mint_canary("XJOBEV", a).token
    marker = _event(own, result_ref=refs["visible"])
    messages = [
        {"event": "job", "data": _event(hidden["running"], stage=gm_stage)},
        {"event": "job", "data": _event(hidden["elsewhere"], stage=gm_stage)},
        {"event": "job", "data": _event(uuid.uuid4(), stage=gm_stage)},
        {"event": "job", "data": _event(own, result_ref=refs["hidden"], secret=gm_stage)},
        {"event": "invalidate", "data": {"domain": "entities", "id": str(uuid.uuid4())}},
        {"event": "job", "data": "junk"},
        "not json",
        {"event": "job", "data": marker},
    ]
    viewers = [actor, previewing(actor)] if is_gm_of_a(ev4, actor) else [actor]
    for viewer in viewers:
        r, frames = await _stream(ev4, viewer, messages)
        assert r.status_code == 200, r.text
        assert r.headers.get("x-accel-buffering") == "no"
        assert_no_canary(viewer, r)
        assert frames[:1] == [("subscribed", {})], frames
        events = [data for event, data in frames if event == "job"]
        if viewer is actor and viewer.grants.get(a) == "gm":
            # Positive control: a GM receives the GM Job's events, raw.
            assert any(e["job_id"] == str(hidden["running"]) for e in events), events
            assert all(e["job_id"] != str(hidden["elsewhere"]) for e in events), events
            continue
        if viewer is not actor:
            expected = []  # the member view sees no Job
        else:
            expected = [{**_event(own), "result_ref": None},
                        {**_event(own), "result_ref": refs["visible_out"]}]
        if events != expected or refs["leak"] in r.text or str(hidden["running"]) in r.text:
            record_leak(f"EV-4 leak: {viewer.name} received a Job event they may not see", [r.text[-500:]])
