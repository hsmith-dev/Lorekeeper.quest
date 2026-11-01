#!/usr/bin/env python
"""Shared scaffold for the eval scripts (EV-1, EV-2, EV-3, EV-5, EV-6, and
eval_retrieval.py).

One seed, one CLI, one report format, so every eval runs the same way and
offline:

  load_campaign  the demo Campaign: seeds it (idempotent) unless
                 --campaign-id names an existing one
  sweep          run an evaluation at each operating point -> ResultTable
  format_table   the fixed-width table used in the docs/*_EVAL.md code blocks
  write_report   fill the generated regions of a docs/*_EVAL.md, never the
                 hand-written prose; a missing doc starts from
                 docs/EVAL_TEMPLATE.md
  build_parser   the shared CLI flags
  make_llm       the LLM handle: Ollama (OpenAI-compatible, ungated) at a
                 configurable URL, or a deterministic fake
  open_session   an AsyncSession on --database-url

Running this module directly is a smoke run: seed, one LLM question per
window of entries, a table on stdout (and in --out if given):

  python scripts/eval_common.py --fake-llm
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import math
import os
import re
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts import seed_demo  # noqa: E402  (sets HF_HUB_OFFLINE before any HF import)
from scripts.seed_demo import EMBEDDING_MODES, SeedError  # noqa: E402

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models.campaign import Campaign  # noqa: E402
from app.db.models.journal import EMBEDDING_DIM, JournalEntry  # noqa: E402

try:
    REPO_ROOT: Path | None = Path(__file__).resolve().parents[3]
except IndexError:  # the container's /app/scripts is too shallow
    REPO_ROOT = None
DOCS_DIR = (REPO_ROOT / "docs") if REPO_ROOT else (_BACKEND_DIR / "docs")
TEMPLATE_PATH = DOCS_DIR / "EVAL_TEMPLATE.md"

RESULTS_REGION = "eval:results"
FAILURES_REGION = "eval:failures"


class ReportError(Exception):
    """An existing report lacks a generated-region marker (doc left unchanged)."""


# ── Session and campaign ────────────────────────────────────────────────────

@asynccontextmanager
async def open_session(database_url: str | None):
    if not database_url:
        raise SeedError("no database: pass --database-url or set DATABASE_URL")
    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


@dataclass
class CampaignData:
    campaign: Campaign
    entries: list[JournalEntry]  # oldest first
    seed: dict | None = None
    seed_result: seed_demo.SeedResult | None = None

    @property
    def id(self) -> uuid.UUID:
        return self.campaign.id


async def load_campaign(
    seed: str | os.PathLike | dict | None,
    session: AsyncSession,
    campaign_id: uuid.UUID | None = None,
    *,
    owner_email: str | None = None,
    embedder: seed_demo.Embedder | None = None,
) -> CampaignData:
    """An existing Campaign by id, or the seed (a path, an already-read seed
    dict, or None for seeds/demo_campaign.json), seeded idempotently."""
    seed_result = None
    if campaign_id is None:
        if not isinstance(seed, dict):
            seed = seed_demo.read_seed(seed or seed_demo.DEFAULT_SEED_PATH)
        seed_result = await seed_demo.seed_campaign(session, seed, owner_email, embedder)
        campaign_id = seed_result.campaign_id
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise SeedError(f"no campaign with id {campaign_id}")
    rows = await session.scalars(
        select(JournalEntry).where(JournalEntry.campaign_id == campaign_id)
        .order_by(JournalEntry.session_date.asc().nulls_last(), JournalEntry.created_at.asc())
    )
    return CampaignData(campaign=campaign, entries=list(rows), seed=seed, seed_result=seed_result)


# ── Embeddings ──────────────────────────────────────────────────────────────

class FakeEmbeddingModel:
    """Deterministic stand-in for the SentenceTransformer: a hashed bag of
    lowercase words, L2-normalised. Shared words -> smaller cosine distance,
    which is enough to exercise the vector path in tests without the model."""

    dim = EMBEDDING_DIM

    def encode(self, text: str, normalize_embeddings: bool = True):
        vec = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            h = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big")
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return _List([v / norm for v in vec])


class _List(list):
    def tolist(self) -> list[float]:
        return list(self)


def install_embedding_model(mode: str = "auto", model=None):
    """Load (or take) the embedding model and install it where
    app.services.embedding_service.embed reads it, so retrieval_service and
    the seed embed the same way. Returns the model, or None (no vectors)."""
    from app.services import embedding_service

    if model is None:
        model = seed_demo.load_embedding_model(mode)
    embedding_service._model = model
    return model


# ── Sweeps and tables ───────────────────────────────────────────────────────

@dataclass
class Failure:
    point: str      # operating-point label
    case: str       # the query / input that failed
    expected: str
    got: str


@dataclass
class ResultTable:
    columns: list[str]
    rows: list[dict] = field(default_factory=list)   # each has a "point" label + one value per column
    chosen: str | None = None                         # label of the chosen operating point
    failures: list[Failure] = field(default_factory=list)
    chosen_marker: str = "← chosen operating point"

    def row(self, point: str) -> dict:
        for r in self.rows:
            if r["point"] == point:
                return r
        raise KeyError(point)


Evaluation = Callable[[object], Awaitable[tuple[dict, list[Failure]]]]


async def sweep(
    points: Sequence[tuple[str, object]],
    evaluate: Evaluation,
    *,
    columns: Sequence[str],
    chosen: str | None = None,
    chosen_marker: str | None = None,
) -> ResultTable:
    """Run `evaluate(point)` at each (label, point); it returns (column
    values, failures). Rows keep the order of `points`."""
    table = ResultTable(columns=list(columns), chosen=chosen)
    if chosen_marker:
        table.chosen_marker = chosen_marker
    labels = [label for label, _ in points]
    if chosen is not None and chosen not in labels:
        raise ValueError(f"chosen point {chosen!r} is not one of {labels}")
    for label, point in points:
        values, failures = await evaluate(point)
        missing = [c for c in columns if c not in values]
        if missing:
            raise ValueError(f"evaluation at {label!r} returned no value for {missing}")
        table.rows.append({"point": label, **values})
        table.failures.extend(failures)
    return table


def format_table(table: ResultTable) -> str:
    """Fixed-width text in the RETRIEVAL_EVAL.md results style."""
    cells = [[str(r[c]) for c in table.columns] for r in table.rows]
    widths = [max([len(c)] + [len(row[i]) for row in cells]) for i, c in enumerate(table.columns)]

    def line(vals: Sequence[str]) -> str:
        return " | ".join(v.rjust(w) if i == 0 else v.ljust(w) for i, (v, w) in enumerate(zip(vals, widths)))

    header = line(table.columns).rstrip()
    out = [header, "-" * len(line(table.columns))]
    for r, row in zip(table.rows, cells):
        text = line(row).rstrip()
        if table.chosen is not None and r["point"] == table.chosen:
            text = f"{line(row)}   {table.chosen_marker}"
        out.append(text)
    return "\n".join(out)


def format_failures(table: ResultTable) -> str:
    if not table.failures:
        return "_No failures._"
    lines = ["| Point | Case | Expected | Got |", "|---|---|---|---|"]
    for f in table.failures:
        lines.append(f"| {_cell(f.point)} | {_cell(f.case)} | {_cell(f.expected)} | {_cell(f.got)} |")
    return "\n".join(lines)


def _cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


# ── Reports ─────────────────────────────────────────────────────────────────

def _region_re(name: str) -> re.Pattern:
    return re.compile(rf"(<!-- {re.escape(name)} -->)(.*?)(<!-- /{re.escape(name)} -->)", re.S)


def _replace_region(doc: str, name: str, body: str) -> str:
    return _region_re(name).sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", doc, count=1)


def write_report(
    path: str | os.PathLike,
    table: ResultTable,
    chosen_point: str | None = None,
    failures: Sequence[Failure] | None = None,
    *,
    title: str = "Evaluation",
    template_path: str | os.PathLike | None = None,
    note: str | None = None,
) -> Path:
    """Rewrite only the results and failures regions of `path`. A missing
    doc is created from the template first. ReportError (doc unchanged) if a
    marker is missing. `chosen_point` / `failures` override the table's own
    (sweep fills both)."""
    if chosen_point is not None or failures is not None:
        table = ResultTable(
            columns=table.columns, rows=table.rows,
            chosen=chosen_point if chosen_point is not None else table.chosen,
            failures=list(failures) if failures is not None else table.failures,
            chosen_marker=table.chosen_marker,
        )
        if table.chosen is not None and table.chosen not in [r["point"] for r in table.rows]:
            raise ValueError(f"chosen point {table.chosen!r} is not a row of the table")
    p = Path(path)
    if p.exists():
        doc = p.read_text(encoding="utf-8")
    else:
        tpl = Path(template_path or TEMPLATE_PATH)
        if not tpl.exists():
            raise ReportError(f"template not found: {tpl}")
        doc = tpl.read_text(encoding="utf-8").replace("{{title}}", title)

    for name in (RESULTS_REGION, FAILURES_REGION):
        if not _region_re(name).search(doc):
            raise ReportError(f"{p}: missing region <!-- {name} -->…<!-- /{name} -->")

    results = f"```\n{format_table(table)}\n```"
    if note:
        results += f"\n\n{note}"
    doc = _replace_region(doc, RESULTS_REGION, results)
    doc = _replace_region(doc, FAILURES_REGION, format_failures(table))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc, encoding="utf-8")
    return p


# ── LLM handle ──────────────────────────────────────────────────────────────

class FakeLLM:
    """Deterministic, offline. No app/clients/fakes.py LLM fake exists yet
    (E0-LLM.5); when it does, this can delegate to it."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def complete(self, messages: list[dict], **_: object) -> str:
        self.calls.append(messages)
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        digest = hashlib.sha256(last.encode()).hexdigest()[:8]
        first = " ".join(last.split()[:12])
        return f"[fake-llm {digest}] {first}"


