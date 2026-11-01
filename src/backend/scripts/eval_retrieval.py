#!/usr/bin/env python
"""Retrieval evaluation harness: measures the RAG layer itself, separately
from generation quality.

Sweeps the vector-relevance threshold and compares vector-only retrieval
(the pre-hybrid implementation) against hybrid RRF retrieval on a labeled
query set, reporting:

  - hit@3           on-topic queries where an expected entry is in the final
                    top-3 (higher = the right record reaches the prompt)
  - gate-holds      off-topic queries where NOTHING passes the gate
                    (higher = fewer confidently-cited bogus sources)

The labeled set targets the demo campaign (seeds/demo_campaign.json, its
9-session arc); each on-topic query names its expected entry by a
distinctive shorthand substring. Positive queries deliberately mix
paraphrase-style questions (dense retrieval's strength) with
rare-proper-noun questions ("Veyra", "Karak Dun", "Dawnbreaker" — its known
weakness, and full-text's strength).

Operating points are thresholds x {vector-only, hybrid}; the chosen point
(default hybrid@0.65, the production RAG_RELEVANCE_MAX_DISTANCE) is marked.
No LLM is called; --fake-llm and the other shared flags are accepted (see
eval_common.build_parser).

Run inside the backend container (seed first, see scripts/seed_demo.py):
  docker compose -f docker-compose.prod.yml exec backend \\
      python scripts/eval_retrieval.py --campaign-id <uuid> --out /tmp/RETRIEVAL_EVAL.md
(copy docs/RETRIEVAL_EVAL.md to /tmp in the container first with
`docker compose cp`, and copy it back out afterwards: the image has neither
docs/RETRIEVAL_EVAL.md nor docs/EVAL_TEMPLATE.md).

Results and the chosen production threshold are recorded in
docs/RETRIEVAL_EVAL.md.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts import eval_common  # noqa: E402  (first: sets HF_HUB_OFFLINE)
from scripts.eval_common import Failure, ReportError, SeedError  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.db.models.journal import JournalEntry  # noqa: E402
from app.services import embedding_service  # noqa: E402
from app.services.retrieval_service import RAG_RELEVANCE_MAX_DISTANCE, hybrid_search_journal  # noqa: E402

# (query, [acceptable expected-entry shorthand substrings]) — a hit is any
# expected entry appearing in the final top-3. Empty list = off-topic query
# whose correct outcome is zero entries passing the gate.
LABELED = [
    # Paraphrase-leaning (dense retrieval should carry these)
    ("What did the party find at the old mill?", ["goblin chief Grukk"]),
    ("Who did the party rescue from the goblins?", ["goblin chief Grukk"]),
    ("Who identified the mysterious key and what did he charge?", ["scholar Aldric"]),
    ("Who joined the party as a mountain guide?", ["Borin Stonebeard"]),
    ("What happened when a bridge collapsed under a party member?", ["deep halls of Karak Dun"]),
    ("How did the party get through the great doors of the lost hold?", ["gates of Karak Dun"]),
    ("What does the ritual to free the sleeping evil require?", ["Aldric deciphered"]),
    ("Where is the party headed to destroy the key?", ["Forge of Dawn", "Aldric deciphered"]),
    # Proper-noun-leaning (lexical retrieval should rescue these)
    ("Who is Veyra the Pale?", ["ash-grey robes", "Sunless Throne"]),
    ("What is the Ashen Hand?", ["ash-grey robes", "gates of Karak Dun", "Forge of Dawn"]),
    ("Tell me about Karak Dun.", ["gates of Karak Dun", "deep halls of Karak Dun", "Borin Stonebeard"]),
    ("Where did we get Dawnbreaker?", ["deep halls of Karak Dun"]),
    ("What do we know about the Hollow King?", ["Borin Stonebeard", "Aldric deciphered"]),
    ("What happened at the Sunless Throne?", ["Sunless Throne"]),
    ("What did Vex steal from Veyra?", ["Sunless Throne"]),
    ("Who warned the party about Veyra's army?", ["Forge of Dawn"]),
    # Off-topic — the gate should hold (zero entries used)
    ("What is the tax filing deadline in the United States?", []),
    ("What's a good recipe for chocolate chip cookies?", []),
    ("How do I fix a flat bicycle tire?", []),
    ("Who is the queen of the elven court?", []),  # plausible-sounding but unrecorded lore
    ("What's the weather like tomorrow?", []),
]

DEFAULT_THRESHOLDS = "0.55,0.65,0.75"
MODES = ("vector-only", "hybrid")
COLUMNS = ["thresh", "mode", "hit@3", "gate-holds"]


def point_label(threshold: float, mode: str) -> str:
    return f"{mode}@{threshold:.2f}"


DEFAULT_CHOSEN = point_label(RAG_RELEVANCE_MAX_DISTANCE, "hybrid")


async def vector_only(db, query, campaign_id, threshold):
    """The pre-hybrid implementation: top-3 by cosine distance, gated."""
    try:
        emb = embedding_service.embed(query)
    except RuntimeError:  # no model loaded (--embeddings skip, or not cached)
        return []
    distance = JournalEntry.embedding.cosine_distance(emb)
    res = await db.execute(
        select(JournalEntry, distance.label("d"))
        .where(JournalEntry.campaign_id == campaign_id, JournalEntry.embedding.isnot(None))
        .order_by(distance)
        .limit(3)
    )
    return [e for e, d in res.all() if d is not None and d <= threshold]


async def hybrid(db, query, campaign_id, threshold):
    results = await hybrid_search_journal(
        db, query, campaign_id=campaign_id, user_id=uuid.uuid4(), max_distance=threshold
    )
    return [r.entry for r in results if r.used]


RETRIEVERS = {"vector-only": vector_only, "hybrid": hybrid}


def _short(entries) -> str:
    return "; ".join(e.shorthand[:40] for e in entries) or "(nothing)"


async def evaluate(db, campaign_id: uuid.UUID, thresholds: list[float], *,
                   chosen: str = DEFAULT_CHOSEN) -> eval_common.ResultTable:
    positives = [(q, exp) for q, exp in LABELED if exp]
    negatives = [q for q, exp in LABELED if not exp]
    points = [(point_label(t, m), (t, m)) for t in thresholds for m in MODES]

    async def run_point(point):
        threshold, mode = point
        fn = RETRIEVERS[mode]
        label = point_label(threshold, mode)
        failures: list[Failure] = []
        hits = 0
        for q, expected in positives:
            used = await fn(db, q, campaign_id, threshold)
            shorthands = " || ".join(e.shorthand for e in used)
            if any(sub.lower() in shorthands.lower() for sub in expected):
                hits += 1
            else:
                failures.append(Failure(label, q, " or ".join(expected), _short(used)))
        holds = 0
        for q in negatives:
            used = await fn(db, q, campaign_id, threshold)
            if not used:
                holds += 1
            else:
                failures.append(Failure(label, q, "nothing passes the gate", _short(used)))
        return {
            "thresh": f"{threshold:.2f}", "mode": mode,
            "hit@3": f"{hits}/{len(positives)}", "gate-holds": f"{holds}/{len(negatives)}",
        }, failures

    table = await eval_common.sweep(
        points, run_point, columns=COLUMNS,
        chosen=chosen,
        chosen_marker="← production operating point",
    )
    # Only the chosen point's misses go in the report; the rest is noise.
    if table.chosen is not None:
        table.failures = [f for f in table.failures if f.point == table.chosen]
    return table


def build_parser() -> argparse.ArgumentParser:
    p = eval_common.build_parser(__doc__)
    p.add_argument("--thresholds", default=DEFAULT_THRESHOLDS,
                   help="comma-separated vector-gate thresholds to sweep (default: %(default)s)")
    p.add_argument("--chosen", default=DEFAULT_CHOSEN,
                   help="operating point to mark, as <mode>@<threshold> (default: %(default)s)")
    return p


def parse_thresholds(raw: str) -> list[float]:
    try:
        thresholds = [float(t) for t in raw.split(",") if t.strip()]
    except ValueError:
        raise SeedError(f"--thresholds must be comma-separated numbers, got {raw!r}") from None
    if not thresholds:
        raise SeedError("--thresholds is empty")
    return thresholds


async def run(args: argparse.Namespace, *, embedding_model=None) -> eval_common.ResultTable:
    thresholds = parse_thresholds(args.thresholds)
    labels = [point_label(t, m) for t in thresholds for m in MODES]
    if args.chosen not in labels:
        raise SeedError(f"--chosen {args.chosen!r} is not a swept point; choose one of {labels}")
    model = eval_common.install_embedding_model(args.embeddings, embedding_model)
    if model is None:
        print("warning: no embedding model; vector retrieval scores 0 and hybrid is lexical-only",
              file=sys.stderr)
    async with eval_common.open_session(args.database_url) as db:
        data = await eval_common.load_campaign(
            args.seed, db, args.campaign_id, owner_email=args.owner_email,
            embedder=eval_common.seed_demo.embedder_from_model(model),
        )
        positives = sum(1 for _, exp in LABELED if exp)
        print(f"campaign {data.id}: {len(data.entries)} entries; "
              f"{positives} on-topic + {len(LABELED) - positives} off-topic labeled queries\n")
        table = await evaluate(db, data.id, thresholds, chosen=args.chosen)
    print(eval_common.format_table(table))
    if args.out:
        embed_name = "fake" if isinstance(model, eval_common.FakeEmbeddingModel) else (
            "none" if model is None else eval_common.seed_demo.EMBEDDING_MODEL)
        eval_common.write_report(
            args.out, table, title="Retrieval Evaluation",
            note=f"{len(data.entries)} entries; embeddings: `{embed_name}`; LLM: unused.",
        )
        print(f"\nwrote {args.out}")
    return table


def main(argv: list[str] | None = None, *, embedding_model=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(run(args, embedding_model=embedding_model))
    except (SeedError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
