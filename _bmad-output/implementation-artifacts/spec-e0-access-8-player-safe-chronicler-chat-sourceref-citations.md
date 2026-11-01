---
title: 'E0-Access.8: Player-safe Chronicler chat with SourceRef citations'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '9160cb62abe2d7cace054d4e95f6d85883b185f9'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** After E0-Access.7 a Player's chat retrieval is Party-only, but responses still use the GM schemas (an empty `shorthand` in every source and candidate, a nullable `system_prompt` in the trace), stored messages are bare `{role, content}` replayed verbatim into the next prompt even after what they drew on is hidden, archived sessions are listed, served and replayed, and there are no `SourceRef` citations or `resolve_sources`.

**Approach:** Add `SourceRef`/`ResolvedSource`/`Grounded` to `schemas/sources.py`; add `app/access/sources.py` (`register_resolver`, `resolve_sources`, `visible_refs`, journal + player_journal resolvers); add GM/Party chat schema pairs to `access/projection.py` (`CHAT_META`, `CHAT_REPLY`, `CHAT_DETAIL` variants of `ChatSession`) with message redaction and a replay helper; rebuild the chat routes on them (ctx via `ctx_for_request`, archived/hidden/missing session → one 404, refs stored per message); EV-4 probes for every chat route.

## Boundaries & Constraints

**Always:** GM ctx behaviour unchanged (Shorthand, glossary, canon, `system_prompt` trace) apart from the new `citations` field and stored refs. Non-GM: Party schemas with no `shorthand` and no `system_prompt` at any depth, canon empty, no glossary, every candidate and citation visible to ctx (re-checked through `visible_refs`). Visibility is checked in `access` before a resolver runs; a kind with no resolver is dropped and logged once as `resolver_missing`. Stored messages are `{role, content, refs, grounded}` (user turns `{role, content, refs: []}`), never titles/snippets. A message whose refs are not all visible (legacy: no `refs` key → visible only to a GM ctx) is redacted on read and left out of replay and of the rewrite history. Replayed turns are `{role, content}` only. The no-relevant-entries note stays in the final user turn.

**Never:** moving non-chat routes off deprecated helpers (E0-Access.5); setting `archived_at` (E0-Access.10); `grant_watch`/stream close (E0-Access.11); a migration; E0-Jobs.2, E0-Platform.5, E0-QA.15 files; editing `sprint-status.yaml`, `epics.md` or the desktop queue.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Player chat | Player ctx, visible + GM-only entries match | `ChatPartyResponse`: sources/candidates without `shorthand`, trace without `system_prompt`, `citations` = ResolvedSource for used visible entries only, `canon_sources=[]` | — |
| GM chat | GM ctx | GM schema, Shorthand, glossary, `system_prompt`, citations | — |
| resolve_sources | refs: visible, GM-only, missing, wrong kind, `field=shorthand`, `field=None` (non-GM), unregistered kind | only the visible field refs, input order, deduped | unregistered kind dropped, `resolver_missing` logged once |
| Stored message | assistant turn saved | `{role, content, refs:[SourceRef], grounded}` | — |
| Read/replay | message refs a since-hidden entry; legacy message (no `refs`) | Player: redacted (`content` = notice, `redacted: true`, `refs: []`), absent from replay; GM: legacy shown | — |
| Archived session | `archived_at` set | Player: absent from list, GET/POST/DELETE 404 (same as missing); GM: listed, readable, deletable, POST 404 | — |
| Session mismatch | `session_id` missing, another user's, other Campaign | 404 | uniform 404 |
| Campaign denied | `campaign_id` not the user's / bad UUID / preview POST | 404 | uniform 404 |
| Session search | Player searches a word only in a redacted message | session not returned | — |

</intent-contract>

## Code Map

