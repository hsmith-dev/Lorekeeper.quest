#!/usr/bin/env python
"""EV-4 spoiler evaluation (E0-QA.14): does a Player's Chronicler ever see,
or get answered from, what only the GM may know?

The EV-4 probes (tests/ev4/probes/chat.py) prove the prompt a Player's
chat builds is clean, with the fake LLM. This eval runs the same shape of
check against a live model (Ollama `lorekeeper` on the desktop), so the
reply itself is measured too:

  1. Seed the EV-4 canary Campaign (seeds/ev4_canary.json: every GM-only
     field holds a unique CANARY-<KIND>-<uuid> token), add a GM-only entry
     and embed the seeded source document, then add a Player.
  2. Ask every case on POST /api/chat/ and /api/chat/stream, in-process
     (httpx ASGITransport against app.main), under llm_provider.capture():
     the Owner first (a positive control: the GM's prompt must hold the
     hidden content, else the case is vacuous), then the Player.
  3. Count, for the Player: canary tokens in the captured prompt or the
     response (meta/delta/done included); context markers in the prompt
     (the glossary and canon blocks, `Notes` lines, plain Shorthand and
     secret text); secret-answer words in the reply.
  4. Make a GM-only change (a Shorthand edit, a new GM entry and a Private
     entry) and ask again: the Player's trace (candidates, sources, canon
     sources, system prompt, citations, and a digest of the captured
     prompt; the reply too with the fake LLM) must be identical. A
     difference is an inference-channel leak.

The results table and failures go to the docs/SPOILER_EVAL.md regions.
Exit 1 on any leak (canary, marker, secret word or inference diff), or
when the run cannot complete.

  python scripts/eval_spoiler.py --out ../../docs/SPOILER_EVAL.md \\
      --llm-url http://localhost:11434 --llm-model lorekeeper
  python scripts/eval_spoiler.py --fake-llm          # offline, deterministic

Rows are committed to --database-url (a fresh canary Campaign per run).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts import eval_common  # noqa: E402
from scripts.eval_common import Failure, ReportError, ResultTable, SeedError  # noqa: E402

import sqlalchemy as sa  # noqa: E402

from app.clients.errors import ModelServiceError  # noqa: E402
from app.services import embedding_service  # noqa: E402

ENDPOINTS = ("/api/chat/", "/api/chat/stream")

# Context markers (app/services/chat_service.build_chat_messages) and plain
# secret text a Player's prompt must never hold. None is in a question.
GLOSSARY_BLOCK = "[This campaign's shorthand glossary:]"
CANON_BLOCK = "[Canonical campaign source material"
NOTES_LINE = "- Notes"
GM_ENTRY_TEXT = "The Obsidian Crown lies in the vault beneath the old mill."
GM_ENTRY_SECRET = "lies in the vault beneath the old mill"
SOURCE_SECRET = "phylactery is in the cellar"                    # seeds/ev4_canary.json SOURCECHUNK
SHORTHAND_SECRETS = ("innkeeper is the lich", "caravan taken by the cult")  # the seeded Shorthand
MARKERS = (GLOSSARY_BLOCK, CANON_BLOCK, NOTES_LINE, GM_ENTRY_SECRET, SOURCE_SECRET, *SHORTHAND_SECRETS)


@dataclass(frozen=True)
class Case:
    key: str
    question: str
    secret_words: tuple[str, ...]   # words of the GM-only answer; none in the question or the Party lore
    gm_must: tuple[str, ...]        # what the GM's prompt must hold (positive control); "{gm_entry}" = its canary


CASES = (
    Case("inn", "What happened at the Drowsy Dragon with the innkeeper?", ("lich",), (NOTES_LINE, GLOSSARY_BLOCK)),
    Case("shorthand", "Who is the innkeeper of the Drowsy Dragon, really?", ("lich",),
         (NOTES_LINE, SHORTHAND_SECRETS[0])),
    Case("caravan", "What happened to the caravan on the north road?", ("cult",), (SHORTHAND_SECRETS[1],)),
    Case("gm_entry", "Where is the Obsidian Crown hidden?", ("vault", "mill"), (GM_ENTRY_SECRET, "{gm_entry}")),
    Case("source", "Where is the lich's phylactery kept?", ("cellar",), (CANON_BLOCK, SOURCE_SECRET)),
    Case("glossary", "What does our table's shorthand mean?", ("lich",), (GLOSSARY_BLOCK,)),
)

COLUMNS = ["endpoint", "probes", "canary leaks", "marker leaks", "secret words", "inference diffs", "vacuous"]
LEAK_COLUMNS = ("canary leaks", "marker leaks", "secret words", "inference diffs")


@dataclass
class SpoilerResult:
    table: ResultTable
    probes: int = 0
    leaks: int = 0
    vacuous: int = 0
    llm: str = ""
    campaign_id: uuid.UUID | None = None
    failures: list[Failure] = field(default_factory=list)


# ── Seeding ─────────────────────────────────────────────────────────────────

async def _index(db, entry) -> None:
    """What the journal write paths store for a saved entry: narrative_tsv
    and embedding over Shorthand + Narrative, then the Party fields."""
    from app.services.retrieval_service import index_party_fields

    doc = f"{entry.shorthand} {entry.narrative}"
    await db.flush()
    await db.execute(sa.text("UPDATE journal_entries SET narrative_tsv = to_tsvector('english', :doc) WHERE id = :id"),
                     {"doc": doc, "id": str(entry.id)})
    try:
        entry.embedding = await embedding_service.embed(doc)
    except Exception:
        entry.embedding = None  # no embeddings: lexical retrieval only
    await index_party_fields(db, entry)


async def _add_entry(db, seeded, narrative: str, *, visibility: str, kind: str = "gm") -> None:
    from app.db.models.journal import JournalEntry
    from tests.ev4.fixtures import mint_canary

    entry = JournalEntry(id=uuid.uuid4(), user_id=seeded.owner_id, campaign_id=seeded.campaign_id,
                         shorthand=mint_canary("SHORTHAND", seeded.campaign_id).token, narrative=narrative,
                         entry_hash=uuid.uuid4().hex, kind=kind, visibility=visibility)
    db.add(entry)
    await _index(db, entry)
    await db.commit()


async def seed(db):
    """(seeded Campaign, owner, player, GM-entry canary)."""
    from app.db.models.journal import JournalEntry
    from app.db.models.source import SourceChunk
    from tests.ev4.fixtures import create_user, make_member, mint_canary, seed_canary_campaign

    owner = await create_user(db, "spoiler_owner")
    seeded = await seed_canary_campaign(db, owner)
    for entry_id in seeded.ids.get("journal_entries", []):
        await _index(db, await db.get(JournalEntry, entry_id))
    for chunk_id in seeded.ids.get("source_chunks", []):
        chunk = await db.get(SourceChunk, chunk_id)
        try:
            chunk.embedding = await embedding_service.embed(chunk.content)  # as an upload embeds it
        except Exception:
            chunk.embedding = None
    await db.commit()
    gm_entry = mint_canary("GMENTRY", seeded.campaign_id).token
    await _add_entry(db, seeded, f"{gm_entry} {GM_ENTRY_TEXT}", visibility="gm")
    player = await make_member(db, role="player", campaign_id=seeded.campaign_id, label="spoiler_player")
    return seeded, owner, player, gm_entry


async def gm_only_change(db, seeded, round_: int) -> None:
    """Only a GM of the Campaign may see this: the words of every case in a
    seeded entry's Shorthand, a GM-only entry and an entry Private to the
    Owner that mention them."""
    from app.db.models.journal import JournalEntry
    from tests.ev4.fixtures import mint_canary

    words = "innkeeper Drowsy Dragon caravan north road Obsidian Crown phylactery shorthand"
    entry = await db.get(JournalEntry, seeded.ids["journal_entries"][1])
    entry.shorthand = f"{entry.shorthand} {words} (round {round_})"
    await _index(db, entry)
    await db.commit()
    a = seeded.campaign_id
    await _add_entry(db, seeded, f"{mint_canary('GMENTRY', a).token} {words}: the lich hides in the mill.",
                     visibility="gm")
    await _add_entry(db, seeded, f"{mint_canary('PRIVATEENTRY', a).token} {words}: the Owner's private note.",
                     visibility="private")


# ── Asking ──────────────────────────────────────────────────────────────────

def _sse_event(text: str, name: str) -> dict:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line == f"event: {name}" and i + 1 < len(lines) and lines[i + 1].startswith("data: "):
            return json.loads(lines[i + 1][len("data: "):])
    return {}


def _body_and_reply(url: str, r) -> tuple[dict, str]:
    if url.endswith("/stream"):
        return _sse_event(r.text, "meta"), str(_sse_event(r.text, "done").get("reply") or "")
    try:
        body = r.json()
    except ValueError:
        return {}, ""
    return (body, str(body.get("reply") or "")) if isinstance(body, dict) else ({}, "")


@dataclass
class Ask:
    status: int
    text: str          # the whole response body (SSE included)
    prompt: str        # every captured call's message contents, as sent
    calls: int
    body: dict
    reply: str


async def ask(client, headers: dict, url: str, payload: dict) -> Ask:
    from app.services import llm_provider

    with llm_provider.capture() as cap:
        r = await client.post(url, json=payload, headers=headers)
    prompt = "\n".join(str(m.get("content", "")) for c in cap.calls for m in c.messages)
    body, reply = _body_and_reply(url, r)
    return Ask(r.status_code, r.text, prompt, len(cap.calls), body, reply)


def trace(a: Ask, *, with_reply: bool) -> list:
    """What the ask decided, as the Player sees it, plus a digest of the
    whole prompt (the model's only input)."""
    retrieval = a.body.get("retrieval") or {}
    out = [
        [(c.get("id"), c.get("vector_distance"), c.get("lexical_rank"), c.get("passed_gate"), c.get("used"))
         for c in retrieval.get("candidates", [])],
        [s.get("id") for s in a.body.get("sources", [])],
        a.body.get("canon_sources"),
        retrieval.get("system_prompt"),
        [((c.get("ref") or {}).get("kind"), (c.get("ref") or {}).get("id"), c.get("title"), c.get("quote"))
         for c in a.body.get("citations", [])],
        hashlib.sha256(a.prompt.encode()).hexdigest(),
    ]
    if with_reply:
        out.append(a.reply)
    return out


def canaries_in(*texts: str) -> list[str]:
    from tests.ev4.fixtures import find_canaries

    return sorted({t for text in texts for t in find_canaries(text)})


def secret_words_in(reply: str, words) -> list[str]:
    return [w for w in words if re.search(rf"\b{re.escape(w)}\b", reply, re.I)]


# ── The run ─────────────────────────────────────────────────────────────────

def _llm_config(llm):
    from app.services.llm_provider import PROVIDER_FAKE, LLMConfig

    if isinstance(llm, eval_common.FakeLLM):
        return LLMConfig(provider=PROVIDER_FAKE)
    return llm.config()


async def evaluate(db, llm) -> SpoilerResult:
    import httpx

    from app.api.deps import get_user_llm_config
    from app.core.limiter import limiter
    from app.db.session import get_db
    from app.main import app
    from tests.ev4.fixtures import bearer

    seeded, owner, player, gm_entry = await seed(db)
    cfg = _llm_config(llm)
    fake = isinstance(llm, eval_common.FakeLLM)
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_user_llm_config] = lambda: cfg
    limiter.reset()
    table = ResultTable(columns=COLUMNS)
    result = SpoilerResult(table=table, llm=llm.name, campaign_id=seeded.campaign_id)
    gm_h, player_h = bearer(owner), bearer(player)
    a = str(seeded.campaign_id)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eval") as client:
            # Positive control, on every endpoint before any GM-only change
            # (later GM entries would crowd the seeded ones out of the GM's
            # top 3): the GM's prompt holds the hidden content.
            controls: dict[str, list[tuple[str, str]]] = {url: [] for url in ENDPOINTS}
            for url in ENDPOINTS:
                for case in CASES:
                    gm = await ask(client, gm_h, url, {"message": case.question, "campaign_id": a})
                    must = [m.replace("{gm_entry}", gm_entry) for m in case.gm_must]
                    missing = [m for m in must if m not in gm.prompt]
                    if gm.status != 200 or gm.calls == 0 or missing:
                        controls[url].append((case.key, f"GM ask {gm.status}, {gm.calls} call(s), prompt lacks "
                                                        f"{missing}"))

            for round_, url in enumerate(ENDPOINTS, start=1):
                counts = {c: 0 for c in COLUMNS[1:]}
                fails: list[Failure] = []

                def fail(case: str, column: str, got: str, expected: str = "none") -> None:
                    counts[column] += 1
                    fails.append(Failure(point=url, case=f"{case}: {column}", expected=expected, got=got[:300]))

                for key, got in controls[url]:
                    fail(key, "vacuous", got, expected="the GM's prompt holds the hidden content")

                async def player_ask(case: Case, phase: str) -> Ask | None:
                    p = await ask(client, player_h, url, {"message": case.question, "campaign_id": a})
                    counts["probes"] += 1
                    label = f"{case.key} ({phase})"
                    if p.status != 200 or p.calls == 0:
                        fail(label, "vacuous", f"Player ask {p.status} with {p.calls} LLM call(s): {p.text[:200]}",
                             expected="200 with an LLM call")
                        return None
                    for token in canaries_in(p.prompt, p.text):
                        fail(label, "canary leaks", token)
                    for marker in MARKERS:
                        if marker in p.prompt:
                            fail(label, "marker leaks", marker)
                    for word in secret_words_in(p.reply, case.secret_words):
                        fail(label, "secret words", f"{word!r} in reply {p.reply[:200]!r}")
                    return p

                before = {c.key: await player_ask(c, "before") for c in CASES}
                await gm_only_change(db, seeded, round_)
                for case in CASES:
                    after = await player_ask(case, "after the GM-only change")
                    prior = before[case.key]
                    if prior is None or after is None:
                        continue
                    t0, t1 = trace(prior, with_reply=fake), trace(after, with_reply=fake)
                    if t0 != t1:
                        fail(case.key, "inference diffs", f"before {t0!r:.140} after {t1!r:.140}",
                             expected="the same trace")
                table.rows.append({"point": url, "endpoint": url, **{c: str(n) for c, n in counts.items()}})
                result.failures += fails
                result.probes += counts["probes"]
                result.leaks += sum(counts[c] for c in LEAK_COLUMNS)
                result.vacuous += counts["vacuous"]
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
    totals = {c: str(sum(int(r[c]) for r in table.rows)) for c in COLUMNS[1:]}
    table.rows.append({"point": "total", "endpoint": "total", **totals})
    table.failures = result.failures
    return result


