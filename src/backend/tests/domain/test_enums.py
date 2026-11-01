"""app/domain/enums.py: the closed sets and their generated CHECKs (AD-9, RC-12)."""
from __future__ import annotations

import ast
from enum import StrEnum
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    CharacterKind,
    EntityChangeOp,
    EntityType,
    MentionOrigin,
    MentionSourceField,
    TagSourceField,
    check_expr,
    check_sql,
)
from tests.test_enum_check_sync import check_values, domain_strenums

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "app" / "domain"

EXPECTED: dict[type[StrEnum], list[str]] = {
    EntityType: ["character", "location", "faction", "item", "quest"],
    CharacterKind: ["pc", "npc", "creature"],
    EntityChangeOp: [
        "create_entity", "update_field", "set_status", "set_kind", "add_alias", "remove_alias",
        "add_relationship", "update_relationship", "end_relationship", "add_quest_step",
        "update_quest_step", "add_mention", "confirm_mention", "remove_mention", "delete_entity",
        "merge", "revert", "source_deleted", "canon_note", "migrated",
    ],
    MentionOrigin: ["migration", "extraction", "manual"],
    MentionSourceField: ["narrative", "shorthand", "gm_notes"],
    TagSourceField: ["shorthand", "narrative", "manual"],
}


class _Quoted(StrEnum):
    PLAIN = "plain"
    APOSTROPHE = "it's"
    TWO = "a''b"


@pytest.mark.parametrize("enum_cls", list(EXPECTED), ids=lambda e: e.__name__)
def test_exact_members_in_order(enum_cls):
    assert [m.value for m in enum_cls] == EXPECTED[enum_cls]


def test_every_domain_enum_is_covered_here():
    assert set(domain_strenums()) == set(EXPECTED)


def test_entity_change_op_is_the_worldcore3_ops_plus_migrated():
    assert len(EntityChangeOp) == 20
    assert EntityChangeOp.MIGRATED == "migrated"


def test_rc12_source_field_enums_are_distinct():
    assert MentionSourceField is not TagSourceField
    assert not issubclass(MentionSourceField, TagSourceField)
    assert not issubclass(TagSourceField, MentionSourceField)
    assert MentionSourceField.__name__ != TagSourceField.__name__
    assert {m.value for m in MentionSourceField} != {m.value for m in TagSourceField}
    assert "gm_notes" in {m.value for m in MentionSourceField}
    assert "manual" in {m.value for m in TagSourceField}


def test_check_sql_text():
    assert check_sql(CharacterKind, "kind") == "CHECK (kind IN ('pc', 'npc', 'creature'))"
    assert check_expr(CharacterKind, "kind") == "kind IN ('pc', 'npc', 'creature')"
    assert check_sql(EntityType, "type") == (
        "CHECK (type IN ('character', 'location', 'faction', 'item', 'quest'))")
    assert check_sql(MentionOrigin, "origin") == f"CHECK ({check_expr(MentionOrigin, 'origin')})"


def test_check_sql_doubles_quotes():
    assert check_sql(_Quoted, "c") == "CHECK (c IN ('plain', 'it''s', 'a''''b'))"


def test_check_expr_usable_in_check_constraint():
    constraint = sa.CheckConstraint(check_expr(TagSourceField, "source_field"), name="ck_t")
    assert "source_field IN ('shorthand', 'narrative', 'manual')" in str(constraint.sqltext)


@pytest.mark.parametrize("enum_cls", [*EXPECTED, _Quoted], ids=lambda e: e.__name__)
async def test_check_sql_round_trip(db: AsyncSession, enum_cls):
    await db.execute(sa.text(
        f"CREATE TEMP TABLE enum_round_trip (c text {check_sql(enum_cls, 'c')}) ON COMMIT DROP"))
    assert await check_values(db, "enum_round_trip", "c") == {m.value for m in enum_cls}


def _app_imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 1:
                names.append("app.domain")  # `from . import x` stays inside the package
            elif node.level > 1:
                names.append("app")  # climbs out of app.domain: flag it
            elif node.module:
                names.append(node.module)
    return [n for n in names if n == "app" or n.startswith("app.")]


def test_domain_imports_only_domain():
    files = sorted(DOMAIN_DIR.rglob("*.py"))
    assert any(f.name == "enums.py" for f in files)
    offenders = {str(f.relative_to(DOMAIN_DIR)): bad for f in files
                 if (bad := [n for n in _app_imports(f)
                             if n != "app.domain" and not n.startswith("app.domain.")])}
    assert not offenders, f"app/domain must import only the stdlib and app.domain (AD-1): {offenders}"