- `src/backend/app/api/routes/chat.py` -- `_ChatPrep`, `_prepare_chat(body,user,db,config)` (ctx via `ctx_for`, falls back to campaign-less on denial; session loaded by id+user, created when missing; candidates/sources with `shorthand=""` for non-GM; `retrieval_debug()`), `_persist_chat_turn` (stores `{role, content}`), `list_sessions` (SQL ILIKE on `cast(messages, Text)`), `get_session`, `delete_session`, `chat`, `chat_stream` (meta dict built inline).
- `src/backend/app/services/chat_service.py:build_chat_messages` -- adds canon, glossary, Notes lines; grounding note into the final user turn; `messages.extend(history[-8:])` passes stored dicts verbatim.
- `src/backend/app/schemas/chat.py` -- `ChatMessage`, `JournalSource`, `RetrievalCandidate`, `RetrievalDebug`, `ChatResponse`, `ChatSessionSummary/Detail`.
- `src/backend/app/schemas/sources.py` -- `SourceKind` only (append-only).
- `src/backend/app/access/projection.py` -- `PROJECTIONS`, `project` (sync; `_check_row`: ChatSession is `stored(column=None)` → Owner(user_id), Campaign scope), `project_all`, import-time `check_party_schemas` (no `shorthand` anywhere in a Party schema).
- `src/backend/app/access/registry.py` -- `scoped_select`, `scope_column`, `gm_fields`, `registration` (Stored.field_visibility), `ALWAYS_GM_FIELDS`.
- `src/backend/app/access/context.py` -- `ctx_for_request(request, db, user, campaign_id)` (preview narrows, POST in preview 404), `RoleMap`, `role_map`, `role_ctx`.
- `src/backend/app/services/retrieval_service.py` -- `hybrid_search_journal(ctx=)`, `hybrid_search_own_journals(roles=)`, `retrieve_sources(kinds=[SOURCE_DOCUMENTS])`; `RetrievedEntry.entry.kind`.
- `src/backend/tests/test_party_retrieval.py:463` -- chat test asserting `shorthand == ""`; update to field absent.
- `src/backend/tests/test_llm_provider_gate.py:381-487` -- monkeypatches `_prepare_chat(body,user,db,config)` and a `fake_prep` shape; adjust to the new signature/meta.
- `src/backend/tests/ev4/probes/retrieval.py` -- chat probes (`_chat_probe`, `_trace`, `_sse_meta`); `tests/ev4/pending_baseline.txt` chat lines; `exemptions.yaml`.
- `src/frontend/src/types/index.ts`, `src/frontend/src/pages/ChatPage.tsx` -- `shorthand` required in `JournalSource`/`RetrievalCandidate`, rendered unconditionally.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/schemas/sources.py` -- append `SourceRef` (frozen; kind, id, field?, span?), `ResolvedSource {ref, title, quote}`, `Grounded {grounded: bool}`.
- `src/backend/app/access/sources.py` -- new: `register_resolver(kind, fn, *, model=None, where=None)`, `visible_refs(db, refs, ctx|RoleMap)`, `resolve_sources(db, refs, ctx|RoleMap)`, `message_refs(msg)`; built-in `journal` (kind gm) and `player_journal` (kind player) resolvers; export from `app/access/__init__.py`.
- `src/backend/app/schemas/chat.py` -- GM/Party pairs: `JournalSource`/`JournalSourceParty`, `RetrievalCandidate`/`RetrievalCandidateParty`, `RetrievalDebug`/`RetrievalDebugParty`, `ChatMetaGM`/`ChatMetaParty`, `ChatGMResponse`/`ChatPartyResponse` (`ChatResponse` alias), `StoredChatMessage`, `ChatSessionDetailGM`/`ChatSessionDetailParty`; `archived_at` on the summary.
- `src/backend/app/access/projection.py` -- register the three ChatSession variants; `project` redacts messages from `visible_refs=`; `project_chat(db, session, ctx|RoleMap, variant, extra)` (RoleMap: campaign-less own sessions, GM schema); `replay_history(db, session, ctx|RoleMap)`.
- `src/backend/app/services/chat_service.py` -- `build_chat_messages(..., ctx=None)`: non-GM ctx drops glossary, canon and Shorthand; history replayed as `{role, content}`.
- `src/backend/app/api/routes/chat.py` -- rebuild on the above (matrix rows).
- `src/backend/tests/test_party_chat.py` -- new: matrix rows, resolver registry, Party schema shape, replay capture, legacy messages, archived sessions, search.
- `src/backend/tests/ev4/probes/chat.py` -- probes for `GET /api/chat/sessions`, `GET /api/chat/sessions/{session_id}`, `DELETE /api/chat/sessions/{session_id}`; `retrieval.py` chat probes extended to citations + replay of a redacted session; exempt `GET /api/chat/health`; delete the four pending lines.
- `src/backend/tests/test_party_retrieval.py`, `tests/test_llm_provider_gate.py` -- adapt to the Party schemas and new prep shape.
- `src/frontend/src/types/index.ts`, `src/frontend/src/pages/ChatPage.tsx`, `src/frontend/src/hooks/useChat.ts` -- `shorthand?`, `system_prompt?`, `citations?`; render Notes only when present.

**Acceptance Criteria:**
- Given a Player in Campaign A, when they chat (blocking and stream) including with a session that holds a since-hidden message, then no GM-only canary appears in the response, SSE events, citations, trace or captured LLM context, and a GM-only change leaves their candidates, sources and citations (ids, order, count) unchanged.
- Given a GM, when they chat, then the captured prompt still has Shorthand and glossary and the trace has `system_prompt`.
- Given CI, when backend-tests, gates and frontend-ci run, then all pass with EV-4 leaks=0 and the four chat routes off `pending_baseline.txt`.

## Spec Change Log

## Review Triage Log

## Design Notes

`field=None` on a ref means the whole record, GM fields included, so a non-GM ctx sees a `field=None` ref only for a model with no GM fields; Party chat stores `field="narrative"`, GM chat `field=None`. That makes a GM-built citation redact itself if the same user later reads it through a non-GM ctx (campaign-less session after a demotion).

`resolve_sources(db, refs, ctx)` takes `db` (it loads rows), like `scoped_get`. The route builds one GM-shaped dict and `project_chat` validates it into the ctx's schema; the Party schemas drop `shorthand`/`system_prompt` and force `canon_sources=[]`, so the strip happens in projection, not in the route.

## Verification

**Commands:**
- `uv run --python 3.11 python -m py_compile <changed .py>` -- expected: no errors.
- `cd src/frontend && npx tsc --noEmit && npm run build` -- expected: success.
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: all green.
