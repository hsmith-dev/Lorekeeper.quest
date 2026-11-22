"""The legacy NPC/Quest vocabulary and the World Model's (E0-WorldCore.6).

Pure data shared by the legacy route adapters (app/api/routes/_legacy_world.py),
the resync job (app/jobs/legacy_resync.py) and the demo seeder. The write
direction (legacy -> World) is exactly the F3-world copy's
(migrations/versions/03c0b504f1d1): role npc/pc/monster -> Character kind
npc/pc/creature, role faction -> a Faction; NPC status alive/dead/unknown ->
Character alive/deceased/unknown, Faction active/disbanded/unknown; a Quest
keeps its status. The read direction (World -> legacy view) maps every World
value onto the legacy enums: Character missing/unknown -> unknown, a
Location or Item never appears as an NPC.
"""
from __future__ import annotations

import hashlib
import uuid

NAMESPACE = "f3-world"  # the F3-world copy's id namespace

CHARACTER, FACTION, QUEST = "character", "faction", "quest"
NPC_TYPES = frozenset({CHARACTER, FACTION})
QUEST_TYPES = frozenset({QUEST})

# legacy role -> Character kind (faction is a type, not a kind)
ROLE_TO_KIND = {"npc": "npc", "pc": "pc", "monster": "creature"}
KIND_TO_ROLE = {"npc": "npc", "pc": "pc", "creature": "monster"}

CHARACTER_STATUS_IN = {"alive": "alive", "dead": "deceased", "unknown": "unknown"}
FACTION_STATUS_IN = {"alive": "active", "dead": "disbanded", "unknown": "unknown"}
CHARACTER_STATUS_OUT = {"alive": "alive", "deceased": "dead", "missing": "unknown", "unknown": "unknown"}
FACTION_STATUS_OUT = {"active": "alive", "disbanded": "dead", "unknown": "unknown"}

QUEST_STATUSES = ("active", "completed", "failed", "abandoned")  # also the GM list order


def legacy_entity_id(kind: str, legacy_id: uuid.UUID | str) -> uuid.UUID:
    """The F3-world copy's id of a legacy row: md5('f3-world:<kind>:' || id)::uuid."""
    if kind not in ("npc", "quest"):
        raise ValueError(f"legacy_entity_id: kind must be npc or quest, got {kind!r}")
    return uuid.UUID(hashlib.md5(f"{NAMESPACE}:{kind}:{legacy_id}".encode()).hexdigest())


def npc_type(role: str) -> str:
    """The Entity type a legacy role becomes."""
    return FACTION if role == "faction" else CHARACTER


def npc_kind(role: str) -> str | None:
    """The Character kind of a legacy role (None for a faction; an unknown role is npc, as F3)."""
    return None if role == "faction" else ROLE_TO_KIND.get(role, "npc")


def npc_status_in(entity_type: str, status: str) -> str:
    """A legacy NPC status as the World status of `entity_type` (unmappable: unknown, as F3)."""
    table = FACTION_STATUS_IN if entity_type == FACTION else CHARACTER_STATUS_IN
    return table.get(status, "unknown")


def npc_status_out(entity_type: str, status: str) -> str:
    """A World Character/Faction status as the legacy NPC status."""
    table = FACTION_STATUS_OUT if entity_type == FACTION else CHARACTER_STATUS_OUT
    return table.get(status, "unknown")


def npc_role_out(entity_type: str, kind: str | None) -> str:
    """The legacy role of a Character (by kind) or a Faction."""
    if entity_type == FACTION:
        return "faction"
    return KIND_TO_ROLE.get(kind or "npc", "npc")


def quest_status_in(status: str) -> str:
    return status if status in QUEST_STATUSES else "active"


def quest_status_out(status: str) -> str:
    return status if status in QUEST_STATUSES else "active"


def quest_status_rank(status: str) -> int:
    return QUEST_STATUSES.index(status) if status in QUEST_STATUSES else len(QUEST_STATUSES)
