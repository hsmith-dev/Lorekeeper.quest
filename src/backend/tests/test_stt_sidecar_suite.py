"""Interim CI hook: run the `stt` sidecar's own test suite from backend CI.

.github/workflows belong to E0-QA, and backend-tests.yml is the only runner
that has fastapi, httpx, python-multipart, numpy and pytest installed, which
is all the sidecar's fake-model tests need. So this runs
src/services/stt/tests in a subprocess (its own rootdir and sys.path, never
importing the backend `app`). Replace with a dedicated `stt` job,
path-filtered on src/services/stt/**, in E0-QA.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SIDECAR = Path(__file__).resolve().parents[2] / "services" / "stt"


@pytest.mark.skipif(not (SIDECAR / "tests").is_dir(), reason="src/services/stt not in this checkout")
def test_stt_sidecar_suite_passes():
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=SIDECAR,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    output = proc.stdout + proc.stderr
    print(output[-4000:])
    assert proc.returncode == 0, f"sidecar suite failed (exit {proc.returncode}):\n{output[-8000:]}"
