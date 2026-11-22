"""Upgrade-safe boot for the prod `web` service (E0-Platform.9).

    python scripts/boot_migrate.py            # boot: back up, then migrate
    python scripts/boot_migrate.py restore [FILE]   # FILE, or stdin

Boot runs before gunicorn (docker-compose.prod.yml). Under a Postgres
advisory lock, so a second web replica waits and then finds the schema at
head:

* at head: nothing to do;
* no user tables (a fresh install): `alembic upgrade head`, no dump;
* a migration pending on a database with data: `pg_dump -Fc` to
  BACKUP_DIR/pre-upgrade_<UTC stamp>_<revision>.dump (written as `.partial`
  and renamed only when non-empty), then `alembic upgrade head`, then prune
  to the newest PRE_UPGRADE_BACKUPS_KEEP (default 5) dumps;
* the dump fails: exit 1 without migrating;
* the database is at a revision this image does not know (it was upgraded by
  a newer image): exit 1, no dump.

`restore` resets the `public` schema and loads a custom-format dump with
this image's pg_restore and psql (pg_dump 17 archives can't be read by the
pg16 server image's client), reset and load in one transaction, so a failed
restore leaves the database as it was. `--clean` is not used: it can't drop
the tables a newer migration added. Rollback: docs/OCI_DEPLOYMENT.md, "Rolling back".

Every log line starts with `boot-migrate:`. The password never reaches argv
or a log line: pg_dump and pg_restore get it through PGPASSWORD.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
LOCK_NAME = "lorekeeper.boot_migrate"
DUMP_PREFIX = "pre-upgrade_"
DEFAULT_BACKUP_DIR = "/backups"
DEFAULT_KEEP = 5
ROLLBACK_DOC = "docs/OCI_DEPLOYMENT.md, 'Rolling back'"
CONNECT_ATTEMPTS = 15
CONNECT_DELAY_S = 2.0


def log(message: str) -> None:
    print(f"boot-migrate: {message}", file=sys.stderr, flush=True)


class BootError(Exception):
    """A refusal: logged as one `boot-migrate:` line, exit 1."""


@dataclass(frozen=True)
class Target:
    host: str | None
    port: int | None
    user: str | None
    password: str | None
    database: str | None

    def pg_env(self, environ: Mapping[str, str]) -> dict[str, str]:
        """The environment for pg_dump / pg_restore: libpq variables, password included."""
        env = dict(environ)
        for key, value in (("PGHOST", self.host), ("PGPORT", self.port), ("PGUSER", self.user),
                           ("PGPASSWORD", self.password), ("PGDATABASE", self.database)):
            if value is not None and value != "":
                env[key] = str(value)
            else:
                env.pop(key, None)
        return env


def target_from_url(url: str) -> Target:
    """DATABASE_URL (`postgresql+asyncpg://...`) -> connection parts."""
    from sqlalchemy.engine import make_url

    try:
        parsed = make_url(url)
    except Exception:  # no exception text: it would echo the URL, password included
        raise BootError("DATABASE_URL could not be parsed") from None
    if not parsed.database:
        raise BootError("DATABASE_URL names no database")
    return Target(parsed.host, parsed.port, parsed.username, parsed.password, parsed.database)


def database_url(environ: Mapping[str, str]) -> str:
    url = environ.get("DATABASE_URL")
    if not url:
        raise BootError("DATABASE_URL is not set")
    return url


# ── Alembic scripts ────────────────────────────────────────────────────────


def _script_directory():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ALEMBIC_INI))
    # Absolute, so this works from any cwd (alembic.ini's is relative).
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return ScriptDirectory.from_config(cfg)


def script_revisions() -> tuple[frozenset[str], frozenset[str]]:
    """(heads, every known revision) of this image's migrations."""
    script = _script_directory()
    known = frozenset(rev.revision for rev in script.walk_revisions())
    return frozenset(script.get_heads()), known


# ── Database state ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DbState:
    revisions: frozenset[str]  # alembic_version rows; empty when the table is missing
    has_user_tables: bool


async def connect(target: Target):
    import asyncpg

    last: BaseException | None = None
    for attempt in range(CONNECT_ATTEMPTS):
        try:
            return await asyncpg.connect(host=target.host, port=target.port, user=target.user,
                                         password=target.password, database=target.database)
        except (OSError, asyncpg.CannotConnectNowError, asyncpg.TooManyConnectionsError) as exc:
            last = exc
            if attempt + 1 < CONNECT_ATTEMPTS:
                await asyncio.sleep(CONNECT_DELAY_S)
    raise BootError(f"cannot connect to the database ({type(last).__name__})")


