"""scripts/eval_common.py and eval_retrieval.py on top of it (E0-QA.12)."""

import argparse
import json
import re
import uuid

import httpx
import pytest

from app.core.config import get_settings
from app.core import llm_gate
from app.services import embedding_service, llm_provider
from scripts import eval_common, eval_retrieval, seed_demo
from scripts.eval_common import (
    FakeEmbeddingModel, FakeLLM, Failure, OllamaLLM, ReportError, ResultTable,
    format_table, make_llm, sweep, write_report,
)
from tests.conftest import TEST_DB_URL


def _table(chosen="b") -> ResultTable:
    t = ResultTable(columns=["thresh", "mode", "score"], chosen=chosen)
    t.rows = [
        {"point": "a", "thresh": "0.50", "mode": "x", "score": "1/2"},
        {"point": "b", "thresh": "0.60", "mode": "y", "score": "2/2"},
    ]
    t.failures = [Failure("a", "q | with pipe", "e1", "nothing")]
    return t


# ── sweep / table ───────────────────────────────────────────────────────────

async def test_sweep_runs_each_point_in_order():
    seen = []

    async def evaluate(point):
        seen.append(point)
        return {"n": str(point * 2)}, ([Failure(str(point), "c", "e", "g")] if point == 2 else [])

    t = await sweep([("one", 1), ("two", 2)], evaluate, columns=["n"], chosen="two")
    assert seen == [1, 2]
    assert [r["point"] for r in t.rows] == ["one", "two"]
    assert t.row("two")["n"] == "4"
    assert [f.point for f in t.failures] == ["2"]


async def test_sweep_rejects_unknown_chosen_and_missing_columns():
    async def evaluate(point):
        return {}, []

    with pytest.raises(ValueError, match="chosen"):
        await sweep([("a", 1)], evaluate, columns=[], chosen="zzz")
    with pytest.raises(ValueError, match="no value"):
        await sweep([("a", 1)], evaluate, columns=["n"])


def test_format_table_marks_the_chosen_row():
    lines = format_table(_table()).splitlines()
    assert lines[0].split(" | ")[0].strip() == "thresh"
    assert set(lines[1]) == {"-"}
    assert len(lines) == 4
    assert "←" not in lines[2]
    assert lines[3].endswith("← chosen operating point") and "0.60" in lines[3]


# ── reports ─────────────────────────────────────────────────────────────────

def test_report_created_from_template(tmp_path):
    out = tmp_path / "docs" / "X_EVAL.md"
    write_report(out, _table(), title="X Evaluation")
    doc = out.read_text()
    assert doc.startswith("# X Evaluation")
    assert "{{title}}" not in doc
    results = re.search(r"<!-- eval:results -->(.*?)<!-- /eval:results -->", doc, re.S).group(1)
    assert "← chosen operating point" in results and "Not run yet" not in results
    failures = re.search(r"<!-- eval:failures -->(.*?)<!-- /eval:failures -->", doc, re.S).group(1)
    assert "q \\| with pipe" in failures
    # The template's hand-written sections come along.
    assert "## Method" in doc and "## Reproducing" in doc


def test_report_rewrites_only_the_regions(tmp_path):
    out = tmp_path / "R.md"
    prose_top = "# Mine\n\nHand-written intro that must survive.\n\n"
    prose_mid = "\n\nA paragraph between the regions.\n\n"
    prose_end = "\n\n## Reproducing\nby hand\n"
    out.write_text(
        prose_top + "<!-- eval:results -->\nold table\n<!-- /eval:results -->"
        + prose_mid + "<!-- eval:failures -->\nold failures\n<!-- /eval:failures -->" + prose_end
    )
    write_report(out, _table())
    doc = out.read_text()
    assert doc.startswith(prose_top)
    assert prose_mid in doc and doc.endswith(prose_end)
    assert "old table" not in doc and "old failures" not in doc

    # A second run replaces, never appends.
    write_report(out, _table(chosen="a"))
    doc2 = out.read_text()
    assert doc2.count("<!-- eval:results -->") == 1
    assert doc2.count("← chosen operating point") == 1


def test_no_failures_says_so(tmp_path):
    t = _table()
    t.failures = []
    out = tmp_path / "R.md"
    write_report(out, t)
    assert "_No failures._" in out.read_text()


