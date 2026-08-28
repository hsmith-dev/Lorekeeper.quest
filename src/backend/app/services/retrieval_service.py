"""Hybrid journal retrieval for chat RAG: dense vector search fused with
lexical (Postgres full-text) search via Reciprocal Rank Fusion.

Why hybrid: the two retrievers fail in opposite ways. Dense embeddings
(384-dim sentence-transformers) capture paraphrase — "the goblin leader we
beat" finds the Grukk entry — but smear rare proper nouns: "Veyra",
"Karak Dun", "Dawnbreaker" are near-noise tokens to the encoder, and those
are exactly what a GM asks about. The GIN-indexed narrative_tsv column
(already maintained on every entry for the journal list's search box) nails
exact terms but knows nothing about meaning. RRF fuses both rankings
without needing their incomparable scores on a common scale:

    rrf(d) = Σ_lists 1 / (K + rank_list(d))        (K = 60, the standard)

Every candidate either retriever surfaced is returned — including the ones
that failed the relevance gate — so the chat response can show its work
(which entries were considered, their distances, why each was kept or
dropped) instead of asserting groundedness."""

from dataclasses import dataclass
import uuid

from sqlalchemy import select, func, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.journal import JournalEntry
from app.services.embedding_service import embed

# Max cosine distance (0 = identical, 2 = opposite) for a *vector* hit to
# count as relevant. Lexical hits pass the gate on their own — an exact
# full-text match on a rare name is strong evidence of relevance precisely
# in the cases where the embedding distance is misleadingly large.
#
# 0.65, measured — not guessed (scripts/eval_retrieval.py sweep against a
# 21-query labeled set; full results in docs/RETRIEVAL_EVAL.md): at 0.75
# hybrid scores 16/16 on-topic hits but plausible-sounding UNRECORDED-lore
# questions ("who is the queen of the elven court?", d≈0.68-0.70 to a
# thematically-adjacent entry) get a confidently-cited bogus source — the
# exact failure the gate exists to prevent. At 0.65 the gate holds on every
# labeled negative while hybrid keeps 14/16 hits (vector-only manages just
# 10/16 here — this is where lexical rescue matters most). Precision over
# the last two recall points: an answer labeled "not from your journal" is
# recoverable; a fabricated citation is not.
RAG_RELEVANCE_MAX_DISTANCE = 0.65

_RRF_K = 60
_CANDIDATE_POOL = 10  # per retriever, pre-fusion

# Words that carry no retrieval signal — filtered before lexical matching so
# "matched content words" means something. Deliberately small and English-only,
# mirroring the 'english' text-search config the tsv column uses.
_STOPWORDS = frozenset(
    "a an and are as at be but by did do does for from get got had has have he her his how i in is it its "
    "like me my of on or our she so tell that the their them they this to under us was we were what when "
    "where which who whom why will with you your".split()
)


@dataclass
class RetrievedEntry:
    entry: JournalEntry
    vector_distance: float | None  # None = not surfaced by vector search
    lexical_rank: int | None       # 1-based rank in the full-text results; None = no match
    rrf_score: float
    passed_gate: bool
    used: bool                     # passed AND within the final top-`limit`

    @property
    def method(self) -> str:
        if self.vector_distance is not None and self.lexical_rank is not None:
            return "both"
        return "semantic" if self.vector_distance is not None else "keyword"