class OllamaLLM:
    """The stack's Ollama through llm_provider.complete_messages with
    provider="custom": OpenAI-compatible at `url`, ungated (no Redis)."""

    def __init__(self, url: str, model: str, *, temperature: float = 0.0, max_tokens: int = 400) -> None:
        self.url = url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def name(self) -> str:
        return f"ollama:{self.model}@{self.url}"

    def config(self):
        from app.services.llm_provider import LLMConfig

        return LLMConfig(provider="custom", api_url=self.url, model=self.model,
                         temperature=self.temperature, max_tokens=self.max_tokens)

    async def complete(self, messages: list[dict], **kwargs) -> str:
        from app.services import llm_provider

        return await llm_provider.complete_messages(messages, self.config(), **kwargs)


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def make_llm(args: argparse.Namespace, environ=os.environ):
    """FakeLLM if --fake-llm or EVAL_FAKE_LLM=1. Otherwise OllamaLLM with
    URL --llm-url > EVAL_LLM_URL > settings.kobold_url and model
    --llm-model > EVAL_LLM_MODEL > settings.local_llm_model."""
    if getattr(args, "fake_llm", False) or _truthy(environ.get("EVAL_FAKE_LLM")):
        return FakeLLM()
    url = getattr(args, "llm_url", None) or environ.get("EVAL_LLM_URL")
    model = getattr(args, "llm_model", None) or environ.get("EVAL_LLM_MODEL")
    if not url or not model:
        from app.core.config import get_settings

        s = get_settings()
        url = url or s.kobold_url
        model = model or s.local_llm_model
    return OllamaLLM(url, model)


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser(description: str | None = None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                   help="SQLAlchemy async URL (default: $DATABASE_URL)")
    p.add_argument("--campaign-id", type=uuid.UUID, default=None,
                   help="evaluate this Campaign (default: seed the demo Campaign and use it)")
    p.add_argument("--seed", default=str(seed_demo.DEFAULT_SEED_PATH), help="seed file (default: %(default)s)")
    p.add_argument("--owner-email", default=None, help="owner of the seeded Campaign")
    p.add_argument("--embeddings", choices=EMBEDDING_MODES, default="auto",
                   help="embedding model: auto (if cached), require, skip")
    p.add_argument("--llm-url", default=None, help="OpenAI-compatible base URL (default: $EVAL_LLM_URL, then KOBOLD_URL)")
    p.add_argument("--llm-model", default=None, help="model name (default: $EVAL_LLM_MODEL, then LOCAL_LLM_MODEL)")
    p.add_argument("--fake-llm", action="store_true", help="deterministic fake LLM (also EVAL_FAKE_LLM=1)")
    p.add_argument("--out", default=None, help="report to write, e.g. docs/X_EVAL.md")
    return p


