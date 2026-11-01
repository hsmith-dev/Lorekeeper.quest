---
title: 'E0-LLM.5: Deterministic fake LLM provider and the EV-4 context-capture hook'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: 'f0431584b210413cf9f9812dc7a3f04ce3705998'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** Every AI route and Job needs Ollama to run, so CI can't exercise them. EV-4's captured-context probes (E0-QA.14) also need a way to see exactly what each LLM call sent. E0-QA.11's harness already calls `llm_provider.capture()`, and E0-QA.12's `eval_common` carries its own interim `FakeLLM`.

**Approach:** Add a deterministic, schema-aware fake to `llm_provider` (`provider="fake"`, also chosen for every config under `ENVIRONMENT=test`). It covers `complete_messages`, `stream_messages` and `complete_structured`, and can be scripted, including invalid replies. Add `llm_provider.capture()`, a contextvar context manager that records each call at the point it is sent. Add `tests/fixtures/fake_llm.py` with the `fake_llm` fixture and an autouse guard that fails any test opening a socket to `KOBOLD_URL`. Move `eval_common.FakeLLM` onto the fake.

## Boundaries & Constraints

**Always:**
- `fake_llm_active(cfg)` is true when `cfg.provider == "fake"` (any environment). Otherwise it is true only when `settings.environment == "test"`, no `llm_provider._transport` is installed (a MockTransport means the test drives the real provider code), and `llm_provider._real_llm_in_test` is false (the `ollama` marker sets it).
- The fake answers in place of the network send, after everything else runs as in production:
  - The gate (`gated`/`reserve_slot`, as today for the platform config).
  - The model choice.
  - `complete_structured`'s schema prompt, budget check, validation, repairs, stats and log lines. Here the fake is the per-attempt sender (`backend` = `"fake"`), and `detect_backend` is not called.
- `detect_backend` returns `BACKEND_OLLAMA` without probing while the fake is active, so `ai_service` skips the KoboldCpp-native request.
- Reply order:
  1. The next scripted item, if any. A `BaseException` instance is raised; anything else is returned as `str`.
  2. With a schema: `json.dumps(fake_json(flat schema))`. In that value enums and consts take their first member, strings are `"fake"`, integers/numbers are 0 (or `minimum`), booleans are false, and lists hold one element.
  3. Otherwise `[fake-llm <sha256(messages)[:8]>] <first 12 words of the last user turn>`, deterministic per messages.
- The fake streams in ≥2 chunks that join to exactly the `complete_messages` reply for the same messages.
- `capture()` is a sync context manager on a contextvar. It yields an `LLMCapture` whose `calls` is a list of `CapturedCall` dataclasses with these fields:
  - `messages`: a deep copy of exactly the messages sent (structured: with the schema prompt, then each repair prompt; one record per attempt).
  - `task`
  - `gate_class`: the resolved class for platform-LLM calls, else None.
  - `model`: what the request names.
  - `provider`
  - `fake`: bool.
  - `schema`: the schema's class name, or None.
- Captures nest: every active capture receives the call. It records for the fake and for real providers. When no capture is active, recording is one contextvar read.
- `tests/fixtures/fake_llm.py`:
  - `fake_llm` fixture: the reset fake, with `.script([...])`.
  - Autouse `no_kobold_socket`: patches `socket.socket.connect`/`connect_ex`. A connect to KOBOLD_URL's resolved (ip, port) is refused and recorded, and teardown fails the test if anything was recorded. `ollama`-marked tests skip it and set `_real_llm_in_test`.
  - `tests/conftest.py` gets exactly one added import line.

