# Benchmarks (EV-5)

<!--
Generated regions: src/backend/scripts/eval_benchmarks.py rewrites ONLY the
content between the bench:nfr and bench:spikes markers below, from
docs/benchmarks.json. Everything else in this file is hand-written. A test
(tests/test_eval_benchmarks.py) fails if the regions drift from the store,
so record measurements through the script, never by editing the tables.
-->

Wall-clock time and peak memory for every NFR-6 latency target and every
NFR-2 memory case, on the Reference Box (CPU) and on a GPU (PRD §EV-5,
SM-5). Each feature epic records its own row when the feature lands; a row
that has not been measured yet shows `pending (<owning epic>)`. The targets
are copied from the PRD and are still provisional: a target the numbers
would reset is proposed as a pending entry in `.memlog.md` and needs owner
sign-off before the PRD changes.

## Method

- **Reference Box (CPU column):** a 16 GB, 4-core, CPU-only box, approximated
  on the x86 desktop. Every CPU case runs in
  `docker run --cpus=4 --cpuset-cpus=0-3` (four physical Zen 5 cores; their
  SMT siblings stay idle), with the GPU hidden (`CUDA_VISIBLE_DEVICES=""`) and
  memory capped at the component's AD-7 limit: stt 1.25 GB, ml 2.5 GB,
  ollama 5.25 GB. Three cases had to go over their limit, and each is
  reported rather than hidden: TTS was OOM-killed at 2.5 GB and re-ran at
  6 GB; `small` STT has no limit of its own, so it ran at 2.5 GB; and the
  uncapped Ollama run was OOM-killed at 5.25 GB and re-ran at the prod
  compose's 14 GB. The host's 60 GB doesn't count
  toward the 16 GB box: only the container limits do.
- **Ollama on CPU:** `ollama/ollama:0.40.3` in its own container, with AD-7's
  configuration (`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`,
  `OLLAMA_CONTEXT_LENGTH=4096`). Ollama sets one thread per *host* core
  (12 here) and ignores the container's `--cpus` and `--cpuset`. A real
  4-core box would get 4 threads, so the Reference Box rows set
  `num_thread 4` in the model's Modelfile. The `cpu-capped-3` and
  `cpu-uncapped` rows measure the production compose before and after the
  v1.1 fix.
- **GPU column:** the RTX 5080. Spikes 1 to 3 use the same image with
  `--gpus all`; SPIKE-6 uses the native Ollama 0.40.3 on `:11434`.
- **Runs:** each spike makes one warm-up call, then measures n runs: n = 5
  for spikes 1 to 3 and n = 3 per prompt shape for SPIKE-6. For SPIKE-2, n
  counts every chunk of 5 s or more across the 5 runs (25 chunks: four 15 s
  chunks and the 7 s tail of the 67 s clip). Timings are the median, with the
  spread (min–max).
- **Memory:** peak RSS of the measured process (`ru_maxrss`), and the
  container's cgroup `memory.peak`, which includes page cache.
- **Prompt cache (SPIKE-6):** each call puts a nonce at the start of the
  user turn, and an unrelated one-token call runs before it. Ollama keeps the
  tail of a prompt that is too long, though, and llama-server's RAM prompt
  cache then serves the truncated `extraction_300` prompt again. Those runs
  are flagged as `cache_hit` in `docs/benchmarks.json` and left out of the
  prompt-side numbers. The spike table's n still counts them.
- **Scripts:** `src/backend/scripts/spikes/`. Spikes 1 to 3 run in a
  throwaway `Dockerfile.bench` image, which never ships. SPIKE-1 xsmall also
  ran in the `ml` sidecar image, the production path, with CPU torch.
  SPIKE-6 runs in the backend image and goes through `complete_structured`.
  `run_x86.sh` drives all of them, and `eval_benchmarks.py --ingest` writes
  the tables.

## Hardware

