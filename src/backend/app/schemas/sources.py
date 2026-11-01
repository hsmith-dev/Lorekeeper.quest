"""Citation vocabulary shared by retrieval and the Chronicler (AD-13, NFR-7).

Append-only: later stories add members and models here, never rename or
remove them. E0-Access.7 ships `SourceKind` (the keys of
`retrieval_service.register_source`); E0-Access.8 adds `SourceRef`,
`ResolvedSource` and `grounded`.
"""
from __future__ import annotations

from enum import StrEnum


class SourceKind(StrEnum):
    """What a cited or retrieved source is."""

    JOURNAL = "journal"                # a GM-kind journal entry (Narrative)
    PLAYER_JOURNAL = "player_journal"  # a Player-kind journal entry
    CANON_NOTE = "canon_note"          # E2.1
    ENTITY_FIELD = "entity_field"      # E0-WorldCore.5
    LIVE_SEGMENT = "live_segment"      # E4.2
    RECAP = "recap"
