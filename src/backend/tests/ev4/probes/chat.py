"""EV-4 probes for the Chronicler's stored sessions (E0-Access.8).

The list, one session and delete. Each authenticated actor gets two
sessions of their own in Campaign A, live and archived, holding a turn that
cites a Party entry (plain text) and turns a non-GM may no longer see (a
reply citing a GM-only entry, and a legacy turn with no `refs`), whose texts
are canaries. The Owner's seeded session (canary title and messages) is
another user's to everyone else. POST /api/chat/ and /stream (citations,
replay of a redacted session) are probed in retrieval.py.
"""
from __future__ import annotations

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.fixtures import mint_canary
from tests.ev4.probes._support import (
    MISSING, add_chat_session, authenticated, is_gm_of_a, redacted_messages, row_count,
)
from tests.ev4.registry import ev4_probe
from tests.ev4.report import record_leak

ACTORS = ("anon_share", "player", "cross_gm_player", "co_gm")
SESSIONS = "/api/chat/sessions"
MISSING_URL = f"{SESSIONS}/{MISSING}"


async def _own_sessions(ev4, actor):
    """(live, archived) sessions of `actor` in A, both with redacted turns."""
    live = await add_chat_session(ev4, actor.user_id, await redacted_messages(ev4))
    archived = await add_chat_session(ev4, actor.user_id, await redacted_messages(ev4), archived=True)
    return live, archived


def _owner_session(ev4):
    return ev4.a.ids["chat_sessions"][0]


async def _listed(actor, url: str) -> set[str]:
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    return {s["id"] for s in r.json()}


async def _gm_only_change(ev4) -> None:
    """Changes only a GM of A may see: the Shorthand of the cited Party entry,
    and a new session of the Owner's that mentions the searched words."""
    from app.db.models.journal import JournalEntry

    a = ev4.a.campaign_id
    entry = await ev4.db.get(JournalEntry, ev4.a.ids["journal_entries"][0])
    entry.shorthand = f"{entry.shorthand} {mint_canary('SHORTHAND', a).token} quiet guards"
    await ev4.db.commit()
    await add_chat_session(ev4, ev4.a.owner_id, [
        {"role": "user", "content": "Was the inn quiet?", "refs": []},
        {"role": "assistant", "content": f"{mint_canary('CHATREPLY', a).token} quiet guards.", "refs": []},
    ])


@ev4_probe("GET", "/api/chat/sessions", actors=ACTORS)
async def probe_chat_sessions(ev4, actor):
    r = await actor.get(SESSIONS)
    assert_no_canary(actor, r)
    if not authenticated(actor):
        return
    live, archived = await _own_sessions(ev4, actor)
    gm = is_gm_of_a(ev4, actor)
    listed = await _listed(actor, SESSIONS)
    assert str(live) in listed, listed  # non-vacuous: the actor's own live session
    if str(_owner_session(ev4)) in listed:
        record_leak(f"EV-4 leak: {actor.name} lists another user's chat session", [str(_owner_session(ev4))])
    if not gm and str(archived) in listed:
        record_leak(f"EV-4 leak: {actor.name} (not a GM of A) lists an archived session", [str(archived)])
    if gm:
        assert str(archived) in listed, listed  # a GM ctx still reads archived sessions

    # Search matches only what the actor may still read: "guards" is only
    # in the reply citing a GM-only entry, "quiet" in the visible reply.
    found = await _listed(actor, f"{SESSIONS}?search=guards")
    if not gm and found & {str(live), str(archived)}:
        record_leak(f"EV-4 leak: {actor.name}'s search matched a redacted message", sorted(found))
    if gm:
        assert str(live) in found, found
    assert str(live) in await _listed(actor, f"{SESSIONS}?search=quiet")
    await assert_counts_and_ranking_unchanged(
        actor, [SESSIONS, f"{SESSIONS}?search=quiet", f"{SESSIONS}?search=guards"], lambda: _gm_only_change(ev4))


@ev4_probe("GET", "/api/chat/sessions/{session_id}", actors=ACTORS)
async def probe_chat_session(ev4, actor):
    # Another user's session, a malformed id and a missing one are the same 404.
    await assert_hidden_equals_missing(actor, f"{SESSIONS}/{_owner_session(ev4)}", MISSING_URL)
    await assert_hidden_equals_missing(actor, f"{SESSIONS}/not-a-uuid", MISSING_URL)
    if not authenticated(actor):
        return
    live, archived = await _own_sessions(ev4, actor)
    gm = is_gm_of_a(ev4, actor)
    url = f"{SESSIONS}/{live}"
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    messages = r.json()["messages"]
    redacted = [m for m in messages if m["redacted"]]
    if gm:
        assert not redacted, messages  # a GM ctx sees what the reply cited, and legacy turns
    else:
        # Non-vacuous: the cited-GM-only reply and both legacy turns.
        assert len(redacted) == 3 and all(m["refs"] == [] for m in redacted), messages
        assert "shorthand" not in r.text
    if gm:
        r = await actor.get(f"{SESSIONS}/{archived}")
        assert r.status_code == 200, r.text  # read-only for a GM ctx
    else:
        await assert_hidden_equals_missing(actor, f"{SESSIONS}/{archived}", MISSING_URL)
    await assert_counts_and_ranking_unchanged(actor, url, lambda: _gm_only_change(ev4))


@ev4_probe("DELETE", "/api/chat/sessions/{session_id}", actors=ACTORS)
async def probe_chat_session_delete(ev4, actor):
    from app.db.models.chat import ChatSession

    owner_session = _owner_session(ev4)
    await assert_hidden_equals_missing(actor, f"{SESSIONS}/{owner_session}", MISSING_URL, method="DELETE")
    if await row_count(ev4, ChatSession, ChatSession.id == owner_session) != 1:
        record_leak(f"EV-4 leak: {actor.name} deleted another user's chat session", [str(owner_session)])
    if not authenticated(actor):
        return
    live, archived = await _own_sessions(ev4, actor)
    # Archived sessions are read-only, even to a GM ctx: DELETE answers like a missing one.
    await assert_hidden_equals_missing(actor, f"{SESSIONS}/{archived}", MISSING_URL, method="DELETE")
    if await row_count(ev4, ChatSession, ChatSession.id == archived) != 1:
        record_leak(f"EV-4 leak: {actor.name} deleted an archived session", [str(archived)])
    r = await actor.delete(f"{SESSIONS}/{live}")
    assert_no_canary(actor, r)
    assert r.status_code == 204, r.text  # the actor's own live session
    assert await row_count(ev4, ChatSession, ChatSession.id == live) == 0
