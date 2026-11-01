---
title: 'E0-QA.15: EV-5 benchmark suite and the x86 spike re-run'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: '9160cb62abe2d7cace054d4e95f6d85883b185f9'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/src/backend/scripts/eval_common.py'
  - '{project-root}/src/backend/tests/test_eval_common.py'
warnings: ['multiple-goals']
deferred: []
---

<intent-contract>

## Intent

**Problem:** NFR-6 latency targets and the SPIKE-1/2/3 decisions rest on an M-series Mac capped at 4 threads (n=1), and there is no reproducible EV-5 harness or `docs/BENCHMARKS.md` where each feature epic records its NFR-6 / NFR-2 row.

**Approach:** Add `src/backend/scripts/eval_benchmarks.py` (on `eval_common`) that renders `docs/BENCHMARKS.md` from a committed JSON store (`docs/benchmarks.json`): one row per NFR-6 target and NFR-2 case, plus spike tables ingested from the JSON that the spike scripts under `src/backend/scripts/spikes/` emit. Re-run the spikes on the x86 desktop (CPU column constrained to the AD-7 limits, GPU column on the RTX 5080), record the results and any proposed target reset in `.memlog.md`.

## Boundaries & Constraints

**Always:** rows whose feature hasn't landed show `pending (E<n>)` with the owning epic; columns are exactly target CPU, target GPU, measured CPU, measured GPU, peak RSS, n, date, hardware, owning epic; only the generated regions of `docs/BENCHMARKS.md` are rewritten (prose is hand-written); the store and the doc stay in sync (a test checks it); stdlib + existing backend deps only.

**Never:** change NFR-6 targets in the PRD (resets are pending `.memlog.md` entries needing owner sign-off); add model packages to the backend image or requirements (spike scripts run in the throwaway `Dockerfile.bench` image or the existing backend image); touch `epics.md`, `sprint-status.yaml`, the desktop's dev/Supabase/lk-v11 containers.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Blank store | `docs/benchmarks.json` with no measurements | 12 rows (9 NFR-6 + 3 NFR-2), measured cells `pending (E<n>)` | — |
| Epic records a row | `record("proposals", "cpu", value=..., n=5, hardware=...)` | that row's measured CPU, n, date, hardware filled; GPU still pending | — |
| Bad row / column | unknown row id, column not cpu/gpu, n < 1 | nothing written | `ValueError` |
| Ingest spike JSON | `--ingest a.json b.json` (the `_bench` result shape) | spike tables show each (spike, config, column) once; a re-ingest of the same key replaces it | malformed file → `ValueError`, store unchanged |
| Doc missing a region | BENCHMARKS.md without `<!-- bench:nfr -->` | doc unchanged | `ReportError` |

</intent-contract>

## Code Map

- `src/backend/scripts/eval_common.py` -- `write_report`, `_region_re`, `_replace_region`, `ReportError`, `DOCS_DIR`; add a public `write_regions(path, regions)` (same marker syntax) and make `write_report` use it.
- `src/backend/tests/test_eval_common.py` -- test style for the scripts (imports `from scripts import ...`, tmp_path docs).
- `src/backend/scripts/spikes/_bench.py` -- (written) result shape: `{"spike","config","column","env":{date,cpu,hardware_label,...},"metrics":{...}}`; `stats()` gives `{n,median,min,max,p25,p75}`.
- `src/backend/scripts/spikes/spike1_nli.py`, `spike2_stt.py`, `spike3_tts.py`, `spike6_llm_throughput.py`, `run_x86.sh`, `Dockerfile.bench` -- (written) metric keys the spike tables render: SPIKE-1 `fifty_pairs_s`, `per_pair_batch1_ms`, `pairs_per_s`, `sanity_correct`, `peak_rss_mb`; SPIKE-2 `chunk_latency_s`, `chunk_rtf`, `full_rtf`, `word_match`, `names_no_prompt`, `names_with_prompt`, `busy.chunk_rtf`, `peak_rss_mb`; SPIKE-3 `generation_s`, `rtf`, `first_audio_s`, `audio_s`, `dropped_words`, `peak_rss_mb`; SPIKE-6 `shapes.<name>.{prompt_tokens,prompt_tok_s,gen_tok_s,ttft_s,total_s}`, `structured.{calls,first_try_valid,valid_after_repair,failed,latency_s}`, env `ollama`, `model_digest`.
- PRD NFR-6 table (`prd.md` §NFR-6) -- the 9 targets; NFR-2 -- the 3 memory cases (sum of limits ≤ 14.5 GB).

