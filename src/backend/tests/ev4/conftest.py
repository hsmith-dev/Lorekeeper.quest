"""EV-4 fixtures and the CI-12 summary line.

The ``ev4`` fixture (tests/ev4/fixtures.py) builds on tests/conftest.py's
``client`` and ``db``. At the end of the run the counts are printed, and
appended to $GITHUB_STEP_SUMMARY in GitHub Actions.

The run fails (exit status 1) when any leak was recorded, even if the
probe that found it swallowed the EV4Leak, and when the summary itself
cannot be computed.
"""
from __future__ import annotations

import os

from tests.ev4 import report
from tests.ev4.fixtures import ev4  # noqa: F401  (registers the fixture)
from tests.ev4.registry import load_exemptions, load_pending, load_probes

_summary_errors: list[str] = []


def _summary() -> str:
    try:
        return report.summary_line(
            probes=len(load_probes()), exemptions=len(load_exemptions()), pending=len(load_pending()),
        )
    except Exception as exc:
        line = f"EV-4: summary unavailable ({type(exc).__name__}: {exc})"
        _summary_errors.append(line)
        return line


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


def _failure_reasons() -> list[str]:
    if not _summary_errors:
        _summary()  # pytest_sessionfinish runs before the terminal summary
    reasons = list(_summary_errors)
    if report.leak_count() > 0:
        reasons.append(f"EV-4 recorded {report.leak_count()} leak(s); a leak fails the build even when "
                       "a probe catches the EV4Leak")
    return reasons


def pytest_sessionfinish(session, exitstatus):
    reasons = _failure_reasons()
    if reasons and session.exitstatus == 0:
        for reason in reasons:
            print(f"\n{reason}")
        session.exitstatus = 1
