"""Audiences (AD-12): who may read a row, as one lattice.

    Public ⊃ Members ⊃ Owner(u) ⊃ GM

A row's Audience is the widest set of viewers who may read it; a ctx's
Audience is the narrowest row Audience its viewer may read. A row is visible
to a ctx when `covers(row_audience, ctx.audience)`:

  * Public covers everything (a Share Link viewer reads only Public rows);
  * Members covers Members, every Owner(u) and GM;
  * Owner(u) covers Owner(u) and GM (not Owner(v), not Members);
  * GM covers only GM.

ctx Audiences: a GM ctx is GM (reads everything), a Player ctx is
Owner(self) (reads Public, Members and their own Private rows), the member
preview (`audience_ctx(member)`) is Members (owns nothing), anon is Public.

`most_restrictive` is the lattice meet: the narrower of two comparable
Audiences, and GM for two different Owners (`Owner(a) ⊓ Owner(b) = GM`).

Stored values map exactly as AD-12 says (`stored_audience`): `party` on a
`kind=gm` row (or a model with no kind) → Public, `party` on `kind=player` →
Members, `private` → Owner(author), `gm` → GM.

`AnyOf` is an any-of reach: a row (a tag) visible when any one of the
Audiences it is reached through covers the ctx; an empty AnyOf is hidden,
even to a GM.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from app.access.policy import ANON, GM, PLAYER
from app.domain.enums import EntryKind, Visibility


class AudienceLevel(StrEnum):
    PUBLIC = "public"
    MEMBERS = "members"
    OWNER = "owner"  # Owner(user_id): private to one author
    GM = "gm"


@dataclass(frozen=True)
class Audience:
    level: AudienceLevel
    user_id: uuid.UUID | None = None  # set only for AudienceLevel.OWNER

    def __post_init__(self) -> None:
        if (self.level is AudienceLevel.OWNER) != (self.user_id is not None):
            raise ValueError("Audience: user_id is required for, and only for, the Owner level")

    def __repr__(self) -> str:
        return f"Owner({self.user_id})" if self.level is AudienceLevel.OWNER else self.level.value.capitalize()


PUBLIC = Audience(AudienceLevel.PUBLIC)
MEMBERS = Audience(AudienceLevel.MEMBERS)
GM_AUDIENCE = Audience(AudienceLevel.GM)


def owner(user_id: uuid.UUID) -> Audience:
    return Audience(AudienceLevel.OWNER, user_id)


@dataclass(frozen=True)
class AnyOf:
    """Visible when any member Audience covers the ctx (empty: hidden)."""

    audiences: tuple[Audience, ...] = ()

    def __init__(self, audiences: Iterable[Audience] = ()) -> None:
        object.__setattr__(self, "audiences", tuple(audiences))
        for a in self.audiences:
            if not isinstance(a, Audience):
                raise TypeError(f"AnyOf: expected Audiences, got {a!r}")


_RANK = {AudienceLevel.PUBLIC: 0, AudienceLevel.MEMBERS: 1, AudienceLevel.OWNER: 2, AudienceLevel.GM: 3}


def ctx_audience(role: str, user_id: uuid.UUID | None) -> Audience:
    """The narrowest Audience a request ctx with `role` (and `user_id`) may
    read. The member preview's Members Audience is built only by
    `audience_ctx`, not here."""
    if role == GM:
        return GM_AUDIENCE
    if role == PLAYER:
        if user_id is None:
            raise ValueError("ctx_audience: a Player ctx needs a user_id")
        return owner(user_id)
    if role == ANON:
        return PUBLIC
    raise ValueError(f"ctx_audience: unknown role {role!r}")


# ── Order ──────────────────────────────────────────────────────────────────

def covers(row: Audience, viewer: Audience) -> bool:
    """`row ⊒ viewer`: a viewer whose ctx Audience is `viewer` may read a row
    whose Audience is `row`."""
    if row.level is AudienceLevel.OWNER and viewer.level is AudienceLevel.OWNER:
        return row.user_id == viewer.user_id
    return _RANK[row.level] <= _RANK[viewer.level]


def _meet(a: Audience, b: Audience) -> Audience:
    if a.level is AudienceLevel.OWNER and b.level is AudienceLevel.OWNER and a.user_id != b.user_id:
        return GM_AUDIENCE
    return a if _RANK[a.level] >= _RANK[b.level] else b


def most_restrictive(*audiences: Audience | Iterable[Audience]) -> Audience:
    """The meet of the given Audiences (varargs, or one iterable). At least
    one is required: "no sources" is a caller decision (derived rows → GM)."""
    flat: list[Audience] = []
    for a in audiences:
        if isinstance(a, Audience):
            flat.append(a)
        else:
            flat.extend(a)
    if not flat:
        raise ValueError("most_restrictive: needs at least one Audience")
    out = flat[0]
    for a in flat[1:]:
        if not isinstance(a, Audience):
            raise TypeError(f"most_restrictive: expected Audiences, got {a!r}")
        out = _meet(out, a)
    return out


def visible_to(audience: Audience | AnyOf, ctx: Any) -> bool:
    """True when a row of `audience` is readable by `ctx` (a CampaignContext,
    or a bare ctx Audience)."""
    viewer = ctx if isinstance(ctx, Audience) else ctx.audience
    if isinstance(audience, AnyOf):
        return any(covers(a, viewer) for a in audience.audiences)
    return covers(audience, viewer)


# ── Stored values → Audiences ──────────────────────────────────────────────

def stored_audience(visibility: Visibility | str, owner_id: uuid.UUID | None,
                    kind: EntryKind | str | None = None) -> Audience:
    """AD-12: party + kind gm (or no kind) → Public, party + kind player →
    Members, private → Owner(owner_id), gm → GM. A private row with no owner
    is GM (nobody's)."""
    vis = Visibility(visibility)
    if vis is Visibility.PARTY:
        if kind is None or EntryKind(kind) is EntryKind.GM:
            return PUBLIC
        return MEMBERS
    if vis is Visibility.PRIVATE:
        return owner(owner_id) if owner_id is not None else GM_AUDIENCE
    return GM_AUDIENCE


# Fields that are GM-only wherever they appear: a value derived from one (a
# tag or Mention found in the Shorthand) is GM. `gm_notes` (entities,
# E0-WorldCore) and `npc_settings.voice_notes` (E3) are declared here so
# their owners do not invent a second rule.
ALWAYS_GM_FIELDS: frozenset[str] = frozenset({"shorthand", "gm_notes", "voice_notes"})


def field_audience(source_field: str | None) -> Audience:
    """The Audience a value inherits from the field it came from: GM for an
    always-GM field, else Public (no narrowing). NULL is no narrowing."""
    if source_field is None:
        return PUBLIC
    return GM_AUDIENCE if str(source_field) in ALWAYS_GM_FIELDS else PUBLIC


def mention_audience(entry: Audience, entity: Audience, source_field: str | None,
                     visibility_floor: Audience | None = None) -> Audience:
    """AD-12 Mention formula, ready for E0-WorldCore's `entity_mentions`:

        aud(mention) = most_restrictive(entry, entity, field_aud(source_field), visibility_floor)
    """
    return most_restrictive(entry, entity, field_audience(source_field), visibility_floor or PUBLIC)
