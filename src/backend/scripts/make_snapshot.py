"""Build the brownfield migration snapshot that tests/migrations/ upgrades.

Wipes the public schema of a *test* database, migrates it to the fixed
revision SNAPSHOT_REVISION (never `head`, so the snapshot stays the baseline
after later revisions land), inserts a small seed with fixed ids and
timestamps, and writes a plain-SQL `pg_dump` of the result. The seed is raw
SQL, independent of the ORM models, so re-running the script gives a
byte-identical file, given the same pg_dump major version (16, matching the
pgvector/pgvector:pg16 server CI restores into).

Run from src/backend, against a pgvector Postgres 16:

    python scripts/make_snapshot.py \\
        --database-url postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test

Regenerate it only when the seed changes; the revision is fixed.
"""

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from sqlalchemy.engine import URL, make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from tests.conftest import (  # noqa: E402
    TEST_DB_NAME_RULE,
    _reset_public_schema,
    alembic_config,
    is_test_database_name,
)

SNAPSHOT_REVISION = "a3e7c1f9d258"
DEFAULT_OUTPUT = BACKEND_DIR / "tests" / "fixtures" / f"snapshot_{SNAPSHOT_REVISION}.sql"

TS = "'2026-01-01 12:00:00+00'"

OWNER = "00000000-0000-4000-8000-000000000001"
MEMBER_A = "00000000-0000-4000-8000-000000000002"
MEMBER_B = "00000000-0000-4000-8000-000000000003"
CAMPAIGN = "00000000-0000-4000-8000-000000000101"

# Shorthand-only vocabulary: "brackenford" and "millwright" appear in entry 1's
# shorthand but not its narrative. tests/migrations downgrades the snapshot past
# a3e7c1f9d258 and upgrades it again to check that revision's backfill, and a
# post-upgrade check keeps later revisions from dropping shorthand from the index.
_ENTRIES = [
    (
        "00000000-0000-4000-8000-000000000201",
        "party reached brackenford, met the millwright, bought rope",
        "We came down out of the hills at dusk and found the old mill still turning.",
        "seed-entry-hash-1",
        "2026-01-01",
    ),
    (
        "00000000-0000-4000-8000-000000000202",
        "fought goblins at the ford, Veyra hurt",
        "Steel rang across the water as the goblins broke from the reeds.",
        "seed-entry-hash-2",
        "2026-01-08",
    ),
    (
        "00000000-0000-4000-8000-000000000203",
        "rest at inn, Veyra recovers, quest for the lost bell",
        "The inn was warm and loud; by morning Veyra could stand again.",
        "seed-entry-hash-3",
        "2026-01-15",
    ),
]


# (name, role, status, description, notes). A pc, an npc and a faction, so
# the F3-world copy (03c0b504f1d1) maps each role; notes become gm_notes.
_NPCS = [
    ("Veyra", "pc", "alive", "A ranger from the eastern hills.", "Secretly the heir to Brackenford."),
    ("The Millwright", "npc", "unknown", None, None),
    ("The Reed Guild", "faction", "dead", "Smugglers who worked the ford.", "Broken up by the party."),
]
# (title, status, description, notes, updated_at). The completed Quest's
# updated_at is its completed_at after F3-world.
_QUESTS = [
    ("Find the lost bell", "active", "The mill bell vanished a year ago.", None, TS),
    ("Clear the ford", "completed", None, "The goblin chief escaped.", "'2026-01-08 18:30:00+00'"),
]


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _q_or_null(value: str | None) -> str:
    return "NULL" if value is None else _q(value)


