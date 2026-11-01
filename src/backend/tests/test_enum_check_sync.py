"""CI-10 (AD-9): every StrEnum-backed CHECK constraint matches its StrEnum.

AD-9: apart from the `visibility` and `campaign_role` PG enums, every closed
set is a text column with a CHECK generated from a StrEnum in
app/domain/enums.py. Register each (StrEnum, table, column) pair in
ENUM_CHECKS in the PR that adds the column; this test then reads the CHECK's
values from pg_constraint on the migrated test database and fails if they
differ from the enum's members (a member added to the enum without a
migration, or the reverse).

The registry is empty until E0-WorldCore creates app/domain/enums.py, so the
comparison passes vacuously; the reader is exercised now by a self-test on a
temporary table.
"""
from __future__ import annotations

import re
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

# (StrEnum class, table, column). Example, once app/domain/enums.py exists:
#   from app.domain.enums import EntityType
#   (EntityType, "entities", "type"),
ENUM_CHECKS: list[tuple[type[StrEnum], str, str]] = []

_CHECKS_ON_COLUMN = sa.text(
    """
    SELECT c.conname, pg_get_constraintdef(c.oid) AS definition
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.contype = 'c'
      AND c.conrelid = to_regclass(:table)
      AND a.attname = :column
      AND array_length(c.conkey, 1) = 1
    ORDER BY c.conname
    """
)
# 'value'::text / 'value'::character varying; '' escapes a quote inside.
_LITERAL = re.compile(r"'((?:[^']|'')*)'::")


def parse_check_values(definition: str) -> set[str]:
    """String literals of a CHECK definition as pg_get_constraintdef renders it."""
    return {m.group(1).replace("''", "'") for m in _LITERAL.finditer(definition)}


async def check_values(db: AsyncSession, table: str, column: str) -> set[str]:
    """The values the single-column CHECK on table.column allows."""
    rows = (await db.execute(_CHECKS_ON_COLUMN, {"table": table, "column": column})).all()
    assert rows, (
        f"no single-column CHECK constraint on {table}.{column}; generate one from the StrEnum "
        "in the migration (AD-9) or fix the ENUM_CHECKS entry")
    assert len(rows) == 1, (
        f"{table}.{column} has {len(rows)} CHECK constraints ({', '.join(r.conname for r in rows)}); "
        "keep the one generated from the StrEnum")
    return parse_check_values(rows[0].definition)


def compare(enum_cls: type[StrEnum], table: str, column: str, allowed: set[str]) -> str | None:
    """None when they match, else a message listing the missing and extra values."""
    members = {m.value for m in enum_cls}
    missing, extra = sorted(members - allowed), sorted(allowed - members)
    if not missing and not extra:
        return None
    parts = []
    if missing:
        parts.append(f"in {enum_cls.__name__} but not allowed by the CHECK: {missing}")
    if extra:
        parts.append(f"allowed by the CHECK but not in {enum_cls.__name__}: {extra}")
    return (f"{table}.{column} drifted from {enum_cls.__module__}.{enum_cls.__name__}: "
            + "; ".join(parts)
            + ". Write a migration that regenerates the CHECK from the enum (AD-9).")


# ---- the gate --------------------------------------------------------------

def test_registry_entries_are_strenums():
    for enum_cls, table, column in ENUM_CHECKS:
        assert issubclass(enum_cls, StrEnum), f"{enum_cls!r} for {table}.{column} is not a StrEnum"
    pairs = [(t, c) for _, t, c in ENUM_CHECKS]
    assert len(pairs) == len(set(pairs)), "a (table, column) is registered twice in ENUM_CHECKS"


async def test_enum_checks_match(db: AsyncSession):
    problems = []
    for enum_cls, table, column in ENUM_CHECKS:
        problem = compare(enum_cls, table, column, await check_values(db, table, column))
        if problem:
            problems.append(problem)
    assert not problems, "\n".join(problems)


# ---- self-tests: the reader and the comparison ------------------------------

async def test_reader_reads_a_real_check(db: AsyncSession):
    await db.execute(sa.text(
        "CREATE TEMP TABLE enum_sync_selftest ("
        " status text CONSTRAINT ck_status CHECK (status IN ('open', 'closed_success', 'it''s')),"
        " kind varchar(20) CHECK (kind IN ('pc', 'npc')),"
        " single text CHECK (single = 'only'),"
        " a text, b text, CHECK (a <> b)"
        ") ON COMMIT DROP"
    ))
    assert await check_values(db, "enum_sync_selftest", "status") == {"open", "closed_success", "it's"}
    assert await check_values(db, "enum_sync_selftest", "kind") == {"pc", "npc"}
    assert await check_values(db, "enum_sync_selftest", "single") == {"only"}


class _Status(StrEnum):
    OPEN = "open"
    DONE = "done"


def test_compare_matches():
    assert compare(_Status, "t", "status", {"open", "done"}) is None


def test_compare_reports_planted_drift():
    message = compare(_Status, "quests", "status", {"open", "abandoned"})
    assert message is not None
    assert "quests.status" in message
    assert "['done']" in message and "['abandoned']" in message
    assert "migration" in message


def test_parse_check_values_forms():
    assert parse_check_values("CHECK ((status = ANY (ARRAY['a'::text, 'b''c'::text])))") == {"a", "b'c"}
    assert parse_check_values(
        "CHECK (((kind)::text = ANY ((ARRAY['pc'::character varying, 'npc'::character varying])::text[])))"
    ) == {"pc", "npc"}
