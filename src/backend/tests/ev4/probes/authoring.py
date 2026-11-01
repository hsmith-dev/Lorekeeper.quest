"""EV-4 probes for the GM authoring routes E0-Access.5 moved onto
require_campaign: api/routes/shorthand.py, session_plans.py and sources.py.

Reads need `player` and list only rows whose Visibility covers the caller;
writes need `gm` in the row's own Campaign (Owner or Co-GM). For anyone else
a write is the one 404, byte-identical to a missing Campaign or row, and
nothing is written. The seeded rows of A are visibility gm and all canary.
"""
from __future__ import annotations

from tests.ev4.families import (
    assert_captured_context_clean, assert_counts_and_ranking_unchanged, assert_hidden_equals_missing,
    assert_no_canary,
)
from tests.ev4.probes._support import (
    MISSING, add_plan, add_source, add_term, assert_same_answer, authenticated, is_gm_of_a, outsider, row_count,
)
from tests.ev4.probes.retrieval import use_fake_llm
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

WITH_CO_GM = (*DEFAULT_ACTORS, "co_gm")


async def _list_probe(ev4, actor, base: str, add, id_key: str = "id") -> None:
    """A Party list: another Campaign answers like a missing one, hidden rows
    are absent (no canary), a party row is listed, and a GM-only row changes
    nothing the caller sees."""
    a = ev4.a.campaign_id
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{base}?campaign_id={hidden.campaign_id}",
                                       f"{base}?campaign_id={MISSING}")
    if not authenticated(actor):
        return
    party = await add(ev4, visibility="party")
    url = f"{base}?campaign_id={a}"
    r = await actor.get(url)
    assert r.status_code == 200, r.text
    assert_no_canary(actor, r)
    assert str(party) in {row[id_key] for row in r.json()}, r.text
    if is_gm_of_a(ev4, actor):
        return
    await assert_counts_and_ranking_unchanged(actor, url, lambda: add(ev4, visibility="gm"))


async def _create_probe(ev4, actor, url: str, model, body, **kwargs) -> None:
    """A GM-only create: for a non-GM of A, A's Campaign answers like a
    missing one and nothing is written; another Campaign likewise for all."""
    a = ev4.a.campaign_id
    before = await row_count(ev4, model, model.campaign_id == a)
    hidden = await outsider(ev4)
    assert_same_answer(actor, await actor.post(url, **body(hidden.campaign_id), **kwargs),
                       await actor.post(url, **body(MISSING), **kwargs), f"{url} in another Campaign")
    if is_gm_of_a(ev4, actor):
        r = await actor.post(url, **body(a), **kwargs)
        assert r.status_code == 201, r.text
        assert_no_canary(actor, r)
        return
    assert_same_answer(actor, await actor.post(url, **body(a), **kwargs),
                       await actor.post(url, **body(MISSING), **kwargs), f"{url} (gm only)")
    assert await row_count(ev4, model, model.campaign_id == a) == before


async def _item_write_probe(ev4, actor, base: str, model, add, method: str, **kwargs) -> None:
    """A GM-only item write: for a non-GM of A, a hidden row and a party row
    of A answer like a missing row and stay untouched; another Campaign's
    row likewise for all. A Co-GM's write succeeds."""
    hidden = await outsider(ev4)
    other = hidden.ids[model.__tablename__][0]
    await assert_hidden_equals_missing(actor, f"{base}/{other}", f"{base}/{MISSING}", method=method, **kwargs)
    rows = [await add(ev4, visibility="gm"), await add(ev4, visibility="party")]
    if is_gm_of_a(ev4, actor):
        r = await actor.request(method, f"{base}/{rows[1]}", **kwargs)
        assert r.status_code in (200, 204), r.text
        assert_no_canary(actor, r)
        return
    for row in rows:
        await assert_hidden_equals_missing(actor, f"{base}/{row}", f"{base}/{MISSING}", method=method, **kwargs)
        assert await row_count(ev4, model, model.id == row) == 1


# ── Shorthand ──────────────────────────────────────────────────────────────

@ev4_probe("GET", "/api/shorthand/", actors=WITH_CO_GM)
async def probe_list_shorthand(ev4, actor):
    await _list_probe(ev4, actor, "/api/shorthand/", add_term)


@ev4_probe("POST", "/api/shorthand/", actors=WITH_CO_GM)
async def probe_create_shorthand(ev4, actor):
    from app.db.models.shorthand import ShorthandTerm

    await _create_probe(ev4, actor, "/api/shorthand/", ShorthandTerm,
                        lambda cid: {"json": {"campaign_id": str(cid), "term": "bbeg", "meaning": "big bad"}})


@ev4_probe("PUT", "/api/shorthand/{term_id}", actors=WITH_CO_GM)
async def probe_update_shorthand(ev4, actor):
    from app.db.models.shorthand import ShorthandTerm

    await _item_write_probe(ev4, actor, "/api/shorthand", ShorthandTerm, add_term, "PUT", json={"meaning": "edited"})
    if not is_gm_of_a(ev4, actor):
        assert await row_count(ev4, ShorthandTerm, ShorthandTerm.campaign_id == ev4.a.campaign_id, ShorthandTerm.meaning == "edited") == 0


