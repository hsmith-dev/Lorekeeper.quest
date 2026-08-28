import uuid
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models.user import User
from app.core.security import decode_token_payload

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token_payload(credentials.credentials)
    user_id = payload["sub"]
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.password_changed_at is not None and payload.get("iat") is not None:
        token_issued_at = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        if token_issued_at < user.password_changed_at:
            # Token predates the account's last password reset — reject it
            # even though it's not expired yet. See User.password_changed_at.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session is no longer valid — please log in again.",
            )
    if user.is_suspended:
        # Checked here, not just in require_active_account, so a suspension
        # blocks *everything* — billing status, settings, avatar upload, not
        # just feature routes — and can't be bypassed by an already-active
        # subscription (access_granted is billing-derived and gets
        # recomputed by the Stripe webhook independent of this).
        detail = "Your account has been suspended."
        if user.suspended_reason:
            detail += f" Reason: {user.suspended_reason}"
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return user


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
    """The single place campaign access is checked, so every route agrees on what
    'this user can touch this campaign' means. Owners always pass. Non-owners pass
    only if require_owner=False AND they're a CampaignMember (joined via a
    'collaborate' share link) — used for read/write on journals/NPCs/quests.
    require_owner=True is for campaign management itself (delete, manage share
    links) where membership isn't enough. 404 (not 403) either way, so a
    non-member can't tell a campaign exists vs. doesn't."""
    from app.db.models.campaign import Campaign
    from app.db.models.campaign_member import CampaignMember

    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.user_id == user.id:
        return campaign

    if not require_owner:
        member = await db.execute(
            select(CampaignMember).where(
                CampaignMember.campaign_id == campaign_id, CampaignMember.user_id == user.id
            )
        )
        if member.scalar_one_or_none():
            return campaign

    raise HTTPException(status_code=404, detail="Campaign not found")


async def accessible_campaign_ids(db: AsyncSession, user: User) -> list[uuid.UUID]:
    """All campaign IDs this user can see: ones they own plus ones they've joined
    as a collaborator. Used to scope list queries (journals/NPCs/quests) so a
    campaign's shared resources are visible to every member, not just whoever
    happens to be asking — the read counterpart to get_campaign_with_access."""
    from app.db.models.campaign import Campaign
    from app.db.models.campaign_member import CampaignMember

    owned = await db.execute(select(Campaign.id).where(Campaign.user_id == user.id))
    joined = await db.execute(select(CampaignMember.campaign_id).where(CampaignMember.user_id == user.id))
    return list({*owned.scalars().all(), *joined.scalars().all()})


async def get_user_llm_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve which LLM this user's AI requests go to.

    - A personal provider (their own API key/URL/model saved in Settings, or a
      non-default provider chosen) always wins — bringing your own key works
      for everyone regardless of subscription status, and costs the platform
      nothing to serve.
    - With no personal config saved, they're relying on the platform's own
      hosted model. That's gated to the "hosted" ($15/mo) tier specifically —
      the cheaper "byok" ($5/mo) tier and promo-code accounts never get it,
      by design, regardless of subscription status — and even a hosted-tier
      subscriber needs quota remaining for this billing period (see
      app/db/models/subscription.py::hosted_model_eligible and
      app/services/billing_service.py, which records usage against that
      quota after each hosted completion). Anyone else gets a clear 402
      pointing at Settings/subscribing instead of a silent free ride on the
      platform's compute.
    """
    from app.db.models.user_settings import UserSettings
    from app.db.models.subscription import Subscription
    from app.services.llm_provider import LLMConfig, get_default_config

    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    us = result.scalar_one_or_none()

    has_personal_config = us is not None and bool(
        us.llm_provider != "kobold" or us.llm_api_key or us.llm_api_url or us.llm_model
    )
    if has_personal_config:
        return LLMConfig(
            provider=us.llm_provider,
            api_url=us.llm_api_url,
            api_key=us.llm_api_key,
            model=us.llm_model,
            temperature=us.llm_temperature,
            max_tokens=us.llm_max_tokens,
        )

    # Open-access mode (admin-portal checkbox, app_config row): the platform
    # default (the operator's own Ollama) is available to every account, no
    # subscription or metering. record_hosted_usage stays harmless if a route
    # calls it anyway — it's a no-op for users with no subscription row.
    from app.services.app_config_service import is_open_access
    if await is_open_access(db):
        default_cfg = get_default_config()
        if us is not None and us.hosted_model_variant == "base":
            from app.core.config import get_settings as _get_settings
            default_cfg.model = _get_settings().kobold_base_model
        return default_cfg

    sub_result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = sub_result.scalar_one_or_none()
    if sub is not None and sub.hosted_model_eligible():
        if sub.has_quota_remaining():
            # The route handler is responsible for recording actual usage
            # after the completion comes back — see
            # app/services/billing_service.record_hosted_usage and its call
            # sites (journals/npcs/quests/chat routes). Metering here, before
            # the prompt even exists, would only let us charge a flat
            # worst-case (cfg.max_tokens) instead of what was actually used.
            default_cfg = get_default_config()
            # Only reached after the hosted_model_eligible()/quota checks
            # above — see UserSettings.hosted_model_variant's docstring for
            # why this can't be resolved any earlier (or via llm_model) than
            # right here.
            if us is not None and us.hosted_model_variant == "base":
                from app.core.config import get_settings
                default_cfg.model = get_settings().kobold_base_model
            return default_cfg
        raise HTTPException(
            status_code=402,
            detail=(
                "You've used your hosted-model quota for this billing period. "
                "Add your own LLM API key in Settings to keep generating, or "
                "wait for your quota to reset next period."
            ),
            # See require_active_account's account-gate 402 above for what
            # this header is for — this one routes to /settings, not
            # /subscribe, since the user already has access and just needs
            # a personal key or to wait out the quota reset.
            headers={"X-Gate-Reason": "llm-config"},
        )

    if sub is not None and sub.is_active() and sub.plan == "byok":
        # Already paying for the $5/mo tier — the message shouldn't suggest
        # subscribing again, just that a personal key is what that tier buys.
        raise HTTPException(
            status_code=402,
            detail=(
                "Add your own LLM API key in Settings (OpenAI, Anthropic, Gemini, "
                "or a custom OpenAI-compatible endpoint) — your plan doesn't "
                "include the hosted model. Upgrade to the $15/mo plan in Settings "
                "→ Billing for metered access to it instead."
            ),
            headers={"X-Gate-Reason": "llm-config"},
        )

    raise HTTPException(
        status_code=402,
        detail=(
            "Add your own LLM API key in Settings (OpenAI, Anthropic, Gemini, "
            "or a custom OpenAI-compatible endpoint), or subscribe to use "
            "Lorekeeper's hosted model."
        ),
        headers={"X-Gate-Reason": "llm-config"},
    )
