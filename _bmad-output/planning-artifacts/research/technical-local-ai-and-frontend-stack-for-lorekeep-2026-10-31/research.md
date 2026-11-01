---
title: 'technical research: Local AI and frontend stack for the Lorekeeper expansion'
type: 'technical'
topic: 'Local AI and frontend stack for Lorekeeper expansion (9 selection topics)'
decision: 'Pick one library or approach per feature for an all-local Docker stack on an 8 GB, CPU-only baseline (NVIDIA GPU optional), with licenses that work for both the GPL and the commercial edition'
source: 'native run (5 parallel researcher subagents + lead spot-checks), 2026-10-31'
status: complete
preset: 'standard'
validation: 'normal'
created: '2026-10-31'
updated: '2026-10-31'
claims_verified: 3
claims_unverified: 33
---

# Technical research: the local AI and frontend stack for the Lorekeeper expansion

**The decision this research serves:** choose one library or approach for each of 9 expansion features. Everything must run inside the Docker stack: FastAPI, Postgres+pgvector, Redis, Ollama with a Mistral-7B fine-tune, and React/Vite/TS. The baseline machine has about 8 GB RAM and no GPU; an NVIDIA GPU is optional. The app is dual-licensed (GPL plus commercial), so every code and model-weight license has to work in both editions.

**Starting point (framing only; this is not evidence):** the backend transcribes batch audio with `openai-whisper` "base". `sentence-transformers` is already a dependency. The frontend has no chart or graph library yet.

The one-page decision table is at `_bmad-output/planning-artifacts/research-decisions-summary.md`.

## Executive summary

For every topic there is a fully local option that is licensed permissively (MIT, BSD or Apache) and works for both editions. Two things decide the overall design.

1. **Licensing is the main trap, more than performance.** Six popular options in this space are non-commercial, AGPL, GPL-only or "ethical-source":
   - react-leaflet uses the Hippocratic License 2.1 [58][59].
   - EbookLib is AGPL-3.0 [70].
   - The XTTS-v2 weights are non-commercial, and the vendor that could sell a licence no longer exists [43][44].
   - The F5-TTS weights are CC-BY-NC [47].
   - The GLiNER v0/v1 weights and Bespoke-MiniCheck-7B are CC-BY-NC [7][16].
   - Piper is now GPL-3.0, and it and Kokoro's fallback both use espeak-ng, which is GPL-3.0-or-later [40][42].

   We recommend picks that avoid all of these, and a license check on every model and package that gets added.
2. **RAM limits the design more than CPU.** The 7B model takes several GB on its own (Q4 GGUF, about 4–5 GB; we did not verify this figure this run). Every new model therefore needs to be small and run in its own process, loaded only when needed or run as an async job:
   - The NLI checker can be the 71M–200M-parameter DeBERTa [10][11].
   - STT can be faster-whisper int8, the "base" model on CPU [20].
   - TTS can be Kokoro-82M [36].

   Diarization and the large NLI model are opt-in, for machines with a GPU.

**Our picks, in brief:**

| # | Topic | Pick |
|---|---|---|
| 1 | Extraction | Ollama JSON-schema `format` with a deliberately flat schema, plus alias table → rapidfuzz + embedding shortlist → LLM adjudication |
| 2 | Canon guard | Sentence-level DeBERTa-v3 NLI with the 7B verifying flagged pairs |
| 3 | Live STT | faster-whisper int8 behind a VAD + LocalAgreement WebSocket |
| 4 | TTS | Kokoro-82M |
| 5 | Relationship graph | Sigma.js 4 + graphology |
| 6 | Book export | One HTML source → WeasyPrint for PDF, a hand-written EPUB3 zip for EPUB |
| 7 | Maps | Plain Leaflet with CRS.Simple + libvips DeepZoom tiles (not react-leaflet) |
| 8 | NPC chat | Retrieval scoped to the NPC's knowledge links + Character Card V2 prompt + an in-character "I don't know" rule re-injected after the history |
| 9 | Streaks | Session-based, opt-in, with built-in grace and no loss messaging |

**The biggest caveat:** the evidence has almost no CPU benchmarks we could check independently. That covers NLI per-pair latency, streaming STT end-to-end latency, Kokoro's CPU real-time factor, and pyannote on CPU. Every performance-dependent pick needs a short local benchmark on the 8 GB reference box before it is committed. Within this research, 3 claims are verified and 33 rest on a single source.

## 1. Structured entity and relationship extraction with a local 7B model

**Findings**
- **How Ollama structured output works.** Ollama's `format` parameter takes a full JSON schema [1]. It arrived in v0.5.0 ("constrain a model's output to a specific format defined by a JSON schema") [2]. Locally it is enforced by llama.cpp's grammar-constrained decoding [3].
- **Ollama's own advice:** set temperature 0, and paste the schema into the prompt as well, because "the model has no visibility into the schema" [1][3].
- **Unsupported schema features are skipped silently.** llama.cpp's converter does not handle `anyOf`/`oneOf` mixed with `properties`, nested `$ref`, `patternProperties`, `uniqueItems`, if/then/else, or string formats. It does not report them; it just ignores them [3]. `additionalProperties:false` "produces faster grammars + reduces hallucinations". Write repeated items as `x{0,N}`, not `x? x? x?` [3].
- **Format constraints cost accuracy (medium confidence; 2024-era models).** Strict format constraints measurably reduce LLM reasoning. Classification-like tasks are hurt less. A two-step "answer freely, then convert to the format" approach recovers most of the loss [4].
- **Expect low accuracy from a 7B used zero-shot (low confidence; search summaries only).** Zero-shot relation extraction with 7B models (Mistral-7B, Llama-2-7B) falls far short of fine-tuned extractors, and few-shot examples help only modestly [5][86]. The human-approved diff UI from the scope is therefore essential, not a nice-to-have.
- **GLiNER as a cheap entity pre-pass.** GLiNER code is Apache-2.0 and supports joint entity and relation extraction [6]. The `gliner_medium-v2.1` checkpoint (about 209M parameters) is Apache-2.0, but **the v0/v1 checkpoints are CC-BY-NC-4.0** [7]. No CPU throughput was published.
- **Entity resolution.** RapidFuzz is MIT and provides `token_set_ratio`, `partial_ratio`, `WRatio` and Jaro-Winkler [8]. Entity-resolution practice splits the work into blocking (finding candidates) and matching. Pre-trained language-model embeddings work for both stages [9].
- **Gaps.** We found no evidence-based thresholds for matching cutoffs, and no evidence on chunk size or how to merge results across chunks.

