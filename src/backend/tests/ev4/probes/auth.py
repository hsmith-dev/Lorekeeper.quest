"""EV-4 probes for api/routes/auth.py's per-user reads and writes
(E0-QA.13): `GET /api/auth/me` and `PUT /api/auth/me/avatar` answer only
about the caller. Another user (canary display name and avatar) never shows
up, and their account is never changed. The anonymous credential routes
(register, login, password reset) and tutorial-complete are exempted in
exemptions.yaml.
"""
from __future__ import annotations

import io
import uuid

import sqlalchemy as sa

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_no_canary
from tests.ev4.fixtures import create_user, mint_canary
from tests.ev4.probes._support import authenticated
from tests.ev4.probes.admin import check_denial
from tests.ev4.registry import ev4_probe
from tests.ev4.report import note_family_call, record_leak

NOBODY = uuid.UUID("00000000-0000-4000-8000-00000000e4a1")  # no actor is GM here


async def other_user(ev4) -> uuid.UUID:
    """A user whose display name and avatar are canaries no actor may see."""
    from app.db.models.user import User

    user = await create_user(ev4.db, "other")
    await ev4.db.execute(sa.update(User).where(User.id == user.id).values(
        display_name=mint_canary("XUSERNAME", NOBODY).token,
        avatar_data=f"data:image/jpeg;base64,{mint_canary('XAVATAR', NOBODY).token}",
    ))
    await ev4.db.commit()
    return user.id


async def _user_row(ev4, user_id):
    from app.db.models.user import User

    return tuple((await ev4.db.execute(sa.select(User.display_name, User.avatar_data, User.has_completed_tutorial)
                                       .where(User.id == user_id))).one())


async def _change_other(ev4, user_id) -> None:
    from app.db.models.user import User

    await ev4.db.execute(sa.update(User).where(User.id == user_id).values(
        display_name=mint_canary("XUSERNAME", NOBODY).token, has_completed_tutorial=True,
        avatar_data=f"data:image/jpeg;base64,{mint_canary('XAVATAR', NOBODY).token}",
    ))
    await ev4.db.commit()


def _check_self(actor, response, label: str) -> None:
    note_family_call()
    assert_no_canary(actor, response)
    if response.status_code != 200 or response.json().get("id") != str(actor.user_id):
        record_leak(f"EV-4 leak: {label} did not answer about {actor.name} itself",
                    [f"status {response.status_code}: {response.text[:200]!r}"])


@ev4_probe("GET", "/api/auth/me")
async def probe_me(ev4, actor):
    other = await other_user(ev4)
    r = await actor.get("/api/auth/me")
    if not authenticated(actor):
        check_denial(actor, r, "GET /api/auth/me")
        return
    _check_self(actor, r, "GET /api/auth/me")
    await assert_counts_and_ranking_unchanged(actor, "/api/auth/me", lambda: _change_other(ev4, other))


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


@ev4_probe("PUT", "/api/auth/me/avatar")
async def probe_avatar(ev4, actor):
    other = await other_user(ev4)
    before = await _user_row(ev4, other)
    r = await actor.put("/api/auth/me/avatar", files={"file": ("a.png", _png(), "image/png")})
    if not authenticated(actor):
        check_denial(actor, r, "PUT /api/auth/me/avatar")
    else:
        _check_self(actor, r, "PUT /api/auth/me/avatar")
        assert r.json()["avatar_data"].startswith("data:image/jpeg;base64,"), r.text
    note_family_call()
    if await _user_row(ev4, other) != before:
        record_leak(f"EV-4 leak: {actor.name}'s avatar upload changed another user's account", [str(other)])
