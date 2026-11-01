"""The EV-4 probe runner: every registered probe (tests/ev4/probes/) once
per actor. A role-dependent actor that is not available yet skips only its
own case. While no probe exists the parameter set is empty and pytest
reports one skipped case.

A probe must call at least one family helper (tests/ev4/families.py): a
probe that checks nothing would count as coverage without testing anything.
"""
from __future__ import annotations

import pytest

from tests.ev4 import report
from tests.ev4.registry import load_probes

CASES = [
    pytest.param(probe, actor, id=f"{probe.key} [{probe.name}] as {actor}")
    for probe in load_probes()
    for actor in probe.actors
]


async def run_probe(probe, ev4, actor) -> None:
    before = report.family_calls()
    await probe.fn(ev4, actor)
    if report.family_calls() == before:
        pytest.fail(f"probe {probe.name} ran no EV-4 family check", pytrace=False)


@pytest.mark.parametrize("probe, actor_name", CASES)
async def test_probe(ev4, probe, actor_name):
    actor = await ev4.actor(actor_name)
    await run_probe(probe, ev4, actor)