| Item | Value |
|---|---|
| CPU | AMD Ryzen 9 9900X, 12 cores / 24 threads (Zen 5, AVX-512 with VNNI and BF16), up to 5.66 GHz |
| RAM | 60 GB host; the Reference Box is the 4-core cpuset plus the AD-7 container limits |
| GPU | NVIDIA RTX 5080 16 GB, driver 615.78.08 |
| OS / runtime | CachyOS, kernel 7.2.9-2-cachyos, Docker 29.9.0 with the NVIDIA toolkit |
| Ollama | 0.40.3, native (GPU) and `ollama/ollama:0.40.3` (CPU). `lorekeeper` is Q4_K_M, 7.2B, digest `68ffea1422de`. The `num_thread` Modelfile variants have the same weights under other manifest digests: `9e042e72bd1e` (4 threads) and `58b2a62db3a2` (3 threads). |
| Bench image | Python 3.12, torch 2.11.0+cu128, faster-whisper 1.2.1, ctranslate2 4.8.4, kokoro / misaki 0.9.4, sentence-transformers 6.2.0, transformers 5.22.1 (pinned in `Dockerfile.bench`) |
| ml image | torch 2.15.0+cpu, sentence-transformers 5.5.1, transformers 5.22.1, baked `nli-deberta-v3-xsmall` (the main-branch build, `qa9b-ml-new`) |

**Read the CPU column as optimistic per core.** Four Zen 5 cores at 5.6 GHz
with DDR5 are faster than most 16 GB boxes. 7B generation is limited by
memory bandwidth: 4 threads gave 8.0 tok/s and 12 gave 7.7 tok/s. A
dual-channel DDR4 box will generate more slowly than these rows show.

**Contention:** other agents' stacks were up but idle during the runs: the
`lk-v11` stack, the dev Postgres and Valkey, and Supabase. The GPU is shared
with the native Ollama. One GPU `rolling_recap` run evaluated its prompt at
196 tok/s against about 7,500 for the other runs, most likely another
client's request. The spike runs were sequential, never overlapping
one another.

## NFR-6 and NFR-2

<!-- bench:nfr -->
| Row | Target CPU | Target GPU | Measured CPU | Measured GPU | Peak RSS | n | Date | Hardware | Owning epic |
|---|---|---|---|---|---|---|---|---|---|
| NFR-6: Change Proposals ready after save (≈500-word entry) | ≤ 3 min | ≤ 30 s | pending (E1) | pending (E1) | — | — | — | — | E1 |
| NFR-6: Continuity check complete after save | ≤ 3 min | ≤ 30 s | pending (E2) | pending (E2) | — | — | — | — | E2 |
| NFR-6: Live caption lag (chunk end → text shown) | ≤ 30 s, with sustained processing ≤ chunk duration | ≤ 5 s | pending (E4) | pending (E4) | — | — | — | — | E4 |
| NFR-6: Rolling Recap update | ≈ 60 s cadence, each update ≤ 45 s | ≈ 60 s | pending (E4) | pending (E4) | — | — | — | — | E4 |
| NFR-6: Quick lookup by name | ≤ 2 s | ≤ 2 s | pending (E4) | pending (E4) | — | — | — | — | E4 |
| NFR-6: NPC Conversation first token | ≤ 20 s | ≤ 3 s | pending (E6) | pending (E6) | — | — | — | — | E6 |
| NFR-6: Narration of a 300-word recap | ≤ 2 min | ≤ 30 s | pending (E5) | pending (E5) | — | — | — | — | E5 |
| NFR-6: Chronicle export, 100 entries | ≤ 3 min | n/a | pending (E8) | n/a | — | — | — | — | E8 |
| NFR-6: Portal page load (warm) | ≤ 2 s | ≤ 2 s | pending (E7) | pending (E7) | — | — | — | — | E7 |
| NFR-2: Stack memory: idle | ≤ 14.5 GB container-limit sum | ≤ 14.5 GB container-limit sum | pending (E0-Platform) | pending (E0-Platform) | — | — | — | — | E0-Platform |
| NFR-2: Stack memory: one heavy Job | ≤ 14.5 GB container-limit sum | ≤ 14.5 GB container-limit sum | pending (E0-Platform) | pending (E0-Platform) | — | — | — | — | E0-Platform |
| NFR-2: Stack memory: Live Session (speech-to-text + Rolling Recap) | ≤ 14.5 GB container-limit sum | ≤ 14.5 GB container-limit sum | pending (E0-Platform, E4) | pending (E0-Platform, E4) | — | — | — | — | E0-Platform, E4 |
<!-- /bench:nfr -->

