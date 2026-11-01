"""Unit tests for scripts/check_table_owners.py (CI-7, E0-QA.10).

Run: python -m pytest -q scripts/test_check_table_owners.py  (stdlib + pytest)
"""
from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check_table_owners", HERE / "check_table_owners.py")
cto = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cto
_spec.loader.exec_module(cto)

# The ceiling: pre-expansion tables with no owner. The legacy list may lose
# entries, never gain them. Shrink this set in the same PR.
FROZEN_LEGACY = frozenset({
    "users", "campaigns", "journal_entries", "tags", "journal_tags", "tag_categories",
    "npcs", "quests", "chat_sessions", "source_documents", "source_chunks",
    "campaign_members", "campaign_share_tokens", "model_evaluations",
    "character_sheet_templates", "character_sheets", "user_settings", "session_plans",
    "shorthand_terms", "feedback", "admin_messages", "password_reset_tokens",
    "promo_codes", "promo_code_redemptions", "subscriptions", "training_samples", "app_config",
})

SPINE = """\
# Spine

### AD-19: Migration ownership

- **Rule:**
  - **Foundation revisions.** Three revisions:
    - **F1-core** (E0-Access): the `visibility` and `campaign_role` enums; the role and `access_epoch` columns on existing tables; `chat_sessions.archived_at` and `npc_entity_id`; and the `entry_hash` uniqueness change.
    - **F2-jobs-files** (E0-Jobs): `jobs`, `data_backfills`, `stored_files` and `derived_sources`.
    - **F3-world** (E0-WorldCore): `entities` with every column; `entity_aliases` + `quest_steps`; and the legacy copy.

### AD-20: Next

## Capability → Architecture Map (epic / module boundary map)

| Epic | FRs | Owns (backend) | Owns (tables) | Owns (frontend) | Governed by |
| --- | --- | --- | --- | --- | --- |
| E0-Access | FR-7 | `app/access/*` | F1-core | — | AD-12 |
| E0-Jobs | FR-1 | `app/jobs/*` | F2-jobs-files: `jobs`, `data_backfills`, `stored_files`, `derived_sources` | — | AD-2 |
| E0-WorldCore | FR-4 | `world_service.py` | F3-world | — | AD-9 |
| E9 Stats | FR-49 | `achievement_service.py` | `activity_events`, `user_achievements`, `user_settings.streaks_enabled` | — | AD-13 |
{extra_rows}
## Deferred
"""

EPICS = """\
### New tables and columns beyond the spine

| Owner | Table / column | Story | Note |
| --- | --- | --- | --- |
| E0-WorldCore | `entities.deleted_at` (soft delete) | E0-WorldCore.2 | x |
| E0-WorldCore | unique index on suggested `entity_mentions` | E0-WorldCore.7 | x |
| E4 | `live_sessions.recap_points`, `recap_now` | E4.5 | x |
| E9 | `user_settings.achievements_enabled` (next to the spine's `streaks_enabled`) | E9.2 | x |
{extra_rows}
### Files more than one epic edits
"""


def make(tmp_path: Path, *, spine_rows: str = "", epics_rows: str = "",
         migrations: dict[str, str] | None = None, legacy: str = "users: core schema\n"):
    (tmp_path / "spine.md").write_text(SPINE.format(extra_rows=spine_rows))
    (tmp_path / "epics.md").write_text(EPICS.format(extra_rows=epics_rows))
    mig = tmp_path / "versions"
    mig.mkdir(exist_ok=True)
    files = {"0001_initial.py": "op.create_table('users', sa.Column('id'))\n"}
    files.update(migrations or {})
    for name, body in files.items():
        (mig / name).write_text(textwrap.dedent(body))
    (tmp_path / "legacy.txt").write_text(legacy)
    errors, owners = cto.check(tmp_path / "spine.md", tmp_path / "epics.md", mig, tmp_path / "legacy.txt")
    return errors, owners


# ---- the real repo ---------------------------------------------------------

def test_repo_passes():
    errors, owners = cto.check()
    assert errors == []
    assert len(owners) > 0


def test_real_foundation_revisions():
    foundation = cto.parse_foundation(cto.SPINE.read_text())
    assert foundation["F1-core"] == ("E0-Access", [])  # enums and columns only
    assert foundation["F2-jobs-files"] == ("E0-Jobs", ["jobs", "data_backfills", "stored_files", "derived_sources"])
    owner, tables = foundation["F3-world"]
    assert owner == "E0-WorldCore" and len(tables) == 7 and tables[0] == "entities"


def test_legacy_never_grows():
    legacy, errors = cto.load_legacy(cto.LEGACY)
    assert errors == []
    grown = set(legacy) - FROZEN_LEGACY
    assert not grown, (
        f"table_owners_legacy.txt gained {sorted(grown)}; the legacy list only shrinks. "
        "Give the table an owner in the boundary map instead.")


# ---- parsing ---------------------------------------------------------------

def test_fixture_owners(tmp_path):
    errors, owners = make(tmp_path)
    assert errors == []
    assert {t: sorted(o) for t, o in owners.items()} == {
        "jobs": ["E0-Jobs"], "data_backfills": ["E0-Jobs"], "stored_files": ["E0-Jobs"],
        "derived_sources": ["E0-Jobs"], "entities": ["E0-WorldCore"],
        "entity_aliases": ["E0-WorldCore"], "quest_steps": ["E0-WorldCore"],
        "activity_events": ["E9"], "user_achievements": ["E9"],
    }