@ev4_probe("DELETE", "/api/shorthand/{term_id}", actors=WITH_CO_GM)
async def probe_delete_shorthand(ev4, actor):
    from app.db.models.shorthand import ShorthandTerm

    await _item_write_probe(ev4, actor, "/api/shorthand", ShorthandTerm, add_term, "DELETE")


# ── Session plans ──────────────────────────────────────────────────────────

@ev4_probe("GET", "/api/session-plans/", actors=WITH_CO_GM)
async def probe_list_session_plans(ev4, actor):
    await _list_probe(ev4, actor, "/api/session-plans/", add_plan)


@ev4_probe("GET", "/api/session-plans/{plan_id}", actors=WITH_CO_GM)
async def probe_get_session_plan(ev4, actor):
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/session-plans/{hidden.ids['session_plans'][0]}",
                                       f"/api/session-plans/{MISSING}")
    if is_gm_of_a(ev4, actor):
        assert_no_canary(actor, await actor.get(f"/api/session-plans/{ev4.a.ids['session_plans'][0]}"))
        return
    for vis in ("gm", "private"):
        await assert_hidden_equals_missing(actor, f"/api/session-plans/{await add_plan(ev4, visibility=vis)}",
                                           f"/api/session-plans/{MISSING}")
    await assert_hidden_equals_missing(actor, f"/api/session-plans/{ev4.a.ids['session_plans'][0]}",
                                       f"/api/session-plans/{MISSING}")
    if authenticated(actor):
        r = await actor.get(f"/api/session-plans/{await add_plan(ev4, visibility='party')}")
        assert r.status_code == 200, r.text
        assert_no_canary(actor, r)


@ev4_probe("POST", "/api/session-plans/", actors=WITH_CO_GM)
async def probe_create_session_plan(ev4, actor):
    from app.db.models.session_plan import SessionPlan

    await _create_probe(ev4, actor, "/api/session-plans/", SessionPlan,
                        lambda cid: {"json": {"campaign_id": str(cid), "title": "Next", "content": "Plan."}})


@ev4_probe("PUT", "/api/session-plans/{plan_id}", actors=WITH_CO_GM)
async def probe_update_session_plan(ev4, actor):
    from app.db.models.session_plan import SessionPlan

    await _item_write_probe(ev4, actor, "/api/session-plans", SessionPlan, add_plan, "PUT",
                            json={"content": "edited"})
    if not is_gm_of_a(ev4, actor):
        assert await row_count(ev4, SessionPlan, SessionPlan.campaign_id == ev4.a.campaign_id, SessionPlan.content == "edited") == 0


@ev4_probe("DELETE", "/api/session-plans/{plan_id}", actors=WITH_CO_GM)
async def probe_delete_session_plan(ev4, actor):
    from app.db.models.session_plan import SessionPlan

    await _item_write_probe(ev4, actor, "/api/session-plans", SessionPlan, add_plan, "DELETE")


@ev4_probe("POST", "/api/session-plans/generate", actors=WITH_CO_GM)
async def probe_generate_session_plan(ev4, actor):
    url = "/api/session-plans/generate"
    await use_fake_llm(ev4, actor)  # so the Campaign check, not a 402, answers
    hidden = await outsider(ev4)

    def body(cid):
        return {"json": {"campaign_id": str(cid), "focus": "the inn"}}

    for cid in (hidden.campaign_id, *(() if is_gm_of_a(ev4, actor) else (ev4.a.campaign_id,))):
        # GM only (Shorthand, NPCs, Quests): refused before any LLM call.
        r = await assert_captured_context_clean(actor, lambda: actor.post(url, **body(cid)), label=f"{url} {cid}")
        assert_same_answer(actor, r, await actor.post(url, **body(MISSING)), f"{url} (gm only)")
    if is_gm_of_a(ev4, actor):
        r = await actor.post(url, **body(ev4.a.campaign_id))
        assert r.status_code == 200, r.text


# ── Sources ────────────────────────────────────────────────────────────────

@ev4_probe("GET", "/api/sources/", actors=WITH_CO_GM)
async def probe_list_sources(ev4, actor):
    await _list_probe(ev4, actor, "/api/sources/", add_source)


@ev4_probe("POST", "/api/sources/")
async def probe_upload_source(ev4, actor):
    from app.db.models.source import SourceDocument

    def body(cid):
        return {"data": {"campaign_id": str(cid)},
                "files": {"file": ("notes.txt", b"The party met the innkeeper at dusk.", "text/plain")}}

    await _create_probe(ev4, actor, "/api/sources/", SourceDocument, body)


@ev4_probe("DELETE", "/api/sources/{source_id}", actors=WITH_CO_GM)
async def probe_delete_source(ev4, actor):
    from app.db.models.source import SourceDocument

    await _item_write_probe(ev4, actor, "/api/sources", SourceDocument, add_source, "DELETE")
