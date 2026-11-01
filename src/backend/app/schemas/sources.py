"""Citation vocabulary shared by retrieval and the Chronicler (AD-13, NFR-7).

Append-only: later stories add members and models here, never rename or
remove them. E0-Access.7 ships `SourceKind` (the keys of
`retrieval_service.register_source`); E0-Access.8 adds `SourceRef`,
`ResolvedSource` and `grounded`.
"""
from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SourceKind(StrEnum):
    """What a cited or retrieved source is."""

    JOURNAL = "journal"                # a GM-kind journal entry (Narrative)
    PLAYER_JOURNAL = "player_journal"  # a Player-kind journal entry
    CANON_NOTE = "canon_note"          # E2.1
    ENTITY_FIELD = "entity_field"      # E0-WorldCore.5
    LIVE_SEGMENT = "live_segment"      # E4.2
    RECAP = "recap"


# ── Citations (E0-Access.8) ────────────────────────────────────────────────

class SourceRef(BaseModel):
    """A pointer to what an AI answer drew on: the row (`kind`, `id`) and,
    optionally, one field of it and a character span in that field.

    `field=None` means the whole record, GM fields included, so a non-GM ctx
    may see a `field=None` ref only for a model with no GM fields. Stored in
    `chat_sessions.messages[*].refs` (never with titles or quotes) and turned
    into a `ResolvedSource` only by `access.resolve_sources`."""

    model_config = ConfigDict(frozen=True)

    kind: SourceKind
    id: uuid.UUID
    field: str | None = None
    span: tuple[int, int] | None = None


class ResolvedSource(BaseModel):
    """A citation as a response carries it. Built only by
    `access.resolve_sources`, after its visibility check."""

    ref: SourceRef
    title: str
    quote: str


class Grounded(BaseModel):
    """The response flag: False when the answer is not from the campaign
    record (nothing relevant was retrieved), so the UI labels it "Not from
    your journal"."""

    grounded: bool = True
