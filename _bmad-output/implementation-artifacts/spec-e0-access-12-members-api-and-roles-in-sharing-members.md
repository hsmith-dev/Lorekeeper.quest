---
title: 'E0-Access.12: Members API and Roles in Sharing › Members'
type: 'feature'
created: '2026-11-20'
status: 'done'
baseline_revision: '0d71955bfb4845679b134717f820267a0d79656d'
review_loop_iteration: 0
followup_review_recommended: true
context: ['/Users/harrisonsmith/Documents/GitHub/Lorekeeper.quest/_bmad-output/implementation-artifacts/orchestration/builder-brief.md']
warnings: ['oversized']
deferred:
  - summary: >-
      The unpaid-login redirect in useAuth.ts is pinned only by a source guard.
    evidence: |-
      check-members.mjs tests loginDestination; nothing runs unpaidDestination or the login branch (no module mocking in the node checks).
    location: >-
      src/frontend/src/hooks/useAuth.ts
    severity: low
  - summary: >-
      Two concurrent joins by the same user can raise the uq_campaign_member IntegrityError as a 500.
    evidence: |-
      Pre-existing check-then-insert in join_campaign; unverified, needs a concurrent-request test.
    location: >-
      src/backend/app/api/routes/share.py
    severity: low (unverified)
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

### 2026-11-20 — Review pass
- verdicts: 27 findings — high 0, medium 3, low 12, false 8, maybe-false 4
- findings:
  - `[medium]` `[patch]` Blind: removing a Co-GM leaves their GM-context chats unarchived; rejoining as a Player brings them back — `_archive_chats` helper now also runs in `remove_member` for a co_gm; test_removing_a_co_gm_archives_their_chats.
  - `[medium]` `[patch]` Blind + Edge: PATCH promotes an unpaid Player to co_gm, after which account_gate 402s their Party reads in every Campaign — PATCH to co_gm runs require_active_account on the Member and answers 409 (not 402, which would bounce the Owner to /subscribe); test_promoting_needs_an_active_account.
  - `[medium]` `[patch]` Blind: the "delete their entries" option lost its permanent / cannot-be-undone warning — the inline confirm says so again.
  - `[low]` `[patch]` Blind: focus fell to body after a successful removal — focus moves to the Members heading and a polite status announces the removal.
  - `[false]` `[reject]` Blind: login comment's 402 claim is wrong — account_gate (deps.py:76) 402s PARTY_READ routes for an unpaid user who is GM anywhere, so an unpaid Owner gets 402 and goes to /subscribe as commented.
  - `[low]` `[defer]` Blind + VerificationGap: the login wiring (unpaidDestination) has no behavioural test, only a source guard — needs a module-mocking harness the node checks lack; deferred.
  - `[false]` `[reject]` Blind: the unpaid co_gm join path is untested — tests/access/test_write_rules.py::test_co_gm_link_needs_a_paid_account covers 402 and no row.
  - `[false]` `[reject]` Blind: read-only link expiry on the anonymous view is untested — E0-Access.4 owns and tests it (resolve_share_token expiry, tests/test_share.py, tests/access/test_grants.py); unchanged here.
  - `[low]` `[patch]` Blind: the demotion probe did not assert the stream subscribed before the PATCH — asserts `not request.done()` and `subscribed()` first.
  - `[low]` `[reject]` Blind: expired links vanish from the Owner's list — the list shows live links as it did for revoked ones; showing dead links is new UI beyond a direct fix.
  - `[low]` `[patch]` Blind: an existing Member redeeming a link keeps their Role, undocumented — join docstring says so.
  - `[low]` `[patch]` Blind: overlong join docstring line — rewrapped.
  - `[low]` `[patch]` Blind: member_id is str without a stated reason — one-line comment (junk id must be the uniform 404, not 422).
  - `[low]` `[patch]` VerificationGap: naive expires_at branch never exercised — test_naive_expires_at_is_utc (future 201 as UTC, past 422).
  - `[maybe-false]` `[defer]` Edge: concurrent double join can hit uq_campaign_member as a 500 — pre-existing join code path; would need a concurrent-request test to settle; low impact.
  - `[low]` `[patch]` Edge: Cancel/Esc on remove focused a still-disabled Remove button — focus moves in an effect once the button is enabled.
  - `[low]` `[patch]` Edge: confirmDemotion focused radios still disabled by isPending — same effect-based focus.
  - `[false]` `[reject]` Edge: an unpaid Player elsewhere who is co-GM in another Campaign lands on /subscribe — by account_gate design a GM anywhere must pay; every Party read would 402 for them anyway.
  - `[false]` `[reject]` Intent: a read-only link with a role is 422 beyond the story — the story gives read_only as `{kind, expires_at?}`; a role there would be stored meaninglessly, rejecting is the strict reading.
  - `[false]` `[reject]` Intent: archiving in the shared mutator reaches every demotion path — intended (requester: role changes only through grants.py).
  - `[maybe-false]` `[reject]` Intent: the UI is checked by pure helpers and source guards, not rendering — a throwaway Playwright run at 375 px exercised the keyboard demotion flow (notice, Esc, PATCH body, badge, no overflow); a committed render harness is out of this repo's frontend-check pattern.
  - `[low]` `[reject]` Intent: SegmentedControl instead of a "Role select" — the requester asked for the role picker built from segmented-control/combobox primitives.
  - `[low]` `[reject]` Intent: expiry is date-only in the UI — a date input is the accessible 375 px control; the API still takes a datetime.
  - `[maybe-false]` `[reject]` Intent: list response shape changed (member_id, joined_at, no email) — the AC fixes that shape; paths unchanged and the only caller is updated.
  - `[false]` `[reject]` Intent: login routing is unrequested — the requester asked to fix the unpaid-Player /subscribe redirect when in scope (join with a Player link is this story).
  - `[maybe-false]` `[reject]` Intent: "invite people with a Role" as a direct invite — the ACs place the Role on collaborate links only.
  - `[false]` `[reject]` Intent: "all management routes" in the EV-4 note vs share routes — share routes keep their probes in probes/campaigns.py.