## Spike results (SPIKE-1, -2, -3, -6)

<!-- bench:spikes -->
### SPIKE-1: NLI cross-encoder (50 pairs)

| Config | Column | 50 pairs (s) | Per pair, batch 1 (ms) | Pairs/s | Sanity correct | Peak RSS (MB) | n | Date | Hardware |
|---|---|---|---|---|---|---|---|---|---|
| nli-deberta-v3-base | cpu | 0.964 (0.961–1.059) | 64.9 (61.5–161.9) | 51.9 | 4 | 1428.1 (cgroup 1240.2) | 5 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| nli-deberta-v3-base | gpu | 0.023 (0.023–0.023) | 4.8 (4.7–473.8) | 2173.9 | 4 | 1959.2 (cgroup 2095.6) | 5 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| nli-deberta-v3-xsmall | cpu | 0.309 (0.304–0.311) | 18.9 (17.9–20) | 161.8 | 4 | 1098.3 (cgroup 870.6) | 5 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| nli-deberta-v3-xsmall | gpu | 0.012 (0.012–0.013) | 4.8 (4.7–480.1) | 4166.7 | 4 | 1964.4 (cgroup 2079) | 5 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| nli-deberta-v3-xsmall (ml image) | cpu | 0.308 (0.308–0.313) | 18.9 (18.1–19.8) | 162.3 | 4 | 766.5 (cgroup 1228.9) | 5 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |

### SPIKE-2: faster-whisper, 15 s chunks

| Config | Column | Chunk latency (s) | Chunk RTF | Full-clip RTF | Word match | Names, no prompt | Names, `initial_prompt` | Chunk RTF, LLM busy | Peak RSS (MB) | n | Date | Hardware |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base float16 | gpu | 0.11 (0.06–0.13) | 0.008 (0.006–0.01) | 0.009 | 0.908 | 1/6 | 6/6 | — | 1107.6 (cgroup 1214.6) | 25 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| base float32 | cpu | 0.98 (0.55–1.11) | 0.068 (0.061–0.081) | 0.072 | 0.908 | 1/6 | 6/6 | — | 608 (cgroup 559.3) | 25 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| base int8 | cpu | 0.43 (0.28–0.49) | 0.029 (0.027–0.042) | 0.033 | 0.888 | 1/6 | 6/6 | — | 405.5 (cgroup 498) | 25 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| base int8 + LLM busy | cpu | 0.43 (0.28–0.58) | 0.03 (0.027–0.04) | 0.032 | 0.888 | 1/6 | 6/6 | 0.14 (0.097–0.178) | 406.6 (cgroup 355.6) | 25 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| small float16 | gpu | 0.18 (0.07–0.21) | 0.012 (0.01–0.014) | 0.014 | 0.937 | 2/6 | 6/6 | — | 1170.8 (cgroup 1180.6) | 25 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| small float32 | cpu | 2.92 (1.27–3.94) | 0.201 (0.172–0.271) | 0.266 | 0.937 | 2/6 | 6/6 | — | 1505.4 (cgroup 1458.5) | 25 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| small int8 | cpu | 1.33 (0.68–2.06) | 0.091 (0.08–0.137) | 0.13 | 0.922 | 2/6 | 6/6 | — | 740.5 (cgroup 1156.2) | 25 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |

### SPIKE-3: Kokoro TTS, 300-word recap

| Config | Column | Generation (s) | RTF | First audio (s) | Audio (s) | Dropped words | Peak RSS (MB) | n | Date | Hardware |
|---|---|---|---|---|---|---|---|---|---|---|
| kokoro-82M af_heart per-sentence | cpu | 13.63 (13.23–14.78) | 0.129 (0.126–0.14) | 1.3 (1.17–1.57) | 105.3 | none | 3110.1 (cgroup 3085.5) | 5 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| kokoro-82M af_heart per-sentence | gpu | 0.49 (0.48–0.63) | 0.005 (0.005–0.006) | 0.04 (0.04–0.07) | 105.3 | none | 2543.3 (cgroup 2369.6) | 5 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |

