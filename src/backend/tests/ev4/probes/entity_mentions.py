"""EV-4 probes for the Mention routes of api/routes/entities.py (E0-WorldCore.7).

A file of its own, so it never conflicts with E0-WorldCore.9's merge probe in
entities.py. Campaign A gets, through `world_service.apply_change`,
`set_visibility` and the backfill's `suggest_mentions`:

* a Party Character "Mira Party";
* a Party gm entry whose plain Narrative names Mira (the backfill gives a
  suggested Mention with a plain quote);
* a confirmed Narrative Mention on a second Party entry (plain quote): the
  one Mention a Player may see;
* a Party entry whose Narrative does not name Mira but whose Shorthand is
  "Mira Party <canary>" (the backfill gives nothing), plus a GM-added
  confirmed Mention sourced from Shorthand with a canary quote;
* a GM-visibility entry (canary Narrative) with a confirmed Mention;
* a GM-only Entity (canary name) with a confirmed Mention on a Party entry.

An outsider Campaign holds a Party Entity, a Party entry and a Mention.

A non-GM sees exactly the one plain confirmed Mention (`confirmed=false` is
empty), counts and ranking do not move when the GM writes GM-only Mentions,
hidden Entities and entries (and another Entity's Mention) answer like
missing ones, and a Player's confirm/remove writes nothing.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.fixtures import mint_canary
from tests.ev4.probes._support import MISSING, authenticated, is_gm_of_a, outsider, row_count
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

BASE = "/api/entities"
WRITERS = (*DEFAULT_ACTORS, "co_gm")


@dataclass
class MentionWorld:
    gm: object
    party: uuid.UUID            # Party Character "Mira Party"
    secret: uuid.UUID           # GM-only Entity (canary name)
    suggested_entry: uuid.UUID  # Party entry naming Mira: a suggested Mention
    confirmed_entry: uuid.UUID  # Party entry with the one visible Mention
    shorthand_entry: uuid.UUID  # Mira only in its Shorthand
    gm_entry: uuid.UUID         # GM-visibility entry
    suggested: uuid.UUID
    confirmed: uuid.UUID
    secret_mention: uuid.UUID   # a Mention of the GM-only Entity
    other: uuid.UUID            # the outsider's Party Entity
    other_entry: uuid.UUID


async def _entry(ev4, narrative: str, *, visibility: str = "party", shorthand: str | None = None,
                 campaign_id: uuid.UUID | None = None, author: uuid.UUID | None = None) -> uuid.UUID:
    from datetime import date

    from app.db.models.journal import JournalEntry

    entry = JournalEntry(
        id=uuid.uuid4(), user_id=author or ev4.a.owner_id, campaign_id=campaign_id or ev4.a.campaign_id,
        shorthand=shorthand or f"plain shorthand {uuid.uuid4().hex[:8]}", narrative=narrative,
        entry_hash=uuid.uuid4().hex, session_date=date(2026, 3, 1), kind="gm", visibility=visibility)
    ev4.db.add(entry)
    await ev4.db.commit()
    return entry.id


async def _suggest(ev4, ctx, entry_id: uuid.UUID) -> int:
    from app.access import scoped_select
    from app.db.models.journal import JournalEntry
    from app.jobs.world import suggest_mentions

    entry = (await ev4.db.execute(scoped_select(JournalEntry, ctx).where(JournalEntry.id == entry_id))).scalars().one()
    added = await suggest_mentions(ev4.db, ctx, entry)
    await ev4.db.commit()
    return added


async def _mention(db, ctx, entity_id, journal_id, **kw) -> uuid.UUID:
    from app.services.world_service import apply_change

    row = await apply_change(db, ctx, {"op": "add_mention", "entity_id": entity_id, "journal_id": journal_id, **kw})
    return uuid.UUID(row.new_value["mention_id"])


async def _publish(db, ctx, entity_id) -> None:
    from app.access import set_visibility
    from app.schemas.sources import RecordRef

    await set_visibility(db, ctx, RecordRef(kind="entity", id=entity_id), "party")


async def _world(ev4) -> MentionWorld:
    import sqlalchemy as sa

    from app.access import ctx_for
    from app.db.models.entity import EntityMention
    from app.services.world_service import apply_change

    db, a = ev4.db, ev4.a.campaign_id
    gm = await ctx_for(db, ev4.a.owner_id, a)

    def c(kind: str) -> str:
        return mint_canary(kind, a).token

    party = (await apply_change(db, gm, {"op": "create_entity", "type": "character", "kind": "npc",
                                         "name": "Mira Party"})).entity_id
    secret = (await apply_change(db, gm, {"op": "create_entity", "type": "character", "kind": "npc",
                                          "name": c("XMENSECRET")})).entity_id
    await _publish(db, gm, party)
    await db.commit()

    suggested_entry = await _entry(ev4, "We met Mira Party at the docks. It rained.")
    assert await _suggest(ev4, gm, suggested_entry) == 1
    suggested = (await db.execute(sa.select(EntityMention.id).where(
        EntityMention.journal_id == suggested_entry, EntityMention.entity_id == party))).scalar_one()

    confirmed_entry = await _entry(ev4, "Mira Party sailed home.")
    confirmed = await _mention(db, gm, party, confirmed_entry, confirmed=True, quote="Mira Party sailed home.",
                               span_start=0, span_end=10)
    secret_mention = await _mention(db, gm, secret, confirmed_entry, confirmed=True, quote=c("XMENSQUOTE"))

    shorthand_entry = await _entry(ev4, "A quiet day at the market.", shorthand=f"Mira Party {c('XMENSH')}")
    await db.commit()
    assert await _suggest(ev4, gm, shorthand_entry) == 0
    await _mention(db, gm, party, shorthand_entry, confirmed=True, source_field="shorthand",
                   quote=c("XMENSHQUOTE"))

    gm_entry = await _entry(ev4, c("XMENGMENTRY"), visibility="gm")
    await _mention(db, gm, party, gm_entry, confirmed=True, quote=c("XMENGMQUOTE"))
    await db.commit()

    seeded = await outsider(ev4)
    other_gm = await ctx_for(db, seeded.owner_id, seeded.campaign_id)
    other = (await apply_change(db, other_gm, {"op": "create_entity", "type": "character", "kind": "npc",
                                               "name": mint_canary("XMENOTHER", seeded.campaign_id).token})).entity_id
    await _publish(db, other_gm, other)
    await db.commit()
    other_entry = await _entry(ev4, mint_canary("XMENOENTRY", seeded.campaign_id).token,
                               campaign_id=seeded.campaign_id, author=seeded.owner_id)
    await _mention(db, other_gm, other, other_entry, confirmed=True,
                   quote=mint_canary("XMENOQUOTE", seeded.campaign_id).token)
    await db.commit()
    return MentionWorld(gm=gm, party=party, secret=secret, suggested_entry=suggested_entry,
                        confirmed_entry=confirmed_entry, shorthand_entry=shorthand_entry, gm_entry=gm_entry,
                        suggested=suggested, confirmed=confirmed, secret_mention=secret_mention, other=other,
                        other_entry=other_entry)


async def _gm_only_mentions(ev4, w: MentionWorld) -> None:
    """GM-only Mention writes: a Shorthand-only canary entry run through the
    backfill (nothing), a new suggested Mention, and a GM-only Entity's Mention."""
    a = ev4.a.campaign_id
    shorthand_only = await _entry(ev4, "Nobody of note.", shorthand=f"Mira Party {mint_canary('XMENSH2', a).token}")
    assert await _suggest(ev4, w.gm, shorthand_only) == 0
    fresh = await _entry(ev4, "Then Mira Party waved.")
    assert await _suggest(ev4, w.gm, fresh) == 1
    await _mention(ev4.db, w.gm, w.secret, w.confirmed_entry, confirmed=True,
                   quote=mint_canary("XMENSQUOTE2", a).token)
    await ev4.db.commit()


