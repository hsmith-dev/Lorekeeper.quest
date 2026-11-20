"""scripts/eval_benchmarks.py, the EV-5 harness (E0-QA.15)."""

import importlib.util
import json
from pathlib import Path

import pytest

from scripts import eval_benchmarks, eval_common
from scripts.eval_benchmarks import ROWS, ingest, load_store, record, render, write
from scripts.eval_common import ReportError, write_regions

NFR_COLUMNS = ["Target CPU", "Target GPU", "Measured CPU", "Measured GPU",
               "Peak RSS", "n", "Date", "Hardware", "Owning epic"]


def _doc(tmp_path) -> Path:
    out = tmp_path / "BENCHMARKS.md"
    out.write_text("# Benchmarks\n\nHand-written.\n\n<!-- bench:nfr -->\nold\n<!-- /bench:nfr -->\n\n"
                   "Between.\n\n<!-- bench:spikes -->\nold\n<!-- /bench:spikes -->\n\n## Tail\n")
    return out


def _nfr_rows(table: str) -> dict[str, list[str]]:
    """Row label -> its cells, from the bench:nfr markdown table."""
    lines = table.splitlines()
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    assert header == ["Row", *NFR_COLUMNS]
    assert set(lines[1].replace("|", "")) == {"-"}
    rows = {}
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        assert len(cells) == len(header), line
        rows[cells[0]] = cells[1:]
    return rows


def _by_id(table: str) -> dict[str, dict[str, str]]:
    rows = _nfr_rows(table)
    return {r.id: dict(zip(NFR_COLUMNS, rows[f"{r.group}: {r.label}"])) for r in ROWS}


def _spike(spike="SPIKE-1", config="nli-deberta-v3-xsmall", column="cpu", **metrics) -> dict:
    return {"spike": spike, "config": config, "column": column,
            "env": {"date": "2026-11-02", "cpu": "AMD Ryzen 7 7700", "hardware_label": "Ryzen 7 7700, 4 cores"},
            "metrics": metrics}


def _stats(median, lo, hi, n=5) -> dict:
    return {"n": n, "median": median, "min": lo, "max": hi, "p25": lo, "p75": hi}


# ── I/O matrix ──────────────────────────────────────────────────────────────

def test_blank_store_renders_13_pending_rows(tmp_path):
    store = load_store(tmp_path / "missing.json")
    assert store == {"format": 1, "rows": {}, "spikes": []}
    rows = _by_id(render(store)[eval_benchmarks.NFR_REGION])
    assert len(rows) == 13
    assert sum(r.group == "NFR-6" for r in ROWS) == 9 and sum(r.group == "NFR-2" for r in ROWS) == 3
    assert [r.id for r in ROWS if r.group == "FR-14"] == ["match_names"]
    for r in ROWS:
        cells = rows[r.id]
        assert cells["Measured CPU"] == f"pending ({r.owner})"
        assert cells["Measured GPU"] == ("n/a" if r.target_gpu == "n/a" else f"pending ({r.owner})")
        assert cells["Owning epic"] == r.owner and r.owner.startswith("E")
        assert cells["Peak RSS"] == cells["n"] == cells["Date"] == cells["Hardware"] == "—"
    assert rows["proposals"]["Measured CPU"] == "pending (E1)"
    assert rows["nfr2_live"]["Owning epic"] == "E0-Platform, E4"


def test_record_fills_one_row_and_column(tmp_path):
    store_path = tmp_path / "benchmarks.json"
    store = record("proposals", "cpu", value="2 min 10 s", n=5, hardware="Ryzen 7 7700, 4 cores",
                   peak_rss_mb=812.5, date="2026-11-02", store=store_path)
    assert load_store(store_path) == store
    rows = _by_id(render(store)[eval_benchmarks.NFR_REGION])
    p = rows["proposals"]
    assert p["Measured CPU"] == "2 min 10 s"
    assert p["Measured GPU"] == "pending (E1)"
    assert (p["Peak RSS"], p["n"], p["Date"], p["Hardware"]) == ("812.5 MB", "5", "2026-11-02",
                                                                  "Ryzen 7 7700, 4 cores")
    assert rows["continuity"]["Measured CPU"] == "pending (E2)"

    # The GPU column joins the cells that differ; a re-record replaces.
    record("proposals", "gpu", value="21 s", n=5, hardware="RTX 5080", peak_rss_mb=900,
           date="2026-11-02", store=store_path)
    store = record("proposals", "cpu", value="2 min", n=6, hardware="Ryzen 7 7700, 4 cores",
                   date="2026-11-02", note="after warm-up", store=store_path)
    p = _by_id(render(store)[eval_benchmarks.NFR_REGION])["proposals"]
    assert p["Measured CPU"] == "2 min (after warm-up)" and p["Measured GPU"] == "21 s"
    assert p["Peak RSS"] == "GPU 900 MB"
    assert p["n"] == "CPU 6; GPU 5"
    assert p["Date"] == "2026-11-02"
    assert p["Hardware"] == "CPU Ryzen 7 7700, 4 cores; GPU RTX 5080"