### SPIKE-6: 7B throughput (Ollama)

| Config | Column | Shape | Ollama / model digest | Prompt tokens | Prompt tok/s | Gen tok/s | TTFT (s) | Total (s) | n | Date | Hardware |
|---|---|---|---|---|---|---|---|---|---|---|---|
| cpu-capped-3 | cpu | continuity_verify | 0.40.3 / 68ffea1422de | 89 | 18.6 (11.7–29.3) | 0.72 (0.52–0.76) | 5 (3.3–7.6) | 56.22 (51.3–62.1) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-capped-3 | cpu | npc_first_turn | 0.40.3 / 68ffea1422de | 96 | 45.8 (32.3–74.7) | 0.74 (0.72–0.93) | 2.4 (1.49–3.09) | 87.89 (71.01–92.48) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-capped-3-t3 | cpu | continuity_verify | 0.40.3 / 58b2a62db3a2 | 87 | 47.4 (45.8–48) | 6.07 (5.74–6.21) | 1.84 (1.82–1.9) | 7.94 (5.84–8.33) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-capped-3-t3 | cpu | npc_first_turn | 0.40.3 / 58b2a62db3a2 | 95 | 83.9 (50.5–107.7) | 5.8 (5.57–6.12) | 1.15 (0.89–1.92) | 11.93 (11.6–13.41) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-ref4 | cpu | continuity_verify | 0.40.3 / 9e042e72bd1e | 88 | 92 (91.8–93.5) | 8.97 (8.97–9.05) | 0.94 (0.94–0.95) | 5.29 (3.7–5.29) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-ref4 | cpu | extraction_300 | 0.40.3 / 9e042e72bd1e | 2051 | 87.7 (87.7–87.7) | 7.82 (7.72–7.82) | 23.43 (23.43–23.43) | 75.22 (75.22–75.22) | 1 (+2 cached) | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-ref4 | cpu | extraction_50 | 0.40.3 / 9e042e72bd1e | 1628 | 90.8 (89.3–90.9) | 7.85 (7.71–8.03) | 17.93 (17.93–18.35) | 68.89 (67.76–70.22) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-ref4 | cpu | npc_first_turn | 0.40.3 / 9e042e72bd1e | 95 | 91.6 (85.4–92.5) | 8.33 (8.31–8.33) | 1.04 (1.03–1.12) | 19.08 (19.04–19.13) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-ref4 | cpu | recap_draft_300 | 0.40.3 / 9e042e72bd1e | 941 | 92.8 (91–93.6) | 8.22 (7.94–8.31) | 10.13 (10.06–10.34) | 64.99 (64.22–66.78) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-ref4 | cpu | rolling_recap | 0.40.3 / 9e042e72bd1e | 518 | 93.9 (92.3–95) | 8.46 (8.14–8.54) | 5.52 (5.43–5.71) | 24.16 (23.6–25.37) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-ref4-default-threads | cpu | continuity_verify | 0.40.3 / 68ffea1422de | 88 | 25.8 (25.6–25.9) | 0.39 (0.39–0.39) | 3.41 (3.41–3.42) | 85.98 (85.76–86.22) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-uncapped | cpu | continuity_verify | 0.40.3 / 68ffea1422de | 85 | 178.7 (178–182.8) | 8.4 (8.39–8.51) | 0.48 (0.48–0.49) | 5.13 (3.43–5.13) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-uncapped | cpu | extraction_300 | 0.40.3 / 68ffea1422de | 2051 | 174.5 (174.5–174.5) | 7.63 (7.63–7.64) | 11.77 (11.77–11.77) | 64.11 (64.11–64.11) | 1 (+2 cached) | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-uncapped | cpu | extraction_50 | 0.40.3 / 68ffea1422de | 1629 | 163.3 (162.7–176.4) | 7.67 (7.35–7.73) | 9.97 (9.24–10.01) | 62.15 (60.97–64.44) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-uncapped | cpu | npc_first_turn | 0.40.3 / 68ffea1422de | 97 | 176.9 (176.4–177.7) | 8.2 (8.18–8.24) | 0.55 (0.53–0.55) | 18.85 (12.94–18.86) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-uncapped | cpu | recap_draft_300 | 0.40.3 / 68ffea1422de | 940 | 181 (180.7–181.2) | 7.91 (7.9–7.92) | 5.21 (5.2–5.21) | 60.7 (52.91–62.14) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-uncapped | cpu | rolling_recap | 0.40.3 / 68ffea1422de | 514 | 179.3 (178.2–183.4) | 8.08 (8.08–8.09) | 2.9 (2.81–2.91) | 22.69 (22.59–22.71) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| gpu | gpu | continuity_verify | 0.40.3 / 68ffea1422de | 89 | 5599.2 (5580.6–5660.5) | 177.78 (176.89–177.95) | 0.02 (0.02–0.02) | 0.23 (0.23–0.24) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| gpu | gpu | extraction_300 | 0.40.3 / 68ffea1422de | 2051 | 8610.3 (8610.3–8610.3) | 163.34 (163.09–163.51) | 0.26 (0.26–0.26) | 2.7 (2.7–2.7) | 1 (+2 cached) | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| gpu | gpu | extraction_50 | 0.40.3 / 68ffea1422de | 1627 | 8415.5 (8415.5–8424.3) | 166.03 (166–166.26) | 0.2 (0.2–0.2) | 2.61 (2.61–2.61) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| gpu | gpu | npc_first_turn | 0.40.3 / 68ffea1422de | 95 | 6016.1 (5945.7–6035.3) | 174.63 (174.3–174.67) | 0.02 (0.02–0.02) | 0.88 (0.83–0.88) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| gpu | gpu | recap_draft_300 | 0.40.3 / 68ffea1422de | 940 | 8528.5 (8525.8–8548.5) | 168.58 (168.13–169.04) | 0.12 (0.12–0.12) | 2.69 (2.54–2.73) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| gpu | gpu | rolling_recap | 0.40.3 / 68ffea1422de | 518 | 7406.7 (195.7–7993.3) | 170.74 (154.28–171.84) | 0.08 (0.07–2.65) | 1.01 (1–3.69) | 3 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |

