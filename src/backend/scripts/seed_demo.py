#!/usr/bin/env python
"""Seed the demo Campaign from seeds/demo_campaign.json.

Writes one owner (if missing), the Campaign, its 12 journal entries, NPCs,
factions and quests through the ORM. Idempotent: a second run creates
nothing and prints the same Campaign id. The only update it ever makes is
filling an entry's NULL embedding once the embedding model is available.

Offline (NFR-1): it talks to nothing but --database-url. No Redis, no spaCy,
no LLM. The embedding model is loaded from the local Hugging Face cache only
(HF_HUB_OFFLINE=1, local_files_only=True):

  --embeddings auto     (default) embed if the model is cached, otherwise
                        leave `embedding` NULL and warn
  --embeddings require  exit 1 if the model is not cached
  --embeddings skip     never load the model

Run inside the backend container (the repo's seeds/ is not in the image, so
copy the file in first):

  docker compose -f docker-compose.prod.yml cp seeds/demo_campaign.json backend:/tmp/demo_campaign.json
  docker compose -f docker-compose.prod.yml exec backend \\
      python scripts/seed_demo.py --seed /tmp/demo_campaign.json --owner-email you@example.com

From a checkout (src/backend/), --seed defaults to ../../seeds/demo_campaign.json.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Before anything imports huggingface_hub (it reads these at import time).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

import app.db.models  # noqa: E402,F401  (registers every mapper)
from app.db.models.campaign import Campaign, Genre  # noqa: E402
from app.db.models.journal import EMBEDDING_DIM, JournalEntry  # noqa: E402
from app.db.models.npc import NpcEntry, NpcRole, NpcStatus  # noqa: E402
from app.db.models.quest import Quest, QuestStatus  # noqa: E402
from app.db.models.user import User  # noqa: E402

EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # same as app/services/embedding_service.py
FORMAT_VERSION = 1
EMBEDDING_MODES = ("auto", "require", "skip")


def _default_seed_path() -> Path:
    # src/backend/scripts/seed_demo.py -> repo root. In the container the
    # tree is shallower, so fall back to /app/seeds (pass --seed there).
    try:
        root = Path(__file__).resolve().parents[3]
    except IndexError:
        root = None
    if root is not None and (root / "seeds").is_dir():
        return root / "seeds" / "demo_campaign.json"
    return _BACKEND_DIR / "seeds" / "demo_campaign.json"


DEFAULT_SEED_PATH = _default_seed_path()


class SeedError(Exception):
    """The seed file is malformed, or a required resource is missing."""


Embedder = Callable[[str], list[float]]


# ── Reading and validating ──────────────────────────────────────────────────

_ENTRY_FIELDS = ("seed_id", "session_number", "session_date", "shorthand", "narrative", "purpose")
_NPC_FIELDS = ("seed_id", "name", "role", "status_history")
_QUEST_FIELDS = ("seed_id", "title", "status")
_SECRET_FIELDS = ("seed_id", "phrase", "where")
# Fields that never reach a share viewer (app/schemas/share.py Public*).
GM_ONLY_FIELDS = {"entry": {"shorthand"}, "npc": {"notes"}, "quest": {"notes"}}


def read_seed(path: str | os.PathLike) -> dict:
    """Load and validate a seed file. Raises SeedError."""
    p = Path(path)
    try:
        seed = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SeedError(f"seed file not found: {p}") from None
    except json.JSONDecodeError as exc:
        raise SeedError(f"seed file {p} is not valid JSON: {exc}") from None
    validate_seed(seed)
    return seed


def _require(obj: dict, fields: tuple[str, ...], where: str) -> None:
    if not isinstance(obj, dict):
        raise SeedError(f"{where}: expected an object")
    for f in fields:
        if f not in obj or obj[f] in (None, ""):
            raise SeedError(f"{where}: missing field {f!r}")


def public_texts(seed: dict) -> list[str]:
    """Every seed string a share viewer could see."""
    out = [seed["campaign"].get("name") or "", seed["campaign"].get("description") or ""]
    out += [e["narrative"] for e in seed["entries"]]
    out += [n["name"] for n in seed["npcs"]] + [n.get("description") or "" for n in seed["npcs"]]
    out += [q["title"] for q in seed["quests"]] + [q.get("description") or "" for q in seed["quests"]]
    return out


def validate_seed(seed: dict) -> None:
    """Check shape and invariants before anything touches the DB."""
    if not isinstance(seed, dict):
        raise SeedError("seed: expected a JSON object")
    if seed.get("format_version") != FORMAT_VERSION:
        raise SeedError(f"seed: format_version must be {FORMAT_VERSION}, got {seed.get('format_version')!r}")
    for key in ("campaign", "owner", "entries", "npcs", "quests", "locations", "gm_secrets"):
        if key not in seed:
            raise SeedError(f"seed: missing field {key!r}")
    _require(seed["campaign"], ("name", "genre"), "campaign")
    try:
        Genre(seed["campaign"]["genre"])
    except ValueError:
        raise SeedError(f"campaign: unknown genre {seed['campaign']['genre']!r}") from None
    _require(seed["owner"], ("email", "display_name"), "owner")

    seen: dict[str, str] = {}

    def claim(seed_id: str, where: str) -> None:
        if seed_id in seen:
            raise SeedError(f"{where}: duplicate seed_id {seed_id!r} (also used by {seen[seed_id]})")
        seen[seed_id] = where

    by_kind: dict[str, dict[str, dict]] = {"entry": {}, "npc": {}, "quest": {}}

    for i, e in enumerate(seed["entries"]):
        where = f"entries[{i}]"
        _require(e, _ENTRY_FIELDS, where)
        claim(e["seed_id"], where)
        try:
            date.fromisoformat(e["session_date"])
        except (TypeError, ValueError):
            raise SeedError(f"{where}: session_date {e['session_date']!r} is not YYYY-MM-DD") from None
        if not isinstance(e["session_number"], int):
            raise SeedError(f"{where}: session_number must be an integer")
        by_kind["entry"][e["seed_id"]] = e

    names: set[str] = set()
    for i, n in enumerate(seed["npcs"]):
        where = f"npcs[{i}]"
        _require(n, _NPC_FIELDS, where)
        claim(n["seed_id"], where)
        if n["name"] in names:
            raise SeedError(f"{where}: duplicate NPC name {n['name']!r}")
        names.add(n["name"])
        try:
            NpcRole(n["role"])
        except ValueError:
            raise SeedError(f"{where}: unknown role {n['role']!r}") from None
        if not isinstance(n["status_history"], list) or not n["status_history"]:
            raise SeedError(f"{where}: status_history must be a non-empty list")
        for h in n["status_history"]:
            _require(h, ("session", "status"), f"{where}.status_history")
            try:
                NpcStatus(h["status"])
            except ValueError:
                raise SeedError(f"{where}: unknown status {h['status']!r}") from None
        by_kind["npc"][n["seed_id"]] = n

    titles: set[str] = set()
    for i, q in enumerate(seed["quests"]):
        where = f"quests[{i}]"
        _require(q, _QUEST_FIELDS, where)
        claim(q["seed_id"], where)
        if q["title"] in titles:
            raise SeedError(f"{where}: duplicate quest title {q['title']!r}")
        titles.add(q["title"])
        try:
            QuestStatus(q["status"])
        except ValueError:
            raise SeedError(f"{where}: unknown status {q['status']!r}") from None
        by_kind["quest"][q["seed_id"]] = q

    for i, loc in enumerate(seed["locations"]):
        _require(loc, ("seed_id", "name"), f"locations[{i}]")
        claim(loc["seed_id"], f"locations[{i}]")

    public = public_texts(seed)
    phrases: set[str] = set()
    for i, s in enumerate(seed["gm_secrets"]):
        where = f"gm_secrets[{i}]"
        _require(s, _SECRET_FIELDS, where)
        claim(s["seed_id"], where)
        _require(s["where"], ("kind", "seed_id", "field"), f"{where}.where")
        kind, ref, fld = s["where"]["kind"], s["where"]["seed_id"], s["where"]["field"]
        if fld not in GM_ONLY_FIELDS.get(kind, set()):
            raise SeedError(f"{where}: {kind}.{fld} is not a GM-only field")
        target = by_kind[kind].get(ref)
        if target is None:
            raise SeedError(f"{where}: no {kind} with seed_id {ref!r}")
        phrase = s["phrase"]
        if phrase in phrases:
            raise SeedError(f"{where}: duplicate phrase {phrase!r}")
        phrases.add(phrase)
        if phrase not in (target.get(fld) or ""):
            raise SeedError(f"{where}: phrase {phrase!r} not found in {kind} {ref!r} {fld}")
        if any(phrase.lower() in t.lower() for t in public):
            raise SeedError(f"{where}: phrase {phrase!r} also appears in a public field")


# ── Embeddings ──────────────────────────────────────────────────────────────

def load_embedding_model(mode: str = "auto"):
    """The SentenceTransformer from the local cache, or None.

    auto: None (with a warning on stderr) if the model is not cached.
    require: SeedError if it is not cached. skip: None, never loads."""
    if mode not in EMBEDDING_MODES:
        raise SeedError(f"--embeddings must be one of {EMBEDDING_MODES}, got {mode!r}")
    if mode == "skip":
        return None
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
    except Exception as exc:  # not cached, or a broken cache
        msg = f"embedding model {EMBEDDING_MODEL!r} is not in the local cache ({type(exc).__name__}: {exc})"
        if mode == "require":
            raise SeedError(msg) from None
        print(f"warning: {msg}; embeddings left NULL", file=sys.stderr)
        return None


def embedder_from_model(model) -> Embedder | None:
    if model is None:
        return None
    return lambda t: model.encode(t, normalize_embeddings=True).tolist()


def load_embedder(mode: str = "auto") -> Embedder | None:
    return embedder_from_model(load_embedding_model(mode))


# ── Seeding ─────────────────────────────────────────────────────────────────

@dataclass
class SeedResult:
    campaign_id: object
    owner_id: object
    user_created: bool = False
    campaign_created: bool = False
    created: dict[str, int] = field(default_factory=lambda: {"entries": 0, "npcs": 0, "quests": 0})
    embedded: int = 0
    entry_ids: dict[str, object] = field(default_factory=dict)  # seed_id -> JournalEntry.id

    @property
    def created_total(self) -> int:
        return int(self.user_created) + int(self.campaign_created) + sum(self.created.values())

    def summary(self) -> str:
        c = self.created
        return (
            f"campaign {self.campaign_id}\n"
            f"created {self.created_total} (user {int(self.user_created)}, campaign {int(self.campaign_created)}, "
            f"entries {c['entries']}, npcs {c['npcs']}, quests {c['quests']}); embedded {self.embedded}"
        )


def entry_hash(campaign_id, seed_id: str) -> str:
    return hashlib.sha256(f"lorekeeper-seed:{campaign_id}:{seed_id}".encode()).hexdigest()


def entry_text(shorthand: str, narrative: str) -> str:
    """What the tsv and the embedding cover (journal_service, migration a3e7c1f9d258)."""
    return f"{shorthand} {narrative}"


def _unusable_password_hash() -> str:
    # A bcrypt hash of a random secret nobody knows. bcrypt directly, not
    # app.core.security, which needs SECRET_KEY at import.
    import bcrypt

    return bcrypt.hashpw(secrets.token_urlsafe(32).encode(), bcrypt.gensalt()).decode()


async def seed_campaign(
    session: AsyncSession,
    seed: dict,
    owner_email: str | None = None,
    embedder: Embedder | None = None,
) -> SeedResult:
    """Write the seed. Idempotent on seed_id; commits once at the end."""
    validate_seed(seed)
    email = (owner_email or seed["owner"]["email"]).strip().lower()

    user = await session.scalar(select(User).where(func.lower(User.email) == email))
    user_created = user is None
    if user is None:
        user = User(email=email, display_name=seed["owner"]["display_name"],
                    hashed_password=_unusable_password_hash())
        session.add(user)
        await session.flush()

    c = seed["campaign"]
    campaign = await session.scalar(
        select(Campaign).where(Campaign.user_id == user.id, Campaign.name == c["name"])
    )
    campaign_created = campaign is None
    if campaign is None:
        campaign = Campaign(user_id=user.id, name=c["name"], genre=Genre(c["genre"]),
                            description=c.get("description"))
        session.add(campaign)
        await session.flush()

    result = SeedResult(campaign_id=campaign.id, owner_id=user.id,
                        user_created=user_created, campaign_created=campaign_created)

    for e in seed["entries"]:
        h = entry_hash(campaign.id, e["seed_id"])
        doc = entry_text(e["shorthand"], e["narrative"])
        entry = await session.scalar(select(JournalEntry).where(JournalEntry.entry_hash == h))
        if entry is None:
            entry = JournalEntry(
                user_id=user.id, campaign_id=campaign.id,
                shorthand=e["shorthand"], narrative=e["narrative"], entry_hash=h,
                session_date=date.fromisoformat(e["session_date"]),
            )
            if embedder is not None:
                entry.embedding = _checked(embedder(doc))
                result.embedded += 1
            session.add(entry)
            await session.flush()
            await session.execute(
                text("UPDATE journal_entries SET narrative_tsv = to_tsvector('english', :doc) WHERE id = :id"),
                {"doc": doc, "id": str(entry.id)},
            )
            result.created["entries"] += 1
        elif entry.embedding is None and embedder is not None:
            entry.embedding = _checked(embedder(doc))
            result.embedded += 1
        result.entry_ids[e["seed_id"]] = entry.id

    for n in seed["npcs"]:
        exists = await session.scalar(
            select(NpcEntry.id).where(NpcEntry.campaign_id == campaign.id, NpcEntry.name == n["name"])
        )
        if exists is None:
            final = sorted(n["status_history"], key=lambda h: h["session"])[-1]["status"]
            session.add(NpcEntry(
                user_id=user.id, campaign_id=campaign.id, name=n["name"],
                role=NpcRole(n["role"]), status=NpcStatus(final),
                description=n.get("description"), notes=n.get("notes"),
            ))
            result.created["npcs"] += 1

    for q in seed["quests"]:
        exists = await session.scalar(
            select(Quest.id).where(Quest.campaign_id == campaign.id, Quest.title == q["title"])
        )
        if exists is None:
            session.add(Quest(
                user_id=user.id, campaign_id=campaign.id, title=q["title"],
                status=QuestStatus(q["status"]), description=q.get("description"), notes=q.get("notes"),
            ))
            result.created["quests"] += 1

    await session.commit()
    return result


def _checked(vec) -> list[float]:
    vec = list(vec)
    if len(vec) != EMBEDDING_DIM:
        raise SeedError(f"embedder returned {len(vec)} dims, expected {EMBEDDING_DIM}")
    return vec


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                   help="SQLAlchemy async URL (default: $DATABASE_URL)")
    p.add_argument("--owner-email", default=None,
                   help="owner of the Campaign; created if missing (default: the seed's owner)")
    p.add_argument("--seed", default=str(DEFAULT_SEED_PATH), help="seed file (default: %(default)s)")
    p.add_argument("--embeddings", choices=EMBEDDING_MODES, default="auto")
    return p


async def run(args: argparse.Namespace) -> SeedResult:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    seed = read_seed(args.seed)  # validated before anything connects
    if not args.database_url:
        raise SeedError("no database: pass --database-url or set DATABASE_URL")
    embedder = load_embedder(args.embeddings)
    engine = create_async_engine(args.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await seed_campaign(session, seed, args.owner_email, embedder)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
