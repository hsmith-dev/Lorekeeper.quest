"""EV-4 probes for the admin portal (api/routes/admin.py, mounted with a
router-level `require_admin`) and the admin-only feedback reads (E0-QA.13).

No EV-4 actor is an admin. Every `/api/admin/*` route must answer a
non-admin with the one uniform admin denial (the same status, body and
headers as `GET /api/admin/users`), whatever the target: a real user or
promo code answers exactly like a missing one, and nothing changes. The
targets carry canaries (a user's display name, a promo code's note), so a
response that leaked one would be caught.

`probe_every_admin_route` also sweeps every `/api/admin/*` route the app
registers (including `GET /api/admin/jobs/stats`, exempted in
exemptions.yaml, and any admin route added later), so a new admin route
cannot ship outside the gate unnoticed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import sqlalchemy as sa

from tests.ev4.families import assert_no_canary
from tests.ev4.fixtures import Actor, create_user, mint_canary
from tests.ev4.probes._support import MISSING, assert_same_answer
from tests.ev4.registry import ev4_probe
from tests.ev4.report import note_family_call, record_leak
from tests.ev4.routes import WS, api_routes, route_key, sample_path

REFERENCE = "/api/admin/users"

# A valid body for each admin write, so that if the gate were missing the
# write would really happen (and _assert_untouched would see it).
BODIES: dict[str, dict] = {
    "POST /api/admin/users/{user_id}/suspend": {"reason": "ev4"},
    "PATCH /api/admin/users/{user_id}/access": {"access_granted": False},
    "POST /api/admin/users/{user_id}/message": {"subject": "ev4", "message": "ev4"},
    "POST /api/admin/promo-codes": {"code": "EV4-NOT-CREATED"},
    "PATCH /api/admin/promo-codes/{promo_id}": {"active": False, "note": "ev4"},
    "PUT /api/admin/config": {"open_access_mode": True},
    "POST /api/admin/models/install": {"variant": "base"},
}

ADMIN_ROUTES = (
    ("GET", "/api/admin/users"),
    ("POST", "/api/admin/users/{user_id}/suspend"),
    ("POST", "/api/admin/users/{user_id}/unsuspend"),
    ("PATCH", "/api/admin/users/{user_id}/access"),
    ("POST", "/api/admin/users/{user_id}/promote"),
    ("POST", "/api/admin/users/{user_id}/demote"),
    ("POST", "/api/admin/users/{user_id}/message"),
    ("DELETE", "/api/admin/users/{user_id}"),
    ("GET", "/api/admin/promo-codes"),
    ("POST", "/api/admin/promo-codes"),
    ("PATCH", "/api/admin/promo-codes/{promo_id}"),
    ("DELETE", "/api/admin/promo-codes/{promo_id}"),
    ("GET", "/api/admin/config"),
    ("PUT", "/api/admin/config"),
    ("GET", "/api/admin/models"),
    ("POST", "/api/admin/models/install"),
    ("GET", "/api/admin/logs"),
    ("GET", "/api/admin/support-bundle"),
)


@dataclass
class Targets:
    user_id: uuid.UUID
    promo_id: uuid.UUID
    promo_note: str
    open_access: bool
    promo_count: int


async def admin_targets(ev4) -> Targets:
    """A user (canary display name) and a promo code (canary note) that no
    EV-4 actor may see or change."""
    from app.db.models.promo_code import PromoCode
    from app.db.models.user import User
    from app.services.app_config_service import is_open_access

    nobody = uuid.uuid4()  # a Campaign id no actor holds: these canaries are visible to no one
    user = await create_user(ev4.db, "admin_target")
    await ev4.db.execute(sa.update(User).where(User.id == user.id)
                         .values(display_name=mint_canary("XADMINUSER", nobody).token))
    note = mint_canary("XPROMONOTE", nobody).token
    promo = PromoCode(id=uuid.uuid4(), code=f"EV4-{uuid.uuid4().hex[:12]}", note=note)
    ev4.db.add(promo)
    await ev4.db.commit()
    return Targets(user.id, promo.id, note, await is_open_access(ev4.db),
                   await _count(ev4, PromoCode))


async def _count(ev4, model, *where) -> int:
    return (await ev4.db.execute(sa.select(sa.func.count()).select_from(model).where(*where))).scalar_one()


async def _assert_untouched(ev4, t: Targets, label: str) -> None:
    """Nothing an admin route could change has changed."""
    from app.db.models.admin_message import AdminMessage
    from app.db.models.promo_code import PromoCode
    from app.db.models.user import User
    from app.services.app_config_service import is_open_access

    note_family_call()
    row = (await ev4.db.execute(sa.select(User.is_suspended, User.is_admin, User.access_granted)
                                .where(User.id == t.user_id))).one_or_none()
    promo = (await ev4.db.execute(sa.select(PromoCode.active, PromoCode.note)
                                  .where(PromoCode.id == t.promo_id))).one_or_none()
    diffs = []
    if row is None:
        diffs.append("the target user was deleted")
    elif tuple(row) != (False, False, True):
        diffs.append(f"the target user changed: suspended/admin/access = {tuple(row)}")
    if await _count(ev4, AdminMessage, AdminMessage.user_id == t.user_id):
        diffs.append("an admin message was sent to the target user")
    if promo is None:
        diffs.append("the promo code was deleted")
    elif tuple(promo) != (True, t.promo_note):
        diffs.append(f"the promo code changed: active/note = {tuple(promo)}")
    if await _count(ev4, PromoCode) != t.promo_count:
        diffs.append("a promo code was created")
    if await is_open_access(ev4.db) != t.open_access:
        diffs.append("the platform config changed")
    if diffs:
        record_leak(f"EV-4 leak: a non-admin ({label}) changed admin state", diffs)


def check_denial(actor: Actor, response: httpx.Response, label: str) -> None:
    """`response` is a refusal (401/403), with no canary."""
    note_family_call()
    assert_no_canary(actor, response)
    if response.status_code not in (401, 403):
        record_leak(f"EV-4 leak: {actor.name} was not refused (401/403) at {label}",
                    [f"status {response.status_code}: {response.text[:200]!r}"])


async def uniform_denial(actor: Actor) -> httpx.Response:
    """The reference denial every admin-only route must match for `actor`."""
    reference = await actor.get(REFERENCE)
    check_denial(actor, reference, f"GET {REFERENCE}")
    return reference


async def _probe_admin_route(ev4, actor: Actor, method: str, path: str) -> None:
    key = route_key(method, path)
    targets = await admin_targets(ev4)
    reference = await uniform_denial(actor)
    body = BODIES.get(key)
    kwargs = {"json": body} if body is not None else {}
    real = path.format(user_id=targets.user_id, promo_id=targets.promo_id)
    missing = path.format(user_id=MISSING, promo_id=MISSING)
    r_real = await actor.request(method, real, **kwargs)
    check_denial(actor, r_real, key)
    if real != missing:
        assert_same_answer(actor, r_real, await actor.request(method, missing, **kwargs), f"admin target of {key}")
    assert_same_answer(actor, r_real, reference, f"{key} vs the uniform admin denial")
    await _assert_untouched(ev4, targets, f"{actor.name} {key}")


def _register(method: str, path: str) -> None:
    async def probe_admin_route(ev4, actor):
        await _probe_admin_route(ev4, actor, method, path)

    probe_admin_route.__name__ = f"probe_admin_{method.lower()}_{path.strip('/').replace('/', '_')}"
    ev4_probe(method, path)(probe_admin_route)


for _method, _path in ADMIN_ROUTES:
    _register(_method, _path)


@ev4_probe("GET", "/api/admin/users")
async def probe_every_admin_route(ev4, actor):
    """Every `/api/admin/*` route the app registers gives `actor` the uniform
    admin denial and changes nothing."""
    from app.main import app

    targets = await admin_targets(ev4)
    reference = await uniform_denial(actor)
    swept = 0
    for route in api_routes(app):
        if route.method == WS or not (route.path == "/api/admin" or route.path.startswith("/api/admin/")):
            continue
        body = BODIES.get(route.key)
        r = await actor.request(route.method, sample_path(route.path), **({"json": body} if body else {}))
        check_denial(actor, r, route.key)
        assert_same_answer(actor, r, reference, f"{route.key} vs the uniform admin denial")
        swept += 1
    assert swept >= len(ADMIN_ROUTES), f"only {swept} admin routes found"
    await _assert_untouched(ev4, targets, f"{actor.name} sweep")
