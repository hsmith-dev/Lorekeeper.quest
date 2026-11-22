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
this image's pg_restore (pg_dump 17 archives can't be read by the pg16
server image's client). `--clean` is not used: it can't drop the tables a
newer migration added. Rollback: docs/OCI_DEPLOYMENT.md, "Rolling back".

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


async def lock(conn) -> None:
    """Session-level: held until the connection closes, so across the subprocesses."""
    await conn.execute("SELECT pg_advisory_lock(hashtext($1))", LOCK_NAME)


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


async def restore(environ: Mapping[str, str], path: str | None, stdin=None) -> int:
    """Reset `public` and load the dump at `path` (or stdin) in one transaction."""
    target = target_from_url(database_url(environ))
    pg_restore = environ.get("PG_RESTORE") or "pg_restore"
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
            log("resetting the public schema")
            await conn.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
            log(f"restoring {archive.name if spooled is None else 'the dump from stdin'}")
            proc = subprocess.run(
                [pg_restore, "--no-owner", "--no-password", "--exit-on-error", "--single-transaction",
                 "-d", target.database or "", str(archive)],
                env=env, capture_output=True)
            if proc.returncode != 0:
                raise BootError(f"pg_restore exited {proc.returncode}{_stderr_tail(proc.stderr)}; "
                                "the public schema is empty, run the restore again")
            state = await read_state(conn)
        finally:
            await conn.close()
        log(f"restored; the database is at {', '.join(sorted(state.revisions)) or 'no alembic revision'}")
        return 0
    finally:
        if spooled is not None:
            spooled.unlink(missing_ok=True)


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


if __name__ == "__main__":
    sys.exit(main())