Structured extraction:

| Config | Column | Calls | First-try valid | Valid after repair | Failed | Latency (s) | n | Date | Hardware |
|---|---|---|---|---|---|---|---|---|---|
| cpu-ref4 | cpu | 10 | 10 | 0 | 0 | 32.4 (24.4–53) | 10 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| cpu-uncapped | cpu | 10 | 10 | 0 | 0 | 34.9 (29.3–43.8) | 10 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |
| gpu | gpu | 50 | 50 | 0 | 0 | 1.6 (1.2–2.5) | 50 | 2026-11-01 | AMD Ryzen 9 9900X 12-Core Processor, 60 GB host |

Timings are `median (min–max)` over n runs. For SPIKE-2, n counts every chunk of 5 s or more in every run: the 15 s chunks and the clip's 7 s tail. For SPIKE-6, runs served from Ollama's prompt cache are left out of n and of the prompt-side columns, and shown as `(+k cached)`.
<!-- /bench:spikes -->

## Verdicts

Measured on 2026-11-01 (E0-QA.15). The NFR-6 rows stay `pending` until each
feature lands. The spike numbers below are inputs for those rows, not the
rows themselves.

- **SPIKE-1 (NLI): the xsmall default holds.** 50 pairs take 0.31 s
  (0.30–0.31) with xsmall and 0.96 s with base on 4 cores. The M-series
  timings were 0.71 s and 2.58 s. On the GPU they take 12 ms and 23 ms. Both
  models give the same verdicts on the sanity set (4/6). Both still make the
  confident false contradiction on the neutral Aldric pair (p = 0.99 / 1.0),
  so the 7B confirmation step stays. xsmall is 3.1× cheaper for the same
  verdicts. Base would now fit the 10 s per-entry budget of
  `cpu-benchmarks.md` §3.3 easily, so it is still worth
  switching to if EV-2 shows it is more accurate. In the `ml` image (CPU
  torch) xsmall runs at the same speed and peaks at 767 MB RSS (1.23 GB
  cgroup), inside ml's 2.5 GB.
