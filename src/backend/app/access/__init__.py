"""app.access: the one place Roles and Audiences are interpreted (AD-13).

Layer (AD-1, .importlinter): below app.services, above app.schemas. It may
import app.schemas, app.db, app.core and app.domain, never app.clients,
app.services or app.api.

Contract names (parallel plan §3.1). E0-Access.2 ships the ctx, the
dependencies, the Role map and the 404; E0-Access.3 adds the registry,
`scoped_select`, `audience_ctx` and the Audience mapping.
"""
from app.access.audience import Audience, AudienceLevel, ctx_audience
from app.access.context import (
    CampaignContext, ctx_for, require_campaign, require_campaign_for, role_map, scoped_select_multi,
)
from app.access.identity import bearer_scheme, get_current_user
from app.access.policy import (
    ANON, GM, OWNER, PLAYER, MinRole, NotFound, Role, SystemReason, ctx_role, display_role, meets, not_found,
)

__all__ = [
    "ANON",
    "Audience",
    "AudienceLevel",
    "CampaignContext",
    "GM",
    "MinRole",
    "NotFound",
    "OWNER",
    "PLAYER",
    "Role",
    "SystemReason",
    "bearer_scheme",
    "ctx_audience",
    "ctx_for",
    "ctx_role",
    "display_role",
    "get_current_user",
    "meets",
    "not_found",
    "require_campaign",
    "require_campaign_for",
    "role_map",
    "scoped_select_multi",
]
