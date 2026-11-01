# Spike: x86 desktop re-run (SPIKE-1, -2, -3 and the SPIKE-6 throughput harness)

Date: 2026-11-01. This is E0-QA.15. It replaces the M-series numbers in
`cpu-benchmarks.md`, which came from 4 threads at n = 1. The tables with
medians and spreads, and the verdicts, are in `docs/BENCHMARKS.md`. The raw
results, every run included, are in `docs/benchmarks.json` under `spikes`.
This file records the machine, the commands and what went wrong on the way,
for E0-Platform.10 (SPIKE-5, SPIKE-6 limits) and E0-LLM.6 (acting on
SPIKE-6).

## Machine

Ryzen 9 9900X, 12 cores / 24 threads, 60 GB RAM. RTX 5080 16 GB on driver
615.78.08. CachyOS, kernel 7.2.9, Docker 29.9.0. Ollama 0.40.3 runs natively
for the GPU, and as `ollama/ollama:0.40.3` for the CPU. `lorekeeper` digest
is `68ffea1422de`.

## Reference Box approximation

The CPU column is 4 physical cores: `--cpus=4 --cpuset-cpus=0-3`, with
`CUDA_VISIBLE_DEVICES=""`. Memory is capped at each component's AD-7 limit:
stt 1.25 GB, ml 2.5 GB, ollama 5.25 GB. The host's 60 GB is irrelevant;
only these limits stand in for the 16 GB box. The CPU is faster per core than
a typical 16 GB box, so read the CPU timings as an upper bound. 7B
generation is limited by memory bandwidth (8 tok/s with 4 threads, 7.7 with
12).

## Commands

```bash
rsync -az --exclude __pycache__ src/backend/ desktop:~/lorekeeper-dev/runs/qa15/backend/
rsync -az seeds/ desktop:~/lorekeeper-dev/runs/qa15/seeds/
# data/clip.wav + data/speech.txt: the 67 s GM clip of cpu-benchmarks.md (16 kHz mono PCM16)
cd ~/lorekeeper-dev/runs/qa15
docker build -t lorekeeper-bench -f backend/scripts/spikes/Dockerfile.bench backend/scripts/spikes
TTS_MEM=6g ML_IMAGE=qa9b-ml-new backend/scripts/spikes/run_x86.sh all   # sections: nli stt tts ollama[-ref|-capped|-uncapped|-gpu]
backend/scripts/spikes/run_x86.sh down
python src/backend/scripts/eval_benchmarks.py --ingest results/*.json  # back in the repo
```

## n per measurement

- SPIKE-1: 5 runs of 50 pairs, plus 30 batch-1 calls.
- SPIKE-2: 5 runs × 5 chunks = 25. The fifth chunk is the 7 s tail.
- SPIKE-3: 5 syntheses of the 316-word recap.
- SPIKE-6: 3 runs per shape. Structured extraction: 10 calls on CPU, 50 on
  the GPU.

## Gotchas found on the way (each is now handled in the scripts)

1. **Ollama ignores the container's CPU limits when it picks a thread
   count.** It starts one thread per host core (12) under `--cpus=4`,
   `--cpuset-cpus=0-3` or `--cpus=3`, and the throttled threads stall each
   other.
   - On 4 cores with 12 threads, generation ran at 0.39 tok/s.
   - Under the prod `cpus: "3.0"` it ran at 0.72 tok/s.
   - With `num_thread` matched to the cores: 7.7–9.0 tok/s on 4 cores and
     5.8–6.1 on the 3.0 cap.

   The fix goes in the Modelfile (`PARAMETER num_thread N`), not as a request
   option. A different per-request `num_thread` reloads the model, and
   `complete_structured` doesn't send one. The `num_thread` variants have
   other manifest digests over the same weights.
2. **llama-server's RAM prompt cache.** Ollama 0.40.3 logs "prompt cache is
   enabled, size limit: 8192 MiB". It also reuses KV chunks after a
   differing prefix.
   - A system-message nonce doesn't help: the `lorekeeper` template keeps
     only the last system message, so the nonce is dropped.
   - A nonce at the start of the user turn, plus a one-token call in
     between, defeats the cache, except for prompts Ollama truncates (next
     item).
   - `spike6_llm_throughput.summarise` flags any run evaluating its prompt
     at over 10k tok/s and 10× its slowest run as `cache_hit`, and leaves it
     out of the prompt-side stats.
