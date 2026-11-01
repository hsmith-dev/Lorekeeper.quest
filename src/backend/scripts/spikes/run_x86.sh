#!/usr/bin/env bash
# E0-QA.15: re-run the spike suite on the remote x86 desktop, CPU and GPU.
#
#   rsync -az --exclude __pycache__ src/backend/ <desktop>:<dir>/backend/
#   rsync -az seeds/ <desktop>:<dir>/seeds/
#   ssh <desktop> "bash -lc 'cd <dir> && backend/scripts/spikes/run_x86.sh all'"
#   # then, on the laptop, with <dir>/results copied back to results/:
#   python src/backend/scripts/eval_benchmarks.py --ingest results/*.json
#
# Sections: ollama (= ollama-ref, -capped, -uncapped, -gpu) | nli | stt | tts | all (run one at a time; they compete
# for the same cores). Needs: Docker with the NVIDIA toolkit, the native GPU
# Ollama on :11434 with `lorekeeper`, data/clip.wav + data/speech.txt (the
# 67 s GM clip of spikes/cpu-benchmarks.md, 16 kHz mono PCM16), and
# ~/lorekeeper-dev/models/{lorekeeper-7b-q4.gguf,lorekeeper-Modelfile}.
#
# CPU column ("Reference Box"): CUDA_VISIBLE_DEVICES="" inside
# `docker run --cpus=$REF_CPUS --cpuset-cpus=$REF_CPUSET`, memory capped at
# the component's AD-7 limit (stt 1.25g, ml/tts 2.5g, ollama 5.25g), all well
# inside the 16 GB box. GPU column: the same image with --gpus all.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
DIR=${BENCH_DIR:-$(pwd)}
RESULTS=$DIR/results
DATA=$DIR/data
BENCH_IMAGE=${BENCH_IMAGE:-lorekeeper-bench}
ML_IMAGE=${ML_IMAGE:-lorekeeper-ml:latest}   # the ml sidecar (CPU torch, xsmall baked in)
BACKEND_IMAGE=${BACKEND_IMAGE:-lorekeeper-backend-test}
OLLAMA_IMAGE=${OLLAMA_IMAGE:-ollama/ollama:0.40.3}
OLLAMA_CPU=qa15-ollama
OLLAMA_CPU_PORT=${OLLAMA_CPU_PORT:-11500}
CPU_URL=http://127.0.0.1:$OLLAMA_CPU_PORT
GPU_OLLAMA_URL=${GPU_OLLAMA_URL:-http://127.0.0.1:11434}
REF_CPUS=${REF_CPUS:-4}
REF_CPUSET=${REF_CPUSET:-0-3}     # 4 physical cores (their SMT siblings are 12-15)
N=${N:-5}
export BENCH_HARDWARE=${BENCH_HARDWARE:-"$(lscpu | sed -n 's/^Model name: *//p'), $(free -g | awk '/Mem:/{print $2}') GB host"}
mkdir -p "$RESULTS"

cpu_run() {  # cpu_run <mem> <args...>: bench image, Reference-Box CPU column
  local mem=$1; shift
  docker run --rm --cpus="$REF_CPUS" --cpuset-cpus="$REF_CPUSET" --memory="$mem" --memory-swap="$mem" \
    -e CUDA_VISIBLE_DEVICES= -e BENCH_HARDWARE="$BENCH_HARDWARE" --network host \
    -v "$HERE":/bench/s:ro -v "$DATA":/bench/data:ro -v "$RESULTS":/results -w /bench "$BENCH_IMAGE" python "$@"
}
gpu_run() {
  docker run --rm --gpus all -e BENCH_HARDWARE="$BENCH_HARDWARE" --network host \
    -v "$HERE":/bench/s:ro -v "$DATA":/bench/data:ro -v "$RESULTS":/results -w /bench "$BENCH_IMAGE" python "$@"
}

ollama_cpu_up() {  # ollama_cpu_up [docker run CPU flags...]: (re)create the CPU Ollama with these limits
  # Re-created rather than `docker update`d: update can't remove a CPU cap
  # (--cpus=0 leaves the old quota). The model lives in the volume.
  docker rm -f "$OLLAMA_CPU" >/dev/null 2>&1 || true
  docker volume create qa15-ollama >/dev/null
  local mem=${OLLAMA_MEM:-5376m}   # AD-7: 5.25g
  docker run -d --name "$OLLAMA_CPU" "$@" -p 127.0.0.1:"$OLLAMA_CPU_PORT":11434 --memory="$mem" --memory-swap="$mem" \
    -e OLLAMA_MAX_LOADED_MODELS=1 -e OLLAMA_NUM_PARALLEL=1 -e OLLAMA_CONTEXT_LENGTH=4096 -e OLLAMA_KEEP_ALIVE=30m \
    -v qa15-ollama:/root/.ollama -v "$HOME/lorekeeper-dev/models":/import-models:ro "$OLLAMA_IMAGE" >/dev/null
  until curl -sf "http://127.0.0.1:$OLLAMA_CPU_PORT/api/version" >/dev/null; do sleep 1; done
}
ollama_threads() {  # ollama_threads [N]: re-create the CPU container's lorekeeper with num_thread N (none = Ollama's pick)
  # A model PARAMETER, not a request option, so complete_structured's calls
  # use it too (a per-request num_thread that differs reloads the model).
  docker exec "$OLLAMA_CPU" sh -c "sed 's#^FROM .*#FROM /import-models/lorekeeper-7b-q4.gguf#' /import-models/lorekeeper-Modelfile > /tmp/Modelfile \
    && echo >> /tmp/Modelfile ${1:+&& echo 'PARAMETER num_thread $1' >> /tmp/Modelfile} && ollama create lorekeeper -f /tmp/Modelfile" >/dev/null
  if [ -n "${1:-}" ]; then  # `ollama create` can print an error and still exit 0
    docker exec "$OLLAMA_CPU" ollama show lorekeeper --modelfile | grep -q "num_thread $1" \
      || { echo "ollama_threads: num_thread $1 not set" >&2; exit 1; }
  fi
}
spike6() {  # spike6 <url> <label> <column> [extra args]
  local url=$1 label=$2 col=$3; shift 3
  docker run --rm --network host -v "$DIR/backend":/app -v "$DIR/seeds":/seeds -v "$RESULTS":/results -w /app \
    -e SECRET_KEY=x -e POSTGRES_PASSWORD=x -e DATABASE_URL=postgresql+asyncpg://x:x@127.0.0.1:1/x \
    -e BENCH_HARDWARE="$BENCH_HARDWARE" "$BACKEND_IMAGE" \
    python scripts/spikes/spike6_llm_throughput.py --url "$url" --label "$label" --column "$col" \
      --out "/results/spike6-$label.json" "$@"
}

# Reference Box: 4 cores. A real 4-core box makes Ollama start 4 threads; in
# a container Ollama counts the HOST's cores (12 here) whatever --cpus or
# --cpuset say, so the model's num_thread is set to match.
ollama_ref() {
  ollama_cpu_up --cpus="$REF_CPUS" --cpuset-cpus="$REF_CPUSET"
  ollama_threads "$REF_CPUS"
  spike6 "$CPU_URL" "cpu-ref$REF_CPUS" cpu --n 3 --structured 10
  # The same container with Ollama's default thread count (12 threads on 4 cores).
  ollama_threads
  spike6 "$CPU_URL" "cpu-ref$REF_CPUS-default-threads" cpu --n 3 --shapes continuity_verify --max-tokens 32
}
# The prod compose cap before v1.1 (cpus: "3.0", any core, default threads),
# then the same cap with num_thread=3. Short shapes only.
ollama_capped() {
  ollama_cpu_up --cpus=3
  ollama_threads
  spike6 "$CPU_URL" cpu-capped-3 cpu --n 3 --shapes continuity_verify,npc_first_turn --max-tokens 64
  ollama_threads 3
  spike6 "$CPU_URL" cpu-capped-3-t3 cpu --n 3 --shapes continuity_verify,npc_first_turn --max-tokens 64
}
# Uncapped (the v1.1 fix): no CPU limit, Ollama's default threads. At the
# AD-7 5.25g limit the runner was OOM-killed on extraction_300 (12 threads,
# llama-server's RAM prompt cache), so this runs at the prod compose's 14g.
ollama_uncapped() {
  OLLAMA_MEM=${OLLAMA_UNCAPPED_MEM:-14g} ollama_cpu_up
  ollama_threads
  spike6 "$CPU_URL" cpu-uncapped cpu --n 3 --structured 10
}
ollama_gpu() {
  spike6 "$GPU_OLLAMA_URL" gpu gpu --n 3 --structured 50
}
section_ollama() { ollama_ref; ollama_capped; ollama_uncapped; ollama_gpu; }

section_nli() {
  for m in xsmall base; do
    cpu_run 2560m s/spike1_nli.py "cross-encoder/nli-deberta-v3-$m" --device cpu --n "$N" --out "/results/spike1-$m-cpu.json"
    gpu_run s/spike1_nli.py "cross-encoder/nli-deberta-v3-$m" --device cuda --n "$N" --out "/results/spike1-$m-gpu.json"
  done
  # The production path: the ml sidecar image's own torch build and baked
  # xsmall, under ml's AD-7 limit (2.5g).
  BENCH_IMAGE=$ML_IMAGE cpu_run 2560m s/spike1_nli.py /models/nli-deberta-v3-xsmall --label "nli-deberta-v3-xsmall (ml image)" \
    --device cpu --n "$N" --out /results/spike1-xsmall-ml-cpu.json
}

section_stt() {
  # base runs inside stt's AD-7 limit (1.25g); small has no limit of its own,
  # so it gets the 2.5g of the largest sidecar and its peak is reported.
  for cfg in "base int8 1280m" "base float32 1280m" "small int8 2560m" "small float32 2560m"; do
    set -- $cfg
    cpu_run "$3" s/spike2_stt.py "$1" "$2" --device cpu --n "$N" --data /bench/data \
      --out "/results/spike2-$1-$2-cpu.json"
  done
  # "LLM busy": the CPU Ollama shares the same cores as stt, as on a real box.
  ollama_cpu_up --cpus="$REF_CPUS" --cpuset-cpus="$REF_CPUSET"
  ollama_threads "$REF_CPUS"
  curl -sf "http://127.0.0.1:$OLLAMA_CPU_PORT/api/generate" -d '{"model":"lorekeeper","prompt":"ok","options":{"num_predict":1}}' >/dev/null
  cpu_run 1280m s/spike2_stt.py base int8 --device cpu --n "$N" --data /bench/data \
    --busy-url "http://127.0.0.1:$OLLAMA_CPU_PORT" --out /results/spike2-base-int8-cpu-busy.json
  for cfg in "base float16" "small float16"; do
    set -- $cfg
    gpu_run s/spike2_stt.py "$1" "$2" --device cuda --n "$N" --data /bench/data --out "/results/spike2-$1-$2-gpu.json"
  done
}

section_tts() {
  # AD-7 gives tts 2.5g. On 2026-11-01 this process (torch cu128, espeak on)
  # was OOM-killed at 2.5g on the 300-word recap, so TTS_MEM lets the run
  # measure the real peak above the limit (results then report it).
  cpu_run "${TTS_MEM:-2560m}" s/spike3_tts.py --device cpu --n "$N" --out /results/spike3-cpu.json
  gpu_run s/spike3_tts.py --device cuda --n "$N" --out /results/spike3-gpu.json
}

case "${1:-all}" in
  ollama) section_ollama ;;
  ollama-ref) ollama_ref ;;
  ollama-capped) ollama_capped ;;
  ollama-uncapped) ollama_uncapped ;;
  ollama-gpu) ollama_gpu ;;
  nli) section_nli ;;
  stt) section_stt ;;
  tts) section_tts ;;
  all) section_nli; section_stt; section_tts; section_ollama ;;
  down) docker rm -f "$OLLAMA_CPU" >/dev/null 2>&1 || true; docker volume rm qa15-ollama >/dev/null 2>&1 || true ;;
  *) echo "usage: $0 ollama[-ref|-capped|-uncapped|-gpu]|nli|stt|tts|all|down" >&2; exit 2 ;;
esac
