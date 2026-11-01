"""Unit tests for scripts/check_scoped_queries.py (CI-8: E0-Access.2, .3, .5 and .9 parts).

Run: python -m pytest -q scripts/test_check_scoped_queries.py  (stdlib + pytest)
"""
from __future__ import annotations

import importlib.util
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check_scoped_queries", HERE / "check_scoped_queries.py")
csq = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = csq  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(csq)

DEFINITION = textwrap.dedent('''
    class CampaignContext:
        def as_system(self, reason):
            """Docstrings may say as_system( freely."""
            return self
''')


def make_app(tmp_path: Path, files: dict[str, str]) -> Path:
    app = tmp_path / "app"
    (app / "access").mkdir(parents=True)
    (app / "access" / "context.py").write_text(DEFINITION)
    for rel, body in files.items():
        p = app / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return app


def violations(tmp_path: Path, files: dict[str, str]) -> list:
    return csq.check(make_app(tmp_path, files))


# ---- the real repo ---------------------------------------------------------

def test_repo_is_clean():
    found = csq.check()
    assert not found, "\n".join(map(str, found))


def test_real_definition_is_found_and_exempt():
    text = (csq.APP / "access" / "context.py").read_text()
    assert "def as_system(" in text
    assert csq.check_source(text, csq.DEFINITION_FILE) == []


def test_main_exit_codes(tmp_path, capsys):
    empty = tmp_path / "empty_baseline.txt"
    empty.write_text("")
    assert csq.main(["--app", str(make_app(tmp_path, {})), "--baseline", str(empty)]) == 0
    bad = make_app(tmp_path / "bad", {"services/other.py": "def f(ctx):\n    return ctx.as_system('merge')\n"})
    assert csq.main(["--app", str(bad), "--baseline", str(empty)]) == 1
    out = capsys.readouterr().out
    assert "app/services/other.py:2" in out and "as_system" in out


# ---- allowed sites -----------------------------------------------------------

def test_allowed_sites_pass(tmp_path):
    assert violations(tmp_path, {
        "services/journal_service.py": """
            async def delete_journal_entry(db, ctx, entry_id):
                sys_ctx = ctx.as_system("entry_deleted")
                def inner():
                    return ctx.as_system("entry_deleted")
                return sys_ctx, inner
        """,
        "services/world_service.py": """
            async def merge_entities(db, ctx, a, b):
                return ctx.as_system("merge")
        """,
    }) == []


# ---- planted violations ------------------------------------------------------

@pytest.mark.parametrize("rel, body, line", [
    # The AC case: a planted ctx.as_system("merge") in another module.
    ("services/npc_service.py", "def f(ctx):\n    return ctx.as_system('merge')\n", 2),
    # Right module, wrong function.
    ("services/journal_service.py", "def update_journal_entry(ctx):\n    return ctx.as_system('entry_deleted')\n", 2),
    ("services/world_service.py", "async def rename(ctx):\n    return ctx.as_system('merge')\n", 2),
    # Right function name, wrong module.
    ("services/other.py", "def merge_entities(ctx):\n    return ctx.as_system('merge')\n", 2),
    # Module level, routes, attribute reads, bare names, imports, getattr.
    ("services/journal_service.py", "SYS = None\nx = ctx.as_system('entry_deleted')\n", 2),
    ("api/routes/journals.py", "async def r(ctx):\n    f = ctx.as_system\n    return f('merge')\n", 2),
    ("api/routes/x.py", "from app.access.context import as_system\n", 1),
    ("api/routes/y.py", "def r(ctx):\n    return getattr(ctx, 'as_system')('merge')\n", 2),
    ("services/z.py", "def r(as_system):\n    return as_system\n", 2),
    # A system ctx built by hand, without as_system.
    ("services/q.py", "def r(ctx):\n    return CampaignContext(actor='system', system_reason=None)\n", 2),
    ("services/q.py", "import dataclasses\ndef r(ctx):\n    return dataclasses.replace(ctx, actor=ACTOR_SYSTEM)\n", 3),
    ("services/q.py", "def r(ctx, why):\n    return dataclasses.replace(ctx, system_reason=why)\n", 2),
    # An allowed name as a method, or nested in another function.
    ("services/world_service.py", "class W:\n    def merge_entities(self, ctx):\n        return ctx.as_system('merge')\n", 3),
    ("services/journal_service.py", "def outer(ctx):\n    def delete_journal_entry():\n        return ctx.as_system('entry_deleted')\n", 3),
    # A second definition elsewhere (a look-alike system ctx).
    ("access/other.py", "class Ctx:\n    def as_system(self, reason):\n        return self\n", 2),
])
def test_planted_violation_fails(tmp_path, rel, body, line):
    found = violations(tmp_path, {rel: body})
    assert found, f"{rel} should fail"
    assert found[0].path == f"app/{rel}" and found[0].line == line
    assert "allowed only in app/services/journal_service.py::delete_journal_entry" in str(found[0])


