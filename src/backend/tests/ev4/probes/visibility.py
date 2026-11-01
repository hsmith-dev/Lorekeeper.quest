"""EV-4 probes for api/routes/visibility.py (E0-Access.9): the bulk
`set_visibility` route, and the downgrade suite.

The route is GM only. For anyone else, A's Campaign answers exactly like a
missing Campaign, whatever the items (a hidden entry, a Party entry, an
always-GM NPC that a GM would get a 422 for), and nothing is written.
Another Campaign answers like a missing one for everyone. A Co-GM's change
succeeds.

The downgrade suite: a Party entry a Player of A can read, list, find and
have quoted to the Chronicler is flipped to GM by the Owner through the
route. On the very next request the Player's detail answers like a missing
entry, the list and its count drop it, search no longer finds it and the
Chronicler's prompt no longer holds it.
"""
from __future__ import annotations

import random
import string

import sqlalchemy as sa

from tests.ev4.families import _captured_text, assert_captured_context_clean, assert_hidden_equals_missing
from tests.ev4.probes._support import MISSING, add_entry, assert_same_answer, authenticated, is_gm_of_a, outsider
from tests.ev4.probes.retrieval import add_entry as add_indexed_entry
from tests.ev4.probes.retrieval import fake_embeddings, index_seeded, use_fake_llm
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe
from tests.ev4.report import record_leak

ACTORS = (*DEFAULT_ACTORS, "co_gm")


def _url(campaign_id) -> str:
    return f"/api/campaigns/{campaign_id}/visibility"


def _body(*ids, kind: str = "journal", value: str = "party") -> dict:
    return {"items": [{"kind": kind, "id": str(i)} for i in ids], "value": value}


async def _visibility(ev4, entry_id) -> str:
    from app.db.models.journal import JournalEntry

    return (await ev4.db.execute(sa.select(JournalEntry.visibility).where(JournalEntry.id == entry_id))).scalar_one()


@ev4_probe("POST", "/api/campaigns/{campaign_id}/visibility", actors=ACTORS)
async def probe_set_visibility(ev4, actor):
    a = ev4.a.campaign_id
    hidden = await add_entry(ev4, visibility="gm")
    party = await add_entry(ev4, visibility="party", canary=False)
    other = await outsider(ev4)
    other_entry = other.ids["journal_entries"][0]
    assert_same_answer(actor, await actor.post(_url(other.campaign_id), json=_body(other_entry)),
                       await actor.post(_url(MISSING), json=_body(other_entry)), "visibility in another Campaign")
    if is_gm_of_a(ev4, actor):
        # Another Campaign's row in A's route is the missing-row 404.
        assert_same_answer(actor, await actor.post(_url(a), json=_body(party, other_entry, value="gm")),
                           await actor.post(_url(a), json=_body(party, MISSING, value="gm")),
                           "an item of another Campaign")
        assert await _visibility(ev4, party) == "party"
        r = await actor.post(_url(a), json=_body(party, value="gm"))
        assert r.status_code == 200 and r.json() == {"updated": 1}, r.text
        assert await _visibility(ev4, party) == "gm"
        return
    for items in (_body(hidden), _body(party, value="gm"), _body(ev4.a.ids["npcs"][0], kind="npc")):
        assert_same_answer(actor, await actor.post(_url(a), json=items), await actor.post(_url(MISSING), json=items),
                           "visibility (gm only)")
    assert await _visibility(ev4, hidden) == "gm"
    assert await _visibility(ev4, party) == "party"
    if authenticated(actor):
        await _downgrade_suite(ev4, actor)


def _word() -> str:
    return "zq" + "".join(random.choices(string.ascii_lowercase, k=10))


async def _downgrade_suite(ev4, player) -> None:
    """A Party entry, downgraded to GM by the Owner: gone from every read of
    `player` (a Player of A) on the very next request."""
    a = ev4.a.campaign_id
    word, secret = _word(), _word()  # `secret` is only in the entry, never in the question
    owner = await ev4.actor("gm_owner")
    await use_fake_llm(ev4, player)
    with fake_embeddings():
        await index_seeded(ev4)
        entry = await add_indexed_entry(
            ev4, f"At the Drowsy Dragon the innkeeper whispered about the {word}: {secret} lies beneath the cellar.",
            shorthand="inn notes")
        detail, missing = f"/api/journals/{entry}", f"/api/journals/{MISSING}"
        listing, search = f"/api/journals/?campaign_id={a}&limit=100", f"/api/journals/?campaign_id={a}&search={word}"
        chat = {"message": f"What did the innkeeper whisper about the {word}?", "campaign_id": str(a)}

        async def reads():
            listed = (await player.get(listing)).json()
            found = (await player.get(search)).json()
            cap: dict = {}

            async def ask():
                from app.services import llm_provider

                with llm_provider.capture() as captured:
                    r = await player.post("/api/chat/", json=chat)
                cap["text"] = _captured_text(captured)
                return r

            r = await assert_captured_context_clean(player, ask, label="chat before/after a downgrade")
            assert r.status_code == 200, r.text
            ids = {i["id"] for i in listed["items"]}
            return ids, listed["total"], {i["id"] for i in found["items"]}, cap["text"]

        assert (await player.get(detail)).status_code == 200
        ids, total, found, prompt = await reads()
        assert str(entry) in ids and str(entry) in found, (ids, found)  # non-vacuous
        assert secret in prompt, "the Party entry never reached the Chronicler's prompt (the check would be vacuous)"

        r = await owner.post(_url(a), json=_body(entry, value="gm"))
        assert r.status_code == 200 and r.json() == {"updated": 1}, r.text

        await assert_hidden_equals_missing(player, detail, missing)
        ids_after, total_after, found_after, prompt_after = await reads()
        leaks = []
        if str(entry) in ids_after or total_after != total - 1:
            leaks.append(f"list: still listed or count {total} -> {total_after}")
        if str(entry) in found_after:
            leaks.append("search: still found")
        if secret in prompt_after:
            leaks.append("chat: still in the Chronicler's prompt")
        if leaks:
            record_leak(f"EV-4 leak: {player.name} still sees an entry downgraded to GM", leaks)
