---
title: 'E0-QA.12 (2.12): Demo seed and the shared eval-script scaffold'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: '2b74d89798a9d9ed3e96c125eeec0a4897d39df8'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** The 9-entry demo Campaign behind `docs/RETRIEVAL_EVAL.md` is not in the repo, and there is no shared way to write an eval. EV-1, EV-2, EV-3, EV-5 and EV-6 would each invent their own seed, CLI and report, and none could run offline.

**Approach:** Commit `seeds/demo_campaign.json`: the 9 demo entries (rebuilt so that every substring `eval_retrieval.py` labels still matches), plus 3 eval entries (Mira dies, a contradiction, a flashback trap), with NPCs, factions, quests, locations and seeded GM secrets, each under a stable `seed_id`. `scripts/seed_demo.py` writes it through the ORM, idempotent on `seed_id`. `scripts/eval_common.py` provides `load_campaign`, `sweep`, `write_report`, the shared CLI and an LLM handle (Ollama at a configurable URL, or a fake). `docs/EVAL_TEMPLATE.md` is the report skeleton. `eval_retrieval.py` moves onto `eval_common`.

## Boundaries & Constraints

**Always:**
- Paths: `seeds/` and `docs/` are at the repo root (B1 path rule). The eval and seed scripts import `app.*`, so they live next to the existing `eval_retrieval.py` in `src/backend/scripts/` (the backend container's `scripts/`, which is the path the story and `RETRIEVAL_EVAL.md` use).
- The seed writes through the ORM models. `narrative_tsv` is set with the same `to_tsvector('english', shorthand || ' ' || narrative)` as `journal_service` and migration `a3e7c1f9d258`. The embedding covers the same text.
- Offline (NFR-1): no network beyond `--database-url`. The embedding model loads with `HF_HUB_OFFLINE=1` and `local_files_only=True`. If it is not cached: `--embeddings auto` (default) leaves `embedding` NULL and warns, `require` exits 1, `skip` never loads it. No Redis, no spaCy, no LLM.
- Idempotent: journal entries are keyed by `entry_hash = sha256("lorekeeper-seed:<campaign id>:<seed_id>")`, NPCs by (campaign, name), quests by (campaign, title), the Campaign by (owner, name). A second run creates nothing and prints the same Campaign id. The only update is filling a NULL embedding once a model is available.
- GM secrets sit only in GM-only fields (journal `shorthand`, NPC `notes`, quest `notes`, which are not in the `Public*` share schemas). Each is listed in a `gm_secrets` block with a unique phrase, so EV-3/EV-4 can probe for it.
- LLM steps go through `llm_provider.complete_messages` with `provider="custom"` (no priority gate, no Redis). URL: `--llm-url` / `EVAL_LLM_URL` / `settings.kobold_url` (the stack's Ollama). Model: `--llm-model` / `EVAL_LLM_MODEL` / `settings.local_llm_model`. `--fake-llm` or `EVAL_FAKE_LLM=1` picks a deterministic fake. There is no `app/clients/fakes.py` LLM fake yet (E0-LLM.5), so the fake lives in `eval_common`.
- `write_report` never touches hand-written prose. In an existing doc it rewrites only the `<!-- eval:results -->…<!-- /eval:results -->` and `<!-- eval:failures -->…<!-- /eval:failures -->` regions. A missing doc is created from `docs/EVAL_TEMPLATE.md`.

**Never:** No migration or new column (E0-QA owns no tables). Don't edit compose files, `app/clients/*`, `embedding_service.py` (E0-Platform.3), `prompt_budget.py`, gate scripts or frontend. No `world` block or `seeds/labels/` (later stories own them). Don't change the numbers published in `RETRIEVAL_EVAL.md` without a real re-run. Don't call the remote desktop from CI.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First seed | empty DB at head | 1 user (if missing), 1 Campaign, 12 entries, NPCs, quests; prints Campaign id | — |
| Re-run | already seeded | `created 0`, same Campaign id, row counts unchanged | — |
| No cached model | `--embeddings auto` | entries seeded with NULL embedding, warning on stderr | `require` → exit 1 with a message |
| Model appears later | re-run with model | NULL embeddings filled, reported as `embedded N` | — |
| Existing owner | `--owner-email` of a real user | Campaign created under that user, user untouched | — |
| Bad seed | duplicate `seed_id` or missing field | exits 1 naming the problem, before touching the DB | `SeedError` |
| Report, new doc | `--out docs/X_EVAL.md` absent | file made from template, regions filled | — |
| Report, existing doc without markers | doc has no regions | doc unchanged | `ReportError` naming the missing marker |

</intent-contract>

## Code Map

- `src/backend/scripts/eval_retrieval.py` -- 21 `LABELED` queries keyed by shorthand substrings: `goblin chief Grukk`, `scholar Aldric`, `Borin Stonebeard`, `deep halls of Karak Dun`, `gates of Karak Dun`, `Aldric deciphered`, `Forge of Dawn`, `ash-grey robes`, `Sunless Throne` (one per demo entry). Move onto `eval_common`; keep `LABELED`, `vector_only`, `hybrid`.
- `src/backend/app/services/journal_service.py:108-121` -- the tsv UPDATE and `embed(f"{notes} {narrative}")` the seed mirrors.
- `src/backend/app/services/retrieval_service.py:26,44` -- `embed` imported by name (tests patch `retrieval_service.embed`), `RAG_RELEVANCE_MAX_DISTANCE = 0.65`.
- `src/backend/app/services/llm_provider.py` -- `LLMConfig`, `complete_messages`, `_transport` (MockTransport hook), and `custom` provider = OpenAI-compatible at `api_url` with `cfg.model`, ungated.
- `src/backend/app/db/models/{user,campaign,journal,npc,quest}.py` -- ORM targets. `NpcRole.faction` holds factions. `entry_hash` is unique.
- `src/backend/app/schemas/share.py` -- `Public*` schemas leave out shorthand and NPC/quest notes (they are GM-only).
- `src/backend/tests/conftest.py` -- `TEST_DB_URL`, the session schema build. Tests commit through their own engine.
- `site/index.html:132` -- the original entry-1 shorthand ("Party defeated goblin chief Grukk at the old mill…").
- `docs/RETRIEVAL_EVAL.md` -- the format to keep: method, results code block, chosen point, failure→fix table, reproduce.

## Tasks & Acceptance

**Execution:**
- `seeds/demo_campaign.json` -- new: `format_version`, `campaign`, `owner`, `entries` (12 with `seed_id`, `session_number`, `session_date`, `shorthand`, `narrative`, `purpose`, optional `eval_label`), `npcs` (PCs, NPCs, factions, `status_history`), `quests`, `locations` (reference only), `gm_secrets`.
- `src/backend/scripts/seed_demo.py` -- new: `read_seed`/`validate_seed`, `load_embedder(mode)`, `async seed_campaign(session, seed, owner_email, embedder) -> SeedResult`, CLI `--database-url --owner-email --seed --embeddings`. Prints the Campaign id and counts.
- `src/backend/scripts/eval_common.py` -- new: `load_campaign`, `sweep`, `ResultTable`, `Failure`, `format_table`, `write_report`, `build_parser`, `make_llm` (`OllamaLLM`, `FakeLLM`), `open_session`. `__main__` is a smoke run (seed → one LLM question per entry window → table).
- `src/backend/scripts/eval_retrieval.py` -- rewrite onto `eval_common`. Operating points are thresholds × {vector-only, hybrid}. Default chosen point hybrid@0.65.
- `docs/EVAL_TEMPLATE.md` -- new skeleton in the RETRIEVAL_EVAL section order, with the region markers.
- `docs/RETRIEVAL_EVAL.md` -- wrap the results block in markers, point the reproduce section at the seed + new CLI. Numbers unchanged.
- `src/backend/tests/seeds/test_demo_seed.py` -- seed file shape, labelled substrings present, secrets only in GM-only fields, idempotent double seed against the test DB, tsv set, embeddings filled by an injected embedder, offline auto mode.
- `src/backend/tests/test_eval_common.py` -- sweep/table/report regions, template creation, missing marker error, LLM selection (fake, URL/model precedence, MockTransport call), and an end-to-end `eval_retrieval` run with a fake embedder and `--out`.

**Acceptance Criteria:**
- Given the committed seed, when `seed_demo.py` runs twice against the test DB, then the second run reports 0 created and the same Campaign id.
- Given `eval_retrieval.py --fake-llm --campaign-id <id> --out <tmp>.md` in CI, when it runs, then the doc holds a 6-row table with hybrid@0.65 marked.
- Given the desktop with the cached embedding model, when the reproduce command runs, then hybrid@0.65 is 14/16 ±1 hit@3 and 5/5 gate-holds (desktop verification).

## Design Notes

The original 9 entries were never committed, so they are rebuilt from the labelled substrings, the landing-page example and the site's plan recap (Silver Key, Ashen Hand, Aldric). Each paraphrase query's answer is in prose, not keywords, and each proper-noun query names a rare noun that appears literally, to keep the original difficulty. The ±1 reproduction can only be checked on the desktop. If it misses, `RETRIEVAL_EVAL.md` is re-measured on this seed, not the seed bent to the numbers.

## Verification

**Commands:**
- `python -m py_compile src/backend/scripts/*.py` -- expected: no output
- CI `backend-tests.yml` -- expected: green, existing tests unchanged plus the new seed/eval tests

## Spec Change Log

## Review Triage Log
