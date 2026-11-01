"""EV-4 probes for api/routes/files.py (E0-Jobs.8): `GET /api/files/{file_id}`.

Files are stored through `file_service.put` as Campaign A's Owner, under a
test-only derived type (owning epics register the real ones), with a canary
in the bytes. A file is served (200, empty body, `X-Accel-Redirect`) only to
a viewer both access checks allow. For everyone else these answer exactly
like a missing id: a GM-only source, an always-GM `ref_field`, an unknown
`ref_kind`, no sources, another Campaign's file, a malformed id, and a file
gone stale. A GM gets fresh and stale files alike; in preview it gets only
what a Player gets. A Party-sourced file a Player can fetch is downgraded
through the bulk Visibility route (DowngradeCase): on the next request it
answers like a missing id while the GM still gets it.

The `/_files/` path: nginx's location is `internal` (a direct request is
nginx's 404) and the app has no route there, so a real storage key and a
made-up one answer the same.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

from tests.ev4 import nginx
from tests.ev4.families import DowngradeCase, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.fixtures import mint_canary
from tests.ev4.probes._support import MISSING, add_entry, authenticated, is_gm_of_a, outsider, previewing
from tests.ev4.registry import ev4_probe
from tests.ev4.report import note_family_call, record_leak

ACTORS = ("anon_share", "anonymous", "player", "cross_gm_player", "co_gm")
FILE_TYPE = "ev4_probe_file"


@contextmanager
def _file_type():
    from app.access.registry import DERIVED_REGISTRY, register_derived

    saved = list(DERIVED_REGISTRY)
    register_derived(FILE_TYPE, ["journal"])
    try:
        yield
    finally:
        DERIVED_REGISTRY[:] = saved


def _url(file_id) -> str:
    return f"/api/files/{file_id}"


async def _put(ev4, sources, *, campaign=None) -> "object":
    from app.access import ctx_for
    from app.services import file_service

    seeded = campaign or ev4.a
    ctx = await ctx_for(ev4.db, seeded.owner_id, seeded.campaign_id)
    data = f"{mint_canary('XFILE', seeded.campaign_id).token} bytes".encode()
    row = await file_service.put(ev4.db, ctx, seeded.campaign_id, FILE_TYPE, data, "audio/mpeg", sources=sources)
    await ev4.db.commit()
    return row


def _src(entry_id, field: str | None = "narrative", kind: str = "journal") -> tuple:
    return (kind, entry_id, field)


def _assert_served(actor, r, row, label: str) -> None:
    note_family_call()
    assert_no_canary(actor, r)
    problems = []
    if r.status_code != 200:
        problems.append(f"status {r.status_code}")
    elif r.content != b"" or r.headers.get("x-accel-redirect") != f"/_files/{row.storage_key}":
        problems.append(f"body {r.content[:50]!r}, accel {r.headers.get('x-accel-redirect')!r}")
    if problems:
        raise AssertionError(f"{actor.name} should be served {label}: {problems}")


def _assert_internal_location(storage_key: str) -> None:
    """nginx: /_files/... resolves to an `internal` location (a direct
    request is nginx's 404), and it is no API location."""
    note_family_call()
    loc = nginx.https_locations().resolve(f"/_files/{storage_key}")
    names = {d.name for d in loc.directives} if loc is not None else set()
    if loc is None or "internal" not in names or loc.uri != "/_files/":
        record_leak("EV-4 leak: /_files/ is reachable directly through nginx",
                    [f"resolved to {loc!r} with directives {sorted(names)}"])


@ev4_probe("GET", "/api/files/{file_id}", actors=ACTORS)
async def probe_file(ev4, actor):
    with _file_type():
        await _probe_file(ev4, actor)


async def _probe_file(ev4, actor):
    party = await add_entry(ev4, visibility="party", canary=False)
    gm_only = await add_entry(ev4, visibility="gm")
    visible = await _put(ev4, [_src(party)])
    hidden = {
        "a GM-only source": await _put(ev4, [_src(party), _src(gm_only)]),
        "an always-GM ref_field": await _put(ev4, [_src(party, "shorthand")]),
        "an unknown ref_kind": await _put(ev4, [_src(party, kind="ev4_unregistered")]),
        "no sources": await _put(ev4, []),
    }
    other = await outsider(ev4)
    other_party = await add_entry(ev4, visibility="party", canary=False, campaign_id=other.campaign_id)
    elsewhere = await _put(ev4, [_src(other_party)], campaign=other)
    missing = _url(MISSING)

    # Another Campaign's file and a malformed id: missing for everyone.
    await assert_hidden_equals_missing(actor, _url(elsewhere.id), missing)
    await assert_hidden_equals_missing(actor, _url("not-a-uuid"), missing)
    # /_files/ is never reachable directly: nginx `internal`, no app route.
    _assert_internal_location(visible.storage_key)
    await assert_hidden_equals_missing(actor, f"/_files/{visible.storage_key}",
                                       f"/_files/{ev4.a.campaign_id}/{FILE_TYPE}/{uuid.uuid4()}")

    if is_gm_of_a(ev4, actor):
        for label, row in [("a Party file", visible), *hidden.items()]:
            _assert_served(actor, await actor.get(_url(row.id)), row, label)
        preview = previewing(actor)
        for label, row in hidden.items():
            await assert_hidden_equals_missing(preview, _url(row.id), missing)
        _assert_served(preview, await preview.get(_url(visible.id)), visible, "a Party file in preview")
        return

    for label, row in hidden.items():
        await assert_hidden_equals_missing(actor, _url(row.id), missing)
    if not authenticated(actor):
        await assert_hidden_equals_missing(actor, _url(visible.id), missing)
        return

    _assert_served(actor, await actor.get(_url(visible.id)), visible, "a Party file")
    owner = await ev4.actor("gm_owner")

    async def downgrade():
        r = await owner.post(f"/api/campaigns/{ev4.a.campaign_id}/visibility",
                             json={"items": [{"kind": "journal", "id": str(party)}], "value": "gm"})
        assert r.status_code == 200, r.text

    await DowngradeCase(FILE_TYPE, ("journal",)).check(actor, _url(visible.id), missing, downgrade)
    # Stale now: still the GM's.
    _assert_served(owner, await owner.get(_url(visible.id)), visible, "a stale file")