**Recommendation**
- Make one Ollama call per chunk of about 1–2k tokens, splitting on paragraph boundaries. Use a flat schema with closed `enum` entity types and closed relation types, `additionalProperties:false`, and no union types. Include the campaign's existing-entity list (name + aliases + id) in the prompt so the model can return `existing_id` rather than inventing a duplicate.
- For relations and status changes (reasoning-heavy), use two calls: free-text notes first, then a constrained JSON conversion [4]. Entity typing can be a single constrained call.
- Merge results across chunks by resolving every mention through the same resolver:
  1. exact match or alias table;
  2. a shortlist of the top 5 candidates by combining rapidfuzz `token_set_ratio` with cosine similarity on the existing sentence-transformers embeddings;
  3. auto-link above a high threshold, send the middle band to the LLM to adjudicate ("is 'the old smith' the same as NPC #12 'Borin, blacksmith'? yes/no/new"), and propose a new entity below it.

  Tune the thresholds on a labelled sample from the journal. Report precision and recall in the style of `docs/RETRIEVAL_EVAL.md`.
- **Runner-up:** GLiNER v2.1 as a CPU NER pre-pass (pin the v2.x weights), with the LLM handling only relations and resolution.
- **Cost:** no new resident model; it reuses the 7B and the embeddings. Run it as an async job after save.

## 2. Contradiction detection (canon guard)

**Findings**
- **Candidate checker models:**

  | Model | License | Size | SNLI | MNLI-mm | ANLI |
  |---|---|---|---|---|---|
  | `cross-encoder/nli-deberta-v3-base` [10] | Apache-2.0 | 0.2B | 92.38 | 90.04 | – |
  | `nli-deberta-v3-xsmall` [11] | Apache-2.0 | 71M | 91.64 | 87.77 | – |
  | `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` [12] | MIT | 0.4B | – | 0.908 | 0.702 |

  The large model is the robust choice for adversarial cases.
- **Score sentence pairs, not whole documents.** NLI applied to whole documents fails because premise and hypothesis are at different granularity. Sentence-level scoring with aggregation (SummaC) adds about 5 points of balanced accuracy [13]. Long-premise methods such as DocNLI/R2F work the same way: split the hypothesis into sentences, retrieve evidence for each, score, then fuse [14].
- **A small checker can match large judges.** On LLM-AggreFact, a 0.4B DeBERTa checker (FactCG-DeBERTa-L) scores 75.6. That is in line with GPT-4o (75.9) and Llama-3.3-70B (74.5). No 7B general instruct model is listed [15] (medium confidence; one source). The top checker, Bespoke-MiniCheck-7B, is **CC BY-NC** and fails the commercial gate [16].
- **CPU runtime.** sentence-transformers CrossEncoder supports ONNX and OpenVINO backends. On CPU it recommends OpenVINO int8 and says to avoid fp16/bf16 [17]. Dynamic int8 ONNX export of DeBERTa-v3-large has broken accuracy in at least one case; use static calibration and validate [18].
- **Gaps.** There is no trustworthy CPU per-pair latency; the only figure, 8–30 ms, is a low-confidence third-party estimate. Nothing in NLI handles flashbacks or past tense ("was dead") explicitly.

**Recommendation**
- Run it as a two-stage async check after save:
  1. Split the new entry into claim sentences, focusing on those that mention linked entities from §1.
  2. Retrieve the top-k canon sentences per claim through the existing hybrid retrieval and relevance gate.
  3. Score with `nli-deberta-v3-base` (or xsmall on weak CPUs) and keep pairs whose contradiction probability is ≥ a high threshold, e.g. 0.9; tune it on a seeded test set.
  4. Have the local 7B verify only those flagged pairs, with an explanation, a check for whether it is a flashback or a deliberate reveal, and citations.
- Show the result as a dismissible "possible continuity issue" with both entries cited, and never block a save. For false-positive control, require that both sentences share a resolved entity id. Record dismissals as negatives so they feed the evaluation metrics.
- **Runner-up:** the 7B as the only judge. It is simpler, but no evidence supports 7B judge reliability, and it costs far more CPU per pair.
- **Upgrade path on a GPU:** the MIT DeBERTa-v3-large model.

## 3. Streaming local STT for live sessions

**Findings**
- **Speed and memory on CPU.** faster-whisper (MIT) "small" on CPU, i7-12700K with 8 threads, on the same audio file:

  | Engine | Time | RAM |
  |---|---|---|
  | faster-whisper int8 | 1m42s | 1,477 MB |
  | whisper.cpp fp32 | 2m05s | 1,049 MB |
  | openai-whisper (the current dependency) | 6m58s | 2,335 MB |

  Source: [20]. faster-whisper bundles Silero VAD [20]. Its latest release is 1.2.1 (2025-10-31), and there has been no release in the 12 months since, which is a maintenance risk [19].
- **whisper.cpp** (MIT) is actively released (v1.9.5) and supports quantized models and Silero VAD. Its unquantized memory use is about 388 MB for base and 852 MB for small. Its `whisper-server` is HTTP, not WebSocket streaming [21].
- **Streaming wrappers:**
  - UFAL `whisper_streaming` (LocalAgreement policy, faster-whisper backend) says it is outdated [22].
  - Its successor, SimulStreaming, is "too slow for real-time" on CPU [23].
  - WhisperLive (MIT) has a CPU Docker image and a WebSocket that takes 16 kHz PCM [24].
  - WhisperLiveKit (Apache-2.0) supports browser AudioWorklet PCM, LocalAgreement and SimulStreaming policies, and ships a CPU Dockerfile [25].
  - The only published latency figure, 3.3 s, was measured on a GPU [22]. **We have no verified CPU end-to-end latency.**