@pytest.mark.parametrize("row, column, n", [
    ("nope", "cpu", 5), ("proposals", "tpu", 5), ("proposals", "cpu", 0), ("proposals", "cpu", -1),
])
def test_bad_record_raises_and_writes_nothing(tmp_path, row, column, n):
    store_path = tmp_path / "benchmarks.json"
    record("continuity", "cpu", value="1 min", n=5, hardware="x", store=store_path)
    before = store_path.read_text()
    with pytest.raises(ValueError):
        record(row, column, value="1 s", n=n, hardware="x", store=store_path)
    assert store_path.read_text() == before

    fresh = tmp_path / "fresh.json"
    with pytest.raises(ValueError):
        record(row, column, value="1 s", n=n, hardware="x", store=fresh)
    assert not fresh.exists()


def test_ingest_shows_each_key_once_and_replaces(tmp_path):
    store_path = tmp_path / "benchmarks.json"
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_spike(config="nli-deberta-v3-xsmall", fifty_pairs_s=_stats(1.5, 1.4, 1.9),
                                   pairs_per_s=33.3, sanity_correct=6, peak_rss_mb=800.0)))
    b.write_text(json.dumps(_spike(config="nli-deberta-v3-base", fifty_pairs_s=_stats(4.0, 3.8, 4.4),
                                   pairs_per_s=12.5, sanity_correct=6, peak_rss_mb=1400.0,
                                   cgroup_peak_mb=1600.0)))
    store = ingest([b, a], store=store_path)
    assert [s["config"] for s in store["spikes"]] == ["nli-deberta-v3-base", "nli-deberta-v3-xsmall"]
    table = render(store)[eval_benchmarks.SPIKES_REGION]
    assert table.count("| nli-deberta-v3-xsmall | cpu |") == 1
    assert "| nli-deberta-v3-base | cpu | 4 (3.8–4.4) |" in table
    assert "1400 (cgroup 1600)" in table

    # Re-ingesting the same (spike, config, column) replaces it.
    a.write_text(json.dumps(_spike(config="nli-deberta-v3-xsmall", fifty_pairs_s=_stats(1.2, 1.1, 1.3))))
    store = ingest([a], store=store_path)
    assert len(store["spikes"]) == 2
    table = render(store)[eval_benchmarks.SPIKES_REGION]
    assert table.count("| nli-deberta-v3-xsmall | cpu |") == 1
    assert "1.2 (1.1–1.3)" in table and "1.5 (1.4–1.9)" not in table

    # A GPU column is its own key.
    a.write_text(json.dumps(_spike(config="nli-deberta-v3-xsmall", column="gpu",
                                   fifty_pairs_s=_stats(0.1, 0.1, 0.2))))
    assert len(ingest([a], store=store_path)["spikes"]) == 3


@pytest.mark.parametrize("bad", [
    "not json",
    json.dumps([1, 2]),
    json.dumps({"config": "x", "column": "cpu", "env": {}, "metrics": {}}),
    json.dumps({"spike": "SPIKE-1", "config": "x", "column": "tpu", "env": {}, "metrics": {}}),
    json.dumps({"spike": "SPIKE-1", "config": "x", "column": "cpu", "env": {}, "metrics": []}),
])
def test_malformed_ingest_raises_and_leaves_store(tmp_path, bad):
    store_path = tmp_path / "benchmarks.json"
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_spike(fifty_pairs_s=_stats(1.5, 1.4, 1.9))))
    ingest([good], store=store_path)
    before = store_path.read_text()
    other = tmp_path / "other.json"
    other.write_text(json.dumps(_spike(config="other")))
    malformed = tmp_path / "bad.json"
    malformed.write_text(bad)
    with pytest.raises(ValueError):
        ingest([other, malformed], store=store_path)
    assert store_path.read_text() == before
    with pytest.raises(ValueError):
        ingest([tmp_path / "missing.json"], store=store_path)
    assert store_path.read_text() == before


@pytest.mark.parametrize("missing", ["bench:nfr", "bench:spikes"])
def test_doc_missing_region_raises_and_is_unchanged(tmp_path, missing):
    out = _doc(tmp_path)
    original = out.read_text().replace(f"<!-- {missing} -->", "")
    out.write_text(original)
    with pytest.raises(ReportError, match=missing):
        write(load_store(tmp_path / "s.json"), out)
    assert out.read_text() == original
    with pytest.raises(ReportError):
        write(load_store(tmp_path / "s.json"), tmp_path / "absent.md")


