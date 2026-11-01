"""EV-4 fixtures and the CI-12 summary line.

The ``ev4`` fixture (tests/ev4/fixtures.py) builds on tests/conftest.py's
``client`` and ``db``. At the end of the run the counts are printed, and
appended to $GITHUB_STEP_SUMMARY in GitHub Actions.
"""
from __future__ import annotations

import os

from tests.ev4 import report
from tests.ev4.fixtures import ev4  # noqa: F401  (registers the fixture)
from tests.ev4.registry import load_exemptions, load_pending, load_probes


def _summary() -> str:
    try:
        return report.summary_line(
            probes=len(load_probes()), exemptions=len(load_exemptions()), pending=len(load_pending()),
        )
    except Exception as exc:  # never hide the test results behind a summary error
        return f"EV-4: summary unavailable ({type(exc).__name__}: {exc})"


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    line = _summary()
    terminalreporter.write_sep("-", "EV-4 spoiler-leak harness")
    terminalreporter.write_line(line)
    for detail in report.current().details:
        terminalreporter.write_line(detail)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"### EV-4 spoiler-leak harness\n\n`{line}`\n\n")
        except OSError:
            pass