@pytest.mark.parametrize("text, expected", [
    ("`jobs`, `data_backfills` and `stored_files`.", ["jobs", "data_backfills", "stored_files"]),
    ("the `visibility` and `campaign_role` enums", []),
    ("`chat_sessions.archived_at` and `npc_entity_id`;", []),
    ("the `entry_hash` uniqueness change", []),
    ("the role and `access_epoch` columns", []),
    ("`a` + `b`; then `c.d`", ["a", "b"]),
    ("`entities` with every column", ["entities"]),
])
def test_group_rule(text, expected):
    assert cto.tables_in(text, "group") == expected


# ---- planted violations ----------------------------------------------------

def test_double_owner_fails(tmp_path):
    errors, _ = make(tmp_path, spine_rows="| E2 Canon | FR-19 | x | `jobs`, `canon_notes` | — | AD-11 |\n")
    assert len(errors) == 1
    assert "'jobs' has two owners" in errors[0] and "E0-Jobs" in errors[0] and "E2" in errors[0]


def test_double_owner_across_docs_fails(tmp_path):
    errors, _ = make(tmp_path, epics_rows="| E10 | `activity_events` | E10.1 | x |\n")
    assert len(errors) == 1 and "E10" in errors[0] and "E9" in errors[0]


def test_unowned_create_table_fails(tmp_path):
    errors, _ = make(tmp_path, migrations={"0002_maps.py": """\
        def upgrade():
            op.create_table(
                'maps_x',
                sa.Column('id'),
            )
        """})
    assert len(errors) == 1
    assert "0002_maps.py" in errors[0] and "'maps_x'" in errors[0] and "Owns (tables)" in errors[0]


def test_unowned_raw_sql_fails(tmp_path):
    errors, _ = make(tmp_path, migrations={"0003_raw.py": 'op.execute("CREATE TABLE IF NOT EXISTS widgets (id uuid)")\n'})
    assert len(errors) == 1 and "'widgets'" in errors[0]


def test_owned_create_table_passes(tmp_path):
    errors, _ = make(tmp_path, migrations={"0004_jobs.py": "op.create_table('jobs')\nop.create_table(\"activity_events\")\n"})
    assert errors == []


def test_legacy_entry_also_owned_fails(tmp_path):
    errors, _ = make(tmp_path, legacy="users: core\njobs: oops\n",
                     migrations={"0005.py": "op.create_table('jobs')\n"})
    assert len(errors) == 1 and "'jobs'" in errors[0] and "remove it from the legacy list" in errors[0]


def test_stale_legacy_entry_fails(tmp_path):
    errors, _ = make(tmp_path, legacy="users: core\nnpcs: legacy\n")
    assert len(errors) == 1 and "'npcs'" in errors[0] and "no longer created" in errors[0]


def test_legacy_entry_without_reason_fails(tmp_path):
    errors, _ = make(tmp_path, legacy="users\n")
    assert any("no reason" in e for e in errors)


def test_foundation_cited_by_wrong_epic_fails(tmp_path):
    errors, _ = make(tmp_path, spine_rows="| E1 | FR-12 | x | F2-jobs-files | — | AD-8 |\n")
    assert any("AD-19 gives F2-jobs-files to E0-Jobs" in e for e in errors)


def test_missing_section_is_an_error(tmp_path):
    (tmp_path / "spine.md").write_text("# nothing here\n")
    with pytest.raises(ValueError, match="AD-19"):
        cto.parse_owners((tmp_path / "spine.md").read_text(), EPICS.format(extra_rows=""))


@pytest.mark.parametrize("source, expected", [
    ('"""Create table for maps (and pins)."""\nop.execute("CREATE TABLE widgets (id uuid)")\n', ["widgets"]),
    ('# CREATE TABLE gadgets (id uuid)\nop.execute("""CREATE TABLE "public"."widgets" (id uuid)""")\n', ["widgets"]),
    ('op.execute("create table if not exists public.widgets(id uuid)")\n', ["widgets"]),
    ('op.execute("CREATE TABLE widgets AS SELECT 1")\n', []),
    ('def upgrade():\n    """Create table for the maps (x)."""\n    op.create_table(table_name="maps")\n', ["maps"]),
    ("op.rename_table('npcs_old', 'npcs_new')\n", ["npcs_new"]),
    ("op.rename_table('a', new_table_name='b')\n", ["b"]),
])
def test_tables_created_in(source, expected):
    assert cto.tables_created_in(source) == expected


def test_prose_create_table_is_not_a_table(tmp_path):
    errors, _ = make(tmp_path, migrations={"0006.py": '"""Create table for maps (and pins)."""\n# CREATE TABLE x (\n'})
    assert errors == []


def test_rename_to_unowned_table_fails(tmp_path):
    errors, _ = make(tmp_path, legacy="users: core\nnpcs: legacy\n", migrations={
        "0007.py": "op.create_table('npcs')\nop.rename_table('npcs', 'npc_archive')\n"})
    assert len(errors) == 1 and "0007.py" in errors[0] and "'npc_archive'" in errors[0]


def test_unparseable_migration_is_an_error():
    with pytest.raises(ValueError, match="bad.py"):
        cto.tables_created_in("def (:\n", "bad.py")


def test_epics_table_without_table_column_is_an_error():
    epics = ("### New tables and columns beyond the spine\n\n| Owner | Story |\n| --- | --- |\n| E4 | E4.5 |\n"
             "### Next\n")
    with pytest.raises(ValueError, match="Table / column"):
        cto.parse_owners(SPINE.format(extra_rows=""), epics)


def test_epics_short_rows_are_skipped(tmp_path):
    errors, owners = make(tmp_path, epics_rows="| E10 |\n")
    assert errors == [] and "maps" not in owners