def test_method_named_like_an_allowed_function_elsewhere_in_context_fails(tmp_path):
    app = make_app(tmp_path, {})
    (app / "access" / "context.py").write_text(DEFINITION + "\ndef helper(ctx):\n    return ctx.as_system('merge')\n")
    found = csq.check(app)
    assert [(v.path, v.line) for v in found] == [("app/access/context.py", 8)]


def test_strings_and_comments_are_not_references(tmp_path):
    assert violations(tmp_path, {
        "services/doc.py": '"""Call ctx.as_system("merge") only in world_service."""\n# ctx.as_system(...)\nX = "as_system"\n',
    }) == []


def test_unparseable_file_fails(tmp_path):
    found = violations(tmp_path, {"services/broken.py": "def (:\n"})
    assert found and "cannot be parsed" in found[0].what


# ---- read_only= (E0-Access.3: reduced ctxs only via audience_ctx) ------------

@pytest.mark.parametrize("rel, body, line", [
    ("services/q.py", "def r(ctx):\n    return CampaignContext(role='anon', read_only=True)\n", 2),
    ("api/routes/r.py", "import dataclasses\ndef r(ctx):\n    return dataclasses.replace(ctx, read_only=True)\n", 3),
    ("services/q.py", "def r(ctx, flag):\n    return dataclasses.replace(ctx, read_only=flag)\n", 2),
    ("services/q.py", "def r(ctx):\n    return dataclasses.replace(ctx, read_only=None)\n", 2),
    # Widening a reduced ctx back to writable (e.g. as_user(other) from a GM).
    ("services/q.py", "def r(ctx):\n    return dataclasses.replace(ctx, read_only=False)\n", 2),
])
def test_read_only_outside_access_fails(tmp_path, rel, body, line):
    found = violations(tmp_path, {rel: body})
    assert [(v.path, v.line) for v in found] == [(f"app/{rel}", line)]
    assert "audience_ctx" in str(found[0]) and "read_only=" in str(found[0])


def test_read_only_inside_access_and_strings_pass(tmp_path):
    assert violations(tmp_path, {
        "access/reduced.py": "def r(ctx):\n    return dataclasses.replace(ctx, read_only=True)\n",
        "services/s.py": "KIND = 'read_only'\nx = {'read_only': True}\n",
    }) == []


# ---- E0-Access.5: deprecated helpers and the scoped-query ratchet -----------

# The ceiling: the baseline may lose lines, never gain them. Lower the count
# (or drop the key) here in the same PR that removes a line from
# scripts/scoped_queries_baseline.txt; test_baseline_never_grows fails until
# both match, so a removed line cannot quietly come back later.
FROZEN_BASELINE = {
    "app/api/routes/admin.py::_user_to_admin_response owner_check:Campaign.user_id": 1,
    "app/api/routes/admin.py::_user_to_admin_response select:Campaign": 1,
    "app/api/routes/admin.py::_user_to_admin_response select:JournalEntry": 1,
    "app/api/routes/admin.py::list_users select:Campaign": 1,
    "app/api/routes/admin.py::list_users select:JournalEntry": 1,
    "app/api/routes/campaigns.py::list_campaigns select:Campaign": 1,
    "app/api/routes/character_sheets.py::delete_template select:CharacterSheet": 1,
    "app/api/routes/chat.py::_prepare_chat get:Campaign": 1,
    "app/api/routes/chat.py::list_sessions select:Campaign": 1,
    "app/api/routes/chat.py::list_sessions select:ChatSession": 1,
    "app/api/routes/feedback.py::get_feedback_context get:Campaign": 1,
    "app/api/routes/feedback.py::get_feedback_context select:JournalEntry": 1,
    "app/api/routes/feedback.py::get_feedback_context select:NpcEntry": 1,
    "app/api/routes/feedback.py::get_feedback_context select:Quest": 1,
    "app/api/routes/feedback.py::get_feedback_context select:SourceDocument": 1,
    "app/api/routes/feedback.py::list_feedback select:Campaign": 1,
    "app/api/routes/journals.py::attach_tag select:Tag": 1,
    "app/api/routes/share.py::join_campaign get:Campaign": 1,
    "app/api/routes/share.py::join_campaign select:CampaignMember": 1,
    "app/services/journal_service.py::create_journal_entry raw_sql:journal_entries": 1,
    "app/services/journal_service.py::create_journal_entry select:JournalEntry": 1,
    "app/services/journal_service.py::create_journal_entry select:Tag": 1,
    "app/services/journal_service.py::generate_draft_narrative select:Campaign": 1,
    "app/services/retrieval_service.py::_search select:JournalEntry": 2,
    "app/services/shorthand_service.py::get_glossary select:ShorthandTerm": 1,
    "app/services/source_service.py::retrieve_canon_context select:SourceChunk": 1,
    "app/services/source_service.py::retrieve_canon_context select:SourceDocument": 1,
}

