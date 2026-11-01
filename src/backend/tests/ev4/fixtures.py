"""Canary seeding and the EV-4 actors.

``seeds/ev4_canary.json`` is loaded into a fresh Campaign per test, with
every ``{canary:KIND}`` placeholder replaced by a unique token
``CANARY-<KIND>-<uuid4>``. The registry ``CANARIES`` maps each token to its
Campaign; a token in a response is a leak unless the actor is a GM of that
Campaign (``Actor.may_see``). Rows are committed (the app reads them through
its own session), so tokens are unique per seeding and never reused.

Actors (``await ev4.actor(name)``):
  gm_owner         owns Campaign A
  anon_share       no auth; a read-only share token for A
  anonymous        no auth, no token
  player           Player in A                       (needs roles)
  player_2         a second Player in A              (needs roles)
  co_gm            role gm (co-GM) in A              (needs roles)
  cross_gm_player  owns Campaign B (same seed, own tokens), Player in A (needs roles)

The role-dependent actors resolve lazily through ``make_member``, which
skips the test with "roles not yet available" until E0-Access adds
``campaign_members.role``; only cases that need them skip.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ev4 import repo_root

GM, PLAYER, ANON = "gm", "player", "anon"

_PLACEHOLDER_RE = re.compile(r"\{canary:([^{}]*)\}")
_KIND_RE = re.compile(r"[A-Z0-9]+")
_UUID4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
# Case-insensitive, so an upper- or lower-cased echo of a token still counts.
CANARY_RE = re.compile(rf"CANARY-([A-Z0-9]+)-({_UUID4})", re.IGNORECASE)

SEED_KEYS = {
    "_doc", "campaign", "journal_entries", "npcs", "quests", "shorthand_terms", "session_plans",
    "chat_sessions", "source_documents", "character_sheet_templates",
}


def seed_path() -> Path:
    path = repo_root() / "seeds" / "ev4_canary.json"
    if not path.is_file():
        raise RuntimeError(f"EV-4: the canary seed {path} is missing")
    return path


@lru_cache(maxsize=1)
def _seed_text() -> str:
    return seed_path().read_text()


def load_seed() -> dict:
    data = json.loads(_seed_text())
    unknown = set(data) - SEED_KEYS
    if unknown:
        raise ValueError(f"seeds/ev4_canary.json: unknown top-level keys {sorted(unknown)} "
                         "(teach tests/ev4/fixtures.py to seed them)")
    data.pop("_doc", None)  # documentation only; it quotes the placeholder syntax
    return data


# ── Canaries ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Canary:
    token: str
    kind: str
    campaign_id: uuid.UUID


CANARIES: dict[str, Canary] = {}


def normalize_token(kind: str, uid: str) -> str:
    return f"CANARY-{kind.upper()}-{uid.lower()}"


def mint_canary(kind: str, campaign_id: uuid.UUID) -> Canary:
    if not _KIND_RE.fullmatch(kind):
        raise ValueError(f"canary kind {kind!r} must match [A-Z0-9]+")
    canary = Canary(normalize_token(kind, str(uuid.uuid4())), kind, campaign_id)
    CANARIES[canary.token] = canary
    return canary


def find_canaries(text: str) -> list[str]:
    """Every canary-shaped token in ``text``, normalized, in order."""
    return [normalize_token(m.group(1), m.group(2)) for m in CANARY_RE.finditer(text)]


def render_seed(data: Any, campaign_id: uuid.UUID, minted: list[Canary]) -> Any:
    """``data`` with every placeholder replaced by a fresh token for ``campaign_id``."""
    if isinstance(data, str):
        def sub(m: re.Match) -> str:
            canary = mint_canary(m.group(1), campaign_id)
            minted.append(canary)
            return canary.token
        out = _PLACEHOLDER_RE.sub(sub, data)
        if "{canary:" in out:
            raise ValueError(f"malformed canary placeholder in seed text {data!r}")
        return out
    if isinstance(data, list):
        return [render_seed(v, campaign_id, minted) for v in data]
    if isinstance(data, dict):
        return {k: render_seed(v, campaign_id, minted) for k, v in data.items()}
    return data


# ── Users and seeding ──────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _password_hash() -> str:
    from app.core.security import hash_password
    return hash_password("ev4-password-not-used")


async def create_user(db: AsyncSession, label: str):
    """A committed User with access_granted (no /register call, so the
    5/minute register limit never applies)."""
    from app.db.models.user import User

    user = User(
        email=f"ev4-{label.replace('_', '-')}-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password=_password_hash(),
        display_name=f"EV4 {label}",
        access_granted=True,
        access_source="promo",
    )
    db.add(user)
    await db.commit()
    return user


# The keys seed_canary_campaign maps for each record type. A key outside
# these would be dropped silently (and a canary in it minted but never
# stored), so validate_seed rejects it.
SEED_FIELDS: dict[str, set[str]] = {
    "campaign": {"name", "genre", "description"},
    "journal_entries": {"narrative", "shorthand", "session_date"},
    "npcs": {"name", "role", "status", "description", "notes"},
    "quests": {"title", "description", "status", "notes"},
    "shorthand_terms": {"term", "meaning", "usage"},
    "session_plans": {"title", "content"},
    "chat_sessions": {"title", "messages"},
    "source_documents": {"title", "filename", "chunks"},
    "source_documents.chunks": {"content"},
    "character_sheet_templates": {"name", "fields", "sheets"},
    "character_sheet_templates.sheets": {"name", "data"},
}


def validate_seed(data: dict) -> None:
    """ValueError naming any key the seeder would not store."""
    def check(record_type: str, row: Any) -> None:
        if not isinstance(row, dict):
            raise ValueError(f"seed {record_type}: expected an object, got {row!r}")
        unknown = set(row) - SEED_FIELDS[record_type]
        if unknown:
            raise ValueError(f"seed {record_type}: unknown keys {sorted(unknown)} (tests/ev4/fixtures.py "
                             f"maps only {sorted(SEED_FIELDS[record_type])})")

    unknown_top = set(data) - SEED_KEYS
    if unknown_top:
        raise ValueError(f"seed: unknown top-level keys {sorted(unknown_top)}")
    check("campaign", data["campaign"])
    for record_type in SEED_FIELDS:
        if record_type == "campaign" or "." in record_type:
            continue
        for row in data.get(record_type, []):
            check(record_type, row)
            for child_key in ("chunks", "sheets"):
                child_type = f"{record_type}.{child_key}"
                if child_type in SEED_FIELDS:
                    for child in row.get(child_key, []):
                        check(child_type, child)


@dataclass
class SeededCampaign:
    campaign_id: uuid.UUID
    owner_id: uuid.UUID
    share_token: str
    canaries: list[Canary]
    ids: dict[str, list[uuid.UUID]] = field(default_factory=dict)

    def canary(self, kind: str) -> Canary:
        for c in self.canaries:
            if c.kind == kind:
                return c
        raise KeyError(f"no {kind} canary in campaign {self.campaign_id}")

    @property
    def tokens(self) -> set[str]:
        return {c.token for c in self.canaries}


async def seed_canary_campaign(db: AsyncSession, owner, seed: dict | None = None) -> SeededCampaign:
    """Insert the canary seed as a new Campaign owned by ``owner`` (committed)."""
    from app.db.models.campaign import Campaign, Genre
    from app.db.models.character_sheet import CharacterSheet, CharacterSheetTemplate
    from app.db.models.chat import ChatSession
    from app.db.models.journal import JournalEntry
    from app.db.models.npc import NpcEntry, NpcRole, NpcStatus
    from app.db.models.quest import Quest, QuestStatus
    from app.db.models.session_plan import SessionPlan
    from app.db.models.share_token import CampaignShareToken
    from app.db.models.shorthand import ShorthandTerm
    from app.db.models.source import SourceChunk, SourceDocument

    campaign_id = uuid.uuid4()
    minted: list[Canary] = []
    raw = seed if seed is not None else load_seed()
    validate_seed(raw)
    raw = {k: v for k, v in raw.items() if k != "_doc"}
    data = render_seed(raw, campaign_id, minted)
    ids: dict[str, list[uuid.UUID]] = {}

    def add(kind: str, row) -> None:
        row.id = row.id or uuid.uuid4()
        db.add(row)
        ids.setdefault(kind, []).append(row.id)

    c = data["campaign"]
    db.add(Campaign(id=campaign_id, user_id=owner.id, name=c["name"], genre=Genre(c.get("genre", "fantasy")),
                    description=c.get("description")))
    await db.flush()

    for e in data.get("journal_entries", []):
        add("journal_entries", JournalEntry(
            id=uuid.uuid4(), user_id=owner.id, campaign_id=campaign_id, shorthand=e["shorthand"],
            narrative=e["narrative"], entry_hash=uuid.uuid4().hex,
            session_date=date.fromisoformat(e["session_date"]) if e.get("session_date") else None,
        ))
    for n in data.get("npcs", []):
        add("npcs", NpcEntry(
            id=uuid.uuid4(), user_id=owner.id, campaign_id=campaign_id, name=n["name"],
            role=NpcRole(n.get("role", "npc")), status=NpcStatus(n.get("status", "unknown")),
            description=n.get("description"), notes=n.get("notes"),
        ))
    for q in data.get("quests", []):
        add("quests", Quest(
            id=uuid.uuid4(), user_id=owner.id, campaign_id=campaign_id, title=q["title"],
            description=q.get("description"), status=QuestStatus(q.get("status", "active")), notes=q.get("notes"),
        ))
    for t in data.get("shorthand_terms", []):
        add("shorthand_terms", ShorthandTerm(
            id=uuid.uuid4(), user_id=owner.id, campaign_id=campaign_id, term=t["term"], meaning=t["meaning"],
            usage=t.get("usage"),
        ))
    for p in data.get("session_plans", []):
        add("session_plans", SessionPlan(
            id=uuid.uuid4(), user_id=owner.id, campaign_id=campaign_id, title=p["title"], content=p["content"],
        ))
    for s in data.get("chat_sessions", []):
        add("chat_sessions", ChatSession(
            id=uuid.uuid4(), user_id=owner.id, campaign_id=campaign_id, title=s["title"],
            messages=s.get("messages", []), message_count=len(s.get("messages", [])),
        ))
    for d in data.get("source_documents", []):
        doc_id = uuid.uuid4()
        add("source_documents", SourceDocument(
            id=doc_id, user_id=owner.id, campaign_id=campaign_id, title=d["title"], filename=d["filename"],
        ))
        await db.flush()
        for i, ch in enumerate(d.get("chunks", [])):
            add("source_chunks", SourceChunk(
                id=uuid.uuid4(), source_document_id=doc_id, user_id=owner.id, campaign_id=campaign_id,
                chunk_index=i, content=ch["content"],
            ))
    for tpl in data.get("character_sheet_templates", []):
        tpl_id = uuid.uuid4()
        add("character_sheet_templates", CharacterSheetTemplate(
            id=tpl_id, campaign_id=campaign_id, created_by_user_id=owner.id, name=tpl["name"],
            fields=tpl.get("fields", []),
        ))
        await db.flush()
        for sh in tpl.get("sheets", []):
            add("character_sheets", CharacterSheet(
                id=uuid.uuid4(), campaign_id=campaign_id, template_id=tpl_id, created_by_user_id=owner.id,
                name=sh["name"], data=sh.get("data", {}),
            ))

    share_token = secrets.token_urlsafe(24)
    db.add(CampaignShareToken(campaign_id=campaign_id, created_by_user_id=owner.id, token=share_token,
                              kind="read_only"))
    await db.commit()
    return SeededCampaign(campaign_id, owner.id, share_token, minted, ids)


# ── Roles ──────────────────────────────────────────────────────────────────

# Spine AD-12: campaign_members.role in {co_gm, player}; the actor model
# calls the co-GM grant "gm". The first label the DB enum actually has wins.
_ROLE_LABELS = {"player": ("player",), "gm": ("co_gm", "gm"), "co_gm": ("co_gm", "gm")}


async def _role_column(db: AsyncSession) -> tuple[str, str] | None:
    row = (await db.execute(sa.text(
        "SELECT data_type, udt_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'campaign_members' AND column_name = 'role'"
    ))).first()
    return None if row is None else (row[0], row[1])


async def roles_available(db: AsyncSession) -> bool:
    return await _role_column(db) is not None


async def _role_value(db: AsyncSession, role: str) -> str:
    if role not in _ROLE_LABELS:
        raise ValueError(f"make_member: unknown role {role!r} (use one of {sorted(_ROLE_LABELS)})")
    column = await _role_column(db)
    candidates = _ROLE_LABELS[role]
    if column and column[0] == "USER-DEFINED":
        labels = set((await db.execute(sa.text(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = :t"
        ), {"t": column[1]})).scalars())
        for label in candidates:
            if label in labels:
                return label
        raise ValueError(f"make_member: enum {column[1]} has none of {candidates} (labels: {sorted(labels)})")
    return candidates[0]


async def make_member(db: AsyncSession, *, role: str = "player", campaign_id: uuid.UUID, user=None,
                      label: str | None = None):
    """Add ``user`` (a new committed User when None) to ``campaign_id`` as a
    CampaignMember with ``role`` ("player", or "gm"/"co_gm" for a co-GM).
    Skips the test with "roles not yet available" until
    ``campaign_members.role`` exists. Returns the user."""
    if not await roles_available(db):
        pytest.skip("roles not yet available")
    value = await _role_value(db, role)
    user = user or await create_user(db, label or role)
    await db.execute(sa.text(
        "INSERT INTO campaign_members (id, campaign_id, user_id, role, created_at, updated_at) "
        "VALUES (:id, :c, :u, :r, now(), now())"
    ), {"id": uuid.uuid4(), "c": campaign_id, "u": user.id, "r": value})
    await db.commit()
    return user


# ── Actors ─────────────────────────────────────────────────────────────────

@dataclass
class Actor:
    name: str
    client: AsyncClient
    headers: dict[str, str] = field(default_factory=dict)
    user_id: uuid.UUID | None = None
    share_token: str | None = None
    grants: dict[uuid.UUID, str] = field(default_factory=dict)

    def may_see(self, canary: Canary | str) -> bool:
        """True only when the actor is a GM of the canary's Campaign."""
        if isinstance(canary, str):
            canary = CANARIES.get(canary)
            if canary is None:
                return False
        return self.grants.get(canary.campaign_id) == GM

    async def request(self, method: str, url: str, **kwargs):
        headers = {**self.headers, **(kwargs.pop("headers", None) or {})}
        return await self.client.request(method, url, headers=headers, **kwargs)

    async def get(self, url: str, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs):
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs):
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs):
        return await self.request("DELETE", url, **kwargs)


