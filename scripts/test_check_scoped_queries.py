"""Unit tests for scripts/check_scoped_queries.py (CI-8, E0-Access.2 part).

Run: python -m pytest -q scripts/test_check_scoped_queries.py  (stdlib + pytest)
"""
from __future__ import annotations

import importlib.util
import sys
import textwrap
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
    assert csq.main(["--app", str(make_app(tmp_path, {}))]) == 0
    bad = make_app(tmp_path / "bad", {"services/other.py": "def f(ctx):\n    return ctx.as_system('merge')\n"})
    assert csq.main(["--app", str(bad)]) == 1
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