REGISTRY_SRC = '''
REGISTRY: dict = {
    JournalEntry: stored(),
    Campaign: membership(PUBLIC),
}
'''
MODELS_SRC = '''
class JournalEntry(Base):
    __tablename__ = "journal_entries"

class Campaign(Base):
    __tablename__ = "campaigns"

class Feedback(Base):
    __tablename__ = "feedback"
'''


def ratchet_app(tmp_path: Path, files: dict[str, str]) -> Path:
    return make_app(tmp_path, {"access/registry.py": REGISTRY_SRC, "db/models/models.py": MODELS_SRC, **files})


def ratchet(tmp_path: Path, files: dict[str, str], baseline: str = "") -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "baseline.txt"
    path.write_text(baseline)
    return csq.check_ratchet(ratchet_app(tmp_path, files), path)


def test_repo_ratchet_is_clean():
    errors = csq.check_ratchet()
    assert not errors, "\n".join(errors)


def test_baseline_never_grows():
    keys, errors = csq.load_baseline(csq.BASELINE)
    assert not errors
    counts = Counter(keys)
    grown = {k: n for k, n in counts.items() if n > FROZEN_BASELINE.get(k, 0)}
    assert not grown, (f"scoped_queries_baseline.txt gained {sorted(grown)}; the baseline only shrinks. Read "
                       "through app.access (scoped_select / scoped_get / scoped_select_multi) instead")
    shrunk = {k: n for k, n in FROZEN_BASELINE.items() if counts.get(k, 0) < n}
    assert not shrunk, (f"scoped_queries_baseline.txt lost {sorted(shrunk)}: lower FROZEN_BASELINE in this test "
                        "to match, so the ceiling shrinks with it")


def test_annotated_tablename_is_read(tmp_path):
    app = ratchet_app(tmp_path, {"db/models/more.py": "class Campaign(Base):\n    __tablename__: str = 'campaigns'\n"})
    assert csq.registered_models(app)["Campaign"] == "campaigns"


def test_registered_models_come_from_the_registry_and_tablenames(tmp_path):
    real = csq.registered_models(csq.APP)
    assert real["JournalEntry"] == "journal_entries" and real["Campaign"] == "campaigns" and "Feedback" not in real
    assert csq.registered_models(ratchet_app(tmp_path, {})) == {"JournalEntry": "journal_entries",
                                                                "Campaign": "campaigns"}


@pytest.mark.parametrize("body, key", [
    ("from sqlalchemy import select\ndef f():\n    return select(JournalEntry)\n",
     "app/services/s.py::f select:JournalEntry"),
    ("import sqlalchemy as sa\ndef f():\n    return sa.select(JournalEntry.shorthand)\n",
     "app/services/s.py::f select:JournalEntry"),
    ("def f():\n    return select(func.count(JournalEntry.id))\n", "app/services/s.py::f select:JournalEntry"),
    ("async def f(db, i):\n    return await db.get(Campaign, i)\n", "app/services/s.py::f get:Campaign"),
    ("async def f(self, i):\n    return await self.session.get(JournalEntry, i)\n",
     "app/services/s.py::f get:JournalEntry"),
    ("def f():\n    return text('UPDATE journal_entries SET x = 1')\n", "app/services/s.py::f raw_sql:journal_entries"),
    ("async def f(c):\n    await c.exec_driver_sql('select * from CAMPAIGNS')\n", "app/services/s.py::f raw_sql:campaigns"),
    ("def f(u):\n    return Campaign.user_id == u.id\n", "app/services/s.py::f owner_check:Campaign.user_id"),
    ("def f(u):\n    return u.id != Campaign.user_id\n", "app/services/s.py::f owner_check:Campaign.user_id"),
    ("class K:\n    def m(self):\n        return select(Campaign)\n", "app/services/s.py::K.m select:Campaign"),
    ("X = select(Campaign)\n", "app/services/s.py::<module> select:Campaign"),
])
def test_unbaselined_site_fails_and_baselined_passes(tmp_path, body, key):
    errors = ratchet(tmp_path / "bad", {"services/s.py": body})
    assert len(errors) == 1 and "outside app/access/" in errors[0], errors
    assert ratchet(tmp_path / "ok", {"services/s.py": body}, key + "\n") == []


