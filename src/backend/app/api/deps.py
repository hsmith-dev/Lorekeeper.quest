import uuid
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models.user import User
# Moved to app.access.identity (E0-Access.2) so app.access can depend on the
# user without importing app.api. Re-exported as the same objects:
# `app.dependency_overrides[get_current_user]` works with either import.
from app.access.identity import bearer_scheme, get_current_user  # noqa: F401
from app.access.context import ctx_for
from app.access.registry import scoped_get
from app.access.policy import not_found


async def require_active_account(user: User = Depends(get_current_user)) -> User:
    """Gate for feature routes: a valid JWT alone isn't enough once account
    gating exists — the account also needs access_granted (redeemed promo code
    or an active/past_due subscription; see app/services/billing_service.py
    and app/api/routes/auth.py's register()). Applied at router-registration
    time in app/main.py via `dependencies=[Depends(require_active_account)]`
    for feature routers, so it's enforced without touching every individual
    route. NOT applied to auth/billing/settings routes, which a not-yet-paid
    account still needs to reach (to see billing status, subscribe, or manage
    their own API key) — and not applied to share.py's public read endpoints,
    which take no user at all."""
    if not user.access_granted:
        # Open-access mode (admin-portal checkbox, app_config row) waives the
        # gate entirely — including for accounts created while gating was on,
        # so flipping the box open immediately unrestricts everyone.
        from app.db.session import AsyncSessionLocal
        from app.services.app_config_service import is_open_access
        async with AsyncSessionLocal() as gate_db:
            if await is_open_access(gate_db):
                return user
        # X-Gate-Reason distinguishes this from get_user_llm_config's 402s
        # below — the frontend's axios interceptor uses it to send the user
        # to the right place (/subscribe here; /settings for an LLM-config
        # 402, since "subscribe again" is nonsensical/misleading for someone
        # who already has access_granted=True but no personal API key).
        raise HTTPException(
            status_code=402,
            detail="An active subscription or promo code is required to use this feature.",
            headers={"X-Gate-Reason": "account-gate"},
        )
    return user


def is_admin_user(user: User) -> bool:
    """The single place 'is this user an admin' is decided — used by
    require_admin below and by get_me's is_admin field (auth.py), so both
    always agree. user.is_admin is the real, DB-backed mechanism (grantable
    to anyone via POST /api/admin/users/{id}/promote, no redeploy needed);
    ADMIN_EMAIL is kept only as a bootstrap fallback so the original admin
    always has a way in even if their is_admin flag somehow never got set
    (e.g. a fresh deploy before the bootstrap migration's UPDATE has run)."""
    from app.core.config import get_settings

    settings = get_settings()
    return bool(user.is_admin) or (bool(settings.admin_email) and user.email.lower() == settings.admin_email.lower())


async def require_admin(user: User = Depends(require_active_account)) -> User:
    """Gate for admin-only routes (app/api/routes/admin.py, and
    feedback.py's GET routes) — built on top of require_active_account so
    admin access also requires a live account, not either check alone."""
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


async def get_campaign_with_access(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    user: User,
    require_owner: bool = False,
):
    """DEPRECATED (E0-Access.2): use `Depends(require_campaign(min_role))` or
    `app.access.ctx_for_request`. E0-Access.5 moved every caller off it, and
    scripts/check_scoped_queries.py (CI-8) fails on any new reference under
    app/: it ignores the preview header and any Role below `owner`.

    Returns the Campaign when the user is its Owner or (unless
    require_owner=True) any Member, whatever the Member's Role. Every denial
    is the one `404 {"detail":"Not found"}` (app.access.not_found)."""
    from app.db.models.campaign import Campaign

    ctx = await ctx_for(db, user.id, campaign_id)
    if require_owner and not ctx.is_owner:
        not_found()
    return await scoped_get(db, Campaign, ctx, ctx.campaign_id)


# `accessible_campaign_ids` is deleted (E0-Access.5): cross-Campaign lists use
# `app.access.role_map_for_request` (or `role_map`) and `scoped_select_multi`.


async def get_user_llm_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Route-dependency wrapper around
    app/services/llm_config_service.py::resolve_llm_config, which holds the
    actual resolution order (personal config > open access > hosted tier with
    quota) and the reasoning behind it. The logic moved there so Job workers,
    which have no request to hang a dependency on, resolve configs the same
    way routes do.

    Kept as a plain HTTPException(402) here rather than letting LLMConfigError
    reach the registered LLMError handler: existing callers (including
    journals.py's direct `get_user_llm_config(user=user, db=db)` call) and the
    frontend rely on this exact body — {"detail": ...} plus the
    X-Gate-Reason: llm-config header (see require_active_account above for
    what that header is for).
    """
    from app.core.errors import LLMConfigError
    from app.services.llm_config_service import resolve_llm_config

    try:
        return await resolve_llm_config(db, user)
    except LLMConfigError as exc:
        raise HTTPException(status_code=402, detail=exc.detail, headers=exc.headers) from exc
