"""CI-10 (AD-9): every StrEnum-backed CHECK constraint matches its StrEnum.

AD-9: apart from the `visibility` and `campaign_role` PG enums, every closed
set is a text column with a CHECK generated from a StrEnum in
app/domain/enums.py (check_sql / check_expr). Register each (StrEnum, table,
column) pair in ENUM_CHECKS in the PR that adds the column; this test then
reads the CHECK's values from pg_constraint on the migrated test database and
fails if they differ from the enum's members (a member added to the enum
without a migration, or the reverse).

The two PG enums are registered in PG_ENUMS (StrEnum, type name); the test
compares each StrEnum with the type's pg_enum labels, in order.

Every StrEnum defined in app/domain/enums.py must be accounted for: either
registered in ENUM_CHECKS or PG_ENUMS, listed in ENUM_CHECKS_PENDING with
the story that adds its CHECK column, or listed in ATTRIBUTE_ENUMS (a closed
set for an `entities.attributes` JSONB key, which has no CHECK and is checked
by entity_types.validate_attributes). When that story lands, its author moves the enum
from ENUM_CHECKS_PENDING to ENUM_CHECKS and nothing else changes. The reader
is also exercised by a self-test on a temporary table, and
tests/domain/test_enums.py round-trips every enum's check_sql through it.
"""
from __future__ import annotations

import inspect
import re
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import enums as domain_enums
from app.domain.enums import (
    CampaignRole,
    CharacterKind,
    EntityChangeOp,
    EntityType,
    EntryKind,
    JobErrorCode,
    JobQueue,
    JobStatus,
    LocationKind,
    MentionOrigin,
    MentionSourceField,
    TagSourceField,
    Visibility,
)

# (StrEnum class, table, column), added in the PR that creates the column, e.g.
#   (EntityType, "entities", "type"),
ENUM_CHECKS: list[tuple[type[StrEnum], str, str]] = [
    (TagSourceField, "journal_tags", "source_field"),  # E0-Access.1
    (EntryKind, "journal_entries", "kind"),            # E0-Access.1
    (JobStatus, "jobs", "status"),                     # E0-Jobs.1
    (JobQueue, "jobs", "queue"),                       # E0-Jobs.1
    (JobErrorCode, "jobs", "error_code"),              # E0-Jobs.1
    (JobStatus, "data_backfills", "status"),           # E0-Jobs.1
    (EntityType, "entities", "type"),                  # E0-WorldCore.2
    (CharacterKind, "entities", "kind"),               # E0-WorldCore.2
    (EntityChangeOp, "entity_changes", "op"),          # E0-WorldCore.2
    (MentionOrigin, "entity_mentions", "origin"),      # E0-WorldCore.2
    (MentionSourceField, "entity_mentions", "source_field"),  # E0-WorldCore.2
]

# (StrEnum class, Postgres enum type name) for the AD-12 PG enums.
PG_ENUMS: list[tuple[type[StrEnum], str]] = [
    (Visibility, "visibility"),       # E0-Access.1
    (CampaignRole, "campaign_role"),  # E0-Access.1
]

# StrEnums in app/domain/enums.py whose CHECK column does not exist yet, with
# the story that adds it. Move an entry to ENUM_CHECKS in that story's PR.
ENUM_CHECKS_PENDING: dict[type[StrEnum], str] = {}

# StrEnums that are the choices of a CHOICE attribute in an entities.attributes
# JSONB key: no CHECK, ever; app.domain.entity_types.validate_attributes checks
# them. The value is the attribute it backs.
ATTRIBUTE_ENUMS: dict[type[StrEnum], str] = {
    LocationKind: "location.attributes.kind",  # owner amendment to E0-WorldCore.1
}