def seed_statements() -> list[str]:
    stmts = []
    for uid, email, name in [
        (OWNER, "owner@example.test", "Owner"),
        (MEMBER_A, "member-a@example.test", "Member A"),
        (MEMBER_B, "member-b@example.test", "Member B"),
    ]:
        stmts.append(
            "INSERT INTO users (id, email, hashed_password, display_name, access_granted, "
            f"created_at, updated_at) VALUES ('{uid}', {_q(email)}, 'not-a-real-hash', "
            f"{_q(name)}, true, {TS}, {TS})"
        )
    stmts.append(
        "INSERT INTO campaigns (id, user_id, name, genre, description, created_at, updated_at) "
        f"VALUES ('{CAMPAIGN}', '{OWNER}', 'The Brackenford Bell', 'fantasy', "
        f"'Seed campaign for the migration snapshot.', {TS}, {TS})"
    )
    for i, uid in enumerate([MEMBER_A, MEMBER_B], start=1):
        stmts.append(
            "INSERT INTO campaign_members (id, campaign_id, user_id, created_at, updated_at) "
            f"VALUES ('00000000-0000-4000-8000-00000000030{i}', '{CAMPAIGN}', '{uid}', {TS}, {TS})"
        )
    for i, kind in enumerate(["read_only", "collaborate"], start=1):
        stmts.append(
            "INSERT INTO campaign_share_tokens (id, campaign_id, created_by_user_id, token, "
            "revoked, kind, created_at, updated_at) VALUES "
            f"('00000000-0000-4000-8000-00000000040{i}', '{CAMPAIGN}', '{OWNER}', "
            f"'seed-share-token-{kind}', false, '{kind}', {TS}, {TS})"
        )
    for eid, shorthand, narrative, entry_hash, session_date in _ENTRIES:
        # Same formula as a3e7c1f9d258, so the dump looks like a DB that ran it.
        stmts.append(
            "INSERT INTO journal_entries (id, user_id, campaign_id, shorthand, narrative, "
            "narrative_tsv, entry_hash, session_date, created_at, updated_at) VALUES "
            f"('{eid}', '{OWNER}', '{CAMPAIGN}', {_q(shorthand)}, {_q(narrative)}, "
            f"to_tsvector('english', {_q(shorthand)} || ' ' || {_q(narrative)}), "
            f"{_q(entry_hash)}, '{session_date}', {TS}, {TS})"
        )
    stmts.append(
        "INSERT INTO shorthand_terms (id, user_id, campaign_id, term, meaning, usage, "
        f"created_at, updated_at) VALUES ('00000000-0000-4000-8000-000000000501', "
        f"'{OWNER}', '{CAMPAIGN}', 'BF', 'Brackenford', 'BF mill', {TS}, {TS})"
    )
    stmts.append(
        "INSERT INTO tags (id, name, tag_type) VALUES "
        "('00000000-0000-4000-8000-000000000601', 'Veyra', 'character')"
    )
    stmts.append(
        "INSERT INTO journal_tags (journal_id, tag_id) VALUES "
        f"('{_ENTRIES[1][0]}', '00000000-0000-4000-8000-000000000601')"
    )
    for i, (name, role, status, description, notes) in enumerate(_NPCS, start=1):
        stmts.append(
            "INSERT INTO npcs (id, user_id, campaign_id, name, role, status, description, "
            f"notes, created_at, updated_at) VALUES ('00000000-0000-4000-8000-00000000070{i}', "
            f"'{OWNER}', '{CAMPAIGN}', {_q(name)}, '{role}', '{status}', {_q_or_null(description)}, "
            f"{_q_or_null(notes)}, {TS}, {TS})"
        )
    for i, (title, status, description, notes, updated_at) in enumerate(_QUESTS, start=1):
        stmts.append(
            "INSERT INTO quests (id, user_id, campaign_id, title, description, status, notes, "
            f"created_at, updated_at) VALUES ('00000000-0000-4000-8000-00000000080{i}', "
            f"'{OWNER}', '{CAMPAIGN}', {_q(title)}, {_q_or_null(description)}, '{status}', "
            f"{_q_or_null(notes)}, {TS}, {updated_at})"
        )
    for i, (uid, campaign) in enumerate(
        [(OWNER, f"'{CAMPAIGN}'"), (MEMBER_A, f"'{CAMPAIGN}'"), (MEMBER_B, "NULL")], start=1
    ):
        messages = '[{"role": "user", "content": "Where is the bell?"}]'
        stmts.append(
            "INSERT INTO chat_sessions (id, user_id, campaign_id, title, messages, "
            f"message_count, created_at, updated_at) VALUES "
            f"('00000000-0000-4000-8000-00000000090{i}', '{uid}', {campaign}, "
            f"'Seed chat {i}', {_q(messages)}::jsonb, 1, {TS}, {TS})"
        )
    # 4b8f2d9e71c3 seeds app_config with now(); pin it so the dump is stable.
    stmts.append(f"UPDATE app_config SET created_at = {TS}, updated_at = {TS}")
    return stmts


# pg_dump >= 16.10/17.6 wraps the dump in `\restrict <random key>` ...
# `\unrestrict <key>` psql meta-commands, which change every run and which
# asyncpg cannot execute. The version comments vary between machines. pg_dump 17+
# also emits `SET transaction_timeout`, which a PG16 server rejects. Only whole
# lines matching these are dropped, so data inside string literals is untouched.
_STRIP_LINE = re.compile(
    r"^(\\(un)?restrict \S+|-- Dumped (from database|by pg_dump) version .*"
    r"|SET transaction_timeout = 0;)$"
)


def clean_dump(text: str) -> str:
    lines = [line for line in text.splitlines() if not _STRIP_LINE.match(line)]
    return "\n".join(lines).strip() + "\n"


async def _seed(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for stmt in seed_statements():
                await conn.execute(sa.text(stmt))
    finally:
        await engine.dispose()


def _libpq_target(url: str) -> tuple[str, dict[str, str]]:
    """A password-free libpq URI for pg_dump's argv, plus env carrying the password."""
    parsed = make_url(url)
    env = {"PGPASSWORD": parsed.password} if parsed.password else {}
    # URL.set(password=None) keeps the password, so build a fresh URL without it.
    uri = URL.create(
        "postgresql",
        username=parsed.username,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    ).render_as_string(hide_password=False)
    return uri, env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", required=True, help="a *_test database; it is wiped")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pg-dump", default="pg_dump", help="pg_dump executable")
    args = parser.parse_args(argv)

    try:
        name = make_url(args.database_url).database
    except Exception:  # no exception text: it can echo the password
        print("Refusing to run: --database-url could not be parsed.", file=sys.stderr)
        return 2
    if not is_test_database_name(name):
        print(
            f"Refusing to run against database {name!r}: {TEST_DB_NAME_RULE}. "
            "This script wipes the public schema.",
            file=sys.stderr,
        )
        return 2

    # Check before wiping anything.
    if shutil.which(args.pg_dump) is None:
        print(f"Refusing to run: {args.pg_dump!r} not found on PATH.", file=sys.stderr)
        return 2

    asyncio.run(_reset_public_schema(args.database_url, with_vector=True))
    command.upgrade(alembic_config(args.database_url), SNAPSHOT_REVISION)
    asyncio.run(_seed(args.database_url))

    uri, pg_env = _libpq_target(args.database_url)
    result = subprocess.run(
        [
            args.pg_dump,
            "--no-owner",
            "--no-privileges",
            "--column-inserts",
            "--dbname",
            uri,
        ],
        capture_output=True,
        text=True,
        # timestamptz values are dumped in the session time zone.
        env={**os.environ, **pg_env, "PGTZ": "UTC"},
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(clean_dump(result.stdout))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
