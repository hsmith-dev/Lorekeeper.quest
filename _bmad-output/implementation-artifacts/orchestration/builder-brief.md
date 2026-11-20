# Builder brief — Lorekeeper expansion (shared by parallel story builders)

You build ONE story from `_bmad-output/planning-artifacts/epics.md` in an isolated git worktree based on `main`, using the BMAD **bmad-build-auto** workflow (unattended). Other builders run in parallel on other stories. Owner decisions that override any planning doc are in `_bmad-output/planning-artifacts/scope-input.md` (rounds 1–4) — read them.

## Setup
1. Rename your worktree branch: `git branch -m story/<story-id-lowercase>-<short-slug>`.
2. Invoke the `bmad-build-auto` skill with intent: "Implement story <STORY-ID> exactly as written in `_bmad-output/planning-artifacts/epics.md`. Planning context: the PRD (`prds/prd-Lorekeeper.quest-2026-10-31/`), `architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md`, `ux-designs/ux-Lorekeeper.quest-2026-10-31/{DESIGN,EXPERIENCE}.md`, `brownfield-context.md`, `epics.md` 'Boundary map additions', and `scope-input.md` owner decisions. Epic ids are non-numeric; the numeric map is `_bmad-output/implementation-artifacts/epics-numeric-alias.md`."
3. Stay inside the story's scope. If the story is wrong or impossible as written, HALT `blocked` with the reason rather than improvising.
4. If you hand implementation to a subagent and it finishes, CONTINUE yourself (review → commit → PR). Don't wait for a notification you already received.

