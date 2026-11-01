#!/usr/bin/env python
"""SPIKE-3 timing (x86 re-run): Kokoro-82M RTF, first audio and peak RSS.

The appendix `tts_kokoro.py` of spikes/cpu-benchmarks.md, made repeatable and
run the way AD-7 allows the tts container to run: one sentence per call. The
input is a 300-word recap (the NFR-6 narration row's size), synthesised --n
times. Reported: generation time, audio length, RTF, time to the first
sentence's audio, and words the phonemizer dropped.

The espeak-ng fallback is on by default (the AGPL tts container ships it);
--no-espeak disables it, as the commercial build must (FR-33), to count the
dropped names. SPIKE-3's listening tests are not part of this script.

    python spike3_tts.py --device cpu --n 5
    python spike3_tts.py --device cuda --n 5

Runs in the bench image (Dockerfile.bench); see run_x86.sh.
"""

from __future__ import annotations

import time

import _bench

RECAP_300 = (
    "Last time on our adventure, the party arrived at the iron gates of Karak Dun, where Borin Stonebeard and "
    "his sentries met them with drawn axes. Grukk talked his way past the guards with a stolen royal seal, "
    "claiming he had found it on a dead courier by the river. The dwarves were not convinced, but the seal was "
    "real, and the law of the hold is older than any guard's suspicion. "
    "Inside the great hall, Aldric noticed the torches burning a sickly green, the same eerie flame he had "
    "witnessed during the siege of Dawnbreaker. Veyra's keen elven eyes spotted a cloaked figure slipping behind "
    "a pillar, clutching a black dagger etched with glowing runes. She said nothing at first, and followed the "
    "stranger with her gaze while the others argued with the steward about rooms for the night. "
    "As the stranger whispered in a forgotten tongue, the green fire roared to life all around them. Steel was "
    "drawn, initiative was rolled, and the fate of the dwarven kingdom now hangs on what happens next. Aldric "
    "charged across the cracked marble floor, his shield raised against the flames. Grukk hurled a bench at the "
    "pillar, and the cloaked figure vanished in a burst of smoke that smelled of tar and old iron. "
    "When the smoke cleared, Borin knelt beside the throne and found a single rune carved into the stone, still "
    "warm to the touch. He told the party that only the priests of the Hollow King had ever used that mark, and "
    "that none of them had been seen in Karak Dun for three hundred years. "
    "Tonight the party must decide whether to chase the stranger into the deep halls, where the old roads run "
    "beneath the mountain, or to warn the council before dawn. Will our heroes unmask the stranger before the "
    "flames consume the hall, or will the Hollow King wake first?"
)
SENTENCE_SPLIT = r"(?<=[.?!])\s+"
SR = 24000


def main(argv=None) -> int:
    p = _bench.base_parser(__doc__)
    p.add_argument("--device", default="cpu")
    p.add_argument("--voice", default="af_heart")
    p.add_argument("--no-espeak", action="store_true", help="disable the GPL espeak-ng fallback (commercial build)")
    p.add_argument("--threads", type=int, default=None)
    args = p.parse_args(argv)

    import torch

    torch.set_num_threads(args.threads or _bench.cpu_threads())
    if args.no_espeak:
        from misaki import espeak

        class NoEspeak:
            def __init__(self, *a, **k):
                raise RuntimeError("espeak fallback disabled")

        espeak.EspeakFallback = NoEspeak
    from kokoro import KPipeline

    t = time.perf_counter()
    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device=args.device)
    list(pipe("Warm up sentence.", voice=args.voice))
    load_s = time.perf_counter() - t
    words = len(RECAP_300.split())

    gen, first, audio_s, dropped = [], [], [], set()
    for _ in range(args.n):
        t = time.perf_counter(); f = None; samples = 0
        for r in pipe(RECAP_300, voice=args.voice, split_pattern=SENTENCE_SPLIT):
            f = f if f is not None else time.perf_counter() - t
            samples += len(r.audio)
            dropped |= {tk.text for tk in (r.tokens or []) if tk.text.strip().isalpha() and not tk.phonemes}
        gen.append(time.perf_counter() - t)
        first.append(f)
        audio_s.append(samples / SR)

    g = _bench.stats(gen, 2)
    a = sum(audio_s) / len(audio_s)
    result = {
        "spike": "SPIKE-3",
        "config": f"kokoro-82M {args.voice} per-sentence" + (" no-espeak" if args.no_espeak else ""),
        "column": _bench.column(args.device),
        "env": {**_bench.environment(), "torch": torch.__version__, "device": args.device},
        "metrics": {
            "load_s": round(load_s, 2),
            "words": words,
            "audio_s": round(a, 1),
            "generation_s": g,
            "rtf": _bench.stats([x / y for x, y in zip(gen, audio_s)], 3),
            "first_audio_s": _bench.stats(first, 2),
            "dropped_words": sorted(dropped),
            "peak_rss_mb": _bench.peak_rss_mb(),
            "cgroup_peak_mb": _bench.cgroup_peak_mb(),
        },
    }
    _bench.emit(result, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
