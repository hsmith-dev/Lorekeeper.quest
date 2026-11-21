"""scripts/eval_spoiler.py, the EV-4 live-model spoiler eval (E0-QA.14),
run here with the fake provider: zero leaks on the product as it is, and a
planted leak is caught and fails the run."""
from __future__ import annotations

import re
import shutil

import pytest

from app.services import embedding_service
from scripts import eval_spoiler
from scripts.eval_common import FakeEmbeddingModel, REPO_ROOT
from tests.conftest import TEST_DB_URL


def _doc(tmp_path):
    out = tmp_path / "SPOILER_EVAL.md"
    if REPO_ROOT is not None and (REPO_ROOT / "docs" / "SPOILER_EVAL.md").exists():
        shutil.copy(REPO_ROOT / "docs" / "SPOILER_EVAL.md", out)
    return out


def _args(out):
    return eval_spoiler.build_parser().parse_args(["--database-url", TEST_DB_URL, "--fake-llm", "--out", str(out)])


async def test_fake_provider_run_has_zero_leaks(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(embedding_service, "_override", None)  # restored after the test
    out = _doc(tmp_path)
    before = out.read_text() if out.exists() else None
    result = await eval_spoiler.run(_args(out), embedding_model=FakeEmbeddingModel())
    assert result.leaks == 0, [f"{f.case}: {f.got}" for f in result.failures]
    assert result.vacuous == 0, [f"{f.case}: {f.got}" for f in result.failures]  # every GM control held
    assert result.probes == len(eval_spoiler.CASES) * len(eval_spoiler.ENDPOINTS) * 2
    total = result.table.row("total")
    assert total["probes"] == str(result.probes)
    assert all(total[c] == "0" for c in eval_spoiler.LEAK_COLUMNS)

    doc = out.read_text()
    block = re.search(r"<!-- eval:results -->\n```\n(.*?)\n```", doc, re.S).group(1)
    assert "/api/chat/stream" in block and "total" in block
    assert f"probes={result.probes} leaks=0" in doc and "LLM: `fake`" in doc
    assert "_No failures._" in re.search(r"<!-- eval:failures -->(.*?)<!-- /eval:failures -->", doc, re.S).group(1)
    if before is not None:  # the hand-written prose survives
        assert doc.split("<!-- eval:results -->")[0] == before.split("<!-- eval:results -->")[0]
    assert "0 leak(s)" in capsys.readouterr().out


async def test_a_planted_leak_is_caught_and_fails_the_run(tmp_path, monkeypatch):
    """The chat route builds a Player's prompt with the Shorthand in it: the
    eval reports marker leaks and main() exits 1."""
    from app.api.routes import chat as chat_route

    monkeypatch.setattr(embedding_service, "_override", None)
    real = chat_route.build_chat_messages

    def leaky(*args, **kwargs):
        messages = real(*args, **kwargs)
        messages[0] = {**messages[0], "content": messages[0]["content"] + "\n- Notes: innkeeper is the lich"}
        return messages

    monkeypatch.setattr(chat_route, "build_chat_messages", leaky)
    out = _doc(tmp_path)
    result = await eval_spoiler.run(_args(out), embedding_model=FakeEmbeddingModel())
    assert result.leaks > 0
    assert int(result.table.row("total")["marker leaks"]) >= result.probes  # every Player ask
    got = {f.got for f in result.failures}
    assert {"- Notes", "innkeeper is the lich"} <= got
    failures = re.search(r"<!-- eval:failures -->(.*?)<!-- /eval:failures -->", out.read_text(), re.S).group(1)
    assert "marker leaks" in failures


def test_main_exits_1_on_a_leak(monkeypatch):
    async def leaky_run(args, *, embedding_model=None):
        return eval_spoiler.SpoilerResult(table=eval_spoiler.ResultTable(columns=eval_spoiler.COLUMNS), leaks=2)

    monkeypatch.setattr(eval_spoiler, "run", leaky_run)
    assert eval_spoiler.main(["--fake-llm"]) == 1

    async def clean_run(args, *, embedding_model=None):
        return eval_spoiler.SpoilerResult(table=eval_spoiler.ResultTable(columns=eval_spoiler.COLUMNS))

    monkeypatch.setattr(eval_spoiler, "run", clean_run)
    assert eval_spoiler.main(["--fake-llm"]) == 0


@pytest.mark.parametrize("reply, words, found", [
    ("The innkeeper is a lich.", ("lich",), ["lich"]),
    ("Unlichlike calm.", ("lich",), []),
    ("Check the CELLAR.", ("cellar",), ["cellar"]),
])
def test_secret_words_match_whole_words(reply, words, found):
    assert eval_spoiler.secret_words_in(reply, words) == found