# ── Smoke run ───────────────────────────────────────────────────────────────

WINDOW = 3


async def smoke(args: argparse.Namespace, *, embedding_model=None) -> ResultTable:
    model = install_embedding_model(args.embeddings, embedding_model)
    embedder = seed_demo.embedder_from_model(model)
    llm = make_llm(args)
    async with open_session(args.database_url) as session:
        data = await load_campaign(args.seed, session, args.campaign_id,
                                   owner_email=args.owner_email, embedder=embedder)
    entries = data.entries
    windows = []
    for i in range(0, len(entries), WINDOW):
        label = f"{i + 1}-{min(i + WINDOW, len(entries))}"
        windows.append((label, (label, entries[i:i + WINDOW])))

    async def evaluate(point):
        label, window = point
        context = "\n\n".join(e.narrative for e in window)
        messages = [
            {"role": "system", "content": "You summarise tabletop campaign journals."},
            {"role": "user", "content": f"In one sentence, what happened in these sessions?\n\n{context}"},
        ]
        t0 = time.perf_counter()
        try:
            reply = await llm.complete(messages)
            ok, err = bool(reply.strip()), ""
        except Exception as exc:
            reply, ok, err = "", False, f"{type(exc).__name__}: {exc}"
        ms = int((time.perf_counter() - t0) * 1000)
        fails = [] if ok else [Failure(point=label, case="summarise window",
                                       expected="a reply", got=err or "empty reply")]
        return {"window": label, "entries": str(len(window)), "reply chars": str(len(reply)),
                "ms": str(ms), "ok": "yes" if ok else "no"}, fails

    table = await sweep(windows, evaluate, columns=["window", "entries", "reply chars", "ms", "ok"])
    print(f"campaign {data.id}; {len(entries)} entries; llm {llm.name}")
    print(format_table(table))
    if args.out:
        write_report(args.out, table, title="Eval scaffold smoke run", note=f"LLM: `{llm.name}`.")
    return table


def main(argv: list[str] | None = None) -> int:
    args = build_parser(__doc__).parse_args(argv)
    try:
        asyncio.run(smoke(args))
    except (SeedError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