async def _mention_rows(ev4) -> int:
    from app.db.models.entity import EntityMention

    return await row_count(ev4, EntityMention, EntityMention.campaign_id == ev4.a.campaign_id)


async def _history_rows(ev4) -> int:
    from app.db.models.entity import EntityChange

    return await row_count(ev4, EntityChange, EntityChange.campaign_id == ev4.a.campaign_id)


async def _refused(ev4, actor, method: str, url: str, missing_url: str) -> None:
    """A non-GM's write answers like the missing target and writes nothing."""
    before = (await _history_rows(ev4), await _mention_rows(ev4))
    await assert_hidden_equals_missing(actor, url, missing_url, method=method)
    assert (await _history_rows(ev4), await _mention_rows(ev4)) == before, f"{actor.name}: {method} {url} wrote"


def _items(response) -> list[dict]:
    return response.json()["items"]


# ── Reads ──────────────────────────────────────────────────────────────────

@ev4_probe("GET", "/api/entities/{entity_id}/mentions")
async def probe_entity_mentions(ev4, actor):
    w = await _world(ev4)
    a = ev4.a.campaign_id
    for entity_id in (w.secret, w.other):
        await assert_hidden_equals_missing(actor, f"{BASE}/{entity_id}/mentions", f"{BASE}/{MISSING}/mentions")
    if not authenticated(actor):
        return
    url = f"{BASE}/{w.party}/mentions"
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    assert [i["id"] for i in _items(r)] == [str(w.confirmed)], r.text
    assert r.json()["total"] == 1 and r.json()["page_size"] == 20
    item = _items(r)[0]
    assert item["confirmed"] is True and "origin" not in item and "source_field" not in item, item
    assert (item["entity_name"], item["quote"]) == ("Mira Party", "Mira Party sailed home."), item
    suggested = await actor.get(f"{url}?confirmed=false")
    assert_no_canary(actor, suggested)
    assert suggested.status_code == 200 and suggested.json()["items"] == [] and suggested.json()["total"] == 0
    await assert_counts_and_ranking_unchanged(
        actor, [url, f"{url}?confirmed=true", f"{BASE}/mentions?journal_id={w.confirmed_entry}", f"{BASE}/{w.party}",
                f"{BASE}/?campaign_id={a}&q=Mira"],
        lambda: _gm_only_mentions(ev4, w))


