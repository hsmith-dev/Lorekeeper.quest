"""Shared setup for the E0-Access.4 probes (no probes registered here).

Every row these helpers add that an actor other than a GM of its Campaign
must not see carries a canary token, so `assert_no_canary` catches it.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import sqlalchemy as sa

from tests.ev4.families import _headers, assert_no_canary
from tests.ev4.fixtures import Actor, create_user, mint_canary, seed_canary_campaign
from tests.ev4.report import note_family_call, record_leak

MISSING = "00000000-0000-4000-8000-000000000000"
UNKNOWN_TOKEN = "ev4-no-such-share-token"


def is_gm_of_a(ev4, actor: Actor) -> bool:
    return actor.grants.get(ev4.a.campaign_id) == "gm"


def authenticated(actor: Actor) -> bool:
    return actor.user_id is not None


async def outsider(ev4):
    """A fully seeded Campaign nobody in the actor set owns or belongs to."""
    owner = await create_user(ev4.db, "outsider")
    return await seed_canary_campaign(ev4.db, owner)


async def add_entry(ev4, *, visibility: str = "gm", kind: str = "gm", author: uuid.UUID | None = None,
                    canary: bool = True, campaign_id: uuid.UUID | None = None) -> uuid.UUID:
    """A committed journal entry in Campaign A (by default) whose narrative
    is a canary (or plain text with canary=False)."""
    from app.db.models.journal import JournalEntry

    cid = campaign_id or ev4.a.campaign_id
    text = mint_canary("XENTRY", cid).token if canary else f"A plain entry {uuid.uuid4().hex}"
    entry = JournalEntry(
        id=uuid.uuid4(), user_id=author or ev4.a.owner_id, campaign_id=cid, shorthand=mint_canary("XSH", cid).token,
        narrative=text, entry_hash=uuid.uuid4().hex, session_date=date(2026, 3, 1), kind=kind, visibility=visibility,
    )
    ev4.db.add(entry)
    await ev4.db.commit()
    return entry.id


async def add_tag(ev4, journal_id: uuid.UUID, *, source_field: str | None = None, name: str | None = None,
                  category_id: uuid.UUID | None = None) -> uuid.UUID:
    """A new tag linked to `journal_id` with `source_field`. With no name, a
    canary name (for a tag that must stay hidden). Tags are global and unique
    by (name, type), so a given name gets a unique suffix ("Bree 1a2b3c4d")."""
    from app.db.models.tag import JournalTag, Tag, TagType

    name = f"{name} {uuid.uuid4().hex[:8]}" if name else mint_canary("XTAG", ev4.a.campaign_id).token
    tag = Tag(id=uuid.uuid4(), name=name,
              tag_type=None if category_id else TagType.character, custom_category_id=category_id)
    ev4.db.add(tag)
    await ev4.db.flush()
    ev4.db.add(JournalTag(journal_id=journal_id, tag_id=tag.id, source_field=source_field))
    await ev4.db.commit()
    return tag.id


async def link(ev4, journal_id: uuid.UUID, tag_id: uuid.UUID, source_field: str | None = None) -> None:
    from app.db.models.tag import JournalTag

    ev4.db.add(JournalTag(journal_id=journal_id, tag_id=tag_id, source_field=source_field))
    await ev4.db.commit()


async def add_category(ev4, *, visibility: str = "gm") -> uuid.UUID:
    """A tag category in A; a hidden one is named with a canary."""
    from app.db.models.tag_category import TagCategory

    hidden = visibility != "party"
    name = mint_canary("XC", ev4.a.campaign_id).token if hidden else f"Deity {uuid.uuid4().hex[:8]}"
    cat = TagCategory(id=uuid.uuid4(), campaign_id=ev4.a.campaign_id, created_by_user_id=ev4.a.owner_id, name=name,
                      visibility=visibility)
    ev4.db.add(cat)
    await ev4.db.commit()
    return cat.id


async def add_share_token(ev4, *, kind: str = "read_only", revoked: bool = False,
                          expired: bool = False) -> str:
    from app.db.models.share_token import CampaignShareToken

    token = secrets.token_urlsafe(24)
    ev4.db.add(CampaignShareToken(
        campaign_id=ev4.a.campaign_id, created_by_user_id=ev4.a.owner_id, token=token, kind=kind, revoked=revoked,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1) if expired else None,
    ))
    await ev4.db.commit()
    return token


async def add_npc(ev4, campaign_id: uuid.UUID | None = None) -> uuid.UUID:
    from app.db.models.npc import NpcEntry

    cid = campaign_id or ev4.a.campaign_id
    npc = NpcEntry(id=uuid.uuid4(), user_id=ev4.a.owner_id, campaign_id=cid, name=f"Npc {uuid.uuid4().hex[:6]}",
                   notes=mint_canary("XNOTES", cid).token)
    ev4.db.add(npc)
    await ev4.db.commit()
    return npc.id


async def add_quest(ev4, campaign_id: uuid.UUID | None = None) -> uuid.UUID:
    from app.db.models.quest import Quest

    cid = campaign_id or ev4.a.campaign_id
    quest = Quest(id=uuid.uuid4(), user_id=ev4.a.owner_id, campaign_id=cid, title=f"Quest {uuid.uuid4().hex[:6]}",
                  notes=mint_canary("XNOTES", cid).token)
    ev4.db.add(quest)
    await ev4.db.commit()
    return quest.id


async def add_sheet(ev4, *, visibility: str = "gm") -> uuid.UUID:
    from app.db.models.character_sheet import CharacterSheet

    cid = ev4.a.campaign_id
    sheet = CharacterSheet(id=uuid.uuid4(), campaign_id=cid, template_id=ev4.a.ids["character_sheet_templates"][0],
                           created_by_user_id=ev4.a.owner_id, name=mint_canary("XSHEET", cid).token,
                           data={}, visibility=visibility)
    ev4.db.add(sheet)
    await ev4.db.commit()
    return sheet.id


async def row_count(ev4, model, *where) -> int:
    return (await ev4.db.execute(sa.select(sa.func.count()).select_from(model).where(*where))).scalar_one()


def assert_same_answer(actor: Actor, hidden: httpx.Response, missing: httpx.Response, label: str) -> None:
    """Hidden ≡ missing for two requests the caller had to build differently
    (a hidden id in the body vs a missing one): same status, body bytes and
    non-volatile headers."""
    note_family_call()
    assert_no_canary(actor, hidden)
    assert_no_canary(actor, missing)
    diffs = []
    if hidden.status_code != missing.status_code:
        diffs.append(f"status: hidden {hidden.status_code} vs missing {missing.status_code}")
    if hidden.content != missing.content:
        diffs.append(f"body: hidden {hidden.text[:200]!r} vs missing {missing.text[:200]!r}")
    if _headers(hidden) != _headers(missing):
        diffs.append("headers differ")
    if diffs:
        record_leak(f"EV-4 leak: {actor.name} can tell a hidden from a missing {label}", diffs)
