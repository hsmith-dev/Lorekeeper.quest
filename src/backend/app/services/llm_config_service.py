"""Which LLM a user's AI work goes to, and metering for it.

The single resolver for both request routes (via the thin
app/api/deps.py::get_user_llm_config dependency, which turns LLMConfigError
into today's 402) and Job workers, which have no FastAPI request to hang a
dependency on. Moved out of deps.py unchanged in behaviour — same resolution
order, same LLMConfig values, same three gate messages.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import LLMConfigError
from app.db.models.user import User
from app.services.llm_provider import LLMConfig, get_default_config, is_hosted_default


async def resolve_llm_config(db: AsyncSession, user: User) -> LLMConfig:
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
      quota after each hosted completion). Anyone else gets a clear
      LLMConfigError (402 at the HTTP edge) pointing at Settings/subscribing
      instead of a silent free ride on the platform's compute.
    """
    from app.db.models.user_settings import UserSettings
    from app.db.models.subscription import Subscription

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
    # meters anyway — it's a no-op for users with no subscription row.
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
            # The caller is responsible for recording actual usage after the
            # completion comes back — see meter() below and its call sites in
            # app/api/routes. Metering here, before the
            # prompt even exists, would only let us charge a flat worst-case
            # (cfg.max_tokens) instead of what was actually used.
            default_cfg = get_default_config()
            # Only reached after the hosted_model_eligible()/quota checks
            # above — see UserSettings.hosted_model_variant's docstring for
            # why this can't be resolved any earlier (or via llm_model) than
            # right here.
            if us is not None and us.hosted_model_variant == "base":
                from app.core.config import get_settings
                default_cfg.model = get_settings().kobold_base_model
            return default_cfg
        # See require_active_account's account-gate 402 in deps.py for what
        # the X-Gate-Reason header is for — this one routes to /settings, not
        # /subscribe, since the user already has access and just needs a
        # personal key or to wait out the quota reset.
        raise LLMConfigError(
            "You've used your hosted-model quota for this billing period. "
            "Add your own LLM API key in Settings to keep generating, or "
            "wait for your quota to reset next period."
        )

    if sub is not None and sub.is_active() and sub.plan == "byok":
        # Already paying for the $5/mo tier — the message shouldn't suggest
        # subscribing again, just that a personal key is what that tier buys.
        raise LLMConfigError(
            "Add your own LLM API key in Settings (OpenAI, Anthropic, Gemini, "
            "or a custom OpenAI-compatible endpoint) — your plan doesn't "
            "include the hosted model. Upgrade to the $15/mo plan in Settings "
            "→ Billing for metered access to it instead."
        )

    raise LLMConfigError(
        "Add your own LLM API key in Settings (OpenAI, Anthropic, Gemini, "
        "or a custom OpenAI-compatible endpoint), or subscribe to use "
        "Lorekeeper's hosted model."
    )


async def meter(db: AsyncSession, user: User, config: LLMConfig, *texts: str) -> None:
    """Record hosted-model usage after a completion — once per completion, or
    once per batch such as an evaluation run, and only when `config` is the platform's hosted default. BYO-key usage never
    counts against a subscription's quota, so this skips the DB entirely for
    a personal config. Pass whatever text changed hands (see
    billing_service.record_hosted_usage / estimate_tokens)."""
    if not is_hosted_default(config):
        return
    from app.services import billing_service
    await billing_service.record_hosted_usage(db, user, *texts)
