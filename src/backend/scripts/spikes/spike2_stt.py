#!/usr/bin/env python
"""SPIKE-2 (x86 re-run): faster-whisper chunk latency, live-caption sizing.

The appendix `stt_fw.py` of spikes/cpu-benchmarks.md, made repeatable. On the
67 s GM clip (data/clip.wav, 16 kHz mono PCM16; data/speech.txt is its
script) it measures:

  * every 15 s chunk, --n times: latency and RTF (latency / chunk length),
    reported as the median, spread and worst over all chunks and runs;
  * the full clip once: time and word match (share of script words recovered
    in order, a rough accuracy proxy, not WER);
  * `initial_prompt` name accuracy: how many of the 6 demo names come back
    spelled right, without and with a prompt listing them (what the stt
    sidecar would seed from the Campaign's Entity list);
  * with --busy-url, the "LLM busy" case: the chunk runs repeat while a
    thread keeps the Ollama at that URL generating.

    python spike2_stt.py base int8 --device cpu --n 5
    python spike2_stt.py base int8 --device cpu --n 5 --busy-url http://127.0.0.1:11500 --busy-model lorekeeper
    python spike2_stt.py small float16 --device cuda --n 5

Runs in the bench image (Dockerfile.bench); see run_x86.sh.
"""

from __future__ import annotations

import difflib
import json
import re
import threading
import time
import urllib.request
import wave
from pathlib import Path

import _bench

NAMES = ["Karak Dun", "Borin Stonebeard", "Grukk", "Aldric", "Veyra", "Dawnbreaker"]
NAME_PROMPT = "Fantasy campaign session. Names: " + ", ".join(NAMES) + "."
CHUNK_S = 15


def _load(path: Path):
    import numpy as np

    w = wave.open(str(path))
    assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, "need 16 kHz mono PCM16"
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def word_match(ref: str, hyp: str) -> float:
    r, h = _words(ref), _words(hyp)
    m = sum(b.size for b in difflib.SequenceMatcher(None, r, h).get_matching_blocks())
    return round(m / len(r), 3)


def names_found(text: str) -> list[str]:
    flat = " ".join(_words(text))
    return [n for n in NAMES if " ".join(_words(n)) in flat]


class Busy:
    """Keeps an Ollama generating (stream off, 256 tokens a call) until stopped."""

    def __init__(self, url: str, model: str, num_thread: int | None = None) -> None:
        self.url, self.model, self.num_thread = url.rstrip("/"), model, num_thread
        self.stop = threading.Event()
        self.calls, self.tokens, self.eval_s = 0, 0, 0.0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        body = json.dumps({"model": self.model, "stream": False,
                           "prompt": "Write a long, detailed history of the dwarven hold of Karak Dun.",
                           "options": {"num_predict": 256, "temperature": 0.7,
                                       **({"num_thread": self.num_thread} if self.num_thread else {})}}).encode()
        while not self.stop.is_set():
            req = urllib.request.Request(f"{self.url}/api/generate", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=900) as r:
                out = json.loads(r.read())
            self.calls += 1
            self.tokens += out.get("eval_count", 0)
            self.eval_s += out.get("eval_duration", 0) / 1e9

    def __enter__(self):
        self.thread.start()
        time.sleep(3)  # let the first generation get past model load and prompt eval
        return self

    def __exit__(self, *exc):
        self.stop.set()
        return False


def main(argv=None) -> int:
    p = _bench.base_parser(__doc__)
    p.add_argument("size", help="base or small")
    p.add_argument("compute_type", help="int8, float32, float16 (cuda), int8_float16 (cuda)")
    p.add_argument("--device", default="cpu")
    p.add_argument("--data", default=str(Path(__file__).with_name("data")), help="dir with clip.wav and speech.txt")
    p.add_argument("--cpu-threads", type=int, default=None, help="CTranslate2 threads (default: the cpuset size)")
    p.add_argument("--busy-url", default=None, help="Ollama to keep generating during the chunk runs")
    p.add_argument("--busy-model", default="lorekeeper")
    p.add_argument("--busy-num-thread", type=int, default=None, help="Ollama num_thread for the busy loop")
    args = p.parse_args(argv)

    from faster_whisper import WhisperModel
    import ctranslate2

    data = Path(args.data)
    audio = _load(data / "clip.wav")
    script = (data / "speech.txt").read_text()
    sr = 16000
    chunks = [audio[i:i + CHUNK_S * sr] for i in range(0, len(audio), CHUNK_S * sr)]

    threads = args.cpu_threads or _bench.cpu_threads()
    t = time.perf_counter()
    m = WhisperModel(args.size, device=args.device, compute_type=args.compute_type, cpu_threads=threads)
    load_s = time.perf_counter() - t

    def tr(a, prompt=None):
        t = time.perf_counter()
        segs, _ = m.transcribe(a, beam_size=5, language="en", vad_filter=False, initial_prompt=prompt)
        txt = " ".join(s.text for s in segs)  # the generator does the work
        return time.perf_counter() - t, txt

    tr(chunks[0])  # warm-up

    def chunk_runs() -> tuple[list[float], list[float], list[float]]:
        lat, rtf, full_len = [], [], []
        for _ in range(args.n):
            for c in chunks:
                if len(c) < 5 * sr:      # the 7 s tail is not a full chunk; skip anything this short
                    continue
                dt, _ = tr(c)
                lat.append(dt)
                rtf.append(dt / (len(c) / sr))
                full_len.append(len(c) / sr)
        return lat, rtf, full_len

    lat, rtf, _ = chunk_runs()
    full_s, full_txt = tr(audio)
    _, prompted_txt = tr(audio, NAME_PROMPT)

    metrics = {
        "load_s": round(load_s, 2),
        "chunk_s": CHUNK_S,
        "chunk_latency_s": _bench.stats(lat, 2),
        "chunk_rtf": _bench.stats(rtf, 3),
        "full_clip_s": round(full_s, 2),
        "full_rtf": round(full_s / (len(audio) / sr), 3),
        "word_match": word_match(script, full_txt),
        "names_no_prompt": names_found(full_txt),
        "names_with_prompt": names_found(prompted_txt),
        "word_match_with_prompt": word_match(script, prompted_txt),
        "transcript": full_txt.strip(),
        "transcript_with_prompt": prompted_txt.strip(),
    }

    if args.busy_url:
        with Busy(args.busy_url, args.busy_model, args.busy_num_thread) as busy:
            blat, brtf, _ = chunk_runs()
        metrics["busy"] = {
            "chunk_latency_s": _bench.stats(blat, 2),
            "chunk_rtf": _bench.stats(brtf, 3),
            "llm_calls": busy.calls,
            "llm_gen_tok_s": round(busy.tokens / busy.eval_s, 2) if busy.eval_s else None,
        }

    metrics["peak_rss_mb"] = _bench.peak_rss_mb()
    metrics["cgroup_peak_mb"] = _bench.cgroup_peak_mb()
    result = {
        "spike": "SPIKE-2",
        "config": f"{args.size} {args.compute_type}" + (" + LLM busy" if args.busy_url else ""),
        "column": _bench.column(args.device),
        "env": {**_bench.environment(), "ctranslate2": ctranslate2.__version__, "cpu_threads": threads,
                "device": args.device, "busy_url": args.busy_url},
        "metrics": metrics,
    }
    _bench.emit(result, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