**Never:**
- A change to gate semantics (`llm_gate.py`), to `errors.py`, to the real senders' behaviour, or to `complete_structured`'s validation/repair rules.
- Recording `api_key` (or any header) in a capture.
- A new dependency.
- Edits to `app/access/`, `members.py`, the stt sidecar, `sprint-status.yaml`, `epics.md` or `desktop-verification-queue.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Plain, test env | default/openai/anthropic(no key)/gemini config, no transport | deterministic fake text; same messages same text; different messages different text | none |
| Stream | same messages | ≥2 chunks, joined == complete reply | none |
| Structured, no script | schema with enum, str, list[nested] | first enum member, "fake", one element; validates | none |
| Scripted repair | script `[bad, valid]` | instance; 2 captured attempts, the 2nd echoes `bad`; stats valid_after_repair | none |
| Scripted exhausted | script `[bad]*3` | — | `StructuredOutputError(attempts=3)` |
| Scripted error | script `[LLMUnavailable(...)]` | raised by plain/stream/structured | as scripted |
| MockTransport test | `_transport` set | real sender runs; capture still records the wire messages | as today |
| ollama marker | `@pytest.mark.ollama` | fake off, socket guard off | — |
| Capture off | no `capture()` | no record work | none |
| Socket to KOBOLD_URL | a test connects | refused (OSError) and recorded | teardown fails the test |

</intent-contract>

## Code Map

- `src/backend/app/services/llm_provider.py` -- add the fake routing and the capture:
  - `complete_messages` (l.190): record and fake inside `gated`.
  - `stream_messages` (l.609): a fake branch with `reserve_slot`/`release`; record before the upstream openai stream.
  - `complete_structured` (l.483): mode `MODE_FAKE` before `_structured_mode`; record per attempt inside `gated`.
  - `_send_structured` (l.451): a fake branch.
  - `detect_backend` (l.68): a fake short-circuit.
  - Default model names for anthropic and gemini: hoist the literals to constants so the capture's `model` matches (no behaviour change).
- `src/backend/app/clients/fakes.py` -- add `FakeLLM` (script queue, `reply`, `chunks`) and `fake_json(json_schema)`, next to `FakeMLClient`.
- `src/backend/app/schemas/llm/__init__.py` -- read-only: `flat_json_schema` inlines refs, so `fake_json` walks one flat tree.
- `src/backend/tests/ev4/families.py:210-246` -- read-only. The harness accepts a sync CM yielding an object with a non-callable `.calls`, which it JSON-dumps with `default=__dict__`, so a plain (non-slots) dataclass is required.
- `src/backend/tests/ev4/test_families.py:280-326` -- add real-capture tests beside the `_FakeCapture` ones.
- `src/backend/scripts/eval_common.py:305-320` -- `FakeLLM` delegates to `complete_messages(..., LLMConfig(provider="fake"))` and keeps `.calls` and `name`.
- `src/backend/tests/test_eval_common.py:146-152` -- determinism test (must still pass).
- `src/backend/tests/conftest.py` -- one import line for the fixtures.
- `src/backend/tests/integration/test_llm_structured_ollama.py:137` -- sets `_transport=None`; relies on the `ollama` marker opt-out.
- `src/backend/tests/test_llm_structured.py`, `test_llm_provider_gate.py`, `test_backend_detection.py` -- all install `_transport`, so the fake stays off for them.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/clients/fakes.py` -- `FakeLLM`, `fake_json`.
- `src/backend/app/services/llm_provider.py` -- `fake_llm` singleton, `fake_llm_active`, `_real_llm_in_test`, `MODE_FAKE`, `CapturedCall`, `LLMCapture`, `capture()`, `_record`, `_call_model`, the branches above, and the docstring.
- `src/backend/tests/fixtures/__init__.py`, `src/backend/tests/fixtures/fake_llm.py` -- fixtures.
- `src/backend/tests/conftest.py` -- one import line.
- `src/backend/scripts/eval_common.py` -- `FakeLLM` delegates to the fake; docstring.
- `src/backend/tests/test_llm_fake.py` -- every matrix row, plus:
  - capture fields, no api_key, nesting, and off-cost;
  - wire messages equal the captured messages (MockTransport, plain and structured);
  - `ai_service.generate_narrative` under the fake with no socket;
  - the guard self-test;
  - `fake_llm_active` in production and the opt-outs.
- `src/backend/tests/ev4/test_families.py` -- `assert_captured_context_clean` with the real `capture()`: a canary in a fake-LLM prompt is caught, and a clean prompt passes.
- `src/backend/tests/test_eval_common.py` -- `FakeLLM` equals the provider fake.

**Acceptance Criteria:**
- Given the PR's backend CI with no Ollama, when the suite runs, then all existing tests and the new ones pass, the guard records no KOBOLD_URL socket, and the `ollama` suite is skipped.
- Given the licence workflow, when it runs, then it passes unchanged (no new dependency).

## Design Notes

- An installed `_transport` disables the fake because those tests deliberately drive the real senders against a MockTransport. Faking them would void E0-LLM.2–.4's coverage.
- The fake replaces only the send, so a test using it still exercises the gate, budgets, repairs and stats. The recording is taken at the same point, so EV-4 sees the final prompt (post-budget, with the schema prompt and the repair turns), not the caller's draft.

## Verification

**Commands:**
- `uv run --python 3.11 python -m py_compile <changed .py>` -- expected: no output.
- Scratch venv with `--noconftest` for the pure unit tests -- expected: pass.
- Draft PR, then `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: all green.