3. **Prompts over the context are cut silently.** `extraction_300` (about
   3.4k tokens) arrived at the model as 2,051 tokens on both CPU and GPU
   (`OLLAMA_CONTEXT_LENGTH=4096`). Ollama kept the tail, so the start of the
   Entity list was lost with no error. This is an E0-LLM.6 input:
   `prompt_budget` must refuse or shortlist before Ollama truncates.
4. **OOM at the AD-7 ollama limit.** At 5.25 GB the 4-thread runner reached
   5.08 GB of anonymous memory. The 12-thread uncapped run was OOM-killed on
   `extraction_300` (cgroup `memory.events`: `oom_kill 1`; the client saw a
   500 or a dropped connection). The uncapped numbers were taken at the prod
   compose's 14 GB, and the cgroup peak was 12.9 GB. That peak includes page
   cache from `ollama create` copying the 4.4 GB blob, so it is not a clean
   RSS figure. E0-Platform.10 (SPIKE-5) has to settle the real limit.
5. **`docker update --cpus=0` doesn't remove a CPU cap.** The quota stays at
   3. `run_x86.sh` re-creates the container for each configuration.
6. **Kokoro was OOM-killed at tts's 2.5 GB.** This was the `kokoro` 0.9.4
   torch package, cu128 build, synthesising one sentence at a time. It
   peaked at 3.1 GB when re-run with a 6 GB limit (`TTS_MEM=6g`). The
   Kokoro-FastAPI CPU image that AD-7 plans has not been measured.

## Results summary (medians; full tables in docs/BENCHMARKS.md)

| Component | CPU (4 cores, AD-7 limits) | GPU (RTX 5080) | M-series spike (4 threads, n = 1) |
|---|---|---|---|
| NLI xsmall, 50 pairs | 0.31 s; RSS 1.10 GB (bench), 0.77 GB (ml image) | 0.012 s | 0.71 s, 844 MB |
| NLI base, 50 pairs | 0.96 s, 1.43 GB | 0.023 s | 2.58 s, 1140 MB |
| Whisper base int8, 15 s chunk | 0.43 s (RTF 0.029, worst 0.042), 406 MB | — | 3.98 s (worst RTF 0.31) |
| Whisper base int8, LLM busy | RTF 0.14 (worst 0.18) | — | not measured |
| Whisper base float32 | 0.98 s (RTF 0.068), 608 MB | — | 1.50 s (RTF 0.11) |
| Whisper base float16 | — | 0.11 s (RTF 0.008) | — |
| Whisper small int8 / float32 | 1.33 s / 2.92 s (RTF 0.09 / 0.20) | float16: 0.18 s | 12.5 s / 3.74 s |
| Names (6), no prompt → `initial_prompt` | base 1 → 6, small 2 → 6 | same | not measured |
| Kokoro, 300 words, per sentence | 13.6 s (RTF 0.13), first audio 1.3 s, 3.1 GB | 0.49 s | RTF 0.25–0.38 (142 words), 2.1 GB |
| 7B prompt / generation tok/s | 91 / 8.0 (4 threads); uncapped 175 / 7.9; old 3.0 cap 19–46 / 0.7 | 5.6–8.6k / 163–178 | not measured |
| Structured extraction (`complete_structured`) | 10/10 first try, 32 s | 50/50 first try, 1.6 s | skipped |

## Decisions this re-run confirms or changes

- The xsmall NLI default, faster-whisper `base`, `int8` and 15 s chunks all
  still hold, with larger margins than on the M-series machine. int8 is now
  the faster compute type, as predicted for x86.
- Name prompting works: seed `initial_prompt` from the Entity list.
- `small` is viable for live use on an x86-class CPU. Whether to offer it is
  a product call, not a requirement.
- Proposed target resets (caption lag, narration) are pending in
  `/.memlog.md`.
