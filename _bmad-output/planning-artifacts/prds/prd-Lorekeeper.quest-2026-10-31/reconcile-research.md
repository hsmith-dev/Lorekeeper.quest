# Input reconciliation: research-decisions-summary.md vs PRD + addendum

Input: `_bmad-output/planning-artifacts/research-decisions-summary.md` (plus spot checks in `research/technical-local-ai-and-frontend-stack-for-lorekeep-2026-10-31/research.md`, cited as "research.md L<n>").
Reviewed: `prd.md`, `addendum.md` (same folder). PRD not edited.

Overall: coverage is strong. All nine recommendations, the rejected/NC options and all three cross-cutting decisions show up somewhere. The gaps below are ordered by importance.

## High

### G1. Live STT: the PRD's chunked framing conflicts with the streaming mechanism in the addendum, and the spike doesn't test the recommended design
- **Source:** Summary #3: "Live mode: a FastAPI WebSocket taking AudioWorklet PCM16 at 16 kHz, with Silero VAD and LocalAgreement-2 … Expected 2–4 s caption lag on CPU (unverified)." research.md L144-148: "chunks of about 0.5 s … re-transcribes a rolling 1–2 s minimum chunk".
- **PRD:** §5.4 says "transcribes each chunk of about 10 to 30 seconds … Near-real-time captions are a GPU-only enhancement". NFR-6 sets caption lag at ≤ 30 s on CPU. SPIKE-2 measures "10 to 30 s chunks" only. The addendum §A (FR-26 to FR-30) picks the LocalAgreement-2 streaming design, which is the opposite approach.
- **Why it matters:** the owner decision (scope-input L37: 10–30 s chunks) and the research recommendation disagree, and the PRD carries both without saying so. If the research is right, CPU streaming at 2–4 s is achievable, and the "GPU-only" claim and the 30 s target are far too loose.
- **Fix:** add the conflict as a §12 open question for the owner. Widen SPIKE-2 to measure both modes (LocalAgreement-2 streaming and 10–30 s chunked) for lag and RAM. Make the addendum mechanism depend on the spike result. Remove the chunk length from the §5.4 description (it is mechanism) and keep only the lag target.

### G2. Rolling Recap runs the 7B every minute while STT is resident, and the research's mitigation for that is missing
- **Source:** Summary cross-cutting #2: "The 7B already takes about half the RAM (unverified), so only STT stays resident during a live session." research.md L268: "Live mode should probably ask Ollama to unload the 7B (`keep_alive`) while transcription runs, or accept slower lookups."
- **PRD:** NFR-3 keeps STT as the only new resident model. However, FR-27 (Rolling Recap every ~60 s) and FR-28 (free-text cited answer) both need the 7B during the Live Session. Neither the PRD, addendum §D nor SPIKE-2/SPIKE-5 addresses having STT and the 7B loaded at the same time. SPIKE-2 measures "while the LLM is busy" for lag only, not memory.
- **Fix:** SPIKE-5 should measure peak RSS for a Live Session with STT plus the 7B producing the Rolling Recap. Addendum §D should record the `keep_alive` unload option and its trade-off: a slower recap or lookup, or recap refresh relaxed beyond 60 s on the Reference Box. NFR-6 could make the Rolling Recap refresh interval degradable on CPU.

### G3. RAM costs of the new models are not in the memory budget
- **Source:** Summary RAM/CPU column: NLI "about 0.3–0.8 GB"; STT "base int8 is under 1 GB; small int8 about 1.5 GB"; Kokoro "About 300 MB model (80 MB quantized)"; GLiNER 209M; WeasyPrint "Pango/HarfBuzz … modest MB (not measured)"; tiling "one-off server CPU cost per upload".
- **PRD/addendum:** addendum §D lists only today's stack (6.4/11.9 GB, 7B Q4 4.4 GB). The per-model costs appear nowhere except Kokoro disk size in §A/§E. NFR-2 says the baseline is already over budget but gives no projected total.
- **Fix:** add a per-model RAM table to addendum §D, marked unverified, and make it SPIKE-5's checklist: NLI base/xsmall, STT base/small int8, Kokoro, pyannote (torch), optional GLiNER, WeasyPrint render, and pyvips tiling of the largest allowed map.