def test_each_site_needs_its_own_line(tmp_path):
    body = "def f():\n    a = select(Campaign)\n    return a, select(Campaign)\n"
    one = "app/services/s.py::f select:Campaign\n"
    assert len(ratchet(tmp_path / "one", {"services/s.py": body}, one)) == 1
    assert ratchet(tmp_path / "two", {"services/s.py": body}, one * 2) == []


def test_unregistered_models_access_package_and_strings_pass(tmp_path):
    assert ratchet(tmp_path, {
        "services/s.py": ("def f(db, campaign, d):\n    return (select(Feedback), db.get(Feedback, 1), "
                          "text('select * from feedback'), campaign.user_id == 1, get(JournalEntry))\n"),
        "access/r.py": "def f(db):\n    return select(JournalEntry), db.get(Campaign, 1), Campaign.user_id == 1\n",
        "services/doc.py": '"""select(JournalEntry) and Campaign.user_id == u in a docstring."""\n',
    }) == []


def test_stale_baseline_line_fails(tmp_path):
    errors = ratchet(tmp_path, {}, "app/services/gone.py::f select:Campaign\n")
    assert len(errors) == 1 and "no longer exist" in errors[0] and "delete the line" in errors[0]


def test_malformed_baseline_line_fails(tmp_path):
    errors = ratchet(tmp_path, {}, "# comment\n\nselect(Campaign) somewhere\n")
    assert len(errors) == 1 and "not `<path>::<function> <kind>:<target>`" in errors[0]


@pytest.mark.parametrize("rel, body", [
    ("api/routes/r.py", "from app.api.deps import get_campaign_with_access\n"),
    ("api/routes/r.py", "from app.api.deps import accessible_campaign_ids as ids\n"),
    ("api/routes/r.py", "import app.api.deps as d\nasync def r(db, c, u):\n    return await d.get_campaign_with_access(db, c, u)\n"),
    ("api/routes/r.py", "async def r(db, u):\n    return await accessible_campaign_ids(db, u)\n"),
    ("api/deps.py", "async def accessible_campaign_ids(db, user):\n    return []\n"),
    ("services/s.py", "async def get_campaign_with_access(db, c, u):\n    return None\n"),
])
def test_deprecated_helper_reference_fails(tmp_path, rel, body):
    errors = ratchet(tmp_path, {rel: body})
    assert errors and "deprecated" in errors[0] and "require_campaign" in errors[0], errors


def test_deprecated_definition_in_deps_and_comments_pass(tmp_path):
    assert ratchet(tmp_path, {
        "api/deps.py": "async def get_campaign_with_access(db, campaign_id, user, require_owner=False):\n    return None\n",
        "api/routes/feedback.py": "# Not gated through get_campaign_with_access (a comment)\nX = 'accessible_campaign_ids'\n",
    }) == []


def test_main_runs_the_ratchet(tmp_path, capsys):
    app = ratchet_app(tmp_path, {"services/s.py": "def f():\n    return select(Campaign)\n"})
    empty = tmp_path / "b.txt"
    empty.write_text("")
    assert csq.main(["--app", str(app), "--baseline", str(empty)]) == 1
    assert "app/services/s.py:2: select `Campaign`" in capsys.readouterr().out


# ---- Owner infrastructure (OWNER_INFRA) ---------------------------------------

# Pinned: widening the allowance means changing this test too.
FROZEN_OWNER_INFRA = {"app/jobs/": ("E0-Jobs", frozenset({"Job", "DataBackfill"}))}

