"""Retrieval evaluation harness: measures the RAG layer itself, separately
from generation quality.

Sweeps the vector-relevance threshold and compares vector-only retrieval
(the pre-hybrid implementation) against hybrid RRF retrieval on a labeled
query set, reporting:

  - hit@3           on-topic queries where an expected entry is in the final
                    top-3 (higher = the right record reaches the prompt)
  - gate-holds      off-topic queries where NOTHING passes the gate
                    (higher = fewer confidently-cited bogus sources)

The labeled set targets the demo campaign's seeded 9-session arc; each
on-topic query names its expected entry by a distinctive shorthand
substring. Positive queries deliberately mix paraphrase-style questions
(dense retrieval's strength) with rare-proper-noun questions ("Veyra",
"Karak Dun", "Dawnbreaker" — its known weakness, and full-text's strength).

Run inside the backend container:
  docker compose -f docker-compose.prod.yml exec backend \
      python scripts/eval_retrieval.py --campaign-id <uuid>

Results and the chosen production threshold are recorded in
docs/RETRIEVAL_EVAL.md.
"""

import argparse
import asyncio
import sys
import uuid

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.db.models.journal import JournalEntry  # noqa: E402
from app.services.embedding_service import embed  # noqa: E402
from app.services.retrieval_service import hybrid_search_journal  # noqa: E402

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


async def vector_only(db, query, campaign_id, threshold):
    """The pre-hybrid implementation: top-3 by cosine distance, gated."""
    emb = embed(query)
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


async def evaluate(campaign_id: uuid.UUID, thresholds: list[float]) -> None:
    # The app loads this at startup (main.py lifespan); a standalone script
    # has to do it itself.
    from app.services.embedding_service import load_embedding_model
    load_embedding_model()

    positives = [(q, exp) for q, exp in LABELED if exp]
    negatives = [q for q, exp in LABELED if not exp]

    print(f"{len(positives)} on-topic + {len(negatives)} off-topic labeled queries\n")
    header = f"{'thresh':>6} | {'mode':<11} | {'hit@3':>7} | {'gate-holds':>10}"
    print(header)
    print("-" * len(header))

    async with AsyncSessionLocal() as db:
        for threshold in thresholds:
            for mode, fn in (("vector-only", vector_only), ("hybrid", hybrid)):
                hits = 0
                for q, expected in positives:
                    used = await fn(db, q, campaign_id, threshold)
                    shorthands = " || ".join(e.shorthand for e in used)
                    if any(sub.lower() in shorthands.lower() for sub in expected):
                        hits += 1
                holds = 0
                for q in negatives:
                    used = await fn(db, q, campaign_id, threshold)
                    if not used:
                        holds += 1
                print(
                    f"{threshold:>6.2f} | {mode:<11} | "
                    f"{hits}/{len(positives):<5} | {holds}/{len(negatives)}"
                )
            print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--thresholds", default="0.55,0.65,0.75,0.85,0.95",
        help="comma-separated vector-gate thresholds to sweep",
    )
    args = parser.parse_args()
    thresholds = [float(t) for t in args.thresholds.split(",")]
    asyncio.run(evaluate(args.campaign_id, thresholds))