## Hard rules
- **Never modify the owner's Mac** outside your worktree and the session scratchpad: no `brew install`, nothing copied into `/opt/homebrew` or system prefixes, no global npm/pip installs.
- **Never run database/queue servers on the Mac** (Postgres, Redis/Valkey). Use the desktop (your own containers) or GitHub CI. Any other local process you start binds to `127.0.0.1` and is stopped before you finish.
- Don't edit `_bmad-output/implementation-artifacts/sprint-status.yaml`, `epics.md`, or `desktop-verification-queue.md` — the orchestrator does that at merge. Don't commit generated `epic-*-context.md` files.
- Push your branch and open a **draft PR**; iterate until GitHub CI is green. **Never merge, never mark ready, never push to main.**
- Commit trailers (exactly):
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017fHFDg8qzK1xh593WLzE65
  ```

## Testing
- **GitHub CI is the gate:** `backend-tests.yml` (full pytest on Postgres+pgvector + Valkey 8.1.11), `gates.yml` (import contracts CI-2, model packages CI-3, scoped queries CI-8, table owners CI-7, enum sync CI-10, property tests CI-11, EV-4 CI-12, memory budget CI-14), `frontend-ci.yml` (build + check scripts incl. `lint:tokens`), `license-check.yml` (both editions + image scans).
- **Desktop** (`ssh harrison@100.119.62.5`, shell is **fish** → wrap in `bash -lc '...'`; RTX 5080; native Ollama `lorekeeper` on :11434): the cached image `lorekeeper-backend-test` has all backend + dev deps (rq, croniter, WeasyPrint libs, CPU torch). Start your OWN `pgvector/pgvector:pg16` and `valkey/valkey:8.1.11-alpine` containers with unique names, run pytest with `-e TEST_DATABASE_URL=… -e DATABASE_URL=<same> -e VALKEY_URL=… -e VALKEY_TEST_URL=…`, and **remove your containers and run dirs afterwards**. Don't touch `~/lorekeeper-dev`, Supabase/`local-setup-*` containers, or port 8000.
- Frontend: `npx tsc --noEmit`, `npm run build`, the `scripts/check-*.mjs` scripts. Throwaway Playwright runs in headless Chromium against a mocked API are encouraged for UI behaviour.
- **Known flaky:** `tests/test_pubsub.py::test_unkeyed_invalidation_burst_is_one_now_and_one_at_window_end[real]` (fix in flight on `fix/deflake-pubsub-burst`). Re-run once if it alone fails.
- List anything CI can't verify under **"Needs desktop verification"** in your spec and reply, with exact commands.

## Return (≤ 12 lines)
Story id, build-auto status, branch, PR number, CI status, files changed, test counts, EV-4 counts, deferred items, "Needs desktop verification".

## Platform facts (merged on main)
- **Access layer (`app/access/`) is the ONLY enforcement point.** Reads via `scoped_select`/`scoped_get`/`scoped_select_multi`/`owned_get`; responses via `project`/`project_all` (GM/Party schema pairs; the single place GM fields are stripped); `require_campaign("player"|"gm"|"owner")`; uniform `not_found()` 404 for hidden ≡ missing; `Vary: Authorization, X-Lorekeeper-Preview`; preview header only narrows. CI-8 (`scripts/check_scoped_queries.py`) fails on raw selects/`db.get`/raw SQL on registered tables or visibility writes outside `app/access/` — **never add a baseline line**; `OWNER_INFRA` allows only `app/jobs/` → `Job`/`DataBackfill`.
- **Writes:** `can_write(ctx, obj)` (`app/access/write.py`) is the single write gate (refuses preview/audience/anon/cross-Campaign; Players write only their own `kind=player` entries; **Character Sheet STOPGAP until E7**: Players may edit sheets they created). Visibility changes only via `set_visibility`/`set_visibility_many` (`app/access/visibility.py`); entities/relationships via `world_service.apply_change` as the registered writer.
- **Grants:** `app/access/grants.py` is the only place roles/membership/share links change (bumps `access_epoch`, publishes `access:{campaign}:{grant}` after commit, closes streams via `grant_watch`). Cache keys only via `app/access/cache.py` (`cache:{campaign}:{generation}:{audience}:{access_epoch}:…`).
- **Retrieval/chat:** `hybrid_search_journal(ctx, …, entry_ids=, narrative_only=)` (non-GMs search only `party_tsv`/`party_embedding`); `access.resolve_sources(db, refs, ctx)` is the only citation builder; chat uses Party schemas for non-GMs.
- **Jobs:** `enqueue(db, ctx, kind, payload, *, idempotency_key, depends_on_job_id=None)`; kind registry; outbox → RQ on Valkey; `JOBS_EAGER=1` in tests; worker wrapper (rights re-check, LLM config, gate class, heartbeat, retries +10 s/+60 s); reaper (30 s); priority interactive > onsave > backfill; heavy-model leases `res:<resource>`; Live admission lease; cursor backfills `run_cursor` + `register_backfill`. Register new kind modules in `registry.KIND_MODULES`.
- **Hooks:** `app/core/after_commit.py` (shared collect/drop-on-rollback/run-after-commit primitive); `app/core/hooks.py` (`emit`, `register_handler`, 8 `HookEvent`s, handlers after commit, 30 s limit); register feature handlers in `app/hooks/__init__.py` `HANDLERS`.
- **Streaming:** `app/core/pubsub.py` is the only publisher/subscriber (`publish_job`, `publish_campaign_event`, `publish_live`); `app/core/sse.py` `sse_response(gen, *, ctx)`; campaign events route `GET /api/campaigns/{id}/events` (audience-filtered in `app/access/events.py`). **Resync contract:** first frame `subscribed`; clients refetch on every `subscribed`. New stream routes need an nginx location with buffering off, 1 h read timeout, gzip off (quote `{36}` regexes).
- **LLM:** `app/core/llm_gate.py` priority gate (live_recap > interactive > jobs; per-attempt slots); `llm_provider.complete_structured` (Ollama `format`, ≤ 2 repairs, flat schemas in `app/schemas/llm/`); `detect_backend`; `app/services/prompt_budget.py`; deterministic fake + `capture()` for EV-4.
- **World model:** `app/domain/entity_types.py` (5 types, owner-amended attributes incl. Character voice/appearance/pronouns/goals, Location `kind` CHOICE, etc.), `app/domain/enums.py`, `app/domain/names.py` (`normalize_name`), `app/services/world_matching.py` (**`match_names(db, ctx, text, …)` / `candidates(db, ctx, surface, …)` take `db` first**), `world_service.apply_change`/`revert_change` (19 ops, per-proposal advisory lock, idempotent replay, one history row each). Migration `03c0b504f1d1` needs **PostgreSQL 15+** (guarded).
- **Files:** `app/services/file_service.py` (`put`, `put_tree`), `app/access/files.py`, `GET /api/files/{id}` via nginx internal `/_files/`; Player-owned files store `cache_key` as `<owner id>:<cache_key>`.
- **Sidecars:** `ml` (embeddings, NER, lazy NLI xsmall + RapidOCR under a memory budget), `stt` (faster-whisper base int8, ffmpeg CLI decode, **no PyAV**). Clients in `app/clients/` with fakes. Queue server is **Valkey** (`VALKEY_URL`, `app/core/valkey_client.py`).
- **Licences:** every new dependency/model/image needs a `licenses/register.yaml` entry; only permissive deps may ship (AGPL + commercial). WeasyPrint for PDF, RapidOCR for OCR, Kokoro+espeak only in the AGPL `tts` image.

## Carry-over notes for specific stories
- **E0-Access.12 (members/roles UI):** role changes MUST call `grants.change_member_role`; archive a demoted member's chat sessions; join should grant the link's Role (today it creates a default Player); an unpaid Player who only reads Party content still gets sent to /subscribe by the frontend.
- **E0-Access.13:** analytics/export cover every Member, scoped by Role via the access layer.
- **E0-Jobs.9 (`lib/sse.ts`):** on `access_changed`, reconnect ONCE and stop only on 401/404 (a promotion also fires `grant_watch`); may replace E0-Access.11's `openFetchStream` transport.
- **E0-Jobs.10 (tray):** follow the `subscribed` → refetch contract; `registerTraySection` hook exists.
- **E0-WorldCore.5:** (a) **OWNER DECISION — pre-publish history stays GM-only:** record the write-time audience on each `entity_changes` row (migration) and filter history by it, not by current visibility; (b) add `aliases` to `HIDEABLE_FIELDS`; hiding the field must hide alias rows; (c) entity ids inside attributes and reference-attribute history must be visibility-checked; (d) default relationship types for Campaigns created after the upgrade (or E3.1).
- **E0-WorldCore.6 = RELEASE BLOCKER:** re-run the legacy copy for NPC/Quest rows written via the old pages after the upgrade, then retire those pages (a ratchet test blocks new writes to legacy `npcs`/`quests`).
- **E0-WorldCore.9 (merge):** re-point attribute refs to absorbed Entities; decide where a merged-away Entity's history shows without exposing GM-only history.
- **E0-LLM.6 (CRITICAL before E1):** a 300-Entity extraction prompt (~3.4k tokens) was silently truncated to 2,051 tokens at the 4096 context — calibrate `prompt_budget` so oversized prompts shortlist/split instead of being cut, and make truncation impossible to miss. Also: a reply cut off at the token limit gets repaired under the same limit.
- **E0-Platform.6:** move callers to the `ml`/`stt` sidecars; remove in-process model loading (CI-3 baseline shrinks).
- **E0-Platform.7:** memory limits to `*_MEM_LIMIT` vars (prod compose literals sum ~34 GiB vs the 16 GB baseline); use `VALKEY_MEM_LIMIT`; any CPU cap needs a matching Ollama `num_thread`.
- **E0-Platform.10:** Kokoro peaks 3.1 GB → OOM at the 2.5 GB `tts` limit (raise or synthesize smaller chunks; measure the real tts image); Ollama at 12 threads OOM at 5.25 GB.
- **E1 (extraction):** replay approved proposals ONLY through `apply_change`; use `match_names`/`candidates` (db-first); register hook handlers in `app/hooks/__init__.py`; structured output via `complete_structured` (10/10 CPU, 50/50 GPU valid first try).
- **E4 (live session):** pass campaign Entity names as faster-whisper `initial_prompt` (fixed 6/6 demo names); per-session `live` leases (today one shared key); **owner target: caption lag ≤ 10 s on CPU**.
- **E5 (narration):** **owner target ≤ 60 s on CPU**; TTSProvider interface; commercial build uses browser speech.
- **E7:** remove the Character Sheet stopgap (`SHEET_AUTHOR_STOPGAP = False`) once Players are linked to PCs; Player chat screen renders `citations`.