INFRA_REGISTRY = """
REGISTRY: dict = {
    JournalEntry: stored(),
    Job: always_gm(owner_field="created_by"),
    DataBackfill: always_gm(),
}
"""
INFRA_MODELS = """
class JournalEntry(Base):
    __tablename__ = "journal_entries"

class Job(Base):
    __tablename__ = "jobs"

class DataBackfill(Base):
    __tablename__ = "data_backfills"
"""


def infra(tmp_path: Path, files: dict[str, str]) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "baseline.txt"
    path.write_text("")
    app = make_app(tmp_path, {"access/registry.py": INFRA_REGISTRY, "db/models/models.py": INFRA_MODELS, **files})
    return csq.check_ratchet(app, path)


def test_owner_infra_is_pinned():
    assert csq.OWNER_INFRA == FROZEN_OWNER_INFRA


def test_owner_infra_matches_the_real_table_owner_map():
    assert csq.check_owner_infra() == []


def test_owner_infra_cross_check_fails_when_the_epic_does_not_own_the_table():
    owners = {"jobs": {"E0-Jobs": "spine"}, "data_backfills": {"E0-Jobs": "spine", "E0-Journal": "epics"}}
    problems = csq.check_owner_infra(csq.APP, owners)
    assert len(problems) == 1 and "data_backfills" in problems[0] and "not E0-Jobs alone" in problems[0]
    assert "nobody" in csq.check_owner_infra(csq.APP, {})[0]


def test_jobs_package_may_read_its_own_tables(tmp_path):
    assert infra(tmp_path, {
        "jobs/worker.py": ("async def _claim(db, i):\n    job = await db.get(Job, i)\n"
                           "    return job, select(DataBackfill), text('UPDATE jobs SET status = 1')\n"),
    }) == []


@pytest.mark.parametrize("rel, body", [
    # app/jobs reading Campaign content: still a scoped-query site.
    ("jobs/worker.py", "def f():\n    return select(JournalEntry)\n"),
    # Another package reading Job (e.g. a route serving a Player their Jobs).
    ("api/routes/jobs.py", "async def r(db, i):\n    return await db.get(Job, i)\n"),
    ("services/reaper.py", "def f():\n    return select(Job)\n"),
    # A look-alike prefix is not the package.
    ("jobsx/w.py", "def f():\n    return select(Job)\n"),
])
def test_owner_infra_allows_nothing_else(tmp_path, rel, body):
    errors = infra(tmp_path, {rel: body})
    assert len(errors) == 1 and "outside app/access/" in errors[0], errors


# ---- E0-Access.9: the one Visibility writer ----------------------------------

# Pinned: widening the allowance means changing this test too.
FROZEN_VISIBILITY_WRITE_ALLOWED = {("app/services/world_service.py", "apply_change"): frozenset({"visibility_floor"})}


def vis(tmp_path: Path, files: dict[str, str]) -> list:
    return csq.check_visibility_writes(make_app(tmp_path, files))


def test_visibility_allowlist_is_pinned_and_separate_from_owner_infra():
    assert csq.VISIBILITY_WRITE_ALLOWED == FROZEN_VISIBILITY_WRITE_ALLOWED
    assert not any(path.startswith(prefix) for path, _ in csq.VISIBILITY_WRITE_ALLOWED for prefix in csq.OWNER_INFRA)


def test_repo_has_no_visibility_write_outside_access():
    found = csq.check_visibility_writes()
    assert not found, "\n".join(map(str, found))


@pytest.mark.parametrize("body, column", [
    ("def f(x, v):\n    x.visibility = v\n", "visibility"),
    ("def f(x, v):\n    x.visibility_floor = v\n", "visibility_floor"),
    ("def f(x, v):\n    x.field_visibility = {'a': v}\n", "field_visibility"),
    ("def f(a, b, v):\n    a.title, b.visibility = 't', v\n", "visibility"),
    ("def f(x, v):\n    x.visibility: str = v\n", "visibility"),
    ("def f(x, v):\n    x.field_visibility['name'] = v\n", "field_visibility"),
    ("def f(x):\n    del x.field_visibility['name']\n", "field_visibility"),
    ("def f(x, v):\n    x.field_visibility.update(name=v)\n", "field_visibility"),
    ("def f(x, v):\n    setattr(x, 'field_visibility', v)\n", "field_visibility"),
    ("def f(x, v):\n    setattr(x, 'visibility', v)\n", "visibility"),
    ("def f(M, v):\n    return update(M).values(visibility=v)\n", "visibility"),
    ("def f(M, v):\n    return sa.update(M).where(M.id == 1).values({'visibility_floor': v})\n", "visibility_floor"),
    ("def f(M, v):\n    return update(M).values({M.visibility: v})\n", "visibility"),
    ("def f(stmt, v):\n    return stmt.on_conflict_do_update(index_elements=['id'], set_={'visibility': v})\n",
     "visibility"),
    ("def f():\n    return text('UPDATE journal_entries SET visibility = :v WHERE id = :id')\n", "visibility"),
    ("async def f(conn):\n    await conn.exec_driver_sql(\"update e set field_visibility = '{}'\")\n",
     "field_visibility"),
    # In a method too.
    ("class S:\n    def f(self, v):\n        self.row.visibility = v\n", "visibility"),
])
def test_planted_visibility_write_fails(tmp_path, body, column):
    found = vis(tmp_path, {"services/thing.py": body})
    assert len(found) == 1, found
    assert found[0].path == "app/services/thing.py" and f"writes `{column}`" in str(found[0])
    assert "set_visibility" in str(found[0])