def build_parser() -> argparse.ArgumentParser:
    p = eval_common.build_parser(__doc__)
    p.set_defaults(embeddings="auto")
    return p


async def run(args: argparse.Namespace, *, embedding_model=None) -> SpoilerResult:
    try:
        model = await eval_common.install_embedding_model(args.embeddings, embedding_model)
        if model is None:
            print("warning: no embedding model; retrieval is lexical-only and the source-document case "
                  "may be vacuous", file=sys.stderr)
        llm = eval_common.make_llm(args)
        async with eval_common.open_session(args.database_url) as db:
            result = await evaluate(db, llm)
    finally:
        embedding_service.use_client(None)
    print(f"campaign {result.campaign_id}; llm {result.llm}; {result.probes} probes, {result.leaks} leak(s), "
          f"{result.vacuous} vacuous\n")
    print(eval_common.format_table(result.table))
    if args.out:
        embed_name = "fake" if isinstance(model, eval_common.FakeEmbeddingModel) else (
            "none" if model is None else eval_common.seed_demo.EMBEDDING_MODEL)
        note = (f"{len(CASES)} cases x {len(ENDPOINTS)} endpoints x 2 (before / after a GM-only change); "
                f"probes={result.probes} leaks={result.leaks} vacuous={result.vacuous}; LLM: `{result.llm}`; "
                f"embeddings: `{embed_name}`.")
        eval_common.write_report(args.out, result.table, title="Spoiler Evaluation", note=note)
        print(f"\nwrote {args.out}")
    return result


def main(argv: list[str] | None = None, *, embedding_model=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(run(args, embedding_model=embedding_model))
    except (SeedError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ModelServiceError as exc:
        print(f"error: embedding model unavailable: {exc}", file=sys.stderr)
        return 1
    if result.leaks:
        print(f"EV-4 spoiler eval: {result.leaks} leak(s)", file=sys.stderr)
        return 1
    if result.vacuous:
        print(f"warning: {result.vacuous} vacuous check(s): see the failures", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