- **SPIKE-2 (speech-to-text): base, int8 and 15 s chunks all hold, with
  large margins.**
  - **int8 vs float32:** base int8 takes 0.43 s per 15 s chunk (RTF 0.029,
    worst 0.042). float32 takes 0.98 s (RTF 0.068). The M-series result
    flips on x86, as predicted: int8 is 2.3× faster and uses less memory
    (406 MB against 608 MB), so `STT_COMPUTE_TYPE=int8` stays the default.
  - **LLM busy:** with the 7B generating on the same 4 cores, base int8 runs
    at a median RTF of 0.14 (worst 0.18). Sustained processing stays below
    the chunk duration with more than 5× headroom. Per-chunk latency is
    1.88 s median and 2.49 s worst (`busy.chunk_latency_s` in the store). The
    LLM slows to 5.7 tok/s meanwhile.
  - **small:** small int8 also fits live use on x86 (RTF 0.09, worst 0.14).
    Its cgroup peak is 1.16 GB, just under stt's 1.25 GB, so on an x86-class
    CPU it could be an opt-in accuracy setting.
  - **Names:** `initial_prompt` listing the six demo names fixes all of them
    (1/6 without the prompt, 6/6 with it, for both base and small). It also
    raises base's word match from 0.888 to 0.956. Seed the prompt from the
    Campaign's Entity list (E0-Platform.5 / E4).
  - **GPU:** base float16 takes 0.11 s per chunk.
- **SPIKE-3 (Kokoro TTS): fast enough on both columns, but over AD-7's
  memory limit.** A 316-word recap synthesised one sentence at a time gives
  105 s of audio. That takes 13.6 s on 4 cores (RTF 0.13, first audio after
  1.3 s) and 0.49 s on the GPU. Both are far inside the narration row's
  ≤ 2 min / ≤ 30 s. No words were dropped, because espeak-ng is on, as in
  the AGPL tts container. **Peak RSS was 3.1 GB, and at the 2.5 GB tts limit
  the process was OOM-killed.** This was the `kokoro` torch package (cu128
  build) in the bench image. The cu128 build costs memory by itself: the
  same NLI model peaked about 330 MB higher in the bench image than in the
  CPU-torch `ml` image. Even so, a CPU-torch Kokoro would sit at about
  2.8 GB, still over the limit. AD-7 plans a Kokoro-FastAPI CPU image, and
  that image must be measured against 2.5 GB before E5 ships
  (E0-Platform.10).
- **SPIKE-6 (7B throughput, the input for E0-Platform.10 and E0-LLM.6):**
  - **Reference Box (4 threads, 5.25 GB):** prompts process at about
    91 tok/s and generation runs at about 8 tok/s.
    - Extraction with 50 Entities takes 69 s in total, with the first token
      after 18 s.
    - Continuity verify takes 5.3 s.
    - A Rolling Recap update takes 24 s.
    - An NPC first turn gets its first token after 1.0 s on a short card
      and finishes 150 tokens in 19 s.
    - A 300-word recap draft takes 65 s.
  - **GPU:** generation runs at 163–178 tok/s and prompts at about
    5,600–8,600 tok/s. Every shape finishes in under 3 s.
  - **Structured extraction** (`complete_structured`, Ollama `format` set to
    a flat schema) was first-try valid every time: 10/10 on CPU (median
    32 s) and 50/50 on the GPU (median 1.6 s).
  - **The 300-Entity prompt doesn't fit.** It is about 3.4k tokens, and
    Ollama cut it to 2,051 tokens by keeping the tail, so the start of the
    Entity list was silently dropped. This happened on both CPU and GPU, at
    `OLLAMA_CONTEXT_LENGTH=4096`. A full 300-Entity list is therefore not an
    option at that context length, which is an input for E0-LLM.6's
    shortlist decision. Its timing (75 s, cold n = 1) measures a truncated
    prompt.
