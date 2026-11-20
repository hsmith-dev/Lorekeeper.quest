---
title: 'E0-Access.12: Members API and Roles in Sharing › Members'
type: 'feature'
created: '2026-11-20'
status: 'in-progress'
baseline_revision: '0d71955bfb4845679b134717f820267a0d79656d'
review_loop_iteration: 0
followup_review_recommended: false
context: ['/Users/harrisonsmith/Documents/GitHub/Lorekeeper.quest/_bmad-output/implementation-artifacts/orchestration/builder-brief.md']
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** The Owner cannot choose who is a Co-GM: every collaborate link makes a Player, there is no Role change route, Members show no Role, and links have no Role or expiry in the UI. An unpaid Player who logs in is sent to /subscribe even though Party reads need no paid account.

**Approach:** Move the member routes into `api/routes/members.py`, add `PATCH .../members/{member_id}` (through `grants.change_member_role`, which now also archives a demoted Member's chat sessions), make share creation and join carry `role`/`expires_at`, and rebuild Sharing › Members with `RoleBadge`, a `SegmentedControl` role picker, the archive notice, link Role/expiry, and loading/empty/error states.

## Boundaries & Constraints

**Always:** every management route is `require_campaign("owner")`; every refusal (non-owner, cross-Campaign id, Owner row, junk id) is the byte-identical `404 {"detail":"Not found"}`. Role and membership changes go only through `app/access/grants.py` (`change_member_role`, `remove_member`), which bump `access_epoch`, publish after commit and close streams. Archiving lives in `change_member_role` (app/access, CI-8 clean). Reads via `scoped_select`/`scoped_get`. Semantic tokens only (`lint:tokens`); 375 px; keyboard operable with visible focus; transient confirmations register with `pushLayer` so Esc cancels.

**Never:** no new `scripts/scoped_queries_baseline.txt` lines; no new pending-baseline lines; no Owner member row; no edits to analytics/export in `campaigns.py` (E0-Access.13); no Player↔PC linking (E7); no migration (columns exist since F1-core).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| List | Owner `GET /members` | `[{member_id:null, user_id, display_name, role:"owner", joined_at}, …members by joined_at {member_id, user_id, display_name, role:"co_gm"/"player", joined_at}]` | non-owner → 404 |
| Promote | Owner `PATCH` `{role:"co_gm"}` | 200 member row; epoch +1; publish; `role` event | — |
| Demote | Owner `PATCH` Co-GM → `{role:"player"}` | all their `chat_sessions` in that Campaign (incl. `npc_entity_id` set) `archived_at=now()`; epoch +1; their streams end `access_changed`; entries unchanged (`kind=gm`, `visibility=party`), now GM-editable only | — |
| Same role | `PATCH` to current role | 200, no epoch bump, no publish | — |
| Escalation | Co-GM/Player `PATCH` self or others; cross-GM; Owner's user id or `MISSING` as member_id; member of B under A | 404, nothing changes | uniform 404 |
| Bad body | `{role:"owner"}`/`"gm"` by Owner | 422 | non-owner still 404 |
| Create link | `{kind:"collaborate", role?, expires_at?}` / `{kind:"read_only", expires_at?}` | stored `role` (collaborate default `player`; read_only `null`); `GET /share` lists `role`, `expires_at` | read_only + role, or `expires_at` ≤ now → 422 |
| Join | `POST /api/share/{token}/join` | Member created with token `role` (null → player); co_gm link needs a paid account (402), player link does not | expired/revoked → 404 |
| Login | unpaid user who is a Member somewhere | `/dashboard` | no Campaigns → `/subscribe` |

</intent-contract>

## Code Map

- `src/backend/app/access/grants.py` -- `change_member_role` (add archive on co_gm→player), `remove_member`. Only grant mutators.
- `src/backend/app/api/routes/campaigns.py` -- `list_campaign_members`, `remove_campaign_member` (move out, same paths); `create_share_token` (role/expiry). Leave `leave_campaign`, export, analytics untouched.
- `src/backend/app/api/routes/members.py` -- has `GET /{campaign_id}/me`; add list/PATCH/DELETE. Router already mounted with `gate` in `app/main.py` after `campaigns`.
- `src/backend/app/api/routes/share.py::join_campaign` -- create `CampaignMember(role=share.role or PLAYER)`; keep its two baselined raw reads unchanged.
- `src/backend/app/schemas/share.py` -- `ShareTokenCreate`, `ShareTokenResponse`, `CampaignMemberResponse` (replace with `MemberResponse` in `schemas/members.py`).
- `src/backend/app/access/registry.py` -- `CampaignMember: membership(MEMBERS)`, `scoped_get` filters by ctx Campaign.
- `src/backend/app/db/models/chat.py` -- `ChatSession.archived_at`, `npc_entity_id`.
- Tests: `tests/test_share.py`, `tests/access/test_write_rules.py` (join), `tests/access/test_campaign_permissions.py:342` (uses `m["id"]`, owner-less set — update), `tests/access/test_grants.py`.
- EV-4: `tests/ev4/probes/members.py`, `probes/campaigns.py` (existing list/remove/share probes), `probes/events.py` (`_channel` fakeredis pattern), `probes/grants.py`; `tests/ev4/fixtures.py` actors.
- Frontend: `pages/SharingPage.tsx`; `hooks/useSharing.ts`; `services/api.ts` (share/members calls), `services/api/members.ts`; `types/index.ts` (`ShareToken`, `CampaignMember`), `types/members.ts`; `components/ui/role-badge.tsx`, `segmented-control.tsx`, `empty-state.tsx`, `inline-error.tsx`, `skeleton.tsx`, `input.tsx`, `button.tsx`; `lib/layers.ts` (`pushLayer`); `hooks/useCampaignEvents.ts` (`role` broadcast already refetches every `[*, campaignId]` key and `campaignRole`); `hooks/useAuth.ts` (login redirect).

## Tasks & Acceptance

**Execution:**
- `src/backend/app/access/grants.py` -- in `change_member_role`, when the old role is `co_gm` and the new is `player`, `UPDATE chat_sessions SET archived_at=now() WHERE user_id=member.user_id AND campaign_id=member.campaign_id AND archived_at IS NULL`; docstring.
- `src/backend/app/schemas/members.py` -- `MemberResponse`, `MemberRoleUpdate {role: Literal["co_gm","player"]}`.
- `src/backend/app/schemas/share.py` -- `ShareTokenCreate` gets `role` and `expires_at` with validators; `ShareTokenResponse` adds `role`, `expires_at`; drop `CampaignMemberResponse`.
- `src/backend/app/api/routes/members.py` -- list (Owner synthetic row first), PATCH, DELETE (moved, `?delete_entries` kept).
- `src/backend/app/api/routes/campaigns.py` -- remove moved routes/imports; `create_share_token` stores role/expiry.
- `src/backend/app/api/routes/share.py` -- join grants the token's role.
- `src/backend/tests/test_members_api.py` (new) -- the I/O matrix: list shape, promote/demote/same-role (epoch, publish via `published`-style capture, archive incl. NPC chat, entries stay and a demoted Player cannot edit them), escalation 404s byte-identical, 422s, share create/list, join with co_gm/player/null role, expired/revoked 404.
- Existing tests -- update `test_campaign_permissions.py` member list assertions.
- `src/backend/tests/ev4/probes/members.py` -- probes: `GET/PATCH/DELETE /members…` escalation (Player/Co-GM/cross-GM promote self or others, Owner row, cross-Campaign ids → 404, no row change); `PATCH` demotion closes the demoted Co-GM's events stream with `access_changed`; `POST /api/share/{token}/join` grants link role.
- `src/frontend/src/types/index.ts`, `types/members.ts`, `services/api.ts`, `services/api/members.ts`, `hooks/useSharing.ts` -- new shapes, `changeMemberRole`, `createShareToken(campaignId, {kind, role?, expires_at?})`; mutations invalidate `campaignMembers`, `campaignRole`, `campaigns`.
- `src/frontend/src/components/ui/role-badge.tsx` -- optional `label` override (Owner row).
- `src/frontend/src/pages/SharingPage.tsx` -- Members (badge, `SegmentedControl` picker, demotion notice + confirm, inline remove confirm, Esc via `pushLayer`), link Role/expiry, link rows show role/expiry, Skeleton/EmptyState/InlineError.
- `src/frontend/src/lib/members.ts` (new, pure) + `scripts/check-members.mjs` (new) + `.github/workflows/frontend-ci.yml` -- archive-notice rule, expiry-date→ISO, owner-row detection, login destination.
- `src/frontend/src/hooks/useAuth.ts` -- unpaid login goes to `/dashboard` when the user has any Campaign.

**Acceptance Criteria:**
- Given the full backend suite, EV-4 coverage and gates (CI-8, CI-12), when CI runs, then all pass with no new baseline lines.
- Given `npm run build`, `lint:tokens` and every `scripts/check-*.mjs`, when frontend CI runs, then all pass.
- Given a throwaway Playwright run against a mocked API at 375 px, when the Owner demotes a Co-GM by keyboard, then the archive notice shows, Esc cancels it, Confirm sends `PATCH {role:"player"}`, and the badge updates.

## Spec Change Log

## Review Triage Log

## Design Notes

Archive in `change_member_role`, not the route: it is the single Role mutator, so any future demotion path archives too. `member_id: null` marks the Owner row, so there is nothing to PATCH or DELETE. `email` leaves the list (the AC's exact field set). Expiry from the UI is a date: end of that local day, sent as ISO with offset. `leave_campaign` stays in `campaigns.py` (not management; avoids churn next to E0-Access.13).

## Verification

**Commands:**
- `gh pr checks <PR>` -- expected: backend-tests, gates, frontend-ci, license-check green.
- `cd src/frontend && npx tsc --noEmit && npm run build && npm run lint:tokens && node scripts/check-members.mjs` -- expected: exit 0.
- `python3 scripts/check_scoped_queries.py` -- expected: clean.
