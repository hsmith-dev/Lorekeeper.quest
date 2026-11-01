"""EV-4 write probes for E0-Access.6: the single write gate (access.can_write).

* Preview writes: a GM sending `X-Lorekeeper-Preview: member` reads as the
  member view, and every write in preview answers exactly like a write on a
  missing row (or in a missing Campaign), with nothing written and no LLM
  call. Probed as the two actors who are GM somewhere: co_gm (GM of A) and
  cross_gm_player (Owner of B), each on their own GM Campaign.
* The two Campaign-less creates, `POST /api/campaigns/` and
  `POST /api/campaigns/generate-concept`: the new Campaign is the caller's
  own, and no response or LLM prompt carries another Campaign's canary.
"""
from __future__ import annotations

import uuid

from tests.ev4.families import assert_captured_context_clean, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import MISSING, assert_same_answer, authenticated, previewing, row_count
from tests.ev4.probes.retrieval import use_fake_llm
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

GM_SOMEWHERE = ("co_gm", "cross_gm_player")


def _own_gm_campaign(ev4, actor):
    """The seeded Campaign `actor` is GM of: A for co_gm, B for cross_gm_player."""
    return ev4.a if actor.name == "co_gm" else ev4.b


async def _add_category(ev4, campaign_id: uuid.UUID) -> uuid.UUID:
    from app.db.models.tag_category import TagCategory

    cat = TagCategory(id=uuid.uuid4(), campaign_id=campaign_id, created_by_user_id=ev4.a.owner_id,
                      name=f"Deity {uuid.uuid4().hex[:8]}", visibility="party")
    ev4.db.add(cat)
    await ev4.db.commit()
    return cat.id


# ── Preview: item writes ───────────────────────────────────────────────────

@ev4_probe("DELETE", "/api/journals/{journal_id}", actors=GM_SOMEWHERE)
async def probe_preview_delete_journal(ev4, actor):
    from app.db.models.journal import JournalEntry

    seeded = _own_gm_campaign(ev4, actor)
    pv = previewing(actor)
    entry = seeded.ids["journal_entries"][0]
    await assert_hidden_equals_missing(pv, f"/api/journals/{entry}", f"/api/journals/{MISSING}", method="DELETE")
    assert await row_count(ev4, JournalEntry, JournalEntry.id == entry) == 1


@ev4_probe("POST", "/api/journals/{journal_id}/tags", actors=GM_SOMEWHERE)
async def probe_preview_attach_tag(ev4, actor):
    from app.db.models.tag import JournalTag

    seeded = _own_gm_campaign(ev4, actor)
    pv = previewing(actor)
    entry = seeded.ids["journal_entries"][0]
    before = await row_count(ev4, JournalTag, JournalTag.journal_id == entry)
    await assert_hidden_equals_missing(pv, f"/api/journals/{entry}/tags", f"/api/journals/{MISSING}/tags",
                                       method="POST", json={"name": "Bree", "tag_type": "location"})
    assert await row_count(ev4, JournalTag, JournalTag.journal_id == entry) == before


@ev4_probe("PUT", "/api/session-plans/{plan_id}", actors=GM_SOMEWHERE)
async def probe_preview_update_plan(ev4, actor):
    from app.db.models.session_plan import SessionPlan

    seeded = _own_gm_campaign(ev4, actor)
    pv = previewing(actor)
    plan = seeded.ids["session_plans"][0]
    await assert_hidden_equals_missing(pv, f"/api/session-plans/{plan}", f"/api/session-plans/{MISSING}",
                                       method="PUT", json={"title": "Edited"})
    assert await row_count(ev4, SessionPlan, SessionPlan.id == plan, SessionPlan.title == "Edited") == 0


@ev4_probe("PATCH", "/api/character-sheets/{sheet_id}", actors=GM_SOMEWHERE)
async def probe_preview_update_sheet(ev4, actor):
    from app.db.models.character_sheet import CharacterSheet

    seeded = _own_gm_campaign(ev4, actor)
    pv = previewing(actor)
    sheet = seeded.ids["character_sheets"][0]
    await assert_hidden_equals_missing(pv, f"/api/character-sheets/{sheet}", f"/api/character-sheets/{MISSING}",
                                       method="PATCH", json={"name": "Renamed"})
    assert await row_count(ev4, CharacterSheet, CharacterSheet.id == sheet, CharacterSheet.name == "Renamed") == 0