def domain_strenums() -> list[type[StrEnum]]:
    """The StrEnum classes defined (not just imported) in app.domain.enums."""
    return [obj for _, obj in inspect.getmembers(domain_enums, inspect.isclass)
            if issubclass(obj, StrEnum) and obj is not StrEnum
            and obj.__module__ == domain_enums.__name__]

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


_PG_ENUM_LABELS = sa.text(
    """
    SELECT e.enumlabel
    FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
    WHERE t.typname = :name AND t.typnamespace = to_regnamespace(current_schema())
    ORDER BY e.enumsortorder
    """
)


async def pg_enum_labels(db: AsyncSession, name: str) -> list[str]:
    """The labels of Postgres enum type `name`, in sort order."""
    labels = list((await db.execute(_PG_ENUM_LABELS, {"name": name})).scalars())
    assert labels, f"no Postgres enum type {name!r}; create it in a migration (AD-12)"
    return labels


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
    for enum_cls, type_name in PG_ENUMS:
        assert issubclass(enum_cls, StrEnum), f"{enum_cls!r} for PG enum {type_name} is not a StrEnum"
    names = [n for _, n in PG_ENUMS]
    assert len(names) == len(set(names)), "a PG enum type is registered twice in PG_ENUMS"


def test_every_domain_enum_is_registered():
    registered = [enum_cls for enum_cls, _, _ in ENUM_CHECKS] + [enum_cls for enum_cls, _ in PG_ENUMS]
    defined = domain_strenums()
    assert defined, "found no StrEnum in app.domain.enums"
    unaccounted = [e.__name__ for e in defined
                   if e not in registered and e not in ENUM_CHECKS_PENDING and e not in ATTRIBUTE_ENUMS]
    assert not unaccounted, (
        f"StrEnums in app/domain/enums.py with no CI-10 entry: {unaccounted}. Register each in "
        "ENUM_CHECKS with the column its CHECK lives on, in PG_ENUMS with its Postgres enum type, "
        "or in ENUM_CHECKS_PENDING with the story that adds that column (AD-9)")
    both = [e.__name__ for e in registered if e in ENUM_CHECKS_PENDING]
    assert not both, f"in both ENUM_CHECKS and ENUM_CHECKS_PENDING (remove the pending entry): {both}"
    stray = [e.__name__ for e in ENUM_CHECKS_PENDING if e not in defined]
    assert not stray, f"ENUM_CHECKS_PENDING lists enums not defined in app/domain/enums.py: {stray}"
    attr_both = [e.__name__ for e in ATTRIBUTE_ENUMS if e in registered or e in ENUM_CHECKS_PENDING]
    assert not attr_both, f"in ATTRIBUTE_ENUMS and also a CHECK/PG enum entry: {attr_both}"
    attr_stray = [e.__name__ for e in ATTRIBUTE_ENUMS if e not in defined]
    assert not attr_stray, f"ATTRIBUTE_ENUMS lists enums not defined in app/domain/enums.py: {attr_stray}"
    for enum_cls, story in ENUM_CHECKS_PENDING.items():
        assert re.fullmatch(r"E\d+(-[A-Za-z]+)?\.\d+", story), (
            f"ENUM_CHECKS_PENDING[{enum_cls.__name__}] = {story!r}: name the story that adds the column")


async def test_enum_checks_match(db: AsyncSession):
    problems = []
    for enum_cls, table, column in ENUM_CHECKS:
        problem = compare(enum_cls, table, column, await check_values(db, table, column))
        if problem:
            problems.append(problem)
    assert not problems, "\n".join(problems)


async def test_pg_enums_match(db: AsyncSession):
    problems = []
    for enum_cls, type_name in PG_ENUMS:
        labels = await pg_enum_labels(db, type_name)
        members = [m.value for m in enum_cls]
        if labels != members:
            problems.append(
                f"PG enum {type_name} has labels {labels}, but {enum_cls.__module__}."
                f"{enum_cls.__name__} has {members}. Write a migration (ALTER TYPE) or fix the enum (AD-12).")
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