def test_visibility_reads_constructors_and_access_pass(tmp_path):
    assert vis(tmp_path, {
        "services/reads.py": (
            "from app.db.models import JournalEntry\n"
            "def f(db, x, cid):\n"
            "    shown = x.visibility == 'party'\n"
            "    e = JournalEntry(campaign_id=cid, visibility='gm')\n"
            "    q = select(JournalEntry).where(JournalEntry.visibility == 'gm')\n"
            "    t = text('SELECT id FROM journal_entries WHERE visibility = :v')\n"
            "    u = text('UPDATE journal_entries SET narrative = :n WHERE visibility = :v')\n"
            "    data = {'visibility': 'gm'}\n"
            "    data.update({'visibility': 'gm'})\n"
            "    return getattr(x, 'visibility'), x.field_visibility.get('a'), e, q, t, u, data, shown\n"
        ),
        "db/models/thing.py": (
            "class Thing(Base):\n"
            "    visibility: Mapped[Visibility] = mapped_column(VISIBILITY_ENUM)\n"
            "    visibility_floor = mapped_column(VISIBILITY_ENUM)\n"
        ),
        # Strings are not writes.
        "services/doc.py": '"""x.visibility = v, setattr(x, "visibility", v)"""\n',
        "access/visibility.py": "def set_visibility(row, v):\n    row.visibility = v\n    setattr(row, 'field_visibility', {})\n",
    }) == []


def test_merge_floor_write_in_apply_change_passes(tmp_path):
    assert vis(tmp_path, {
        "services/world_service.py": (
            "async def apply_change(db, ctx, op, rows, floor):\n"
            "    for row in rows:\n"
            "        row.visibility_floor = floor\n"
            "    def inner(r):\n"
            "        r.visibility_floor = floor\n"
            "    return update(Mention).values(visibility_floor=floor)\n"
        ),
    }) == []


@pytest.mark.parametrize("rel, body", [
    # The same write anywhere else.
    ("services/world_service.py", "def merge_entities(row, floor):\n    row.visibility_floor = floor\n"),
    ("services/other_service.py", "def apply_change(row, floor):\n    row.visibility_floor = floor\n"),
    ("api/routes/world.py", "def apply_change(row, floor):\n    row.visibility_floor = floor\n"),
    ("services/world_service.py", "row.visibility_floor = 'gm'\n"),
    # A method named apply_change is not the module-level function.
    ("services/world_service.py", "class W:\n    def apply_change(self, row, floor):\n        row.visibility_floor = floor\n"),
    # apply_change may write only visibility_floor.
    ("services/world_service.py", "def apply_change(row, v):\n    row.visibility = v\n"),
    ("services/world_service.py", "def apply_change(row, v):\n    row.field_visibility = {'a': v}\n"),
    ("services/world_service.py", "def apply_change(M, v):\n    return update(M).values(visibility=v)\n"),
])
def test_floor_write_elsewhere_fails(tmp_path, rel, body):
    found = vis(tmp_path, {rel: body})
    assert len(found) == 1, found


def test_main_runs_the_visibility_check(tmp_path, capsys):
    empty = tmp_path / "b.txt"
    empty.write_text("")
    app = make_app(tmp_path, {"services/s.py": "def f(x, v):\n    x.visibility = v\n"})
    assert csq.main(["--app", str(app), "--baseline", str(empty)]) == 1
    assert "app/services/s.py:2: writes `visibility` outside app/access/" in capsys.readouterr().out
