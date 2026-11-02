"""app.access: the one place Roles and Audiences are interpreted (AD-13).

Layer (AD-1, .importlinter): below app.services, above app.schemas. It may
import app.schemas, app.db, app.core and app.domain, never app.clients,
app.services or app.api.

Contract names (parallel plan §3.1). E0-Access.2 ships the ctx, the
dependencies, the Role map and the 404; E0-Access.3 adds the Audience
lattice, the registry (`visible_clause`, `audience_of`, `scoped_select`,
`scoped_get`, `DERIVED_REGISTRY`), `audience_ctx` and the preview header.
E0-Access.4 adds the projections (`project`, `project_all`, `PROJECTIONS`),
Share Links (`share_ctx`, `resolve_share_token`), `ctx_for_request`,
`role_ctx` and the `Vary` middleware. E0-Access.5 adds `role_map_for_request`
(cross-Campaign lists honour the preview header). E0-Access.8 adds citations
(`register_resolver`, `visible_refs`, `resolve_sources`, `message_refs`) and
the chat projections (`project_chat`, `replay_history`). E0-Access.9 adds
the one Visibility writer (`set_visibility`, `set_visibility_many`), its kind
map (`register_visibility_kind`), the extension points
(`register_stale_marker`, `register_visibility_listener`) and
`mark_dependents_stale`. E0-Access.10 adds grant changes (`change_member_role`,
`remove_member`, `revoke_share_token`, `campaign_grants_removed`,
`publish_grant_change`, `grant_channel`, `grant_changed`, `grant_watch`, `GRANT_POLL_S`) and
the cache key scheme (`cache_key`, `cache_generation`, `cached_json`,
`invalidate_campaign_cache`, `CACHE_TTL_S`). E0-Jobs.6 registers `grant_watch` as
app/core/sse.py's close watch (app.core may not import app.access), so every
`sse_response` stream ends when its ctx's grant changes. E0-WorldCore.3 adds
`register_writer` (world_service registers the Canon tables' writer) and the
registry's `gm_when` (deleted or merged Entities are GM only). E0-Access.11 adds
Campaign events (`campaign_event_stream`, `deliverable`, `stream_ctx`,
`register_event_domain`, `event_domains`, `BROADCAST_DOMAINS`): who receives
which `campaign:{id}:events` invalidation. E0-Jobs.7 adds the Job reads (`get_job`,
`list_jobs`, `queue_positions`, `job_response`, `visible_result_ref`,
`register_result_kind`, `result_kinds`) and the `jobs:{id}` stream filter
(`job_event_stream`, `deliverable_job_event`, `JobEventCheckFailed`).
"""
from app.access.audience import (
    ALWAYS_GM_FIELDS, GM_AUDIENCE, MEMBERS, PUBLIC, AnyOf, Audience, AudienceLevel, covers, ctx_audience,
    field_audience, mention_audience, most_restrictive, owner, stored_audience, visible_to,
)
from app.access.context import (
    ANON_VIEW, MEMBER_VIEW, PREVIEW_HEADER, AsUser, CampaignContext, RoleMap, VaryMiddleware, as_user,
    audience_ctx, ctx_for, ctx_for_request, require_campaign, require_campaign_for, role_ctx, role_map,
    role_map_for_request,
    scoped_select_multi,
)
from app.access.cache import CACHE_TTL_S, cache_generation, cache_key, cached_json, invalidate_campaign_cache
from app.access.grants import (
    GRANT_POLL_S, campaign_grants_removed, change_member_role, grant_changed, grant_channel, grant_watch,
    publish_grant_change, remove_member, revoke_share_token,
)
from app.access.identity import bearer_scheme, get_current_user
from app.access.policy import (
    ANON, GM, OWNER, PLAYER, MinRole, NotFound, Role, SystemReason, ctx_role, display_role, meets, not_found,
)
from app.access.registry import (
    DERIVED_REGISTRY, REGISTRY, SOURCE_KIND_MODELS, DerivedType, UnregisteredModel, always_gm, audience_of,
    derived, derived_from_sources, gm_fields, membership, parent, reached_through, register_derived,
    owned_get, register_source_kind, register_writer, registration, scoped_get, scoped_select, stored,
    visible_clause,
)
from app.access.projection import (
    CHAT_DETAIL, CHAT_META, CHAT_REPLY, LITE, PROJECTIONS, REDACTED_NOTICE, WITH_COUNT, Projection,
    check_chat_session, check_create, check_party_schemas, project, project_all, project_chat, redact_messages,
    replay_history, schema_for, session_visible_text,
)
from app.access.sources import (
    field_visible, message_refs, register_resolver, registered_resolvers, resolve_sources, visible_refs,
)
from app.access.share import COLLABORATE, READ_ONLY, ctx_for_share, resolve_share_token, share_ctx
from app.access.visibility import (
    VisibilityError, VisibilityKind, mark_dependents_stale, register_stale_marker, register_visibility_kind,
    register_visibility_listener, set_visibility, set_visibility_many, visibility_exception_handler,
    visibility_kinds,
)
from app.access.events import (
    BROADCAST_DOMAINS, EventCheckFailed, campaign_event_stream, deliverable, event_domains, register_event_domain,
    stream_ctx,
)
from app.access.jobs import (
    JobEventCheckFailed, deliverable_job_event, get_job, job_event_stream, job_response, list_jobs,
    queue_positions, register_result_kind, result_kinds, visible_result_ref,
)
from app.access.grants import _check_watchable
from app.core import sse as _sse