LOCK_POLL_S = 2.0
LOCK_REPORT_S = 30.0


async def lock(conn) -> None:
    """Session-level: held until the connection closes, so across the subprocesses.

    Waits as long as it takes (another web replica may be mid-dump), but says
    so every LOCK_REPORT_S with the holder's pid, so a hung holder is visible
    in the log instead of a silent stall.
    """
    waited = 0.0
    next_report = LOCK_REPORT_S
    while not await conn.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", LOCK_NAME):
        await asyncio.sleep(LOCK_POLL_S)
        waited += LOCK_POLL_S
        if waited >= next_report:
            holder = await conn.fetchval(
                "SELECT string_agg(pid::text, ', ') FROM pg_locks "
                "WHERE locktype = 'advisory' AND objid = hashtext($1)::oid AND granted", LOCK_NAME)
            log(f"still waiting for the migration lock after {int(waited)} s (held by pid {holder or '?'})")
            next_report += LOCK_REPORT_S


async def read_state(conn) -> DbState:
    revisions: frozenset[str] = frozenset()
    if await conn.fetchval("SELECT to_regclass('public.alembic_version')") is not None:
        rows = await conn.fetch("SELECT version_num FROM public.alembic_version")
        revisions = frozenset(r["version_num"] for r in rows)
    user_tables = await conn.fetchval(
        "SELECT count(*) FROM pg_catalog.pg_tables "
        "WHERE schemaname = 'public' AND tablename <> 'alembic_version'")
    return DbState(revisions, bool(user_tables))


# ── pg_dump ────────────────────────────────────────────────────────────────


def utc_stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def dump_name(stamp: str, revisions: frozenset[str]) -> str:
    rev = "-".join(sorted(revisions)) or "none"
    return f"{DUMP_PREFIX}{stamp}_{rev}.dump"


def _stderr_tail(text: str | bytes | None) -> str:
    if not text:
        return ""
    if isinstance(text, bytes):
        text = text.decode(errors="replace")
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return f": {lines[-1]}" if lines else ""


