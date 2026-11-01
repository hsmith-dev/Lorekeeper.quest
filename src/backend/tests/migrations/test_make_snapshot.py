"""Unit tests for scripts/make_snapshot.py (no database needed)."""
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_snapshot.py"
_spec = importlib.util.spec_from_file_location("make_snapshot", _SCRIPT)
make_snapshot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_snapshot)


def test_clean_dump_strips_meta_commands_and_version_comments():
    raw = (
        "\\restrict abc123\n"
        "-- Dumped from database version 16.10\n"
        "-- Dumped by pg_dump version 16.10\n"
        "\n\n\n"
        "CREATE TABLE t (id int);\n"
        "\\unrestrict abc123\n"
    )
    assert make_snapshot.clean_dump(raw) == "CREATE TABLE t (id int);\n"


def test_refuses_non_test_database(tmp_path, capsys):
    out = tmp_path / "snap.sql"
    code = make_snapshot.main([
        "--database-url", "postgresql+asyncpg://u:p@127.0.0.1:1/lorekeeper",
        "--output", str(out),
    ])
    assert code == 2
    assert not out.exists()
    assert "Refusing" in capsys.readouterr().err


def test_seed_matches_the_snapshot_test_counts():
    from tests.migrations.test_upgrade_snapshot import SEEDED_COUNTS

    inserts = [s for s in make_snapshot.seed_statements() if s.startswith("INSERT INTO ")]
    per_table: dict[str, int] = {}
    for stmt in inserts:
        table = stmt.split()[2]
        per_table[table] = per_table.get(table, 0) + 1
    # app_config's row comes from migration 4b8f2d9e71c3, not the seed.
    assert per_table == {t: n for t, n in SEEDED_COUNTS.items() if t != "app_config"}
