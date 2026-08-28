# Retrieval Evaluation

The RAG layer is evaluated separately from generation quality, using
`src/backend/scripts/eval_retrieval.py` — a labeled query set run against the
seeded demo campaign's 9-entry journal, sweeping the vector-relevance
threshold and comparing retrieval modes.

## Method

- **21 labeled queries**: 16 on-topic (each names its expected entry;
  deliberately split between *paraphrase-style* questions, where dense
  retrieval should carry, and *rare-proper-noun* questions — "Veyra",
  "Karak Dun", "Dawnbreaker" — where 384-dim sentence embeddings are known
  to blur) and 5 off-topic (including a hard negative: plausible-sounding
  but **unrecorded** campaign lore, "who is the queen of the elven court?").
- **hit@3** — on-topic queries whose expected entry reaches the final top-3
  (i.e., the right record actually enters the prompt).
- **gate-holds** — off-topic queries where *nothing* passes the relevance
  gate (no confidently-cited bogus sources; the reply gets the
  "Not from your journal" label instead).

## Results (final configuration)

```
thresh | mode        |  hit@3 | gate-holds
-------------------------------------------
  0.55 | vector-only |  6/16  | 5/5
  0.55 | hybrid      | 12/16  | 5/5
  0.65 | vector-only | 10/16  | 5/5
  0.65 | hybrid      | 14/16  | 5/5   ← production operating point
  0.75 | vector-only | 15/16  | 4/5
  0.75 | hybrid      | 16/16  | 4/5
```

**Chosen: hybrid retrieval, vector gate at cosine distance ≤ 0.65.**
At 0.75 hybrid reaches 16/16 — but the unrecorded-lore negative leaks
(d≈0.68 to a thematically-adjacent entry), which is precisely the failure
the gate exists to prevent. Precision was chosen over the last two recall
points: an answer labeled "not from your journal" is recoverable by the
user; a fabricated citation is not. Note that 0.65 is also where hybrid's
margin over vector-only is largest (+4 queries, all proper-noun rescues).

## The retrieval architecture these numbers validate

1. **Dense retriever**: pgvector cosine distance over sentence-transformer
   embeddings, top-10 pool.
2. **Lexical retriever**: per-content-word full-text matching against the
   GIN-indexed tsv column, top-10 pool, ranked by matched-word count.
3. **Reciprocal Rank Fusion** (K=60) merges the two rankings.
4. **Relevance gate**: a candidate enters the prompt only if its vector
   distance ≤ 0.65, or its lexical evidence is strong on its own terms —
   a case-sensitive literal match on a proper noun from the query, or
   coverage of ≥75% (min 3) of the query's content words.
5. Everything either retriever surfaced — kept or gated — is returned to the
   client and rendered in the chat's "How this answer was built" panel.

## Measured failure modes this process caught and fixed

Every rule above exists because the evaluation caught a concrete failure:

| Failure (measured live) | Fix |
|---|---|
| `plainto_tsquery` ANDs terms: "where did we get **Dawnbreaker**" matched nothing because "get" was absent | OR-semantics per-word matching |
| `ts_rank` normalizes by query length: matching **all 4** content words of one query scored *below* matching 1 word of another (0.015 vs 0.020) — no rank floor can work across queries | rank by matched-word **count** |
| Off-topic "chocolate chip cookies" grazed an entry on stray words and got cited | lexical hits alone can't pass the gate |
| Stemming: "the United **States**" → `state` matched "**stated**" | proper-noun match is literal, not stemmed |
| Case-folding: "**United**" matched "…more **united** than ever" | proper-noun match is case-sensitive (names are capitalized in prose) |
| tsv indexed only the narrative — first-person prose ("we") lacks the notes' plain words ("party", "mill"), blinding lexical retrieval to the vocabulary users search with | tsv now indexes shorthand + narrative, same text the embeddings already use (migration `a3e7c1f9d258`) |

The two remaining on-topic misses at the operating point are pure-paraphrase
questions whose expected entry sits at d≈0.71–0.73 with no strong lexical
evidence — the deliberate price of a gate that never fabricates a citation.

## Reproducing

```bash
docker compose -f docker-compose.prod.yml exec backend \
    python scripts/eval_retrieval.py --campaign-id <campaign-uuid> \
    --thresholds 0.55,0.65,0.75
```
