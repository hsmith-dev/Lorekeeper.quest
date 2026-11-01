"""EV-4 spoiler-leak harness (AD-21, AD-13, AD-20; NFR-5).

Every API route needs a probe in ``tests/ev4/probes/<feature>.py``, a
reasoned exemption in ``exemptions.yaml``, or (routes that existed when the
harness landed) a line in the shrink-only ``pending_baseline.txt``.

Modules:
  nginx      nginx config tokenizer/parser and location matching (nginx order)
  routes     app.routes enumeration, sample paths, route -> nginx location
  registry   @ev4_probe, probe loading, exemptions/pending, coverage check
  report     counters, EV4Leak, record_leak, scoped report for self-tests
  fixtures   canary seed, actors, the ``ev4`` pytest fixture
  families   the seven probe-family helpers
"""
from __future__ import annotations

from pathlib import Path

EV4_DIR = Path(__file__).resolve().parent


def repo_root() -> Path:
    """The repository root (the directory holding ``nginx/`` and ``seeds/``),
    found from this file's path so the harness works from any cwd."""
    for candidate in EV4_DIR.parents:
        if (candidate / "nginx" / "nginx.conf").is_file() and (candidate / "src" / "backend").is_dir():
            return candidate
    raise RuntimeError(
        f"EV-4: could not find the repository root above {EV4_DIR} "
        "(looked for a directory holding nginx/nginx.conf and src/backend). "
        "Run the suite from a full checkout of the repository."
    )