@ev4_probe("GET", "/api/entities/mentions")
async def probe_entry_mentions(ev4, actor):
    w = await _world(ev4)
    a = ev4.a.campaign_id
    missing = f"{BASE}/mentions?journal_id={MISSING}"
    for entry_id in (w.gm_entry, w.other_entry):
        await assert_hidden_equals_missing(actor, f"{BASE}/mentions?journal_id={entry_id}", missing)
    if not authenticated(actor):
        return
    r = await actor.get(f"{BASE}/mentions?journal_id={w.confirmed_entry}")
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    # The GM-only Entity's Mention of the same entry is left out.
    assert [i["id"] for i in _items(r)] == [str(w.confirmed)], r.text
    assert (_items(r)[0]["entity_name"], _items(r)[0]["entity_type"]) == ("Mira Party", "character")
    for entry_id in (w.suggested_entry, w.shorthand_entry):
        only_gm = await actor.get(f"{BASE}/mentions?journal_id={entry_id}")
        assert_no_canary(actor, only_gm)
        assert only_gm.status_code == 200 and _items(only_gm) == [], only_gm.text
    await assert_counts_and_ranking_unchanged(
        actor, [f"{BASE}/mentions?journal_id={w.confirmed_entry}", f"{BASE}/mentions?journal_id={w.suggested_entry}",
                f"{BASE}/{w.party}", f"{BASE}/?campaign_id={a}&q=Mira"],
        lambda: _gm_only_mentions(ev4, w))


# ── Writes ─────────────────────────────────────────────────────────────────

@ev4_probe("POST", "/api/entities/{entity_id}/mentions/{mention_id}/confirm", actors=WRITERS)
async def probe_confirm_mention(ev4, actor):
    w = await _world(ev4)
    missing = f"{BASE}/{MISSING}/mentions/{MISSING}/confirm"
    if is_gm_of_a(ev4, actor):
        # Another Entity's Mention is the 404.
        await assert_hidden_equals_missing(actor, f"{BASE}/{w.party}/mentions/{w.secret_mention}/confirm",
                                           f"{BASE}/{w.party}/mentions/{MISSING}/confirm", method="POST")
        r = await actor.post(f"{BASE}/{w.party}/mentions/{w.suggested}/confirm")
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json()["confirmed"] is True, r.text
        return
    for entity_id, mention_id in ((w.party, w.suggested), (w.party, w.confirmed), (w.secret, w.secret_mention)):
        await _refused(ev4, actor, "POST", f"{BASE}/{entity_id}/mentions/{mention_id}/confirm", missing)


@ev4_probe("DELETE", "/api/entities/{entity_id}/mentions/{mention_id}", actors=WRITERS)
async def probe_remove_mention(ev4, actor):
    w = await _world(ev4)
    missing = f"{BASE}/{MISSING}/mentions/{MISSING}"
    if is_gm_of_a(ev4, actor):
        await assert_hidden_equals_missing(actor, f"{BASE}/{w.party}/mentions/{w.secret_mention}",
                                           f"{BASE}/{w.party}/mentions/{MISSING}", method="DELETE")
        r = await actor.delete(f"{BASE}/{w.party}/mentions/{w.confirmed}")
        assert_no_canary(actor, r)
        assert r.status_code == 204, r.text
        return
    for entity_id, mention_id in ((w.party, w.confirmed), (w.party, w.suggested), (w.secret, w.secret_mention)):
        await _refused(ev4, actor, "DELETE", f"{BASE}/{entity_id}/mentions/{mention_id}", missing)
