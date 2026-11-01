"""Audiences (AD-12), minimal form for E0-Access.2.

The Audiences are `Public ⊃ Members ⊃ Owner(u) ⊃ GM`. A ctx carries the
narrowest Audience its viewer can read: a GM reads down to GM, a Player down
to Owner(themself), an anonymous Share Link viewer only Public.

E0-Access.3 extends this module (stored-value mapping, `most_restrictive`,
`visible_to`, `audience_ctx`); the names here stay.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.access.policy import ANON, GM, PLAYER


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


PUBLIC = Audience(AudienceLevel.PUBLIC)
MEMBERS = Audience(AudienceLevel.MEMBERS)
GM_AUDIENCE = Audience(AudienceLevel.GM)


def owner(user_id: uuid.UUID) -> Audience:
    return Audience(AudienceLevel.OWNER, user_id)


def ctx_audience(role: str, user_id: uuid.UUID | None) -> Audience:
    """The narrowest Audience a ctx with `role` (and `user_id`) may read."""
    if role == GM:
        return GM_AUDIENCE
    if role == PLAYER:
        if user_id is None:
            raise ValueError("ctx_audience: a Player ctx needs a user_id")
        return owner(user_id)
    if role == ANON:
        return PUBLIC
    raise ValueError(f"ctx_audience: unknown role {role!r}")