async def hybrid_search_journal(
    db: AsyncSession,
    query_text: str,
    *,
    campaign_id: uuid.UUID | None,
    user_id: uuid.UUID,
    limit: int = 3,
    max_distance: float = RAG_RELEVANCE_MAX_DISTANCE,
) -> list[RetrievedEntry]:
    """Top-`limit` fused results plus every also-ran, ordered by RRF score.
    Callers use the `used` entries for prompt context and the full list for
    the transparency panel."""
    if campaign_id:
        # A selected campaign is shared context — every member's entries
        # count, not just the requesting user's.
        base_filter = JournalEntry.campaign_id == campaign_id
    else:
        base_filter = JournalEntry.user_id == user_id

    # ── Dense retriever ────────────────────────────────────────────────────
    vector_hits: dict[uuid.UUID, tuple[JournalEntry, float, int]] = {}
    try:
        query_embedding = embed(query_text)
        distance = JournalEntry.embedding.cosine_distance(query_embedding)
        result = await db.execute(
            select(JournalEntry, distance.label("dist"))
            .where(base_filter, JournalEntry.embedding.isnot(None))
            .order_by(distance)
            .limit(_CANDIDATE_POOL)
        )
        for rank, (entry, dist) in enumerate(result.all(), start=1):
            if dist is not None:
                vector_hits[entry.id] = (entry, float(dist), rank)
    except Exception:
        pass  # embedding/DB failure must not break chat — lexical may still serve

    # ── Lexical retriever ──────────────────────────────────────────────────
    # Per-content-word matching with OR recall, counted per word. Why not a
    # single OR tsquery ranked by ts_rank: ts_rank normalizes by query
    # length, so "matched all 4 content words of a 4-word question" (0.015)
    # scores BELOW "matched the 1 word of a 1-word question" (0.020) —
    # measured live; no rank floor can work across queries. Counting matched
    # content words directly is comparable across queries and is also what
    # the gate-bypass rule below reasons about.
    lexical_hits: dict[uuid.UUID, tuple[JournalEntry, int]] = {}
    bypass_ids: set[uuid.UUID] = set()
    try:
        tokens = query_text.split()
        cleaned = ["".join(c for c in w if c.isalnum()) for w in tokens]
        content = [w for w in cleaned if len(w) > 2 and w.lower() not in _STOPWORDS][:16]
        if not content:
            raise ValueError("no lexical terms")
        # Non-leading capitalized tokens ≈ proper nouns ("Veyra", "Karak").
        # Original capitalization kept: the bypass match below is
        # case-sensitive, because a real name is capitalized in the entry's
        # prose too — while a capitalized common word in the query ("the
        # United States") appears only lowercase in prose ("more united than
        # ever", a measured leak) and correctly fails to match.
        proper_cased = {
            w for i, w in enumerate(cleaned)
            if i > 0 and w[:1].isupper() and len(w) > 2 and w.lower() not in _STOPWORDS
        }

        match_cases = [
            (w, func.cast(JournalEntry.narrative_tsv.op("@@")(func.plainto_tsquery("english", w)), Integer))
            for w in content
        ]
        total_expr = sum((expr for _, expr in match_cases[1:]), match_cases[0][1])
        rows = await db.execute(
            select(JournalEntry, *[expr.label(f"m{i}") for i, (_, expr) in enumerate(match_cases)])
            .where(base_filter, total_expr > 0)
            .order_by(total_expr.desc())
            .limit(_CANDIDATE_POOL)
        )
        scored: list[tuple[JournalEntry, int, bool]] = []
        for row in rows.all():
            entry = row[0]
            flags = row[1:]
            matched = sum(flags)
            # Proper nouns must match LITERALLY and CASE-SENSITIVELY, not
            # through the stemmer — two measured failures otherwise: stemming
            # let States→state match "stated", and case-folding let "United"
            # match "...more united than ever". A real name appears verbatim
            # and capitalized when it appears at all.
            haystack = f"{entry.shorthand} {entry.narrative}"
            matched_proper = any(p in haystack for p in proper_cased)
            # Gate-bypass rule — lexical evidence waives the vector gate only
            # when it's strong on its own terms:
            #   (a) it matched a proper noun from the query — rare names are
            #       exactly where embeddings mislead (measured: the entry
            #       containing "Dawnbreaker" sat at d=0.68) and where a
            #       full-text hit is near-conclusive; or
            #   (b) it covered ≥75% of the question's content words with at
            #       least 3 matches — "what did the party find at the old
            #       mill" matching find+old+mill+party (4/4) is compelling
            #       even with no name.
            # Grazes fail both tests (measured: "weather like tomorrow"
            # matching weather+like was 2/3 = 67%, which the old 60%/min-2
            # bar wrongly admitted); they still boost RRF ranking, but can't
            # unlock the gate.
            strong = matched_proper or (matched >= 3 and matched / max(len(content), 1) >= 0.75)
            scored.append((entry, matched, strong))
        scored.sort(key=lambda t: t[1], reverse=True)
        for rank, (entry, _matched, strong) in enumerate(scored, start=1):
            lexical_hits[entry.id] = (entry, rank)
            if strong:
                bypass_ids.add(entry.id)
    except Exception:
        pass  # ditto — vector alone can still serve

    # ── Fuse ───────────────────────────────────────────────────────────────
    fused: list[RetrievedEntry] = []
    for eid in vector_hits.keys() | lexical_hits.keys():
        entry = vector_hits[eid][0] if eid in vector_hits else lexical_hits[eid][0]
        vec_dist = vector_hits[eid][1] if eid in vector_hits else None
        vec_rank = vector_hits[eid][2] if eid in vector_hits else None
        lex_rank = lexical_hits[eid][1] if eid in lexical_hits else None
        score = 0.0
        if vec_rank is not None:
            score += 1.0 / (_RRF_K + vec_rank)
        if lex_rank is not None:
            score += 1.0 / (_RRF_K + lex_rank)
        passed = (vec_dist is not None and vec_dist <= max_distance) or eid in bypass_ids
        fused.append(RetrievedEntry(
            entry=entry, vector_distance=vec_dist, lexical_rank=lex_rank,
            rrf_score=score, passed_gate=passed, used=False,
        ))

    fused.sort(key=lambda r: r.rrf_score, reverse=True)
    kept = 0
    for r in fused:
        if r.passed_gate and kept < limit:
            r.used = True
            kept += 1
    return fused
