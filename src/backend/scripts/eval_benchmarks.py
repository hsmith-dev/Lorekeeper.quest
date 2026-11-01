#!/usr/bin/env python
"""EV-5 performance harness: docs/BENCHMARKS.md from docs/benchmarks.json.

The store holds one measurement per (row, column) for every NFR-6 latency
target and NFR-2 memory case, plus the raw spike results (the JSON the
scripts in scripts/spikes/ emit, see spikes/_bench.py). This script renders
the two generated regions of docs/BENCHMARKS.md from it (`bench:nfr`,
`bench:spikes`) through eval_common.write_regions; the prose around them is
hand-written and never touched.

  python scripts/eval_benchmarks.py                       # re-render the doc
  python scripts/eval_benchmarks.py --ingest results/*.json
  python scripts/eval_benchmarks.py --record proposals --column cpu \\
      --value "2 min 10 s" --peak-rss-mb 812 --n 5 --hardware "Ryzen 7 7700, 4 cores (AD-7)"

A row nobody has measured yet shows `pending (<owning epic>)`. Each feature
epic records its own row when it lands (EV-5); the CI test checks that the
committed doc equals a render of the committed store.

Store shape:
  {"format": 1,
   "rows": {"<row id>": {"cpu": M, "gpu": M}},
   "spikes": [<spike result>, ...]}       keyed by (spike, config, column)
  M = {"value": str, "peak_rss_mb": float|null, "n": int, "date": "YYYY-MM-DD",
       "hardware": str, "note": str|null}
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts.eval_common import DOCS_DIR, ReportError, write_regions  # noqa: E402

STORE_PATH = DOCS_DIR / "benchmarks.json"
DOC_PATH = DOCS_DIR / "BENCHMARKS.md"
FORMAT = 1
NFR_REGION = "bench:nfr"
SPIKES_REGION = "bench:spikes"
COLUMNS = ("cpu", "gpu")
DASH = "—"
SPIKE2_DEMO_NAMES = 6  # len(spikes/spike2_stt.NAMES)


@dataclass(frozen=True)
class Row:
    id: str
    group: str        # "NFR-6" or "NFR-2"
    label: str
    target_cpu: str
    target_gpu: str
    owner: str        # owning epic(s)


# The PRD's NFR-6 table and NFR-2 memory cases. Targets are copied, never
# changed here: a reset needs owner sign-off in .memlog.md and a PRD update.
NFR2_LIMIT = "≤ 14.5 GB container-limit sum"
ROWS: tuple[Row, ...] = (
    Row("proposals", "NFR-6", "Change Proposals ready after save (≈500-word entry)", "≤ 3 min", "≤ 30 s", "E1"),
    Row("continuity", "NFR-6", "Continuity check complete after save", "≤ 3 min", "≤ 30 s", "E2"),
    Row("caption_lag", "NFR-6", "Live caption lag (chunk end → text shown)",
        "≤ 30 s, with sustained processing ≤ chunk duration", "≤ 5 s", "E4"),
    Row("rolling_recap", "NFR-6", "Rolling Recap update", "≈ 60 s cadence, each update ≤ 45 s", "≈ 60 s", "E4"),
    Row("quick_lookup", "NFR-6", "Quick lookup by name", "≤ 2 s", "≤ 2 s", "E4"),
    Row("npc_first_token", "NFR-6", "NPC Conversation first token", "≤ 20 s", "≤ 3 s", "E6"),
    Row("narration_300", "NFR-6", "Narration of a 300-word recap", "≤ 2 min", "≤ 30 s", "E5"),
    Row("chronicle_100", "NFR-6", "Chronicle export, 100 entries", "≤ 3 min", "n/a", "E8"),
    Row("portal_warm", "NFR-6", "Portal page load (warm)", "≤ 2 s", "≤ 2 s", "E7"),
    Row("nfr2_idle", "NFR-2", "Stack memory: idle", NFR2_LIMIT, NFR2_LIMIT, "E0-Platform"),
    Row("nfr2_heavy_job", "NFR-2", "Stack memory: one heavy Job", NFR2_LIMIT, NFR2_LIMIT, "E0-Platform"),
    Row("nfr2_live", "NFR-2", "Stack memory: Live Session (speech-to-text + Rolling Recap)",
        NFR2_LIMIT, NFR2_LIMIT, "E0-Platform, E4"),
)
ROWS_BY_ID = {r.id: r for r in ROWS}


# ── Store ───────────────────────────────────────────────────────────────────

def blank_store() -> dict:
    return {"format": FORMAT, "rows": {}, "spikes": []}


def load_store(path: str | os.PathLike = STORE_PATH) -> dict:
    """The store at `path` (a missing file is a blank store). ValueError if
    it is not a format-1 store of known rows and columns."""
    p = Path(path)
    if not p.exists():
        return blank_store()
    try:
        store = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{p}: not JSON: {exc}") from None
    if not isinstance(store, dict) or store.get("format") != FORMAT:
        raise ValueError(f"{p}: not a format-{FORMAT} benchmark store")
    rows, spikes = store.setdefault("rows", {}), store.setdefault("spikes", [])
    if not isinstance(rows, dict) or not isinstance(spikes, list):
        raise ValueError(f"{p}: rows must be an object and spikes a list")
    for row_id, cols in rows.items():
        if row_id not in ROWS_BY_ID:
            raise ValueError(f"{p}: unknown row {row_id!r}")
        if not isinstance(cols, dict) or set(cols) - set(COLUMNS):
            raise ValueError(f"{p}: row {row_id!r} has columns other than {COLUMNS}")
        for col, m in cols.items():
            if not isinstance(m, dict):
                raise ValueError(f"{p}: {row_id}.{col} is not a measurement object")
            try:
                measurement(row_id, col, **m)
            except TypeError as exc:
                raise ValueError(f"{p}: {row_id}.{col}: {exc}") from None
    for result in spikes:
        _check_spike(result, str(p))
    return store


def save_store(store: dict, path: str | os.PathLike = STORE_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def measurement(
    row_id: str,
    column: str,
    *,
    value: str,
    n: int,
    hardware: str,
    peak_rss_mb: float | None = None,
    note: str | None = None,
    date: str | None = None,
) -> dict:
    """A validated measurement M. ValueError on an unknown row, a column
    other than cpu/gpu, n < 1, or an empty value / hardware."""
    if row_id not in ROWS_BY_ID:
        raise ValueError(f"unknown row {row_id!r}; one of {', '.join(ROWS_BY_ID)}")
    if column not in COLUMNS:
        raise ValueError(f"column must be cpu or gpu, not {column!r}")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be an integer ≥ 1, not {n!r}")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("value is required")
    if not isinstance(hardware, str) or not hardware.strip():
        raise ValueError("hardware is required")
    if peak_rss_mb is not None:
        peak_rss_mb = float(peak_rss_mb)
        if peak_rss_mb < 0:
            raise ValueError(f"peak RSS must be ≥ 0, not {peak_rss_mb}")
    if date is None:
        date = _dt.date.today().isoformat()
    else:
        try:
            _dt.date.fromisoformat(date)
        except (TypeError, ValueError):
            raise ValueError(f"date must be YYYY-MM-DD, not {date!r}") from None
    return {"value": value.strip(), "peak_rss_mb": peak_rss_mb, "n": n, "date": date,
            "hardware": hardware.strip(), "note": (note.strip() or None) if note else None}


def record(
    row_id: str,
    column: str,
    *,
    value: str,
    n: int,
    hardware: str,
    peak_rss_mb: float | None = None,
    note: str | None = None,
    date: str | None = None,
    store: str | os.PathLike = STORE_PATH,
) -> dict:
    """Record one row's CPU or GPU measurement in the store file (replacing
    any earlier one) and return the store. Nothing is written on ValueError."""
    m = measurement(row_id, column, value=value, n=n, hardware=hardware,
                    peak_rss_mb=peak_rss_mb, note=note, date=date)
    data = load_store(store)
    data["rows"].setdefault(row_id, {})[column] = m
    data["rows"] = {r.id: data["rows"][r.id] for r in ROWS if r.id in data["rows"]}
    save_store(data, store)
    return data


def _check_spike(result: object, source: str) -> tuple[str, str, str]:
    if not isinstance(result, dict):
        raise ValueError(f"{source}: a spike result must be a JSON object")
    for key in ("spike", "config"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise ValueError(f"{source}: missing {key!r}")
    if result.get("column") not in COLUMNS:
        raise ValueError(f"{source}: column must be cpu or gpu, not {result.get('column')!r}")
    for key in ("env", "metrics"):
        if not isinstance(result.get(key), dict):
            raise ValueError(f"{source}: {key!r} must be an object")
    return _spike_key(result)


def _spike_key(result: dict) -> tuple[str, str, str]:
    return (result["spike"], result["config"], result["column"])


def _spike_sort_key(result: dict) -> tuple:
    spike, config, column = _spike_key(result)
    num = spike.rsplit("-", 1)[-1]
    return (int(num) if num.isdigit() else 10**6, spike, config, COLUMNS.index(column))


def ingest(paths: list[str | os.PathLike], *, store: str | os.PathLike = STORE_PATH) -> dict:
    """Add spike result files (the _bench result shape) to the store file and
    return it. A result with the same (spike, config, column) as one already
    there replaces it. ValueError, store unchanged, if any file is malformed."""
    results = []
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"{path}: {exc.strerror or exc}") from None
        try:
            result = json.loads(text)
        except ValueError as exc:
            raise ValueError(f"{path}: not JSON: {exc}") from None
        _check_spike(result, str(path))
        results.append(result)
    data = load_store(store)
    by_key = {_spike_key(r): r for r in data["spikes"]}
    for r in results:
        by_key[_spike_key(r)] = r
    data["spikes"] = sorted(by_key.values(), key=_spike_sort_key)
    save_store(data, store)
    return data


# ── Rendering ───────────────────────────────────────────────────────────────

NFR_HEADER = ("Row", "Target CPU", "Target GPU", "Measured CPU", "Measured GPU",
              "Peak RSS", "n", "Date", "Hardware", "Owning epic")


def _cell(v: object) -> str:
    s = DASH if v is None or v == "" else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def _table(header: tuple[str, ...] | list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _num(x: object) -> str:
    if isinstance(x, float):
        return f"{x:g}"
    return str(x)


def _mb(x: float | None) -> str | None:
    return None if x is None else f"{_num(x)} MB"


def _joined(cols: dict, fmt) -> str | None:
    """The Peak RSS / n / date / hardware cells: plain when one column is
    measured (or both agree), else the values that exist, labelled."""
    vals = {c: fmt(cols[c]) for c in COLUMNS if c in cols}
    vals = {c: v for c, v in vals.items() if v is not None}
    if not vals:
        return None
    if len(cols) == 1 or (len(vals) == 2 and len(set(vals.values())) == 1):
        return next(iter(vals.values()))
    return "; ".join(f"{c.upper()} {v}" for c, v in vals.items())


def _measured(row: Row, cols: dict, column: str) -> str:
    m = cols.get(column)
    if m is None:
        target = row.target_cpu if column == "cpu" else row.target_gpu
        return "n/a" if target == "n/a" else f"pending ({row.owner})"
    return m["value"] + (f" ({m['note']})" if m.get("note") else "")


def render_nfr(store: dict) -> str:
    rows = []
    for row in ROWS:
        cols = store.get("rows", {}).get(row.id, {})
        rows.append([
            f"{row.group}: {row.label}", row.target_cpu, row.target_gpu,
            _measured(row, cols, "cpu"), _measured(row, cols, "gpu"),
            _joined(cols, lambda m: _mb(m.get("peak_rss_mb"))),
            _joined(cols, lambda m: str(m["n"])),
            _joined(cols, lambda m: m["date"]),
            _joined(cols, lambda m: m["hardware"]),
            row.owner,
        ])
    return _table(NFR_HEADER, rows)


def _stat(s: object) -> str | None:
    """A _bench.stats dict as `median (min–max)`; plain numbers as-is."""
    if isinstance(s, dict):
        if not s.get("n"):
            return None
        return f"{_num(s['median'])} ({_num(s['min'])}–{_num(s['max'])})"
    if s is None:
        return None
    if isinstance(s, list):
        return ", ".join(map(str, s)) or "none"
    return _num(s)


def _stat_n(s: object) -> int | None:
    return s.get("n") if isinstance(s, dict) else None


def _get(d: dict, dotted: str):
    for part in dotted.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def _peak(m: dict) -> str | None:
    rss, cg = m.get("peak_rss_mb"), m.get("cgroup_peak_mb")
    if rss is None and cg is None:
        return None
    if cg is None:
        return _num(rss)
    return f"{_num(rss) if rss is not None else DASH} (cgroup {_num(cg)})"


def _names(found: object) -> str | None:
    if not isinstance(found, list):
        return None
    return f"{len(found)}/{SPIKE2_DEMO_NAMES}"


def _hardware(env: dict) -> str | None:
    return env.get("hardware_label") or env.get("cpu")


# Per spike: (heading, [(column header, formatter(result))], the metric whose n is shown).
def _m(key: str, fmt=_stat):
    return lambda r: fmt(_get(r["metrics"], key))


SPIKE_TABLES: dict[str, tuple[str, list[tuple[str, object]], str]] = {
    "SPIKE-1": ("SPIKE-1: NLI cross-encoder (50 pairs)", [
        ("50 pairs (s)", _m("fifty_pairs_s")),
        ("Per pair, batch 1 (ms)", _m("per_pair_batch1_ms")),
        ("Pairs/s", _m("pairs_per_s")),
        ("Sanity correct", _m("sanity_correct")),
        ("Peak RSS (MB)", lambda r: _peak(r["metrics"])),
    ], "fifty_pairs_s"),
    "SPIKE-2": ("SPIKE-2: faster-whisper, 15 s chunks", [
        ("Chunk latency (s)", _m("chunk_latency_s")),
        ("Chunk RTF", _m("chunk_rtf")),
        ("Full-clip RTF", _m("full_rtf")),
        ("Word match", _m("word_match")),
        ("Names, no prompt", _m("names_no_prompt", _names)),
        ("Names, `initial_prompt`", _m("names_with_prompt", _names)),
        ("Chunk RTF, LLM busy", _m("busy.chunk_rtf")),
        ("Peak RSS (MB)", lambda r: _peak(r["metrics"])),
    ], "chunk_latency_s"),
    "SPIKE-3": ("SPIKE-3: Kokoro TTS, 300-word recap", [
        ("Generation (s)", _m("generation_s")),
        ("RTF", _m("rtf")),
        ("First audio (s)", _m("first_audio_s")),
        ("Audio (s)", _m("audio_s")),
        ("Dropped words", _m("dropped_words")),
        ("Peak RSS (MB)", lambda r: _peak(r["metrics"])),
    ], "generation_s"),
}
SPIKE6_SHAPE_COLS = (("Prompt tokens", "prompt_tokens"), ("Prompt tok/s", "prompt_tok_s"),
                     ("Gen tok/s", "gen_tok_s"), ("TTFT (s)", "ttft_s"), ("Total (s)", "total_s"))
SPIKE6_STRUCT_COLS = (("Calls", "calls"), ("First-try valid", "first_try_valid"),
                      ("Valid after repair", "valid_after_repair"), ("Failed", "failed"),
                      ("Latency (s)", "latency_s"))
TAIL = ("n", "Date", "Hardware")


def _tail(r: dict, n: object) -> list[object]:
    return [n, r["env"].get("date"), _hardware(r["env"])]


def _render_spike6(results: list[dict]) -> list[str]:
    out = ["### SPIKE-6: 7B throughput (Ollama)", ""]
    rows = []
    for r in results:
        env = r["env"]
        model = f"{env.get('ollama') or DASH} / {env.get('model_digest') or DASH}"
        for shape, s in sorted((_get(r["metrics"], "shapes") or {}).items()):
            n = _stat_n(s.get("total_s"))
            if s.get("cache_hits"):  # served from the prompt cache: out of the prompt-side stats
                n = f"{n} (+{s['cache_hits']} cached)"
            rows.append([r["config"], r["column"], shape, model]
                        + [_stat(s.get(k)) for _, k in SPIKE6_SHAPE_COLS]
                        + _tail(r, n))
    out.append(_table(["Config", "Column", "Shape", "Ollama / model digest"]
                      + [h for h, _ in SPIKE6_SHAPE_COLS] + list(TAIL), rows))
    struct = [r for r in results if isinstance(_get(r["metrics"], "structured"), dict)]
    if struct:
        rows = [[r["config"], r["column"]]
                + [_stat(r["metrics"]["structured"].get(k)) for _, k in SPIKE6_STRUCT_COLS]
                + _tail(r, r["metrics"]["structured"].get("calls")) for r in struct]
        out += ["", "Structured extraction:", "",
                _table(["Config", "Column"] + [h for h, _ in SPIKE6_STRUCT_COLS] + list(TAIL), rows)]
    return out


def _render_generic(spike: str, results: list[dict]) -> list[str]:
    """A spike without its own table: its top-level scalar and stats metrics."""
    rows = []
    for r in results:
        parts = [f"{k}: {_stat(v)}" for k, v in r["metrics"].items()
                 if (isinstance(v, dict) and "median" in v) or isinstance(v, (int, float, str))]
        rows.append([r["config"], r["column"], "; ".join(parts) or DASH] + _tail(r, None))
    return [f"### {spike}", "", _table(["Config", "Column", "Metrics"] + list(TAIL), rows)]


def render_spikes(store: dict) -> str:
    results = sorted(store.get("spikes", []), key=_spike_sort_key)
    if not results:
        return "_No spike results ingested yet (`--ingest`)._"
    by_spike: dict[str, list[dict]] = {}
    for r in results:
        by_spike.setdefault(r["spike"], []).append(r)
    out: list[str] = []
    for spike, rs in by_spike.items():
        if out:
            out.append("")
        if spike == "SPIKE-6":
            out += _render_spike6(rs)
        elif spike in SPIKE_TABLES:
            heading, cols, n_key = SPIKE_TABLES[spike]
            rows = [[r["config"], r["column"]] + [fmt(r) for _, fmt in cols]
                    + _tail(r, _stat_n(_get(r["metrics"], n_key))) for r in rs]
            out += [f"### {heading}", "",
                    _table(["Config", "Column"] + [h for h, _ in cols] + list(TAIL), rows)]
        else:
            out += _render_generic(spike, rs)
    note = "Timings are `median (min–max)` over n runs."
    if "SPIKE-2" in by_spike:
        note += (" For SPIKE-2, n counts every chunk of 5 s or more in every run: the 15 s chunks"
                 " and the clip's 7 s tail.")
    if "SPIKE-6" in by_spike:
        note += (" For SPIKE-6, runs served from Ollama's prompt cache are left out of n and"
                 " of the prompt-side columns, and shown as `(+k cached)`.")
    out += ["", note]
    return "\n".join(out)


def render(store: dict) -> dict[str, str]:
    """The generated regions of docs/BENCHMARKS.md for this store."""
    return {NFR_REGION: render_nfr(store), SPIKES_REGION: render_spikes(store)}


def write(store: dict, out: str | os.PathLike = DOC_PATH) -> Path:
    """Rewrite only the generated regions of `out`; ReportError, doc
    unchanged, if a region marker is missing (or the doc is)."""
    return write_regions(out, render(store))


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", default=str(STORE_PATH), help="benchmark store (default: %(default)s)")
    p.add_argument("--out", default=str(DOC_PATH), help="doc to re-render (default: %(default)s)")
    p.add_argument("--ingest", nargs="+", metavar="FILE", help="spike result JSON files to add")
    p.add_argument("--record", metavar="ROW", choices=list(ROWS_BY_ID), help="row to record a measurement for")
    p.add_argument("--column", choices=COLUMNS, help="cpu (Reference Box) or gpu")
    p.add_argument("--value", help='the measured value as shown, e.g. "2 min 10 s"')
    p.add_argument("--peak-rss-mb", type=float, default=None)
    p.add_argument("--n", type=int, default=None, help="measured runs")
    p.add_argument("--hardware", help="the machine and its limits")
    p.add_argument("--note", default=None)
    p.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.record is None and any(
                v is not None for v in (args.column, args.value, args.n, args.hardware, args.note, args.date,
                                        args.peak_rss_mb)):
            raise ValueError("--column/--value/--n/--hardware/--note/--date/--peak-rss-mb need --record")
        if args.record:
            if args.column is None or args.n is None:
                raise ValueError("--record needs --column, --value, --n and --hardware")
            fields = dict(value=args.value, n=args.n, hardware=args.hardware,
                          peak_rss_mb=args.peak_rss_mb, note=args.note, date=args.date)
            measurement(args.record, args.column, **fields)  # validate before anything is written
        # Render the current store first: a doc missing a region fails here,
        # before ingest/record change the store (store and doc never drift).
        write(load_store(args.store), args.out)
        if args.ingest:
            ingest(args.ingest, store=args.store)
        if args.record:
            record(args.record, args.column, store=args.store, **fields)
        path = write(load_store(args.store), args.out)
    except (ValueError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
