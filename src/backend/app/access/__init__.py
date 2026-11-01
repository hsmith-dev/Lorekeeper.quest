"""app.access: the one place Roles and Audiences are interpreted (AD-13).

Layer (AD-1, .importlinter): below app.services, above app.schemas. It may
import app.schemas, app.db, app.core and app.domain, never app.clients,
app.services or app.api.

Contract names (parallel plan §3.1). E0-Access.2 ships the ctx, the
dependencies, the Role map and the 404; E0-Access.3 adds the Audience
lattice, the registry (`visible_clause`, `audience_of`, `scoped_select`,
`scoped_get`, `DERIVED_REGISTRY`), `audience_ctx` and the preview header.
"""
from app.access.audience import (
    ALWAYS_GM_FIELDS, GM_AUDIENCE, MEMBERS, PUBLIC, AnyOf, Audience, AudienceLevel, covers, ctx_audience,
    field_audience, mention_audience, most_restrictive, owner, stored_audience, visible_to,
)
from app.access.context import (
    ANON_VIEW, MEMBER_VIEW, PREVIEW_HEADER, AsUser, CampaignContext, RoleMap, as_user, audience_ctx, ctx_for,
    require_campaign, require_campaign_for, role_map, scoped_select_multi,
)
from app.access.identity import bearer_scheme, get_current_user
from app.access.policy import (
    ANON, GM, OWNER, PLAYER, MinRole, NotFound, Role, SystemReason, ctx_role, display_role, meets, not_found,
)
from app.access.registry import (
    DERIVED_REGISTRY, REGISTRY, DerivedType, UnregisteredModel, always_gm, audience_of, derived, gm_fields,
    membership, parent, reached_through, register_derived, registration, scoped_get, scoped_select, stored,
    visible_clause,
)

__all__ = [
    "ALWAYS_GM_FIELDS",
    "ANON",
    "ANON_VIEW",
    "AnyOf",
    "AsUser",
    "Audience",
    "AudienceLevel",
    "CampaignContext",
    "DERIVED_REGISTRY",
    "DerivedType",
    "GM",
    "GM_AUDIENCE",
    "MEMBERS",
    "MEMBER_VIEW",
    "MinRole",
    "NotFound",
    "OWNER",
    "PLAYER",
    "PREVIEW_HEADER",
    "PUBLIC",
    "REGISTRY",
    "Role",
    "RoleMap",
    "SystemReason",
    "UnregisteredModel",
    "always_gm",
    "as_user",
    "audience_ctx",
    "audience_of",
    "bearer_scheme",
    "covers",
    "ctx_audience",
    "ctx_for",
    "ctx_role",
    "derived",
    "display_role",
    "field_audience",
    "get_current_user",
    "gm_fields",
    "meets",
    "membership",
    "mention_audience",
    "most_restrictive",
    "not_found",
    "owner",
    "parent",
    "reached_through",
    "register_derived",
    "registration",
    "require_campaign",
    "require_campaign_for",
    "role_map",
    "scoped_get",
    "scoped_select",
    "scoped_select_multi",
    "stored",
    "stored_audience",
    "visible_clause",
    "visible_to",
]