# ── Rendering ───────────────────────────────────────────────────────────────

def test_write_rewrites_only_regions_and_is_idempotent(tmp_path):
    out = _doc(tmp_path)
    store = load_store(tmp_path / "s.json")
    write(store, out)
    doc = out.read_text()
    assert doc.startswith("# Benchmarks\n\nHand-written.\n\n<!-- bench:nfr -->\n| Row |")
    assert "\n\nBetween.\n\n" in doc and doc.endswith("<!-- /bench:spikes -->\n\n## Tail\n")
    assert "old" not in doc
    write(store, out)
    assert out.read_text() == doc


def test_spike_tables_render_the_spike_metrics():
    stt = _spike("SPIKE-2", "base int8", chunk_latency_s=_stats(2.1, 1.9, 2.6, n=20),
                 chunk_rtf=_stats(0.14, 0.127, 0.173, n=20), full_rtf=0.15, word_match=0.93,
                 names_no_prompt=["Aldric", "Veyra"], names_with_prompt=["Karak Dun", "Grukk", "Aldric",
                                                                         "Veyra", "Dawnbreaker"],
                 busy={"chunk_rtf": _stats(0.3, 0.25, 0.41, n=20)}, peak_rss_mb=750.0)
    tts = _spike("SPIKE-3", "kokoro-82M af_heart per-sentence", column="gpu",
                 generation_s=_stats(3.2, 3.0, 3.5), rtf=_stats(0.05, 0.04, 0.06), first_audio_s=_stats(0.3, 0.2, 0.4),
                 audio_s=110.2, dropped_words=["Karak"], peak_rss_mb=2100.0)
    llm = _spike("SPIKE-6", "cpu-ref4")
    llm["env"].update(ollama="0.40.3", model_digest="abc123def456")
    llm["metrics"] = {
        "shapes": {"npc_first_turn": {"prompt_tokens": 900, "prompt_tok_s": _stats(60.0, 55.0, 62.0, n=3),
                                      "gen_tok_s": _stats(8.1, 8.0, 8.3, n=3), "ttft_s": _stats(15.0, 14.0, 16.0, n=3),
                                      "total_s": _stats(40.0, 38.0, 41.0, n=3)}},
        "structured": {"calls": 10, "first_try_valid": 8, "valid_after_repair": 1, "failed": 1,
                       "latency_s": _stats(60.0, 50.0, 90.0, n=10)},
    }
    other = _spike("SPIKE-5", "stack idle", total_mb=9000)
    text = render({"format": 1, "rows": {}, "spikes": [llm, other, tts, stt]})[eval_benchmarks.SPIKES_REGION]
    # Sorted by spike number.
    order = [text.index(h) for h in ("### SPIKE-2", "### SPIKE-3", "### SPIKE-5", "### SPIKE-6")]
    assert order == sorted(order)
    assert ("| base int8 | cpu | 2.1 (1.9–2.6) | 0.14 (0.127–0.173) | 0.15 | 0.93 | 2/6 | 5/6 | "
            "0.3 (0.25–0.41) | 750 | 20 | 2026-11-02 | Ryzen 7 7700, 4 cores |") in text
    assert "| gpu | 3.2 (3–3.5) | 0.05 (0.04–0.06) | 0.3 (0.2–0.4) | 110.2 | Karak | 2100 | 5 |" in text
    assert "| cpu-ref4 | cpu | npc_first_turn | 0.40.3 / abc123def456 | 900 | 60 (55–62) |" in text
    assert "| cpu-ref4 | cpu | 10 | 8 | 1 | 1 | 60 (50–90) | 10 |" in text
    assert "total_mb: 9000" in text


def test_committed_doc_matches_committed_store():
    store = load_store(eval_benchmarks.STORE_PATH)
    doc = eval_benchmarks.DOC_PATH.read_text(encoding="utf-8")
    for name, body in render(store).items():
        assert doc.count(f"<!-- {name} -->") == 1 and doc.count(f"<!-- /{name} -->") == 1, name
        assert eval_common._region_re(name).search(doc).group(2) == f"\n{body}\n", (
            f"docs/BENCHMARKS.md region {name} is stale: run python scripts/eval_benchmarks.py")
    assert len(_nfr_rows(render(store)[eval_benchmarks.NFR_REGION])) == 13


