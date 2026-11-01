"""EV-4 probes for the AI helper routes E0-Access.5 moved off
get_campaign_with_access: journals autocomplete / generate-draft / recap /
summarize-session, npcs extract and quests suggest.

E0-Access.6: every one of them needs `gm` and refuses anyone else with the
missing-Campaign 404 before any LLM call (generate-draft and
summarize-session included: Players are locked out of the AI helpers). A
GM's LLM context may hold the GM-only glossary term and source chunk of A
(canaries only a GM of A may see).
"""
from __future__ import annotations

from app.services import llm_provider
from tests.ev4.families import assert_captured_context_clean, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import MISSING, assert_same_answer, authenticated, is_gm_of_a, outsider
from tests.ev4.probes.retrieval import use_fake_llm
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

WITH_CO_GM = (*DEFAULT_ACTORS, "co_gm")


async def _body_route(ev4, actor, url: str, body, *, allowed: bool) -> None:
    """POST `url` with a Campaign in the body: another Campaign answers like
    a missing one for everyone (and makes no LLM call that could carry its
    canaries); in A an `allowed` actor gets 200 with a clean LLM context,
    anyone else the missing-Campaign answer. The actor has an LLM config,
    so the Campaign check (not a 402) is what answers."""
    await use_fake_llm(ev4, actor)
    hidden = await outsider(ev4)
    targets = [hidden.campaign_id] + ([] if allowed else [ev4.a.campaign_id])
    for cid in targets:
        with llm_provider.capture() as cap:
            r = await assert_captured_context_clean(actor, lambda: actor.post(url, json=body(cid)),
                                                    label=f"{url} {cid}")
        assert cap.calls == [], f"{url}: a refused request made an LLM call"
        assert_same_answer(actor, r, await actor.post(url, json=body(MISSING)), url)
    if allowed:
        r = await assert_captured_context_clean(actor, lambda: actor.post(url, json=body(ev4.a.campaign_id)),
                                                label=f"{url} in A")
        assert r.status_code == 200, r.text
        assert_no_canary(actor, r)


@ev4_probe("POST", "/api/journals/autocomplete", actors=WITH_CO_GM)
async def probe_autocomplete(ev4, actor):
    url = "/api/journals/autocomplete"
    await _body_route(ev4, actor, url, lambda cid: {"text": "The party met", "campaign_id": str(cid)},
                      allowed=is_gm_of_a(ev4, actor))
    if authenticated(actor):
        # No Campaign: no Campaign context at all.
        r = await assert_captured_context_clean(actor, lambda: actor.post(url, json={"text": "The party met"}),
                                                label=f"{url} without a Campaign")
        assert r.status_code == 200, r.text


@ev4_probe("POST", "/api/journals/generate-draft", actors=WITH_CO_GM)
async def probe_generate_draft(ev4, actor):
    await _body_route(ev4, actor, "/api/journals/generate-draft",
                      lambda cid: {"notes": "met the innkeeper", "campaign_id": str(cid)},
                      allowed=is_gm_of_a(ev4, actor))


@ev4_probe("POST", "/api/journals/summarize-session", actors=WITH_CO_GM)
async def probe_summarize_session(ev4, actor):
    await _body_route(ev4, actor, "/api/journals/summarize-session",
                      lambda cid: {"transcript": "We went to the inn.", "campaign_id": str(cid)},
                      allowed=is_gm_of_a(ev4, actor))


@ev4_probe("POST", "/api/journals/recap", actors=WITH_CO_GM)
async def probe_recap(ev4, actor):
    await _body_route(ev4, actor, "/api/journals/recap", lambda cid: {"campaign_id": str(cid)},
                      allowed=is_gm_of_a(ev4, actor))


async def _query_route_gm_only(ev4, actor, url: str) -> None:
    """POST `url?campaign_id=`: GM only; refused like a missing Campaign
    (no LLM call) for anyone who is not GM there."""
    await use_fake_llm(ev4, actor)
    hidden = await outsider(ev4)
    targets = [hidden.campaign_id] + ([] if is_gm_of_a(ev4, actor) else [ev4.a.campaign_id])
    for cid in targets:
        await assert_captured_context_clean(
            actor, lambda: assert_hidden_equals_missing(actor, f"{url}?campaign_id={cid}",
                                                        f"{url}?campaign_id={MISSING}", method="POST"),
            label=f"{url} {cid}")


@ev4_probe("POST", "/api/npcs/extract")
async def probe_extract_npcs(ev4, actor):
    await _query_route_gm_only(ev4, actor, "/api/npcs/extract")


@ev4_probe("POST", "/api/quests/suggest")
async def probe_suggest_quests(ev4, actor):
    await _query_route_gm_only(ev4, actor, "/api/quests/suggest")