def bearer(user) -> dict[str, str]:
    from app.core.security import create_access_token
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


ACTOR_NAMES = ("gm_owner", "anon_share", "anonymous", "player", "player_2", "co_gm", "cross_gm_player")


class EV4:
    """Per-test EV-4 context: Campaign A seeded, actors on demand."""

    def __init__(self, client: AsyncClient, db: AsyncSession):
        self.client = client
        self.db = db
        self.a: SeededCampaign | None = None
        self.b: SeededCampaign | None = None
        self._actors: dict[str, Actor] = {}

    async def setup(self) -> "EV4":
        owner = await create_user(self.db, "gm_owner")
        self.a = await seed_canary_campaign(self.db, owner)
        a = self.a.campaign_id
        self._actors["gm_owner"] = Actor("gm_owner", self.client, bearer(owner), owner.id, None, {a: GM})
        self._actors["anon_share"] = Actor("anon_share", self.client, {}, None, self.a.share_token, {a: ANON})
        self._actors["anonymous"] = Actor("anonymous", self.client, {}, None, None, {})
        return self

    @property
    def canaries(self) -> list[Canary]:
        return list(self.a.canaries) + (list(self.b.canaries) if self.b else [])

    async def require_roles(self) -> None:
        if not await roles_available(self.db):
            pytest.skip("roles not yet available")

    async def make_member(self, role: str = "player", campaign_id: uuid.UUID | None = None, user=None,
                          label: str | None = None):
        """Add a CampaignMember with ``role`` (Campaign A by default); skips
        while roles do not exist. See the module-level make_member."""
        return await make_member(self.db, role=role, campaign_id=campaign_id or self.a.campaign_id,
                                 user=user, label=label)

    async def actor(self, name: str) -> Actor:
        if name in self._actors:
            return self._actors[name]
        a = self.a.campaign_id
        if name in ("player", "player_2"):
            user = await self.make_member("player", label=name)
            actor = Actor(name, self.client, bearer(user), user.id, None, {a: PLAYER})
        elif name == "co_gm":
            user = await self.make_member("gm", label=name)
            actor = Actor(name, self.client, bearer(user), user.id, None, {a: GM})
        elif name == "cross_gm_player":
            await self.require_roles()
            user = await create_user(self.db, name)
            await self.make_member("player", user=user)
            self.b = await seed_canary_campaign(self.db, user)
            actor = Actor(name, self.client, bearer(user), user.id, None,
                          {a: PLAYER, self.b.campaign_id: GM})
        else:
            raise KeyError(f"unknown EV-4 actor {name!r}; actors are {', '.join(ACTOR_NAMES)}")
        self._actors[name] = actor
        return actor


@pytest_asyncio.fixture
async def ev4(client, db) -> EV4:
    return await EV4(client, db).setup()