- **The CPU cap (prod compose `cpus: "3.0"`, v1.1 fix):**

  | Ollama on CPU | Generation tok/s | Prompt tok/s |
  |---|---|---|
  | `cpus: "3.0"`, Ollama's default 12 threads (prod before v1.1) | **0.72–0.74** | 19–46 |
  | `cpus: "3.0"` with `num_thread 3` | 5.8–6.1 | 47–84 |
  | uncapped, 12 threads (the v1.1 fix) | **7.6–8.4** | 163–181 |
  | 4-core cpuset, Ollama's default 12 threads | 0.39 | 26 |
  | 4-core cpuset, `num_thread 4` (Reference Box rows) | 7.7–9.0 | 90–94 |

  This confirms the release-prep finding of about 1 tok/s. The cause is
  that Ollama starts one thread per host core, whatever CPU quota or cpuset
  the container has, and the throttled threads stall each other. Removing
  the cap fixes it, and so does setting `num_thread` to match any cap. Any
  CPU limit on the `ollama` service needs a matching `num_thread`.
- **Memory (input for E0-Platform.10 / SPIKE-5):** under AD-7's 5.25 GB
  ollama limit, the 4-thread runner's anonymous memory reached 5.08 GB,
  leaving about 170 MB of headroom. The 12-thread uncapped run was
  **OOM-killed at 5.25 GB** on `extraction_300` (cgroup `oom_kill 1`, and
  Ollama answered with a 500). The uncapped numbers above were therefore
  re-run at the prod compose's 14 GB. Ollama 0.40.3's llama-server turns on
  a RAM prompt cache by default (logged as "size limit: 8192 MiB"), which
  may be what grows. The 5.25 GB limit needs re-checking before it ships.

What the spikes imply for the provisional NFR-6 rows (the owning epics still
measure the real rows):

| NFR-6 row | Spike evidence (CPU / GPU) | Provisional target |
|---|---|---|
| Change Proposals | one extraction call 69 s (50 Entities) / 2.6 s; under the old 3.0 cap an estimated 10 min (1,628 prompt tokens at 19–46 tok/s plus 400 at 0.7 tok/s; extraction itself was not run capped) | holds (≤ 3 min / ≤ 30 s), only without the CPU cap |
| Continuity check | NLI 50 pairs 0.31 s plus about 5.3 s per 7B verify / 0.23 s | holds for up to about 30 verifies |
| Live caption lag | processing 0.43 s per chunk, worst 2.49 s with the LLM busy / 0.11 s | holds; the CPU target could tighten (see `.memlog.md`) |
| Rolling Recap update | 24 s alone / 1 s; but the gate has no preemption, so a recap queued behind a 69 s extraction misses 45 s | holds only if E0-LLM.6 caps the wait |
| NPC first token | 1.0 s first token on a 95-token card; at 91 tok/s a 1,500-token memory prompt would take about 17 s / 0.02 s | holds if E6 keeps the prompt ≤ about 1,500 tokens |
| 300-word narration | 13.6 s / 0.49 s (Kokoro, per sentence) | holds; the CPU target could tighten (see `.memlog.md`) |
| Quick lookup, Chronicle, Portal | not model-bound; not measured by the spikes | pending |

**Proposed target resets:** the pending entries in `.memlog.md` (repo root). None takes
effect until the owner signs off there.

## Reproducing

```bash
# On the x86 desktop (see src/backend/scripts/spikes/run_x86.sh for setup).
# The 2026-11-01 run used TTS_MEM=6g (Kokoro is OOM-killed at the 2.5g limit)
# and ML_IMAGE=qa9b-ml-new (the ml sidecar image built from main):
docker build -t lorekeeper-bench -f backend/scripts/spikes/Dockerfile.bench backend/scripts/spikes
TTS_MEM=6g ML_IMAGE=qa9b-ml-new backend/scripts/spikes/run_x86.sh all
backend/scripts/spikes/run_x86.sh down     # removes the CPU Ollama container and volume

# Back on the laptop, with the results/ directory copied over:
python src/backend/scripts/eval_benchmarks.py --ingest results/*.json

# A feature epic recording its NFR-6 / NFR-2 row:
python src/backend/scripts/eval_benchmarks.py --record proposals --column cpu \
    --value "2 min 10 s" --peak-rss-mb 812 --n 5 --hardware "<machine and limits>"

# Re-render this doc from docs/benchmarks.json (idempotent):
python src/backend/scripts/eval_benchmarks.py
```