## Tasks & Acceptance

**Execution:**
- `src/backend/scripts/eval_common.py` -- add `write_regions`; `write_report` delegates to it -- one region writer for every eval.
- `src/backend/scripts/eval_benchmarks.py` -- `ROWS` (id, group, label, target CPU, target GPU, owner) for proposals/E1, continuity/E2, caption_lag/E4, rolling_recap/E4, quick_lookup/E4, npc_first_token/E6, narration_300/E5, chronicle_100/E8, portal_warm/E7, nfr2_idle, nfr2_heavy_job, nfr2_live (E0-Platform; live also E4); `load_store`, `record`, `ingest`, `render` (regions `bench:nfr`, `bench:spikes`), `write`; CLI: no args re-renders, `--ingest FILE...`, `--record ROW --column --value --peak-rss-mb --n --hardware --note`, `--store`, `--out` -- the EV-5 harness every epic fills.
- `docs/benchmarks.json`, `docs/BENCHMARKS.md` -- store (no measurements yet) and doc with both region markers, rendered by the script, plus prose placeholders for method/hardware/verdicts -- EV-5 output. (The measured numbers, verdict prose, `.memlog.md` and the x86 spike doc below are filled by the desktop run, not the implementer.)
- `src/backend/tests/test_eval_benchmarks.py` -- one test per matrix row, plus: committed doc regions equal `render(committed store)`; `_bench.stats` median/spread -- CI guard.
- `.memlog.md` -- (desktop run) pending owner-sign-off entries for each NFR-6 target the x86 numbers would reset -- AC 3.
- `_bmad-output/planning-artifacts/spikes/x86-desktop-benchmarks.md` -- (desktop run) machine, versions, commands, n, raw results -- the record E0-Platform.10 / E0-LLM.6 read.

**Acceptance Criteria:**
- Given the committed store, when `python scripts/eval_benchmarks.py` runs, then `docs/BENCHMARKS.md` is unchanged (idempotent) and has the 12 rows with the 9 columns plus the row label.
- Given the spike results from the desktop, when ingested, then BENCHMARKS.md records SPIKE-1 (xsmall vs base, 50 pairs) and SPIKE-2 (base int8 vs float32 per 15 s chunk, LLM busy, `initial_prompt` names on the 6 demo names) with n ≥ 5, median and spread, and states whether xsmall / base STT / 15 s chunks still hold.
- Given a target the x86 numbers would change, then `.memlog.md` holds a pending entry and the PRD is untouched.

## Design Notes

Store shape: `{"format": 1, "rows": {"<id>": {"cpu": M, "gpu": M}}, "spikes": [result, ...]}` with `M = {"value": str, "peak_rss_mb": float|null, "n": int, "date": "YYYY-MM-DD", "hardware": str, "note": str|null}`. Peak RSS cell joins the cpu/gpu values that exist. Spike results are keyed by `(spike, config, column)`; tables sort by spike, then config, then column. Values format medians as `median (min–max)`.

## Verification

**Commands:**
- `cd src/backend && python -m pytest -q tests/test_eval_benchmarks.py tests/test_eval_common.py` (CI / desktop backend image) -- expected: all pass
- `uv run --python 3.11 python -m py_compile src/backend/scripts/eval_benchmarks.py src/backend/scripts/spikes/*.py` -- expected: no output