@ev4_probe("DELETE", "/api/campaigns/{campaign_id}/tag-categories/{category_id}", actors=GM_SOMEWHERE)
async def probe_preview_delete_tag_category(ev4, actor):
    from app.db.models.tag_category import TagCategory

    seeded = _own_gm_campaign(ev4, actor)
    pv = previewing(actor)
    cat = await _add_category(ev4, seeded.campaign_id)
    await assert_hidden_equals_missing(
        pv, f"/api/campaigns/{seeded.campaign_id}/tag-categories/{cat}",
        f"/api/campaigns/{MISSING}/tag-categories/{cat}", method="DELETE")
    assert await row_count(ev4, TagCategory, TagCategory.id == cat) == 1


# ── Preview: creates and AI routes (Campaign in the body) ──────────────────

@ev4_probe("POST", "/api/npcs/", actors=GM_SOMEWHERE)
async def probe_preview_create_npc(ev4, actor):
    from app.db.models.npc import NpcEntry

    seeded = _own_gm_campaign(ev4, actor)
    pv = previewing(actor)
    before = await row_count(ev4, NpcEntry, NpcEntry.campaign_id == seeded.campaign_id)
    body = {"name": "Spy", "notes": "secret"}
    assert_same_answer(pv, await pv.post("/api/npcs/", json={**body, "campaign_id": str(seeded.campaign_id)}),
                       await pv.post("/api/npcs/", json={**body, "campaign_id": MISSING}), "NPC create in preview")
    assert await row_count(ev4, NpcEntry, NpcEntry.campaign_id == seeded.campaign_id) == before


@ev4_probe("POST", "/api/shorthand/", actors=GM_SOMEWHERE)
async def probe_preview_create_shorthand(ev4, actor):
    from app.db.models.shorthand import ShorthandTerm

    seeded = _own_gm_campaign(ev4, actor)
    pv = previewing(actor)
    before = await row_count(ev4, ShorthandTerm, ShorthandTerm.campaign_id == seeded.campaign_id)

    def body(cid):
        return {"campaign_id": str(cid), "term": "bbeg", "meaning": "big bad"}

    assert_same_answer(pv, await pv.post("/api/shorthand/", json=body(seeded.campaign_id)),
                       await pv.post("/api/shorthand/", json=body(MISSING)), "shorthand create in preview")
    assert await row_count(ev4, ShorthandTerm, ShorthandTerm.campaign_id == seeded.campaign_id) == before


@ev4_probe("POST", "/api/journals/generate-draft", actors=GM_SOMEWHERE)
async def probe_preview_generate_draft(ev4, actor):
    from app.services import llm_provider

    await use_fake_llm(ev4, actor)
    seeded = _own_gm_campaign(ev4, actor)
    pv = previewing(actor)

    def body(cid):
        return {"notes": "met the innkeeper", "campaign_id": str(cid)}

    with llm_provider.capture() as cap:
        r = await pv.post("/api/journals/generate-draft", json=body(seeded.campaign_id))
    assert cap.calls == [], "a preview draft made an LLM call"
    assert_same_answer(pv, r, await pv.post("/api/journals/generate-draft", json=body(MISSING)),
                       "generate-draft in preview")


# ── Campaign-less creates ──────────────────────────────────────────────────

@ev4_probe("POST", "/api/campaigns/", actors=(*DEFAULT_ACTORS, "co_gm"))
async def probe_create_campaign(ev4, actor):
    from app.db.models.campaign import Campaign

    r = await actor.post("/api/campaigns/", json={"name": "My table", "genre": "fantasy"})
    assert_no_canary(actor, r)
    if not authenticated(actor):
        assert r.status_code in (401, 403), r.text
        return
    assert r.status_code == 201, r.text
    new_id = uuid.UUID(r.json()["id"])
    # The caller owns what they created, and nothing else changed hands.
    assert await row_count(ev4, Campaign, Campaign.id == new_id, Campaign.user_id == actor.user_id) == 1
    assert await row_count(ev4, Campaign, Campaign.id == ev4.a.campaign_id, Campaign.user_id == ev4.a.owner_id) == 1
    listed = await actor.get("/api/campaigns/")
    assert_no_canary(actor, listed)
    mine = {c["id"]: c for c in listed.json()}
    assert mine[str(new_id)]["is_owner"] is True, listed.text


@ev4_probe("POST", "/api/campaigns/generate-concept", actors=(*DEFAULT_ACTORS, "co_gm"))
async def probe_generate_concept(ev4, actor):
    from app.services import llm_provider

    await use_fake_llm(ev4, actor)
    body = {"genre": "fantasy", "prompt": "a border town"}
    with llm_provider.capture() as cap:
        r = await assert_captured_context_clean(
            actor, lambda: actor.post("/api/campaigns/generate-concept", json=body), label="generate-concept")
    assert_no_canary(actor, r)
    if not authenticated(actor):
        assert r.status_code in (401, 403) and cap.calls == [], r.text
        return
    assert r.status_code == 200, r.text
