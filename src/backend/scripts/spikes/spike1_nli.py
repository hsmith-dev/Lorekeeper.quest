#!/usr/bin/env python
"""SPIKE-1 (x86 re-run): DeBERTa-v3 NLI cross-encoder, xsmall vs base.

The appendix `nli.py` of spikes/cpu-benchmarks.md, made repeatable: the same
6-pair sanity set, batch-1 latency over 30 calls, and the 50-pair batch (the
continuity check's per-entry budget) timed --n times so the median and the
spread can be reported.

    python spike1_nli.py cross-encoder/nli-deberta-v3-xsmall --device cpu --n 7
    python spike1_nli.py cross-encoder/nli-deberta-v3-base --device cuda --n 7
    python spike1_nli.py /models/nli-deberta-v3-xsmall --label "ml image xsmall" --n 7   # in the ml sidecar image

Runs in the bench image (Dockerfile.bench); see run_x86.sh for the docker
flags of each column.
"""

from __future__ import annotations

import time

import _bench

PAIRS = [
    ("Mira died in the fire at the Silver Stag.", "Mira greeted the party at the inn the next morning.", "contradiction"),
    ("Borin Stonebeard is the king of Karak Dun.", "Borin Stonebeard rules the dwarven city of Karak Dun.", "entailment"),
    ("The black dagger was destroyed in the forge at Dawnbreaker.", "Veyra drew the black dagger and stabbed the cultist.", "contradiction"),
    ("Aldric swore an oath never to take a life.", "Aldric ordered supper and asked about the weather.", "neutral"),
    ("Grukk cannot read.", "Grukk read the ancient inscription aloud to the group.", "contradiction"),
    ("The party left Karak Dun heading north.", "The party travelled north away from Karak Dun.", "entailment"),
]


def main(argv=None) -> int:
    p = _bench.base_parser(__doc__)
    p.add_argument("model", help="e.g. cross-encoder/nli-deberta-v3-xsmall")
    p.add_argument("--device", default="cpu", help="cpu or cuda")
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--threads", type=int, default=None, help="torch threads (default: the cpuset size)")
    p.add_argument("--label", default=None, help="config label (default: the model name)")
    args = p.parse_args(argv)

    import numpy as np
    import torch

    torch.set_num_threads(args.threads or _bench.cpu_threads())
    from sentence_transformers import CrossEncoder

    sync = torch.cuda.synchronize if args.device.startswith("cuda") else (lambda: None)
    t = time.perf_counter()
    m = CrossEncoder(args.model, device=args.device)
    load_s = time.perf_counter() - t
    labels = [m.model.config.id2label[i].lower() for i in range(3)]
    ex = [(a, b) for a, b, _ in PAIRS]
    m.predict(ex[:2])  # warm-up
    m.predict((ex * 9)[:50], batch_size=args.batch_size)

    probs = m.predict(ex, apply_softmax=True)
    sanity = [{"expected": e, "got": labels[int(np.argmax(pr))],
               "p_contradiction": round(float(pr[labels.index("contradiction")]), 3)}
              for (_, _, e), pr in zip(PAIRS, probs)]

    lat = []
    for i in range(30):
        t = time.perf_counter(); m.predict([ex[i % 6]], batch_size=1); sync()
        lat.append((time.perf_counter() - t) * 1000)

    fifty = []
    batch = (ex * 9)[:50]
    for _ in range(args.n):
        t = time.perf_counter(); m.predict(batch, batch_size=args.batch_size); sync()
        fifty.append(time.perf_counter() - t)

    s50 = _bench.stats(fifty)
    result = {
        "spike": "SPIKE-1",
        "config": args.label or args.model.rsplit("/", 1)[-1],
        "column": _bench.column(args.device),
        "env": {**_bench.environment(), "torch": torch.__version__, "torch_threads": torch.get_num_threads(),
                "device": args.device},
        "metrics": {
            "load_s": round(load_s, 2),
            "per_pair_batch1_ms": _bench.stats(lat, 1),
            "fifty_pairs_s": s50,
            "pairs_per_s": round(50 / s50["median"], 1),
            "sanity_correct": sum(s["expected"] == s["got"] for s in sanity),
            "sanity": sanity,
            "peak_rss_mb": _bench.peak_rss_mb(),
            "cgroup_peak_mb": _bench.cgroup_peak_mb(),
        },
    }
    _bench.emit(result, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