## Design Notes

Archive in `change_member_role`, not the route: it is the single Role mutator, so any future demotion path archives too. `member_id: null` marks the Owner row, so there is nothing to PATCH or DELETE. `email` leaves the list (the AC's exact field set). Expiry from the UI is a date: end of that local day, sent as ISO with offset. `leave_campaign` stays in `campaigns.py` (not management; avoids churn next to E0-Access.13).

## Verification

**Commands:**
- `gh pr checks <PR>` -- expected: backend-tests, gates, frontend-ci, license-check green.
- `cd src/frontend && npx tsc --noEmit && npm run build && npm run lint:tokens && node scripts/check-members.mjs` -- expected: exit 0.
- `python3 scripts/check_scoped_queries.py` -- expected: clean.

## Auto Run Result

Status: done

**Summary:** Owner-only Members API in `members.py` (list with a synthetic Owner row, PATCH Role, DELETE moved from `campaigns.py`). Role changes go only through `grants.change_member_role`, which archives a demoted Co-GM's chats; `remove_member` archives a removed Co-GM's chats. Promotion to Co-GM needs an active account (409 otherwise). Share links store `role`/`expires_at`; join grants the link's role. Sharing › Members has RoleBadge, a SegmentedControl picker with the archive notice, inline remove confirm, link Role/expiry, loading/empty/error states, Esc via pushLayer. An unpaid user already in a Campaign logs in to `/dashboard`.

**Files:** `app/access/grants.py` (archive on demotion/removal), `app/api/routes/members.py` (routes), `app/api/routes/campaigns.py` (routes moved out; share role/expiry), `app/api/routes/share.py` (join role), `app/schemas/members.py`, `app/schemas/share.py`, `tests/test_members_api.py` (new), `tests/ev4/probes/members.py`, `tests/ev4/probes/campaigns.py`, `tests/access/test_campaign_permissions.py`, frontend `SharingPage.tsx`, `useSharing.ts`, `useAuth.ts`, `lib/members.ts` (new), `services/api.ts`, `services/api/members.ts`, `types/*`, `role-badge.tsx`, `scripts/check-members.mjs` (new), `frontend-ci.yml`.

**Review:** 27 findings; 13 patched (3 medium, 10 low), 2 deferred, 12 rejected (reasons in the triage log). Follow-up review recommended: true — 3 medium patches; the risk is that the patch round (409 promotion gate, archive-on-removal, effect-based focus) is verified only by CI and the throwaway Playwright run.

**Verification:** First commit c14f8ea: all GitHub CI checks green (backend tests on Postgres+Valkey, gates incl. EV-4 and CI-8, frontend, licences). Patch round: tsc, lint:tokens, check-members (12/12), check_scoped_queries clean, Playwright 375 px keyboard demotion run passed; backend re-run by CI on the follow-up push.

**Residual risks:** `probe_demotion_closes_the_events_stream` holds a live stream and may be timing-sensitive. Needs desktop verification: an unpaid Player browsing the dashboard after login (other dashboard calls may still 402).