def test_write_regions_keeps_prose_and_requires_every_marker(tmp_path):
    out = tmp_path / "D.md"
    out.write_text("top\n<!-- a -->\nx\n<!-- /a -->\nmid\n<!-- b -->\ny\n<!-- /b -->\nend\n")
    write_regions(out, {"a": "A", "b": "B"})
    assert out.read_text() == "top\n<!-- a -->\nA\n<!-- /a -->\nmid\n<!-- b -->\nB\n<!-- /b -->\nend\n"
    with pytest.raises(ReportError, match="<!-- c -->"):
        write_regions(out, {"a": "changed", "c": "C"})
    assert "changed" not in out.read_text()
    new = tmp_path / "new.md"
    write_regions(new, {"a": "A"}, initial="<!-- a --><!-- /a -->\n")
    assert new.read_text() == "<!-- a -->\nA\n<!-- /a -->\n"


# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_record_ingest_and_errors(tmp_path, capsys):
    store, out = tmp_path / "s.json", _doc(tmp_path)
    spike = tmp_path / "spike.json"
    spike.write_text(json.dumps(_spike(fifty_pairs_s=_stats(1.5, 1.4, 1.9))))
    common = ["--store", str(store), "--out", str(out)]
    assert eval_benchmarks.main(common + ["--ingest", str(spike), "--record", "quick_lookup", "--column", "cpu",
                                          "--value", "0.4 s", "--n", "5", "--hardware", "box"]) == 0
    doc = out.read_text()
    assert "| 0.4 s |" in doc and "| nli-deberta-v3-xsmall | cpu | 1.5 (1.4–1.9) |" in doc

    before = store.read_text()
    assert eval_benchmarks.main(common + ["--ingest", str(spike), "--record", "quick_lookup", "--column", "cpu",
                                          "--value", "1 s", "--n", "0", "--hardware", "box"]) == 1
    assert "n must be" in capsys.readouterr().err
    assert store.read_text() == before and out.read_text() == doc
    assert eval_benchmarks.main(common + ["--column", "cpu"]) == 1

    assert eval_benchmarks.main(common) == 0
    assert out.read_text() == doc


def test_cli_doc_missing_region_leaves_store_unchanged(tmp_path, capsys):
    """The doc is checked before ingest/record touch the store, so the two never drift."""
    store, out = tmp_path / "s.json", tmp_path / "BENCHMARKS.md"
    out.write_text("<!-- bench:nfr -->\n<!-- /bench:nfr -->\n")  # no bench:spikes region
    spike = tmp_path / "spike.json"
    spike.write_text(json.dumps(_spike(fifty_pairs_s=_stats(1.5, 1.4, 1.9))))
    assert eval_benchmarks.main(["--store", str(store), "--out", str(out), "--ingest", str(spike)]) == 1
    assert "bench:spikes" in capsys.readouterr().err
    assert not store.exists()


def test_load_store_rejects_a_malformed_measurement(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"format": 1, "rows": {"proposals": {"cpu": {"value": "1 s"}}}, "spikes": []}))
    with pytest.raises(ValueError, match="proposals.cpu"):
        load_store(p)
    p.write_text(json.dumps({"format": 1, "rows": {"proposals": {"cpu": "1 s"}}, "spikes": []}))
    with pytest.raises(ValueError, match="not a measurement"):
        load_store(p)


def test_spike6_cache_hits_are_shown_and_left_out_of_n():
    shape = {"prompt_tokens": 2051, "cache_hits": 2, "total_s": _stats(75.2, 75.2, 75.2, n=1),
             "ttft_s": _stats(23.4, 23.4, 23.4, n=1), "prompt_tok_s": _stats(87.7, 87.7, 87.7, n=1),
             "gen_tok_s": _stats(7.8, 7.7, 7.8, n=3)}
    store = {"format": 1, "rows": {}, "spikes": [
        {**_spike("SPIKE-6", "cpu-ref4", "cpu", shapes={"extraction_300": shape}),
         "env": {"date": "2026-11-01", "ollama": "0.40.3", "model_digest": "68ffea1422de"}}]}
    text = render(store)["bench:spikes"]
    assert "| 1 (+2 cached) |" in text and "prompt cache" in text


# ── spikes/_bench.py ────────────────────────────────────────────────────────

def _load_bench():
    path = Path(eval_benchmarks.__file__).resolve().parent / "spikes" / "_bench.py"
    spec = importlib.util.spec_from_file_location("_bench_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bench_stats_median_and_spread():
    stats = _load_bench().stats
    assert stats([5, 1, 3, 2, 4]) == {"n": 5, "median": 3.0, "min": 1.0, "max": 5.0, "p25": 2.0, "p75": 4.0}
    assert stats([1.23456, 2.0], digits=2) == {"n": 2, "median": 1.62, "min": 1.23, "max": 2.0,
                                               "p25": 1.43, "p75": 1.81}
    assert stats([7]) == {"n": 1, "median": 7.0, "min": 7.0, "max": 7.0, "p25": 7.0, "p75": 7.0}
    assert stats([]) == {"n": 0}
