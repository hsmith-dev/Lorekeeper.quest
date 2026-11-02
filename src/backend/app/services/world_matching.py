"""The only name matchers (E0-WorldCore.4, AD-9, AR-9, FR-14).

    hits = await match_names(db, ctx, narrative)              # exact name / alias spans, in text order
    best = await candidates(db, ctx, "Aldrik", type=EntityType.CHARACTER)   # RapidFuzz shortlist

Both are re-exported by app.services.world_service, with `normalize_name`
and `NAME_PREFIXES` (app/domain/names.py). No other module matches names.

**Index.** Each call builds its index from ctx-scoped queries (no cache):
the Entities of `scoped_select(Entity, ctx)` that are not deleted, the
aliases of `scoped_select(EntityAlias, ctx)` whose Entity's `aliases` field
ctx may see (`parent_field_audience` + `visible_to`), and the Mention count
of each Entity over `scoped_select(EntityMention, ctx)`. Alias keys are
recomputed from `alias` (a stale `normalized_alias` never matters). A merged
Entity's name and aliases resolve to its survivor, following the chain with
a cycle guard, only when ctx sees every merged row on the way and a live
survivor; otherwise they are dropped. A merged id is never returned.

**match_names.** Word tokens (app.domain.names.name_tokens), so "Mira" never
matches inside "Miranda". A key matches a run of consecutive text tokens
equal to its tokens; between two of them there may only be whitespace (no
blank line), hyphens, apostrophes or periods. A match extends back over
directly preceding `NAME_PREFIXES` tokens ("Brother Aldric"). Overlaps
resolve longest first (character length, then leftmost); the result is in
text order. One span naming several Entities picks one: a name beats an
alias (a merged Entity's name counts as an alias of its survivor), then more
visible Mentions, then the earliest `created_at`, then the id.

**candidates.** The surface's key against every visible Entity's key and
alias keys by `rapidfuzz.fuzz.WRatio` (best per Entity, /100, only > 0),
sorted by score desc, mention_count desc, then name; at most `limit`
(1..100, else ValueError).
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import sqlalchemy as sa
from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import CampaignContext, scoped_select, visible_to
from app.access.registry import parent_field_audience
from app.db.models.entity import Entity, EntityAlias, EntityMention
from app.domain.enums import EntityType
from app.domain.names import PREFIX_SET, key_tokens, name_tokens, normalize_name

MAX_LIMIT = 100
_ALIASES_FIELD = "aliases"
# Between two tokens of one match: whitespace, hyphens, apostrophes, periods.
_SEPARATOR = re.compile(r"[\s\-‐‑'’.]+")
_BLANK_LINE = re.compile(r"\n[^\S\n]*\n")
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class NameMatch:
    """An exact name or alias span of `text`: `surface == text[start:end]`."""

    entity_id: uuid.UUID
    surface: str
    start: int
    end: int
    score: float
    exact: bool
    name: str         # the Entity's name
    type: EntityType
    matched: str      # the name or alias (surface form) that matched
    alias: bool       # matched through an alias (or a merged Entity's name)


@dataclass(frozen=True)
class NameCandidate:
    entity_id: uuid.UUID
    name: str
    type: EntityType
    matched: str      # the name or alias (surface form) with the best score
    score: float      # in (0, 1]
    mention_count: int


@dataclass(frozen=True)
class _Key:
    entity: Entity    # the live Entity the key resolves to
    tokens: tuple[str, ...]
    key: str          # normalize_name(matched)
    matched: str
    alias: bool


@dataclass
class _Index:
    entities: dict[uuid.UUID, Entity]
    keys: list[_Key]
    mentions: dict[uuid.UUID, int]

    def rank(self, k: _Key) -> tuple:
        e = k.entity
        return (k.alias, -self.mentions.get(e.id, 0), e.created_at or _EPOCH, str(e.id))


def _type_values(types: Any) -> frozenset[str] | None:
    if types is None:
        return None
    if isinstance(types, (str, EntityType)):
        types = [types]
    return frozenset(EntityType(t).value for t in types)


async def _rows(db: AsyncSession, stmt: sa.Select) -> list[Any]:
    return list((await db.execute(stmt.execution_options(populate_existing=True))).scalars().all())


def _aliases_visible(entity: Entity, ctx: CampaignContext) -> bool:
    return visible_to(parent_field_audience(Entity, entity, _ALIASES_FIELD), ctx)


async def _index(db: AsyncSession, ctx: CampaignContext, types: Any) -> _Index:
    if not isinstance(ctx, CampaignContext):
        raise TypeError("world_matching: ctx must be a CampaignContext")
    wanted = _type_values(types)
    seen = {e.id: e for e in await _rows(db, scoped_select(Entity, ctx)) if e.deleted_at is None}

    def resolve(entity: Entity) -> Entity | None:
        visited: set[uuid.UUID] = set()
        while entity.merged_into_id is not None:
            if entity.id in visited:
                return None  # a cycle
            visited.add(entity.id)
            nxt = seen.get(entity.merged_into_id)
            if nxt is None:
                return None  # the survivor is deleted, hidden or gone
            entity = nxt
        return entity

    live = {i: e for i, e in seen.items() if e.merged_into_id is None
            and (wanted is None or str(e.type) in wanted)}
    keys: list[_Key] = []

    def add(owner: Entity, matched: str, alias: bool) -> None:
        target = resolve(owner)
        if target is None or target.id not in live:
            return
        if target is not owner:
            # A merged Entity's names are aliases of its survivor.
            if alias and not _aliases_visible(target, ctx):
                return
            alias = True
        key = normalize_name(matched)
        tokens = key_tokens(matched)
        if key and tokens:
            keys.append(_Key(target, tokens, key, matched, alias))

    for entity in seen.values():
        add(entity, entity.name, False)
    for row in await _rows(db, scoped_select(EntityAlias, ctx)):
        owner = seen.get(row.entity_id)
        if owner is not None and _aliases_visible(owner, ctx):
            add(owner, row.alias, True)

    counts = scoped_select(EntityMention, ctx).with_only_columns(
        EntityMention.entity_id, sa.func.count(EntityMention.id)).group_by(EntityMention.entity_id)
    mentions = {eid: int(n) for eid, n in (await db.execute(counts)).all()}
    return _Index(live, keys, mentions)


def _separator_ok(gap: str) -> bool:
    return bool(_SEPARATOR.fullmatch(gap)) and not _BLANK_LINE.search(gap)


def _overlaps(a: tuple[int, int], taken: Iterable[tuple[int, int]]) -> bool:
    return any(a[0] < b[1] and b[0] < a[1] for b in taken)


async def match_names(db: AsyncSession, ctx: CampaignContext, text: str, *, types: Any = None) -> list[NameMatch]:
    """Every exact, non-overlapping name or alias span of `text` (text order)."""
    if not text:
        return []
    index = await _index(db, ctx, types)
    # One best key per token sequence (a name beats an alias, then the rank).
    best: dict[tuple[str, ...], _Key] = {}
    for k in index.keys:
        cur = best.get(k.tokens)
        if cur is None or index.rank(k) < index.rank(cur):
            best[k.tokens] = k
    by_first: dict[str, list[_Key]] = defaultdict(list)
    for k in best.values():
        by_first[k.tokens[0]].append(k)

    toks = name_tokens(text)
    gap_ok = [_separator_ok(text[toks[i].end:toks[i + 1].start]) for i in range(len(toks) - 1)]
    spans: dict[tuple[int, int], _Key] = {}
    for i, tok in enumerate(toks):
        for k in by_first.get(tok.text, ()):
            last = i + len(k.tokens) - 1
            if last >= len(toks):
                continue
            if not all(toks[i + n].text == k.tokens[n] and gap_ok[i + n - 1] for n in range(1, len(k.tokens))):
                continue
            first = i
            while first > 0 and toks[first - 1].text in PREFIX_SET and gap_ok[first - 1]:
                first -= 1
            span = (toks[first].start, toks[last].end)
            cur = spans.get(span)
            if cur is None or index.rank(k) < index.rank(cur):
                spans[span] = k

    taken: list[tuple[int, int]] = []
    for span in sorted(spans, key=lambda s: (-(s[1] - s[0]), s[0])):
        if not _overlaps(span, taken):
            taken.append(span)
    out = []
    for start, end in sorted(taken):
        k = spans[(start, end)]
        out.append(NameMatch(entity_id=k.entity.id, surface=text[start:end], start=start, end=end, score=1.0,
                             exact=True, name=k.entity.name, type=EntityType(k.entity.type), matched=k.matched,
                             alias=k.alias))
    return out


async def candidates(db: AsyncSession, ctx: CampaignContext, surface: str, *, type: Any = None,
                     limit: int = 3) -> list[NameCandidate]:
    """Up to `limit` visible Entities ranked by RapidFuzz WRatio against `surface`."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"candidates: limit must be an integer in 1..{MAX_LIMIT}, not {limit!r}")
    query = normalize_name(surface or "")
    if not query:
        return []
    index = await _index(db, ctx, type)
    scored: dict[uuid.UUID, tuple[float, _Key]] = {}
    for k in index.keys:
        score = fuzz.WRatio(query, k.key) / 100.0
        cur = scored.get(k.entity.id)
        if cur is None or score > cur[0] or (score == cur[0] and index.rank(k) < index.rank(cur[1])):
            scored[k.entity.id] = (score, k)
    rows = [NameCandidate(entity_id=eid, name=k.entity.name, type=EntityType(k.entity.type), matched=k.matched,
                          score=min(score, 1.0), mention_count=index.mentions.get(eid, 0))
            for eid, (score, k) in scored.items() if score > 0]
    rows.sort(key=lambda c: (-c.score, -c.mention_count, c.name, str(c.entity_id)))
    return rows[:limit]


__all__ = ["MAX_LIMIT", "NameCandidate", "NameMatch", "candidates", "match_names"]
