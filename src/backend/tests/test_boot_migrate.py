"""scripts/boot_migrate.py: the upgrade-safe boot of the prod web service (E0-Platform.9).

Unit tests (no database) cover each row of the spec's I/O matrix with a fake
connection and fake pg_dump programs. The integration test restores the
a3e7c1f9d258 snapshot into the test DB, boots with the real pg_dump (skipped
when it is missing or older than the server), restores the dump it wrote,
proves a failing pg_dump leaves the revision alone, and runs two boots at
once. Its teardown rebuilds the session schema.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import boot_migrate as bm
from scripts.boot_migrate import DbState

BACKEND_DIR = Path(__file__).resolve().parents[1]
HEAD = "headrev000001"
OLD = "oldrev0000001"
NOW = datetime(2026, 11, 21, 10, 15, 0, tzinfo=timezone.utc)
URL = "postgresql+asyncpg://lk:s3cret-pw@db.example:5433/lorekeeper"


def _program(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _good_pg_dump(tmp_path: Path) -> Path:
    # Records its argv and environment, then writes a non-empty "archive" to -f.
    log = tmp_path / "pg_dump.log"
    return _program(tmp_path / "pg_dump_ok", f"""
echo "argv: $*" >> {log}
echo "PGPASSWORD=$PGPASSWORD PGHOST=$PGHOST PGPORT=$PGPORT PGUSER=$PGUSER PGDATABASE=$PGDATABASE" >> {log}
while [ $# -gt 0 ]; do
  if [ "$1" = "-f" ]; then shift; printf 'PGDMP fake archive' > "$1"; fi
  shift
done
""")


class FakeConn:
    closed = False

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_db(monkeypatch, tmp_path):
    """Patch the database, the scripts and alembic; return the call record."""
    rec = {"states": [], "alembic": [], "alembic_rc": 0, "locked": 0, "conn": FakeConn()}

    async def connect(target):
        rec["target"] = target
        return rec["conn"]

    async def lock(conn):
        rec["locked"] += 1

    async def read_state(conn):
        return rec["states"].pop(0) if len(rec["states"]) > 1 else rec["states"][0]

    def run_alembic(environ):
        rec["alembic"].append(dict(environ))
        return rec["alembic_rc"]

    monkeypatch.setattr(bm, "connect", connect)
    monkeypatch.setattr(bm, "lock", lock)
    monkeypatch.setattr(bm, "read_state", read_state)
    monkeypatch.setattr(bm, "run_alembic", run_alembic)
    monkeypatch.setattr(bm, "script_revisions", lambda: (frozenset({HEAD}), frozenset({HEAD, OLD})))
    backups = tmp_path / "backups"
    backups.mkdir()
    rec["backups"] = backups
    rec["env"] = {"DATABASE_URL": URL, "BACKUP_DIR": str(backups), "PATH": os.environ.get("PATH", "")}
    return rec


def _boot(rec, **env) -> int:
    environ = {**rec["env"], **env}
    try:
        return asyncio.run(bm.boot(environ, now=NOW))
    except bm.BootError as exc:
        bm.log(str(exc))
        return 1


def _state(revs, tables=True) -> DbState:
    return DbState(frozenset(revs), tables)


# ── the I/O matrix ─────────────────────────────────────────────────────────


def test_upgrade_dumps_first_then_migrates_and_prunes(fake_db, tmp_path, capsys):
    old_dumps = [fake_db["backups"] / f"pre-upgrade_2026010{i}T000000Z_{OLD}.dump" for i in range(1, 7)]
    for p in old_dumps:
        p.write_bytes(b"old")
    order = []
    real_dump = bm.pre_upgrade_dump

    def dump(*a, **k):
        order.append("dump")
        return real_dump(*a, **k)

    def alembic(environ):
        order.append("alembic")
        assert (fake_db["backups"] / f"pre-upgrade_20261121T101500Z_{OLD}.dump").stat().st_size > 0
        return 0

    pg_dump = _good_pg_dump(tmp_path)
    fake_db["states"] = [_state({OLD}), _state({HEAD})]
    mp = pytest.MonkeyPatch()
    mp.setattr(bm, "pre_upgrade_dump", dump)
    mp.setattr(bm, "run_alembic", alembic)
    try:
        assert _boot(fake_db, PG_DUMP=str(pg_dump), PRE_UPGRADE_BACKUPS_KEEP="3") == 0
    finally:
        mp.undo()

    assert order == ["dump", "alembic"]
    names = sorted(p.name for p in fake_db["backups"].iterdir())
    # The new dump plus the two newest old ones; no .partial left.
    assert names == [old_dumps[4].name, old_dumps[5].name, f"pre-upgrade_20261121T101500Z_{OLD}.dump"]
    assert fake_db["locked"] == 1 and fake_db["conn"].closed

    log = (tmp_path / "pg_dump.log").read_text()
    assert "s3cret-pw" not in log.splitlines()[0]  # argv
    assert "-Fc" in log and "PGPASSWORD=s3cret-pw" in log
    assert "PGHOST=db.example PGPORT=5433 PGUSER=lk PGDATABASE=lorekeeper" in log
    err = capsys.readouterr().err
    assert "s3cret-pw" not in err
    assert all(line.startswith("boot-migrate: ") for line in err.strip().splitlines())


def test_at_head_skips_dump_and_alembic(fake_db, tmp_path, capsys):
    fake_db["states"] = [_state({HEAD})]
    pg_dump = _program(tmp_path / "pg_dump_never", f"touch {tmp_path}/called\nexit 1\n")
    assert _boot(fake_db, PG_DUMP=str(pg_dump)) == 0
    assert fake_db["alembic"] == []
    assert not (tmp_path / "called").exists()
    assert list(fake_db["backups"].iterdir()) == []
    assert "boot-migrate: at head" in capsys.readouterr().err


def test_fresh_install_upgrades_without_dump(fake_db, tmp_path, capsys):
    fake_db["states"] = [_state(set(), tables=False), _state({HEAD})]
    pg_dump = _program(tmp_path / "pg_dump_never", f"touch {tmp_path}/called\nexit 1\n")
    assert _boot(fake_db, PG_DUMP=str(pg_dump)) == 0
    assert len(fake_db["alembic"]) == 1
    assert not (tmp_path / "called").exists()
    assert list(fake_db["backups"].iterdir()) == []
    assert "boot-migrate: empty database, nothing to back up" in capsys.readouterr().err


@pytest.mark.parametrize("case", ["missing", "rc", "empty", "unwritable"])
def test_dump_failure_never_migrates(fake_db, tmp_path, capsys, case):
    fake_db["states"] = [_state({OLD})]
    env = {}
    if case == "missing":
        env["PG_DUMP"] = str(tmp_path / "no-such-pg_dump")
    elif case == "rc":
        # Writes part of a file, then fails.
        env["PG_DUMP"] = str(_program(tmp_path / "pg_dump_rc", """
while [ $# -gt 0 ]; do [ "$1" = "-f" ] && { shift; printf 'half' > "$1"; }; shift; done
echo 'pg_dump: error: connection failed' >&2
exit 3
"""))
    elif case == "empty":
        env["PG_DUMP"] = str(_program(tmp_path / "pg_dump_empty", """
while [ $# -gt 0 ]; do [ "$1" = "-f" ] && { shift; : > "$1"; }; shift; done
exit 0
"""))
    else:
        env["PG_DUMP"] = str(_good_pg_dump(tmp_path))
        if os.geteuid() == 0:
            pytest.skip("root ignores directory permissions")
        fake_db["backups"].chmod(0o500)
    try:
        assert _boot(fake_db, **env) == 1
    finally:
        fake_db["backups"].chmod(0o700)
    assert fake_db["alembic"] == []
    assert list(fake_db["backups"].iterdir()) == []  # the partial file is gone
    err = capsys.readouterr().err
    assert re.search(r"^boot-migrate: pre-upgrade backup failed \(.+\); not migrating$", err, re.M), err
    if case == "rc":
        assert "exited 3" in err and "connection failed" in err


def test_unknown_revision_refuses_without_dump(fake_db, tmp_path, capsys):
    fake_db["states"] = [_state({"futurerev9999"})]
    pg_dump = _program(tmp_path / "pg_dump_never", f"touch {tmp_path}/called\nexit 1\n")
    assert _boot(fake_db, PG_DUMP=str(pg_dump)) == 1
    assert fake_db["alembic"] == [] and not (tmp_path / "called").exists()
    err = capsys.readouterr().err
    assert "boot-migrate: " in err and "futurerev9999" in err and "docs/OCI_DEPLOYMENT.md" in err


def test_migration_failure_names_the_dump(fake_db, tmp_path, capsys):
    fake_db["states"] = [_state({OLD})]
    fake_db["alembic_rc"] = 2
    assert _boot(fake_db, PG_DUMP=str(_good_pg_dump(tmp_path))) == 1
    dump = f"pre-upgrade_20261121T101500Z_{OLD}.dump"
    assert (fake_db["backups"] / dump).exists()
    err = capsys.readouterr().err
    assert "boot-migrate: migration failed (alembic exited 2)" in err
    assert f"restore-db.sh --no-restart {dump}" in err


def test_keep_must_be_positive_whole_number(fake_db):
    fake_db["states"] = [_state({HEAD})]
    assert _boot(fake_db, PRE_UPGRADE_BACKUPS_KEEP="zero") == 1
    assert _boot(fake_db, PRE_UPGRADE_BACKUPS_KEEP="0") == 1
    assert bm.keep_count({}) == 5


def test_main_reports_one_line_and_exit_code(capsys):
    assert bm.main([], {}) == 1
    assert capsys.readouterr().err.strip() == "boot-migrate: DATABASE_URL is not set"
    assert bm.main(["bogus"], {}) == 2


def test_unparseable_url_does_not_echo_it(capsys):
    assert bm.main([], {"DATABASE_URL": "postgresql+asyncpg://u:pw@[::bad"}) == 1
    err = capsys.readouterr().err
    assert "pw" not in err and err.startswith("boot-migrate: ")


def test_target_strips_driver_and_keeps_parts():
    t = bm.target_from_url(URL)
    assert (t.host, t.port, t.user, t.password, t.database) == ("db.example", 5433, "lk", "s3cret-pw", "lorekeeper")
    env = t.pg_env({"PGPASSWORD": "stale", "X": "1"})
    assert env["PGPASSWORD"] == "s3cret-pw" and env["X"] == "1"


def test_real_scripts_have_one_head():
    heads, known = bm.script_revisions()
    assert len(heads) == 1 and heads <= known and "a3e7c1f9d258" in known


def test_restore_refuses_unreadable_archive_before_touching_db(monkeypatch, tmp_path, capsys):
    async def connect(target):  # pragma: no cover - must not be reached
        raise AssertionError("connected before the archive was checked")

    monkeypatch.setattr(bm, "connect", connect)
    bad = tmp_path / "bad.dump"
    bad.write_bytes(b"not an archive")
    pg_restore = _program(tmp_path / "pg_restore_bad", "echo 'pg_restore: error: input file is not a valid archive' >&2\nexit 1\n")
    code = bm.main(["restore", str(bad)], {"DATABASE_URL": URL, "PG_RESTORE": str(pg_restore)})
    assert code == 1
    assert "nothing was touched" in capsys.readouterr().err


# ── integration: the real test database ────────────────────────────────────


def _pg_major(text: str) -> int | None:
    m = re.search(r"(\d+)(?:\.\d+)?", text)
    return int(m.group(1)) if m else None


@pytest.fixture
def snapshot_db(tmp_path):
    from tests.conftest import TEST_DB_URL, _guard_test_database, _reset_public_schema, build_test_schema
    from tests.migrations.test_upgrade_snapshot import SNAPSHOT_SQL, _restore

    pg_dump = shutil.which("pg_dump")
    if pg_dump is None or shutil.which("pg_restore") is None:
        pytest.skip("pg_dump / pg_restore not installed")
    _guard_test_database(TEST_DB_URL)

    async def server_major() -> int:
        target = bm.target_from_url(TEST_DB_URL)
        conn = await bm.connect(target)
        try:
            return int(await conn.fetchval("SHOW server_version_num")) // 10000
        finally:
            await conn.close()

    client = _pg_major(subprocess.run([pg_dump, "--version"], capture_output=True, text=True).stdout)
    if client is None or client < asyncio.run(server_major()):
        pytest.skip(f"pg_dump {client} is older than the test server")

    def load_snapshot():
        asyncio.run(_reset_public_schema(TEST_DB_URL, with_vector=False))
        asyncio.run(_restore(TEST_DB_URL, SNAPSHOT_SQL.read_text()))

    backups = tmp_path / "backups"
    backups.mkdir()
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL, "BACKUP_DIR": str(backups)}
    try:
        load_snapshot()
        yield {"url": TEST_DB_URL, "env": env, "backups": backups, "load": load_snapshot}
    finally:
        build_test_schema(TEST_DB_URL)


def _revision(url: str) -> frozenset[str]:
    async def read():
        conn = await bm.connect(bm.target_from_url(url))
        try:
            return (await bm.read_state(conn)).revisions
        finally:
            await conn.close()

    return asyncio.run(read())


def _dumps(backups: Path) -> list[str]:
    return sorted(p.name for p in backups.iterdir())


def test_boot_on_snapshot_dumps_upgrades_and_restores(snapshot_db, tmp_path):
    url, env, backups = snapshot_db["url"], snapshot_db["env"], snapshot_db["backups"]
    heads, _ = bm.script_revisions()
    assert _revision(url) == {"a3e7c1f9d258"}

    # Upgrade: one dump named for the old revision, then head.
    assert bm.main([], env) == 0
    names = _dumps(backups)
    assert len(names) == 1 and re.fullmatch(r"pre-upgrade_\d{8}T\d{6}Z_a3e7c1f9d258\.dump", names[0]), names
    assert _revision(url) == heads

    # The dump restores to the old revision (the newer tables are gone too).
    assert bm.main(["restore", str(backups / names[0])], env) == 0
    assert _revision(url) == {"a3e7c1f9d258"}

    # A failing pg_dump: exit 1, the revision unchanged, no new file.
    failing = _program(tmp_path / "pg_dump_fail", "echo 'pg_dump: error: disk full' >&2\nexit 1\n")
    assert bm.main([], {**env, "PG_DUMP": str(failing)}) == 1
    assert _revision(url) == {"a3e7c1f9d258"}
    assert _dumps(backups) == names

    # Two boots at once: exactly one dump and one upgrade, both exit 0.
    for p in backups.iterdir():
        p.unlink()
    procs = [subprocess.Popen([sys.executable, "scripts/boot_migrate.py"], cwd=BACKEND_DIR, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
             for _ in range(2)]
    outs = [p.communicate(timeout=600)[0] for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    assert len(_dumps(backups)) == 1, (_dumps(backups), outs)
    assert sum("running alembic upgrade head" in o for o in outs) == 1, outs
    assert sum("boot-migrate: at head" in o for o in outs) == 1, outs
    assert _revision(url) == heads