@pytest.mark.parametrize("missing", ["eval:results", "eval:failures"])
def test_missing_marker_raises_and_leaves_doc_unchanged(tmp_path, missing):
    regions = {
        "eval:results": "<!-- eval:results -->\nx\n<!-- /eval:results -->",
        "eval:failures": "<!-- eval:failures -->\ny\n<!-- /eval:failures -->",
    }
    regions.pop(missing)
    out = tmp_path / "R.md"
    original = "# Hand-written\n\n" + "\n\n".join(regions.values()) + "\n"
    out.write_text(original)
    with pytest.raises(ReportError, match=missing):
        write_report(out, _table())
    assert out.read_text() == original


def test_committed_docs_have_both_regions():
    for name in ("EVAL_TEMPLATE.md", "RETRIEVAL_EVAL.md"):
        doc = (eval_common.DOCS_DIR / name).read_text()
        for region in (eval_common.RESULTS_REGION, eval_common.FAILURES_REGION):
            assert doc.count(f"<!-- {region} -->") == 1, (name, region)
            assert doc.count(f"<!-- /{region} -->") == 1, (name, region)


# ── LLM handle ──────────────────────────────────────────────────────────────

def _args(*argv) -> argparse.Namespace:
    return eval_common.build_parser().parse_args(list(argv))


def test_fake_llm_selected_by_flag_or_env():
    assert isinstance(make_llm(_args("--fake-llm"), environ={}), FakeLLM)
    assert isinstance(make_llm(_args(), environ={"EVAL_FAKE_LLM": "1"}), FakeLLM)
    assert isinstance(make_llm(_args(), environ={"EVAL_FAKE_LLM": "0"}), OllamaLLM)


async def test_fake_llm_is_deterministic():
    a, b = FakeLLM(), FakeLLM()
    msgs = [{"role": "user", "content": "What happened at the mill?"}]
    assert await a.complete(msgs) == await b.complete(msgs)
    assert await a.complete(msgs) != await a.complete([{"role": "user", "content": "else"}])
    assert len(a.calls) == 3


def test_llm_url_and_model_precedence():
    s = get_settings()
    llm = make_llm(_args(), environ={})
    assert (llm.url, llm.model) == (s.kobold_url, s.local_llm_model)

    env = {"EVAL_LLM_URL": "http://env:11434", "EVAL_LLM_MODEL": "env-model"}
    llm = make_llm(_args(), environ=env)
    assert (llm.url, llm.model) == ("http://env:11434", "env-model")

    llm = make_llm(_args("--llm-url", "http://flag:1", "--llm-model", "flag-model"), environ=env)
    assert (llm.url, llm.model) == ("http://flag:1", "flag-model")

    llm = make_llm(_args("--llm-model", "flag-model"), environ={"EVAL_LLM_URL": "http://env:11434"})
    assert (llm.url, llm.model) == ("http://env:11434", "flag-model")


