"""EV-4 probes: one module per feature, ``tests/ev4/probes/<feature>.py``.

This package is the shared append point. E0-Access, E0-QA.13, E0-QA.14 and
the feature epics each add their own module here; nobody restructures the
package. tests/ev4/registry.py imports every module in it.

Template (copy into tests/ev4/probes/<feature>.py):

    from tests.ev4.families import assert_hidden_equals_missing, assert_no_canary
    from tests.ev4.registry import ev4_probe


    # The path is the route template exactly as FastAPI registers it. The
    # default actors are anon_share, player and cross_gm_player; pass
    # actors=(...) to choose others (see tests/ev4/fixtures.py).
    @ev4_probe("GET", "/api/npcs/{npc_id}")
    async def probe_npc_detail(ev4, actor):
        npc_id = ev4.a.ids["npcs"][0]
        r = await actor.get(f"/api/npcs/{npc_id}")
        assert_no_canary(actor, r)
        await assert_hidden_equals_missing(
            actor, f"/api/npcs/{npc_id}", "/api/npcs/00000000-0000-4000-8000-000000000000"
        )

In the same PR, delete the route's line from tests/ev4/pending_baseline.txt
(the coverage test fails until you do). A route that cannot leak gets an
entry with a reason in tests/ev4/exemptions.yaml instead of a probe.
"""