- **Other engines:**
  - Whisper code and weights are MIT [26].
  - Parakeet-TDT-0.6B-v3 weights are CC-BY-4.0, with 6.34% average WER and at least 2 GB RAM [27]. It runs at RTFx 36 on a fast desktop CPU through onnx-asr, but it is chunked rather than true streaming [28].
  - Vosk's small English model is 40 MB and about 300 MB RAM, but much less accurate on hard audio (29.78% WER on call-center audio for the large model) [29].
  - Moonshine is MIT apart from its legacy non-English models, and it publishes no CPU numbers [30].
- **Diarization:**
  - pyannote community-1: MIT code, CC-BY-4.0 weights gated on Hugging Face. The only speed figure is 31 s per hour of audio on an H100; there is no CPU figure [31][32].
  - Streaming Sortformer is capped at 4 speakers [33].
  - diart streams, but its default models are gated and its maintenance is weak [34].
  - sherpa-onnx offers torch-free offline diarization [35].

**Recommendation**
- Replace `openai-whisper` with **faster-whisper int8** for both batch and live transcription: about 4× faster and about 37% less RAM on the same benchmark [20].
- For live mode, add a FastAPI WebSocket endpoint:
  - The browser AudioWorklet sends PCM16 at 16 kHz mono in chunks of about 0.5 s.
  - The server uses Silero VAD to segment, re-transcribes a rolling 1–2 s minimum chunk, and commits text with LocalAgreement-2.
  - Commit only finalized segments to the rolling recap.