### G4. The licence register is missing transitive and system dependencies, and some entries are unsourced
- **Source:** research.md L267: licences "hide in weights …, in UI wrappers … and in transitive dependencies (espeak-ng under Kokoro and Piper)", with CI via "e.g. `pip-licenses`, `license-checker`". research.md L227: "libvips is LGPL; we did not verify this". research.md L201: WeasyPrint needs `libpango`, `libharfbuzz-subset0`.
- **Addendum §F gaps:**
  - Pango (LGPL-2.1+) and HarfBuzz, the system libraries behind WeasyPrint, are missing. They are in the same situation as libvips (dynamic LGPL linking) and need the same allowlist note.
  - The code licences of kokoro-onnx and of the Kokoro-FastAPI image are not stated; only the weights are covered. misaki (Apache-2.0, research [39]) is missing.
  - Silero VAD is listed as "MIT (verify version)", but no research source gives its licence. The research only says it is bundled with faster-whisper.
  - The Unicode font is "a bundled Unicode font with an OFL licence" and is not named or registered.
  - The job runner (arq or RQ) is missing from the register.
  - pyvips/libvips "MIT / LGPL-2.1" is unverified per research.md L227, but the register states it as fact.
  - The CI tooling and the way model weights get checked (pip/npm licence scanners can't read weights or Docker base images) are not described. NFR-4 requires weights to be checked but no mechanism is given.
- **Fix:** add the missing rows, mark the unsourced ones "unverified". Add an addendum note that weights, voices, fonts and container system packages are tracked by hand in the register, with a CI step that fails when a model or container in compose is not listed. Name the candidate scanners. Reviewer note, beyond the research: if the CI check scans existing containers, check the Redis licence too (Redis 7.4+ is RSAL/SSPL and Redis 8 adds AGPL), even though Redis is not a new dependency.

## Medium

### G5. Single-source and unverified figures appear in the addendum as fact
- **Source:** Summary: "Claims ledger: 3 verified, 33 single-source." Unverified items: caption lag, NLI ms per pair, Kokoro real-time factor, "7B about half the RAM".
- **Addendum:** §A states "about 4× faster and about 37% less RAM" (single benchmark [20]) and the Kokoro first-chunk timing without a confidence marker. §A's header warns only about versions.
- **Fix:** add a line to the addendum header: "33 of 36 claims are single-source. Figures are indicative until the Phase 0 spikes." Optionally tag individual figures as unverified.

### G6. Maintenance risk and an unmeasured cost are missing from the risks
- **Source:** research.md L122: faster-whisper's "latest release is 1.2.1 (2025-10-31) … no release in the 12 months since, which is a maintenance risk." research.md L286: open question on "tiling time and RAM for an 8k×8k image".
- **PRD:** §8 has no faster-whisper maintenance risk and no tiling spike, yet FR-52 allows images up to 16,000 px.
- **Fix:** add R-9 (faster-whisper unmaintained; whisper.cpp, which is actively released, is the fallback) and a small tiling measurement in SPIKE-5 (time and RSS for `dzsave` on a 16k px image).

### G7. Extraction chunking guidance is missing from the addendum
- **Source:** research.md L73: "one Ollama call per chunk of about 1–2k tokens, splitting on paragraph boundaries … return `existing_id`"; L70 and L284: chunk size and matching thresholds have no evidence and should be found by labelling ~100 mentions.
- **Addendum §A FR-13/14:** no chunking or merge-across-chunks note, and no note that matching thresholds are unknown.
- **Fix:** add both points to addendum §A, and add "matching threshold calibration" to the EV-1 operating points.

### G8. The EV-1 "NER pre-pass" operating point doesn't line up with the recommended pipeline
- **Source:** Summary #1: GLiNER v2.1 is the runner-up pre-pass, not the recommendation.
- **PRD:** EV-1 lists "with and without the NER pre-pass" without saying which one. Addendum §A says "the existing spaCy NER can seed candidates", which is not in the research. GLiNER's RAM (209M) isn't budgeted under NFR-3.
- **Fix:** name the pre-pass being compared (existing spaCy vs GLiNER v2.1), and note that GLiNER would be another lazily loaded model under NFR-3.

## Low

### G9. Other small mismatches
- **FR-14** shows "up to three candidate Entities", while the research shortlists the top 5. This is fine as a UX choice, but the addendum should say the top-5 shortlist is internal and the top 3 are displayed.
- **pgvector ≥ 0.8 iterative scan** (Summary #8): the addendum doesn't say whether the deployed pgvector version meets this. Add a version check, or default to the exact-search plus B-tree path.
- **WeasyPrint** needs Python ≥ 3.10 and has no official Docker image (research.md L201). Add this to addendum §A as a build note.
- **Diarization** (pyannote, gated weights): R-4 covers it well. No gap.
- **espeak-ng:** the PRD (R-6, §11, §12 Q1) matches the research's "disable (misaki dictionary only) or separate process, legal check". No gap.

## FRs that build in technology or mechanism (should move to the addendum)

| Location | Text | Suggested fix |
|---|---|---|
| §5.4 description | "A small local speech-to-text model transcribes each chunk of about 10 to 30 seconds" | Keep the user-visible behaviour (captions arrive incrementally within the NFR-6 lag) and move the chunk size and model to the addendum (see G1). |
| §5.4 / FR-26 | "Near-real-time captions are a GPU-only enhancement" | This is a hardware claim that the research disputes. Leave it to SPIKE-2 and NFR-6. |
| FR-19 | "Flags are limited to claims that share an Entity with the cited Canon, so unrelated sentences are never compared" | The second clause describes the NLI pair-filter mechanism. Keep "each flag shares an Entity with the cited Canon" and move "sentences compared" to the addendum. |
| FR-28 | "(no LLM needed)" | Mechanism. Drop it and keep the 2 s target. |
| FR-33 | "the browser's built-in speech" | This is fine as a behaviour, but it names the Web Speech API. Consider "a degraded read-aloud fallback". |
| FR-5 | "it runs at boot without crash-looping" | This is a deployment mechanism and is already covered by NFR-8. Move it there. |
| §5.2 description | "It reuses the existing retrieval and relevance gate" | This is mechanism. It is already in addendum §A (FR-19), so remove it here. |
| NFR-3 | names "NLI, diarization" model classes | Acceptable for an NFR, but it assumes the NLI choice. Use "new AI models (for example …)". |
| EV-2 | "NLI threshold sweep (0.8, 0.9, 0.95)" | Acceptable in an eval, but tie it to the addendum mechanism ("if the NLI mechanism is used"). |

FR-1, FR-3, FR-24, FR-45 and FR-52/53 stay technology-neutral. The licence register, CI check, sidecar and async-job pattern, and the Story 0 benchmark spike (as SPIKE-1 to SPIKE-5 in Phase 0) all appear in the right places (NFR-3, NFR-4, §8, §9).