_sse.register_close_watch(grant_watch, check=_check_watchable)

__all__ = [
    "JobEventCheckFailed",
    "deliverable_job_event",
    "get_job",
    "job_event_stream",
    "job_response",
    "list_jobs",
    "queue_positions",
    "register_result_kind",
    "result_kinds",
    "visible_result_ref",
    "BROADCAST_DOMAINS",
    "EventCheckFailed",
    "campaign_event_stream",
    "deliverable",
    "event_domains",
    "register_event_domain",
    "stream_ctx",
    "CACHE_TTL_S",
    "GRANT_POLL_S",
    "cache_generation",
    "cache_key",
    "cached_json",
    "campaign_grants_removed",
    "change_member_role",
    "grant_changed",
    "grant_channel",
    "grant_watch",
    "invalidate_campaign_cache",
    "publish_grant_change",
    "remove_member",
    "revoke_share_token",
    "VisibilityError",
    "VisibilityKind",
    "mark_dependents_stale",
    "register_stale_marker",
    "register_visibility_kind",
    "register_visibility_listener",
    "set_visibility",
    "set_visibility_many",
    "visibility_exception_handler",
    "visibility_kinds",
    "CHAT_DETAIL",
    "CHAT_META",
    "CHAT_REPLY",
    "REDACTED_NOTICE",
    "check_chat_session",
    "field_visible",
    "message_refs",
    "project_chat",
    "redact_messages",
    "register_resolver",
    "registered_resolvers",
    "replay_history",
    "resolve_sources",
    "session_visible_text",
    "visible_refs",
    "COLLABORATE",
    "READ_ONLY",
    "LITE",
    "PROJECTIONS",
    "Projection",
    "VaryMiddleware",
    "WITH_COUNT",
    "check_create",
    "check_party_schemas",
    "ctx_for_request",
    "ctx_for_share",
    "project",
    "project_all",
    "resolve_share_token",
    "role_ctx",
    "schema_for",
    "share_ctx",
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
    "SOURCE_KIND_MODELS",
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
    "derived_from_sources",
    "display_role",
    "field_audience",
    "get_current_user",
    "gm_fields",
    "meets",
    "membership",
    "mention_audience",
    "most_restrictive",
    "not_found",
    "owned_get",
    "owner",
    "parent",
    "reached_through",
    "register_derived",
    "register_source_kind",
    "register_writer",
    "registration",
    "require_campaign",
    "require_campaign_for",
    "role_map",
    "role_map_for_request",
    "scoped_get",
    "scoped_select",
    "scoped_select_multi",
    "stored",
    "stored_audience",
    "visible_clause",
    "visible_to",
]
