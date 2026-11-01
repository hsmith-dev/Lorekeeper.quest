"""Shared helpers for the spike scripts (stdlib only, so the throwaway bench
image and the backend image can both import it).

Every spike prints one JSON object (and writes it to --out) shaped as

    {"spike": "SPIKE-1", "config": "...", "column": "cpu"|"gpu",
     "env": {...}, "metrics": {...}}

scripts/eval_benchmarks.py --ingest reads these into docs/benchmarks.json and
re-renders docs/BENCHMARKS.md.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import resource
import statistics
import sys
from pathlib import Path


def stats(values: list[float], digits: int = 3) -> dict:
    """median plus spread (min, max, p25, p75) and n."""
    v = sorted(float(x) for x in values)
    if not v:
        return {"n": 0}
    q = statistics.quantiles(v, n=4, method="inclusive") if len(v) > 1 else [v[0]] * 3
    r = lambda x: round(x, digits)  # noqa: E731
    return {"n": len(v), "median": r(statistics.median(v)), "min": r(v[0]), "max": r(v[-1]),
            "p25": r(q[0]), "p75": r(q[2])}


def peak_rss_mb() -> float:
    """This process's peak RSS (ru_maxrss is KiB on Linux, bytes on macOS)."""
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(ru / (1024 * 1024) if sys.platform == "darwin" else ru / 1024, 1)


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def cgroup_peak_mb() -> float | None:
    """The container's cgroup v2 memory.peak (whole container, page cache
    included), if readable."""
    raw = _read("/sys/fs/cgroup/memory.peak")
    return round(int(raw) / (1024 * 1024), 1) if raw and raw.isdigit() else None


def cpu_threads() -> int:
    """CPUs this process may run on (the cpuset), not the host's count."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # macOS
        return os.cpu_count() or 1


def environment() -> dict:
    cpu_max = _read("/sys/fs/cgroup/cpu.max")
    mem_max = _read("/sys/fs/cgroup/memory.max")
    model = None
    cpuinfo = _read("/proc/cpuinfo") or ""
    for line in cpuinfo.splitlines():
        if line.startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break
    return {
        "date": _dt.date.today().isoformat(),
        "cpu": model or platform.processor() or platform.machine(),
        "arch": platform.machine(),
        "cpuset_threads": cpu_threads(),
        "cgroup_cpu_max": cpu_max,          # "400000 100000" = --cpus=4
        "cgroup_memory_max": mem_max,       # bytes, or "max"
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "python": platform.python_version(),
        "hardware_label": os.environ.get("BENCH_HARDWARE"),
    }


def column(device: str) -> str:
    return "gpu" if device.startswith("cuda") else "cpu"


def _positive(v: str) -> int:
    n = int(v)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def base_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--out", default=None, help="also write the JSON result here")
    p.add_argument("--n", type=_positive, default=5, help="measured repetitions (default %(default)s)")
    return p


def emit(result: dict, out: str | None) -> None:
    text = json.dumps(result, indent=2, default=float)
    print(text)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n")