async def test_ollama_llm_calls_custom_provider_ungated(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": "  the answer  "}}]})

    async def no_gate(*a, **k):
        raise AssertionError("the eval LLM must not take a gate slot")

    monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(llm_gate, "acquire", no_gate)

    llm = make_llm(_args("--llm-url", "http://ollama.test:11434/", "--llm-model", "qwen-eval"), environ={})
    assert llm.config().provider == "custom"
    reply = await llm.complete([{"role": "user", "content": "hi"}])
    assert reply == "the answer"
    assert len(seen) == 1
    url, body = seen[0]
    assert url == "http://ollama.test:11434/v1/chat/completions"
    assert body["model"] == "qwen-eval"
    assert body["messages"] == [{"role": "user", "content": "hi"}]


# ── End to end ──────────────────────────────────────────────────────────────

async def test_eval_retrieval_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(embedding_service, "_model", None)  # restored after the test
    out = tmp_path / "RETRIEVAL_X_EVAL.md"
    email = f"eval_{uuid.uuid4().hex[:10]}@example.com"

    # First run seeds the demo campaign (no --campaign-id) ...
    args = eval_retrieval.build_parser().parse_args([
        "--database-url", TEST_DB_URL, "--owner-email", email, "--fake-llm", "--out", str(out),
    ])
    await eval_retrieval.run(args, embedding_model=FakeEmbeddingModel())
    campaign_id = re.search(r"campaign ([0-9a-f-]{36})", capsys.readouterr().out).group(1)

    # ... the CI command then runs against it by id.
    args = eval_retrieval.build_parser().parse_args([
        "--database-url", TEST_DB_URL, "--fake-llm", "--campaign-id", campaign_id, "--out", str(out),
    ])
    table = await eval_retrieval.run(args, embedding_model=FakeEmbeddingModel())
    assert len(table.rows) == 6
    assert table.chosen == "hybrid@0.65"
    assert all(f.point == "hybrid@0.65" for f in table.failures)

    doc = out.read_text()
    block = re.search(r"<!-- eval:results -->\n```\n(.*?)\n```", doc, re.S).group(1).splitlines()
    rows = block[2:]
    assert len(rows) == 6
    marked = [r for r in rows if "← production operating point" in r]
    assert len(marked) == 1 and "0.65" in marked[0] and "hybrid" in marked[0]
    assert "12 entries" in doc and "embeddings: `fake`" in doc and "LLM: unused" in doc

    # The failures are exactly the chosen point's misses, and the doc lists them.
    chosen = table.row("hybrid@0.65")
    hits = int(chosen["hit@3"].split("/")[0])
    holds = int(chosen["gate-holds"].split("/")[0])
    assert len(table.failures) == (16 - hits) + (5 - holds)
    failures_region = re.search(r"<!-- eval:failures -->(.*?)<!-- /eval:failures -->", doc, re.S).group(1)
    if table.failures:
        for f in table.failures:
            assert f.case in failures_region, f.case
    else:
        assert "_No failures._" in failures_region
    # Scores are well-formed: n/16 hits, m/5 holds.
    for r in rows:
        cols = [c.strip() for c in r.split("|")]
        assert re.fullmatch(r"\d+/16", cols[2]) and re.fullmatch(r"\d+/5", cols[3].split()[0])


async def test_eval_retrieval_without_embeddings_is_lexical_only(monkeypatch, capsys):
    monkeypatch.setattr(embedding_service, "_model", None)
    args = eval_retrieval.build_parser().parse_args([
        "--database-url", TEST_DB_URL, "--owner-email", f"lex_{uuid.uuid4().hex[:10]}@example.com",
        "--fake-llm", "--embeddings", "skip",
    ])
    table = await eval_retrieval.run(args)
    assert "no embedding model" in capsys.readouterr().err
    for t in ("0.55", "0.65", "0.75"):
        assert table.row(f"vector-only@{t}")["hit@3"] == "0/16"
    # Lexical retrieval alone still finds the rare proper nouns.
    assert int(table.row("hybrid@0.65")["hit@3"].split("/")[0]) > 0


@pytest.mark.parametrize("argv, message", [
    (["--chosen", "hybrid@0.99"], "not a swept point"),
    (["--thresholds", "0.55,abc"], "comma-separated numbers"),
])
def test_eval_retrieval_bad_args_exit_1(argv, message, capsys):
    rc = eval_retrieval.main(["--database-url", "postgresql+asyncpg://nobody:x@127.0.0.1:1/nothing_test",
                              "--embeddings", "skip", *argv])
    assert rc == 1
    assert message in capsys.readouterr().err


async def test_sweep_rejects_duplicate_labels():
    async def evaluate(point):
        return {"n": "1"}, []

    with pytest.raises(ValueError, match="duplicate point labels"):
        await sweep([("a", 1), ("a", 2)], evaluate, columns=["n"])


async def test_load_campaign_orders_entries_by_session(db):
    seed = seed_demo.read_seed(seed_demo.DEFAULT_SEED_PATH)
    data = await eval_common.load_campaign(
        seed, db, owner_email=f"order_{uuid.uuid4().hex[:10]}@example.com")
    assert [e.session_date.isoformat() for e in data.entries] == [e["session_date"] for e in seed["entries"]]


async def test_smoke_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(embedding_service, "_model", None)
    out = tmp_path / "SMOKE_EVAL.md"
    args = eval_common.build_parser().parse_args([
        "--database-url", TEST_DB_URL, "--owner-email", f"smoke_{uuid.uuid4().hex[:10]}@example.com",
        "--fake-llm", "--embeddings", "skip", "--out", str(out),
    ])
    table = await eval_common.smoke(args)
    assert [r["window"] for r in table.rows] == ["1-3", "4-6", "7-9", "10-12"]
    assert all(r["ok"] == "yes" for r in table.rows)
    assert not table.failures
    assert "LLM: `fake`" in out.read_text()