def pre_upgrade_dump(target: Target, backup_dir: Path, revisions: frozenset[str],
                     environ: Mapping[str, str], now: datetime | None = None) -> Path:
    """Write the dump; return its path, or raise BootError (no partial file left)."""
    if not backup_dir.is_dir() or not os.access(backup_dir, os.W_OK | os.X_OK):
        raise BootError(f"backup directory {backup_dir} is missing or not writable")
    # A crashed earlier boot's leftovers (we hold the lock, so none is in flight).
    for stale in backup_dir.glob(f"{DUMP_PREFIX}*.partial"):
        stale.unlink(missing_ok=True)
    final = backup_dir / dump_name(utc_stamp(now), revisions)
    partial = final.with_name(final.name + ".partial")
    pg_dump = environ.get("PG_DUMP") or "pg_dump"
    try:
        try:
            proc = subprocess.run([pg_dump, "-Fc", "--no-password", "-f", str(partial)],
                                  env=target.pg_env(environ), capture_output=True)
        except OSError as exc:
            raise BootError(f"cannot run {pg_dump} ({exc.strerror or type(exc).__name__})") from None
        if proc.returncode != 0:
            raise BootError(f"pg_dump exited {proc.returncode}{_stderr_tail(proc.stderr)}")
        if not partial.is_file() or partial.stat().st_size == 0:
            raise BootError("pg_dump wrote an empty file")
        os.replace(partial, final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return final


def prune(backup_dir: Path, keep: int) -> list[Path]:
    """Keep the newest `keep` pre-upgrade dumps (the UTC stamp sorts by name)."""
    dumps = sorted(backup_dir.glob(f"{DUMP_PREFIX}*.dump"), key=lambda p: p.name)
    doomed = dumps[:-keep] if keep > 0 else dumps
    for path in doomed:
        path.unlink(missing_ok=True)
    return doomed


def keep_count(environ: Mapping[str, str]) -> int:
    raw = (environ.get("PRE_UPGRADE_BACKUPS_KEEP") or "").strip()
    if not raw:
        return DEFAULT_KEEP
    try:
        value = int(raw)
    except ValueError:
        raise BootError(f"PRE_UPGRADE_BACKUPS_KEEP must be a whole number, got {raw!r}") from None
    if value < 1:
        raise BootError("PRE_UPGRADE_BACKUPS_KEEP must be at least 1")
    return value


# ── alembic ────────────────────────────────────────────────────────────────


def run_alembic(environ: Mapping[str, str]) -> int:
    """`alembic upgrade head` in a subprocess (migrations/env.py runs it in one transaction)."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=BACKEND_DIR, env=dict(environ)).returncode


# ── boot ───────────────────────────────────────────────────────────────────


async def boot(environ: Mapping[str, str], now: datetime | None = None) -> int:
    target = target_from_url(database_url(environ))
    backup_dir = Path(environ.get("BACKUP_DIR") or DEFAULT_BACKUP_DIR)
    keep = keep_count(environ)
    heads, known = script_revisions()

    conn = await connect(target)
    try:
        log("waiting for the migration lock")
        await lock(conn)
        state = await read_state(conn)

        if state.revisions and state.revisions == heads:
            log(f"at head ({', '.join(sorted(heads))}); nothing to migrate")
            return 0
        unknown = sorted(state.revisions - known)
        if unknown:
            raise BootError(
                f"the database is at revision {', '.join(unknown)}, which this image does not know "
                f"(it was upgraded by a newer Lorekeeper); deploy that version again, or restore "
                f"its pre-upgrade dump: {ROLLBACK_DOC}")

        dump: Path | None = None
        if not state.has_user_tables:
            log("empty database, nothing to back up")
        else:
            current = ", ".join(sorted(state.revisions)) or "no alembic_version"
            log(f"migration pending ({current} -> {', '.join(sorted(heads))}); backing up first")
            try:
                dump = pre_upgrade_dump(target, backup_dir, state.revisions, environ, now)
            except BootError as exc:
                raise BootError(f"pre-upgrade backup failed ({exc}); not migrating") from None
            log(f"backup written: {dump}")

        log("running alembic upgrade head")
        rc = run_alembic(environ)
        if rc != 0 and dump is not None:
            # restart: unless-stopped re-runs a failed boot, each time with a
            # new dump: keep the volume bounded on this path too.
            prune(backup_dir, keep)
        if rc != 0:
            where = (f"restore {dump.name} with scripts/restore-db.sh --no-restart {dump.name} "
                     f"({ROLLBACK_DOC})") if dump else "there was no data to back up"
            raise BootError(f"migration failed (alembic exited {rc}); {where}")

        after = await read_state(conn)
        log(f"migrated to {', '.join(sorted(after.revisions)) or '?'}")
        if dump is not None:
            for old in prune(backup_dir, keep):
                log(f"pruned old backup {old.name} (keeping {keep})")
        return 0
    finally:
        await conn.close()  # releases the advisory lock


# ── restore ────────────────────────────────────────────────────────────────


def _spool(source) -> Path:
    fd, name = tempfile.mkstemp(prefix="restore-", suffix=".dump")
    with os.fdopen(fd, "wb") as out:
        shutil.copyfileobj(source, out, 1 << 20)
    return Path(name)


# pg_restore 17 always opens its SQL with `SET transaction_timeout = 0;`, a
# setting PostgreSQL 16 does not know (the bundled server is pg16), so the
# load fails on its first line. The SETs come only in the script header,
# before any object, so only the first lines are filtered, and only when the
# server is older than 17.
_PG17_ONLY_SETS = (b"SET transaction_timeout = 0;",)
_HEADER_LINES = 100
_RESET = b"DROP SCHEMA IF EXISTS public CASCADE;\nCREATE SCHEMA public;\n"


def _copy_script(source, sink, *, drop_pg17_sets: bool) -> None:
    for n, line in enumerate(source):
        if drop_pg17_sets and n < _HEADER_LINES and line.strip() in _PG17_ONLY_SETS:
            continue
        sink.write(line)


async def restore(environ: Mapping[str, str], path: str | None, stdin=None) -> int:
    """Reset `public` and load the dump at `path` (or stdin), all in one transaction.

    `pg_restore -f -` turns the archive into SQL, which psql runs after the
    schema reset under --single-transaction with ON_ERROR_STOP: a failed load
    rolls back the reset too, and the database is left as it was.
    """
    target = target_from_url(database_url(environ))
    pg_restore = environ.get("PG_RESTORE") or "pg_restore"
    psql = environ.get("PSQL") or "psql"
    env = target.pg_env(environ)

    spooled: Path | None = None
    if path in (None, "-"):
        spooled = _spool(stdin if stdin is not None else sys.stdin.buffer)
        archive = spooled
    else:
        archive = Path(path)
        if not archive.is_file():
            raise BootError(f"no such dump file: {archive}")
    try:
        if archive.stat().st_size == 0:
            raise BootError("the dump is empty; nothing was touched")
        # Read the archive's table of contents before anything is dropped.
        try:
            listed = subprocess.run([pg_restore, "--list", str(archive)], env=env, capture_output=True)
        except OSError as exc:
            raise BootError(f"cannot run {pg_restore} ({exc.strerror or type(exc).__name__})") from None
        if listed.returncode != 0:
            raise BootError(f"not a readable pg_dump archive{_stderr_tail(listed.stderr)}; "
                            "nothing was touched")

        conn = await connect(target)
        try:
            log("waiting for the migration lock")
            await lock(conn)
            server = int(await conn.fetchval("SHOW server_version_num"))
            log(f"restoring {archive.name if spooled is None else 'the dump from stdin'} "
                "(schema reset and load in one transaction)")
            rc_restore, rc_psql, err = _pipe_restore(pg_restore, psql, archive, env,
                                                    drop_pg17_sets=server < 170000)
            if rc_restore != 0 or rc_psql != 0:
                raise BootError(f"restore failed (pg_restore {rc_restore}, psql {rc_psql}){_stderr_tail(err)}; "
                                "rolled back, the database is unchanged")
            state = await read_state(conn)
        finally:
            await conn.close()
        log(f"restored; the database is at {', '.join(sorted(state.revisions)) or 'no alembic revision'}")
        return 0
    finally:
        if spooled is not None:
            spooled.unlink(missing_ok=True)


def _pipe_restore(pg_restore: str, psql: str, archive: Path, env: Mapping[str, str], *,
                  drop_pg17_sets: bool) -> tuple[int, int, bytes]:
    """pg_restore -f - | (reset + filter) | psql --single-transaction. Returns both exit codes and stderr."""
    with tempfile.TemporaryFile() as restore_err, tempfile.TemporaryFile() as psql_err:
        try:
            dumper = subprocess.Popen([pg_restore, "--no-owner", "-f", "-", str(archive)],
                                      env=env, stdout=subprocess.PIPE, stderr=restore_err)
        except OSError as exc:
            raise BootError(f"cannot run {pg_restore} ({exc.strerror or type(exc).__name__})") from None
        try:
            loader = subprocess.Popen([psql, "--no-password", "--no-psqlrc", "--quiet", "-v", "ON_ERROR_STOP=1",
                                       "--single-transaction", "-d", env.get("PGDATABASE", ""), "-f", "-"],
                                      env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=psql_err)
        except OSError as exc:
            dumper.kill()
            dumper.wait()
            raise BootError(f"cannot run {psql} ({exc.strerror or type(exc).__name__})") from None
        try:
            loader.stdin.write(_RESET)
            _copy_script(dumper.stdout, loader.stdin, drop_pg17_sets=drop_pg17_sets)
        except BrokenPipeError:
            pass  # psql stopped on an error; its exit code says so
        finally:
            try:
                loader.stdin.close()
            except BrokenPipeError:
                pass
        rc_psql = loader.wait()
        if rc_psql != 0 and dumper.poll() is None:
            dumper.kill()
        rc_restore = dumper.wait()
        if rc_psql != 0 and rc_restore < 0:
            rc_restore = 0  # killed by us after psql failed: psql's error is the one to report
        restore_err.seek(0)
        psql_err.seek(0)
        err = psql_err.read() or restore_err.read()
    return rc_restore, rc_psql, err


# ── entry point ────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    command = args.pop(0) if args else "boot"
    try:
        if command == "boot" and not args:
            return asyncio.run(boot(env))
        if command == "restore" and len(args) <= 1:
            return asyncio.run(restore(env, args[0] if args else None))
        log("usage: boot_migrate.py [boot] | restore [FILE|-]")
        return 2
    except BootError as exc:
        log(str(exc))
        return 1
    except Exception as exc:  # e.g. a wrong password or a missing database: one readable line, no traceback
        log(f"failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