- Use the "base"/"base.en" model on the CPU baseline (about half of small's RAM) and "small" or turbo when a GPU is present. Adapting WhisperLive or WhisperLiveKit's server is an acceptable shortcut; both are MIT or Apache [24][25].
- Expect about 2–4 s of caption lag on CPU (unverified). Benchmark it.
- **Runner-up:** whisper.cpp (least RAM, active releases) behind our own WebSocket wrapper.
- **Diarization:** off by default, run offline after the session, GPU-recommended. Use pyannote community-1 (the user accepts the HF terms once, then it runs offline), with sherpa-onnx as the CPU-light runner-up. Do not do live diarization: tables of 4–6 players exceed Sortformer's cap, and there are no CPU numbers.

## 4. Local TTS for narrated recaps

**Findings**
- **Kokoro-82M:**
  - Weights are Apache-2.0 (three sources agree [36][37][38]). v1.0 has 54 voices in 8 languages [36].
  - The `misaki` G2P is Apache-2.0, and espeak-ng is an *optional* fallback for out-of-vocabulary words [39].
  - **espeak-ng is GPL-3.0-or-later** [40].
  - Kokoro-FastAPI publishes CPU and GPU images, supports weighted voice blending (`af_bella(2)+af_sky(1)`) and sentence-chunked long-form output. CPU first-chunk latency is about 3.5 s on an older i7 and under 1 s on an M3 [37].
  - kokoro-onnx is about 300 MB, or about 80 MB quantized [38].
- **Piper:** rhasspy/piper (MIT) was archived on 2025-10-06. Development moved to OHF-Voice/piper1-gpl, which is GPL-3.0, embeds espeak-ng, and is looking for maintainers [41][42].
- **Coqui XTTS-v2:** the weights are under the CPML, which is non-commercial. Coqui has shut down, so no commercial licence can be bought [43][44].
- **Chatterbox:** MIT for both the repo and the HF model card [45][46]. The Nano variant (110M) is self-reported at 3× real-time on 8 CPU cores. It supports zero-shot voice cloning, and every output carries a Perth watermark [45].
- **Others:**
  - The F5-TTS weights are CC-BY-NC [47].
  - KittenTTS 2 needs about 6 GB RAM, and its weights use a custom license [48].
  - We did not screen StyleTTS2, Orpheus, Dia, Sesame CSM or MeloTTS.
  - We could not retrieve the TTS Arena rankings, so voice quality is judged on vendor claims only (low confidence).

**Recommendation**
- Use **Kokoro-82M** (kokoro-onnx or Kokoro-FastAPI) in its own `tts` container. Generate recaps as an async job and cache the MP3/Opus files.
- Map each genre to a voice preset, including blended voices: a fantasy narrator, noir, sci-fi.
- In the commercial edition, either disable the espeak-ng fallback (misaki dictionary only) or ship espeak-ng only as a separate program in the container. Whether that keeps the commercial edition clear of the GPL ("mere aggregation") is a **legal question** to settle before release.
- **Runner-up:** Chatterbox Nano. MIT, expressive, and can clone a custom narrator, but the watermark is mandatory and the CPU speed figure is self-reported.
- **Avoid for the commercial edition:** XTTS-v2, F5-TTS and piper1-gpl.

## 5. Relationship web graph (React)

**Findings**

| Library | Version | License | Size (gz) | Rendering | React 18 |
|---|---|---|---|---|---|
| sigma [52][50] | 4.0.4 (the current major is v4, not v3) | MIT | ≈94 KB | WebGL [53] | via @react-sigma/core 6.0.0 (MIT), which peers React `^18 \|\| ^19` [54] |
| react-force-graph-2d [49][50] | 1.29.2 | MIT | ≈58 KB | HTML Canvas; 3D variant uses three.js/WebGL [51] | peers `react: *` |
| cytoscape [55][50] | 3.34.4 | MIT | ≈134 KB before layout extensions | – | – |
| @xyflow/react (React Flow) [56][50] | 12.12.0 | MIT | ≈59 KB | DOM nodes | – |

- react-force-graph uses d3-force-3d physics by default, with ngraph as an option [51].
- React Flow's own docs warn that performance is "challenging" with large numbers of nodes [57].
- We found no primary benchmark at 500–5,000 nodes.

**Recommendation**
- Use **Sigma.js 4 + graphology + @react-sigma/core**: WebGL rendering, ForceAtlas2 layout and Louvain clustering. Those two layout packages come from the graphology ecosystem; we have not verified their bundle sizes. Run the layout in a web worker.
- About 94 KB gz plus graphology, all MIT, and the work happens client-side.
- **Runner-up:** react-force-graph-2d, the simplest API and fine at about 500 nodes on Canvas.
- **Not chosen:** React Flow is for editable diagrams and does not scale to a 500-node force web. Cytoscape is heavier.

## 6. PDF/EPUB campaign chronicle

**Findings**
- **WeasyPrint** 70.0 (2026-09) is BSD-licensed and requires Python ≥ 3.10 and Pango ≥ 1.44. On Debian it needs `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`. There is no official Docker image [67][68].
- WeasyPrint supports the CSS Paged Media features a book needs: margin boxes and running elements, page counters (with a known limitation), `target-counter()` for tables of contents, and `string-set`. PDF/A and PDF/UA output is supported but "not guaranteed to be valid" [69].
- **EbookLib is AGPL-3.0** [70].
- **typst-py** 0.15.0 is Apache-2.0, with wheels of about 26–37 MB. It outputs PDF/PNG/SVG/HTML but not EPUB [71].
- **Pandoc** is GPL. Its images range from about 320 MB to several GB with LaTeX [72] (low–medium confidence).

**Recommendation**
- Write each chronicle once as semantic HTML+CSS from Jinja templates. Render the PDF with **WeasyPrint**: one stylesheet per genre, cover, TOC through `target-counter`, chapter running headers. Run it as an async export job. The Pango/HarfBuzz system libraries add a modest number of MB; measure this.
- Build **EPUB3** from the same chapter XHTML with a small stdlib `zipfile` writer (mimetype, container.xml, OPF, nav.xhtml), and validate it with EPUBCheck in CI. This avoids AGPL EbookLib.
- **Runner-up:** Typst for print quality, but it needs a second template language and still needs the EPUB writer.
- **Avoid:** Pandoc, because of its image weight and GPL license.

## 7. Map pins on uploaded images

**Findings**
- **react-leaflet is under the Hippocratic License 2.1**, which calls itself "Ethical Source", not open source. It adds human-rights use restrictions, indemnification, and mandatory arbitration under the Hague Rules; declining arbitration terminates the license [59]. This applies to both 4.2.1 and 5.0.0. Version 5.0.0 also requires React 19; 4.2.1 peers React 18 [58].
- **Leaflet** 1.9.4 is BSD-2-Clause and about 42 KB gz [60].
- In `L.CRS.Simple`, one map unit equals one pixel at zoom 0, coordinates are `[y, x]`, and zooming out on large images needs a negative minZoom [61].
- DeepZoom, Zoomify and gdal2tiles plugins exist for Leaflet; we did not check their licenses [62].
- **OpenLayers** 10.11.0 is BSD-2 and has a built-in Zoomify source with a pixel projection [63][64].
- **libvips `dzsave`** writes DeepZoom, Google and IIIF tile pyramids [65].
- react-zoom-pan-pinch is MIT and peers any React version [66].

**Recommendation**
- Use **Leaflet 1.9.4 directly**, with a small in-house React hook or component (useRef/useEffect), `CRS.Simple`, and pins stored as `(map_id, x_px, y_px, location_id?, entry_id?)` in the source image's pixel space.
- **Do not use react-leaflet.** Its license conflicts with GPL's "no further restrictions" clause (our inference; get legal confirmation), and v5 also requires React 19.
- Show maps up to about 4k px as a single `ImageOverlay`. For larger uploads, generate a DeepZoom pyramid on the server at upload time with pyvips `dzsave` (libvips is LGPL; we did not verify this run).
- **Runner-up:** OpenLayers, whose first-party Zoomify/IIIF support needs no third-party plugin, at the cost of a larger API surface.

## 8. NPC roleplay limited to what the NPC knows

**Findings**
- **pgvector filters after the approximate index scan.** With HNSW at `ef_search=40` and a 10%-selective filter, only about 4 rows come back. Version 0.8.0 added iterative index scans to fix this. Exact search with a B-tree on the filter column, partial indexes, or partitioning are the alternatives [73]. pgvector uses the PostgreSQL License [74].
- **"Character hallucination"** is when a role-played character shows knowledge it should not have. Training on "protective scenes" teaches it to feign ignorance [75]. Point-in-time character hallucination persists even in GPT-4o [76]. Boundary-aware retrieval over a character knowledge graph reduces hallucinated answers (RoleRAG preprint, no numbers in the abstract) [77].
- **Persona drift** becomes significant within about 8 dialog rounds, attributed to attention decaying on the system prompt (tested on 70B-class models) [78].
- **Fine-tuning helps.** Persona fine-tuning (RoleLLM/RoCIT) brings open models close to GPT-4 prompting [79].
- **Character Card V2** fields include `post_history_instructions`, which is placed *after* the history, where the spec says instructions carry more weight [80].
- **Gap:** we found no evidence specific to 7B models refusing in character.

**Recommendation**
- Add an `npc_knowledge` link table: entity id, entry id, and how the NPC knows (present / told / rumor). §1's extraction proposes these links for human approval. Restrict NPC chat retrieval to those entries plus the NPC's own bio and public world facts.
- Per-NPC sets are small, so use exact (non-ANN) search with a B-tree pre-filter. Alternatively, set `hnsw.iterative_scan = relaxed_order` [73].
- Build the prompt from Character Card V2 fields: description, personality, speech style, 2–4 example lines including one in-character "I wouldn't know that" exchange.
- After the history, every turn, re-inject a short reminder: "Stay in character. Only use the memories provided. If something isn't in them, answer in character with uncertainty."
- Keep 6–8 turns of history and summarize anything older.
- Label each answer with the entries it drew on. This keeps the grounding ethos and gives a leakage metric: the share of answers that cite facts outside the allowed set.
- **Runner-up:** RoleRAG-style retrieval over the §1 entity graph once that graph exists.
- **Cost:** no new model; the only cost is prompt length on the 7B.

## 9. Achievements and streaks without dark patterns

**Findings**
- **Duolingo** says its streak keeps people practicing through loss aversion. Streak Freeze, a form of slack, raised daily active users by 0.38%, and milestone animations raised day-7 retention by 1.7% [81] (vendor self-report).
- **deceptive.design** names Nagging, Confirmshaming, Fake urgency, Obstruction and Addictive design as dark patterns [82].
- **Regulators.** The FTC published "Bringing Dark Patterns to Light" (2022-09) [83]. The EU Digital Fairness Act consultation targets dark patterns and the gamification of products (reward loops, countdowns). The proposal's timing is unconfirmed [84].
- **Streak anxiety.** Practitioner sources report streak anxiety and people faking activity to protect a streak (low confidence) [85].

**Recommendation**
- Count streaks in **sessions played, not calendar days**, because tabletop groups often meet weekly or biweekly. Let a gap of up to N planned weeks pass without breaking the streak, with grace that is automatic, not spent.
- Make streaks hideable and opt-in for players.
- Never use loss or guilt copy, push nagging, or countdowns. Celebrate milestones instead: first quest done, 10 sessions, an NPC mentioned 50 times.
- Implementation: an append-only `activity_events` table, pure rule functions, and `UNIQUE(user_id, campaign_id, achievement_key)` so awards are idempotent. Compute everything in Postgres, at negligible cost. This design is ours; no source supports it directly.
- **Runner-up:** achievements only, with no streaks at all.

## Cross-dimension insights

- **Licenses run through every feature.** Six of the screened options fail the commercial edition, and they hide in weights (GLiNER v0/v1, MiniCheck-7B, XTTS, F5), in UI wrappers (react-leaflet) and in transitive dependencies (espeak-ng under Kokoro and Piper). The architecture should keep a dependency-license register and add a CI check (e.g. `pip-licenses`, `license-checker`) that fails on GPL, AGPL, NC or Hippocratic licenses in the commercial build.
- **The RAM budget forces a "sidecar + async job" pattern.** The 7B already takes about half of 8 GB (unverified). Of the new models, only STT needs to be resident during a live session. NLI, TTS, diarization and export should be queued jobs on Redis that load models lazily and release them afterwards. Live mode should probably ask Ollama to unload the 7B (`keep_alive`) while transcription runs, or accept slower lookups.
- **§1 is the foundation for §2, §3 and §8.** Entity ids produced by extraction anchor contradiction checks (comparing only sentences about the same entity cuts false positives), supply the graph's nodes and edges, and provide the NPC knowledge links. Resolution quality in §1 therefore caps the quality of everything downstream. Evaluate it first.

## Recommendations (bound to downstream artifacts)

1. **Architecture spine:** adopt the sidecar/async-job pattern and the license register as cross-cutting constraints. High confidence on licenses; the RAM figures are unverified.
2. **Architecture and PRD (features 1, 2, 6):** use the extraction, NLI and NPC-scope designs above. Medium confidence. The claims about 7B accuracy are low confidence, so the PRD must keep human review and define evaluation metrics: extraction precision and recall, contradiction precision on a seeded set, NPC knowledge leakage rate.
3. **Architecture (features 4, 5):** move to faster-whisper and add a `tts` container running Kokoro. Medium confidence, with CPU latency unverified. Add a benchmark spike as story 0 for each.
4. **Frontend stack (features 3, 10):** sigma + graphology and plain Leaflet. Versions and licenses are high confidence (npm registry plus LICENSE files); performance is unverified.
5. **Export (feature 8):** WeasyPrint plus a stdlib EPUB writer. High confidence on licenses and features.
6. **UX (feature 9):** the humane streak rules above. Medium to low confidence; they rest mainly on the dark-pattern taxonomy.

## Open questions

- CPU benchmarks on the 8 GB reference box: NLI ms per pair (xsmall/base, ONNX/OpenVINO int8); faster-whisper base/small int8 streaming lag; Kokoro real-time factor and RAM; pyannote and sherpa-onnx time per hour of audio. Answer with a one-day benchmark spike.
- Legal: does running espeak-ng as a separate process keep the commercial edition clear of the GPL? Is Hippocratic-2.1 compatible with GPL? Ask counsel or the owner.
- Matching thresholds for entity resolution, and chunk size for extraction. Answer by labelling about 100 mentions from a real campaign.
- How reliably current 7–8B models refuse in character, and how fast their persona drifts. Check the CharacterEval and TimeChara tables, or measure with our own leakage evaluation.
- Licenses and maintenance of the Leaflet DeepZoom plugins; libvips license and tiling time and RAM for an 8k×8k image.
- Not screened for TTS: StyleTTS2, Orpheus, Dia, Sesame CSM, MeloTTS. Run a Deepen if Kokoro's voice quality disappoints.
- faster-whisper has had no release for 12 months. Watch its CTranslate2/Python compatibility; whisper.cpp is the hedge.

## Source appendix

| # | Claim/finding supported | Publisher | Pub date | Accessed | Confidence |
|---|---|---|---|---|---|
| 1 | Ollama `format` JSON schema; temp 0; schema in prompt | [Ollama docs](https://docs.ollama.com/capabilities/structured-outputs) | unknown | 2026-10-31 | high |
| 2 | Structured outputs added in v0.5.0 | [Ollama GitHub release](https://github.com/ollama/ollama/releases/tag/v0.5.0) | 2024-12 | 2026-10-31 | high |
| 3 | llama.cpp grammar gaps skipped silently; additionalProperties:false; repetition tip | [ggml-org llama.cpp grammars README](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md) | unknown | 2026-10-31 | high |
| 4 | Format restrictions hurt reasoning; NL-to-format mitigates | [Tam et al., arXiv 2408.02442](https://arxiv.org/abs/2408.02442) | 2024-08 | 2026-10-31 | medium |
| 5 | Zero-shot 7B relation extraction far below fine-tuned | [arXiv 2509.15089](https://arxiv.org/pdf/2509.15089v1) | 2025-09 | 2026-10-31 | low |
| 6 | GLiNER Apache-2.0 code; relation extraction support | [urchade/GLiNER GitHub](https://github.com/urchade/GLiNER) | unknown | 2026-10-31 | high |
| 7 | gliner_medium-v2.1 Apache-2.0, 209M; v0/v1 CC-BY-NC | [Hugging Face urchade](https://huggingface.co/urchade/gliner_medium-v2.1) | unknown | 2026-10-31 | high |
| 8 | RapidFuzz MIT; scorers | [RapidFuzz GitHub](https://github.com/rapidfuzz/RapidFuzz) | unknown | 2026-10-31 | high |
| 9 | Entity resolution = blocking + matching with LM embeddings | [Zeakis et al., PVLDB / arXiv 2304.12329](https://arxiv.org/abs/2304.12329) | 2023-04 | 2026-10-31 | medium |
| 10 | nli-deberta-v3-base Apache-2.0, 0.2B, SNLI 92.38 / MNLI-mm 90.04 | [Hugging Face cross-encoder](https://huggingface.co/cross-encoder/nli-deberta-v3-base) | unknown | 2026-10-31 | high |
| 11 | nli-deberta-v3-xsmall Apache-2.0, 70.8M, 91.64 / 87.77 | [Hugging Face cross-encoder](https://huggingface.co/cross-encoder/nli-deberta-v3-xsmall) | unknown | 2026-10-31 | high |
| 12 | DeBERTa-v3-large NLI MIT, 0.4B, ANLI 0.702 | [Hugging Face MoritzLaurer](https://huggingface.co/MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli) | 2022-06 | 2026-10-31 | high |
| 13 | SummaC sentence-level aggregation +5 pts | [ACL Anthology TACL 2022](https://aclanthology.org/2022.tacl-1.10) | 2022 | 2026-10-31 | high |
| 14 | DocNLI long premises; R2F decompose-retrieve-fuse | [ACL Anthology EMNLP 2022](https://aclanthology.org/2022.emnlp-main.204) | 2022 | 2026-10-31 | high |
| 15 | LLM-AggreFact: 0.4B DeBERTa checker ≈ GPT-4o / 70B judges | [LLM-AggreFact leaderboard](https://llm-aggrefact.github.io/) | unknown | 2026-10-31 | medium |
| 16 | Bespoke-MiniCheck-7B CC BY-NC | [Hugging Face Bespoke Labs](https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B) | unknown | 2026-10-31 | high |
| 17 | CrossEncoder ONNX/OpenVINO; OpenVINO int8 recommended on CPU | [Sentence Transformers docs](https://sbert.net/docs/cross_encoder/usage/efficiency.html) | unknown | 2026-10-31 | high |
| 18 | Dynamic int8 DeBERTa-v3-large export broke accuracy | [Hugging Face third-party card](https://huggingface.co/Bei0001/deberta-merge-verifier-onnx) | unknown | 2026-10-31 | low |
| 19 | faster-whisper 1.2.1 on 2025-10-31, no release since | [PyPI faster-whisper](https://pypi.org/project/faster-whisper/#history) | 2025-10 | 2026-10-31 | high |
| 20 | faster-whisper MIT; CPU benchmark vs openai-whisper and whisper.cpp; bundled Silero VAD | [SYSTRAN faster-whisper GitHub](https://github.com/SYSTRAN/faster-whisper) | 2024-11 | 2026-10-31 | high |
| 21 | whisper.cpp MIT, v1.9.5, quantization, VAD, memory per model; HTTP server | [ggml-org whisper.cpp GitHub](https://github.com/ggml-org/whisper.cpp) | 2026-10 | 2026-10-31 | medium |
| 22 | whisper_streaming outdated; LocalAgreement; 3.3 s latency on GPU | [UFAL whisper_streaming GitHub](https://github.com/ufal/whisper_streaming) | 2023 | 2026-10-31 | medium |
| 23 | SimulStreaming too slow for real-time on CPU | [UFAL SimulStreaming GitHub](https://github.com/ufal/SimulStreaming) | unknown | 2026-10-31 | high |
| 24 | WhisperLive MIT, CPU image, 16 kHz PCM WebSocket | [Collabora WhisperLive GitHub](https://github.com/collabora/WhisperLive) | unknown | 2026-10-31 | high |
| 25 | WhisperLiveKit Apache-2.0, AudioWorklet PCM, policies, CPU Dockerfile | [WhisperLiveKit GitHub](https://github.com/QuentinFuxa/WhisperLiveKit) | unknown | 2026-10-31 | high |
| 26 | Whisper code and weights MIT | [OpenAI whisper GitHub](https://github.com/openai/whisper) | unknown | 2026-10-31 | high |
| 27 | Parakeet-TDT-0.6B-v3 CC-BY-4.0, 6.34% WER, ≥2 GB RAM | [Hugging Face NVIDIA](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | 2025-08 | 2026-10-31 | high |
| 28 | onnx-asr Parakeet RTFx 36 on CPU; chunked rather than streaming | [onnx-asr GitHub](https://github.com/istupakov/onnx-asr) | unknown | 2026-10-31 | medium |
| 29 | Vosk model sizes, RAM, WER, licenses | [Alpha Cephei](https://alphacephei.com/vosk/models) | unknown | 2026-10-31 | high |
| 30 | Moonshine MIT except legacy non-English models | [Moonshine AI GitHub](https://github.com/moonshine-ai/moonshine) | unknown | 2026-10-31 | medium |
| 31 | pyannote community-1 CC-BY-4.0 gated; DER figures | [Hugging Face pyannote](https://huggingface.co/pyannote/speaker-diarization-community-1) | 2025-09 | 2026-10-31 | high |
| 32 | pyannote.audio MIT 4.0.x; 31 s/h on H100 | [pyannote-audio GitHub](https://github.com/pyannote/pyannote-audio) | 2025-09 | 2026-10-31 | high |
| 33 | Streaming Sortformer capped at 4 speakers; GPU numbers | [Hugging Face NVIDIA](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2) | 2025-07 | 2026-10-31 | high |
| 34 | diart streaming, gated models, weak maintenance | [diart GitHub](https://github.com/juanmc2005/diart) | unknown | 2026-10-31 | medium |
| 35 | sherpa-onnx offline diarization pipeline | [k2-fsa sherpa docs](https://k2-fsa.github.io/sherpa/onnx/rust-api/examples/offline_speaker_diarization.html) | unknown | 2026-10-31 | medium |
| 36 | Kokoro-82M Apache weights, 54 voices, v1.0 | [Hugging Face hexgrad](https://huggingface.co/hexgrad/Kokoro-82M) | 2025-01 | 2026-10-31 | high |
| 37 | Kokoro-FastAPI images, blending, chunking, CPU first-chunk latency | [remsky Kokoro-FastAPI GitHub](https://github.com/remsky/Kokoro-FastAPI) | unknown | 2026-10-31 | medium |
| 38 | kokoro-onnx MIT, ~300 MB / ~80 MB quantized | [kokoro-onnx GitHub](https://github.com/thewh1teagle/kokoro-onnx) | unknown | 2026-10-31 | medium |
| 39 | misaki Apache-2.0; espeak-ng optional fallback | [hexgrad misaki GitHub](https://github.com/hexgrad/misaki) | unknown | 2026-10-31 | medium |
| 40 | espeak-ng GPL-3.0-or-later | [espeak-ng GitHub](https://github.com/espeak-ng/espeak-ng) | unknown | 2026-10-31 | high |
| 41 | rhasspy/piper archived 2025-10-06, MIT | [rhasspy piper GitHub](https://github.com/rhasspy/piper) | 2025-10 | 2026-10-31 | high |
| 42 | piper1-gpl GPL-3.0, embeds espeak-ng, looking for maintainers | [OHF-Voice piper1-gpl GitHub](https://github.com/OHF-Voice/piper1-gpl) | unknown | 2026-10-31 | medium |
| 43 | XTTS-v2 weights under CPML | [Hugging Face coqui](https://huggingface.co/coqui/XTTS-v2) | unknown | 2026-10-31 | high |
| 44 | CPML non-commercial; Coqui shut down | [CPML text, HF mirror](https://huggingface.co/Borcherding/XTTS-v2_CarliG/blob/418d3f6406d97c9c4d1ff2767be43db54e380643/LICENSE.txt) | unknown | 2026-10-31 | high |
| 45 | Chatterbox MIT repo, Nano 3× real-time on 8 cores, watermark | [Resemble AI chatterbox GitHub](https://github.com/resemble-ai/chatterbox) | unknown | 2026-10-31 | medium |
| 46 | Chatterbox model card license MIT | [Hugging Face ResembleAI](https://huggingface.co/ResembleAI/chatterbox) | unknown | 2026-10-31 | high |
| 47 | F5-TTS weights CC-BY-NC | [SWivid F5-TTS GitHub](https://github.com/SWivid/F5-TTS) | 2025-03 | 2026-10-31 | high |
| 48 | KittenTTS 2 ~6 GB RAM; custom weights license | [KittenML GitHub](https://github.com/KittenML/KittenTTS) | 2026 | 2026-10-31 | medium |
| 49 | react-force-graph-2d 1.29.2 MIT, peers react * | [npm registry](https://registry.npmjs.org/react-force-graph-2d/latest) | unknown | 2026-10-31 | high |
| 50 | Bundle sizes (react-force-graph-2d, cytoscape, sigma, @xyflow/react, leaflet) | [bundlephobia](https://bundlephobia.com/package/sigma) | unknown | 2026-10-31 | high |
| 51 | react-force-graph 2D Canvas / 3D WebGL; d3-force-3d or ngraph | [vasturiano react-force-graph GitHub](https://github.com/vasturiano/react-force-graph) | unknown | 2026-10-31 | high |
| 52 | sigma 4.0.4 MIT | [npm registry](https://registry.npmjs.org/sigma/latest) | unknown | 2026-10-31 | high |
| 53 | sigma.js renders with WebGL | [sigmajs.org](https://www.sigmajs.org/) | unknown | 2026-10-31 | high |
| 54 | @react-sigma/core 6.0.0 MIT, peers React ^18 \|\| ^19 | [npm registry](https://registry.npmjs.org/@react-sigma/core/latest) | unknown | 2026-10-31 | high |
| 55 | cytoscape 3.34.4 MIT | [npm registry](https://registry.npmjs.org/cytoscape/latest) | unknown | 2026-10-31 | high |
| 56 | @xyflow/react 12.12.0 MIT | [npm registry](https://registry.npmjs.org/@xyflow/react/latest) | unknown | 2026-10-31 | high |
| 57 | React Flow DOM nodes; large-graph performance warning | [xyflow docs](https://reactflow.dev/learn/advanced-use/performance) | unknown | 2026-10-31 | medium |
| 58 | react-leaflet Hippocratic-2.1; v5 requires React 19, 4.2.1 peers React 18 | [npm registry](https://registry.npmjs.org/react-leaflet/latest) | unknown | 2026-10-31 | high |
| 59 | react-leaflet LICENSE: Hippocratic 2.1 terms | [react-leaflet GitHub LICENSE.md](https://github.com/PaulLeCam/react-leaflet/blob/master/LICENSE.md) | unknown | 2026-10-31 | high |
| 60 | leaflet 1.9.4 BSD-2-Clause | [npm registry](https://registry.npmjs.org/-/package/leaflet/dist-tags) | unknown | 2026-10-31 | high |
| 61 | CRS.Simple: [y, x] pixel units, negative minZoom | [Leaflet tutorial](https://leafletjs.com/examples/crs-simple/crs-simple.html) | unknown | 2026-10-31 | high |
| 62 | Leaflet DeepZoom, Zoomify and rastercoords plugins | [leaflet-deepzoom GitHub](https://github.com/alfarisi/leaflet-deepzoom) | unknown | 2026-10-31 | medium |
| 63 | ol 10.11.0 BSD-2 | [npm registry](https://registry.npmjs.org/ol/latest) | unknown | 2026-10-31 | high |
| 64 | OpenLayers Zoomify source with pixel projection | [OpenLayers example](https://openlayers.org/en/latest/examples/zoomify.html) | unknown | 2026-10-31 | high |
| 65 | libvips dzsave writes DeepZoom, Google and IIIF layouts | [libvips API](https://www.libvips.org/API/current/method.Image.dzsave.html) | unknown | 2026-10-31 | high |
| 66 | react-zoom-pan-pinch 4.2.0 MIT | [npm registry](https://registry.npmjs.org/react-zoom-pan-pinch/latest) | unknown | 2026-10-31 | high |
| 67 | WeasyPrint 70.0 BSD, Python ≥ 3.10 | [PyPI weasyprint](https://pypi.org/project/weasyprint/) | 2026-09 | 2026-10-31 | high |
| 68 | WeasyPrint Pango ≥ 1.44, Debian packages, no official image | [CourtBouillon docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) | unknown | 2026-10-31 | high |
| 69 | WeasyPrint margin boxes, target-counter, string-set; PDF/A not guaranteed | [CourtBouillon API reference](https://doc.courtbouillon.org/weasyprint/stable/api_reference.html) | unknown | 2026-10-31 | high |
| 70 | EbookLib AGPL-3.0 | [aerkalov ebooklib GitHub](https://github.com/aerkalov/ebooklib) | unknown | 2026-10-31 | high |
| 71 | typst-py 0.15.0 Apache-2.0, ~30 MB wheels, no EPUB | [PyPI typst](https://pypi.org/project/typst/) | 2026-06 | 2026-10-31 | high |
| 72 | Pandoc image sizes; GPL | [dalibo pandocker releases](https://github.com/dalibo/pandocker/releases) | unknown | 2026-10-31 | low |
| 73 | pgvector post-filtering; iterative scans in 0.8.0; B-tree, partial indexes, partitioning | [pgvector GitHub](https://github.com/pgvector/pgvector) | unknown | 2026-10-31 | high |
| 74 | pgvector PostgreSQL License | [pgvector LICENSE](https://github.com/pgvector/pgvector/blob/master/LICENSE) | unknown | 2026-10-31 | high |
| 75 | Character hallucination; protective scenes | [Shao et al., arXiv 2310.10158](https://arxiv.org/pdf/2310.10158) | 2023-10 | 2026-10-31 | medium |
| 76 | TimeChara: point-in-time hallucination persists in GPT-4o | [Ahn et al., arXiv 2405.18027](https://arxiv.org/abs/2405.18027) | 2024-05 | 2026-10-31 | high |
| 77 | RoleRAG boundary-aware retrieval | [arXiv 2505.18541](https://arxiv.org/abs/2505.18541) | 2025-05 | 2026-10-31 | medium |
| 78 | Persona drift within 8 rounds | [Li et al., arXiv 2402.10962](https://arxiv.org/abs/2402.10962) | 2024-02 | 2026-10-31 | medium |
| 79 | RoleLLM / RoCIT persona fine-tuning | [Wang et al., arXiv 2310.00746](https://arxiv.org/abs/2310.00746) | 2023-10 | 2026-10-31 | medium |
| 80 | Character Card V2 fields, post_history_instructions | [character-card-spec-v2 GitHub](https://github.com/malfoyslastname/character-card-spec-v2) | unknown | 2026-10-31 | medium |
| 81 | Duolingo streak: loss aversion, freeze +0.38% DAU, milestones +1.7% | [Duolingo blog](https://blog.duolingo.com/how-duolingo-streak-builds-habit/) | 2022-01 | 2026-10-31 | medium |
| 82 | Dark pattern taxonomy | [deceptive.design](https://www.deceptive.design/types) | 2023 | 2026-10-31 | high |
| 83 | FTC dark patterns report exists (2022-09) | [US FTC](https://www.ftc.gov/reports/bringing-dark-patterns-light) | 2022-09 | 2026-10-31 | high |
| 84 | EU Digital Fairness Act targets dark patterns and gamification | [European Parliament legislative train](https://www.europarl.europa.eu/legislative-train/theme-protecting-our-democracy-upholding-our-values/file-digital-fairness-act) | 2026 | 2026-10-31 | medium |
| 85 | Streak anxiety and faked activity | [Yu-kai Chou blog](https://yukaichou.com/gamification-analysis/streak-design-gamification-motivation-burnout/) | 2025 | 2026-10-31 | low |
| 86 | GenRES: open 7B models on generative relation extraction | [arXiv 2402.10744](https://arxiv.org/pdf/2402.10744) | 2024-02 | 2026-10-31 | low |

## Staleness map

Computed by `recon_kit.py staleness`. The re-check windows in months per claim class are: version 1, license 6, performance 3, failure 12, pattern 24.

- **Re-check first, around 2026-11-01:** version and package claims: sigma 4.0.4 / @react-sigma 6.0.0, WeasyPrint 70.0, typst-py 0.15.0, the faster-whisper release gap.
- **Stale already:**
  - Some evidence is old by its publication date, not because we know it is wrong: DeBERTa-large and Duolingo (2022), the format-restriction, persona-drift and TimeChara papers (2024), and the faster-whisper benchmark (v1.1.0, 2024-11). Re-check these if a decision hinges on them; the papers are old, but the effects they describe still apply to current models.
  - The Kokoro (2025-01), F5-TTS (2025-03) and pyannote (2025-09) license claims are past the 6-month window and should be re-read at implementation time.
- **License claims taken this run:** re-check by 2027-04-01.
- **Earliest re-check date:** 2022-09-01 (the DeBERTa-large performance card). The earliest forward date is 2026-11-01 (package versions).
