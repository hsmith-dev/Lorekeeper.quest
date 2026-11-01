# Epic 1 Context: Share Links stop leaking GM content (P0 hotfix)

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Owners who share a read-only Share Link must be able to trust it: anonymous viewers see only the player-facing chronicle, never GM Shorthand, NPC or Quest notes, or Secrets. This is a P0 privacy fix for a leak in the shipped product (read-only tokens used to anonymously serve every Journal Entry with its Shorthand plus NPC and Quest notes). Most of the fix shipped already (E0a.1, PR #1); the remaining work locks the fix in with an exact-field test, makes the frontend share page use Public-only types, and tells Owners what changed. The epic ships first and alone, as its own release, before any other expansion work. It is on the "never cut" list.

## Stories

- Story 1.1 (E0a.1): Share Links serve only player-visible fields (Done)
- Story 1.2 (E0a.2): Exact-field share test, frontend Public types and release notes

## Requirements & Constraints

- Read-only Share Link responses contain no Shorthand, no NPC or Quest notes and no Secrets. An automated test must assert this field by field, so any newly added model column cannot quietly reach a share response.
- The test asserts the exact key set of each share response (campaign, journal including nested tags, NPC, quest) against a list written in the test, with rows built with every column filled.
- A `collaborate` token gets 404 on every content endpoint and can read only the campaign metadata.
- Release notes (a new `docs/RELEASE_NOTES.md`, linked from `README.md`) must state: read-only links no longer show Shorthand or NPC/Quest notes; collaborate links were never readable; links already issued keep working.
- Must ship independently, with no dependency on the Roles/Visibility migration (F1-core). Nothing in this epic may require new tables or columns.
- Out of scope here (handled later in the Roles and Visibility epic): link expiry, Role-aware filtering, hiding GM-only records once Visibility exists, chat/search/retrieval leak paths (FR-9(b)), and the uniform 404 contract across all routes.

## Technical Decisions

- Share-specific response schemas are allowlists: `PublicJournalResponse`, `PublicJournalListResponse`, `PublicNpcResponse`, `PublicQuestResponse`, `PublicCampaignResponse` in `app/schemas/share.py`. Never reuse owner schemas for share responses, and never widen Public schemas to fit a consumer.
- This epic owns `app/api/routes/share.py`, the share schemas and `frontend/.../pages/SharedCampaignPage.tsx`. It owns no tables.
- Share routes are unauthenticated (public router), rate-limited by slowapi (30/min; join 10/min). Token kinds are strings `read_only` / `collaborate` on `campaign_share_tokens`.
- `Tag` is global (no `campaign_id`); nested tags in journal responses must also be allowlisted.
- Frontend: add `PublicJournal`, `PublicJournalList`, `PublicNpc`, `PublicQuest` types in `types/index.ts` matching the backend schemas exactly, so strict `tsc` fails if the share page reads `shorthand` or `notes`. `JournalCard` currently takes the owner `JournalEntry` type: give it a narrowed prop type or a `preview` variant rather than widening the Public types.
- These schemas are the seed for the later single authorization enforcement point (Party projections omit GM fields; hidden renders as unset) and the EV-4 zero-leak harness, which uses canary strings across every route.

## Cross-Story Dependencies

- E0a.2 depends on E0a.1 (done).
- Later epics build on this: the Roles and Visibility epic adds share-link expiry (resolution and UI), Role-aware filtering and the Visibility filter on share routes; the EV-4 harness extends the share seed test to every route; the Player Portal epic may extend the read-only share view. Legacy NPCs/Quests become GM-only once Roles ship, so read-only links will show no NPC/Quest lists until GMs publish Entities; that later release's notes must say so.
