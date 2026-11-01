"""AD-18: after F3-world (03c0b504f1d1), `npcs` and `quests` are frozen.

The F3-world revision copied every legacy row into `entities`; the world is
the source of truth from then on, and E0-WorldCore.6 turns the legacy routes
into adapters over it. Until then this is a ratchet: the modules that write
`npcs` or `quests` today are LEGACY_WRITERS, and E0-WorldCore.6 empties the
list. Any other module under src/backend/app or src/backend/scripts that
writes them fails, and an allowlisted module that no longer writes them
fails too (delete its line). The list only shrinks (FROZEN_CEILING).

A row written through an allowlisted writer after the upgrade reaches
`entities` only when E0-WorldCore.6 re-applies the (idempotent) copy.

"Writes" (found through the AST, so prose and docstrings never count):

  * constructing a legacy model (`NpcEntry(...)`, `Quest(...)`): an insert;
  * `insert(...)` / `update(...)` / `delete(...)` naming a legacy model;
  * raw SQL in a string constant: INSERT INTO / UPDATE / DELETE FROM npcs or quests;
  * in a function, mutating a row it got from an expression naming a
    legacy model (or a parameter annotated with one): `setattr(row, ...)`,
    `row.attr = ...`, `<session>.delete(row)` or `<session>.add(row)`.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCANNED = ("app", "scripts")
LEGACY_MODELS = frozenset({"NpcEntry", "Quest"})

# Module -> why it still writes. E0-WorldCore.6 empties this.
LEGACY_WRITERS: dict[str, str] = {
    "app/api/routes/npcs.py": "legacy NPC CRUD; E0-WorldCore.6 turns it into an adapter over entities",
    "app/api/routes/quests.py": "legacy Quest CRUD; E0-WorldCore.6 turns it into an adapter over entities",
    "scripts/seed_demo.py": "the demo seeder writes the legacy format; E0-WorldCore.6 moves it to entities",
}
# The allowlist may only shrink.
FROZEN_CEILING = frozenset({"app/api/routes/npcs.py", "app/api/routes/quests.py", "scripts/seed_demo.py"})

# Not services: they write a database that is older than F3-world.
EXEMPT: dict[str, str] = {
    "scripts/make_snapshot.py": "seeds the a3e7c1f9d258 snapshot DB (before F3-world exists), never a live one",
}

_RAW_WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:public\.)?\"?(npcs|quests)\b", re.I)
_DML = frozenset({"insert", "update", "delete"})


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.add(id(body[0].value))
    return out


def _callee(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _function_writes(fn: ast.AST) -> list[str]:
    """Mutations of rows this function got from a legacy-model expression."""
    rows: set[str] = set()
    args = getattr(fn, "args", None)
    if args is not None:
        for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
            if a.annotation is not None and _names(a.annotation) & LEGACY_MODELS:
                rows.add(a.arg)
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            if _names(node.value) & LEGACY_MODELS or (
                    isinstance(node, ast.AnnAssign) and _names(node.annotation) & LEGACY_MODELS):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    rows |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
        if isinstance(node, (ast.For, ast.AsyncFor)) and _names(node.iter) & rows:
            rows |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
    found = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and node.args:
            name = _callee(node)
            first = node.args[0]
            if name == "setattr" and isinstance(first, ast.Name) and first.id in rows:
                found.append(f"line {node.lineno}: setattr({first.id}, ...)")
            if name in ("delete", "add") and isinstance(node.func, ast.Attribute) and isinstance(first, ast.Name) \
                    and first.id in rows:
                found.append(f"line {node.lineno}: .{name}({first.id})")
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id in rows:
                    found.append(f"line {node.lineno}: {t.value.id}.{t.attr} = ...")
    return found


def legacy_writes(source: str) -> list[str]:
    """Every write to npcs/quests in a module's source (see the module docstring)."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _callee(node)
            if isinstance(node.func, ast.Name) and name in LEGACY_MODELS:
                found.append(f"line {node.lineno}: {name}(...)")
            if name in _DML and any(_names(a) & LEGACY_MODELS for a in node.args):
                found.append(f"line {node.lineno}: {name}(<legacy model>)")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            m = _RAW_WRITE.search(node.value)
            if m:
                found.append(f"line {node.lineno}: raw SQL {m.group(0)!r}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.extend(_function_writes(node))
    return sorted(set(found))


def _modules() -> list[tuple[str, Path]]:
    out = []
    for top in SCANNED:
        for path in sorted((BACKEND / top).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            out.append((path.relative_to(BACKEND).as_posix(), path))
    return out


def test_no_new_writer_of_npcs_or_quests():
    writers = {}
    for rel, path in _modules():
        if rel in EXEMPT:
            continue
        hits = legacy_writes(path.read_text())
        if hits:
            writers[rel] = hits
    new = {rel: hits for rel, hits in writers.items() if rel not in LEGACY_WRITERS}
    assert not new, (
        "npcs and quests are frozen after F3-world (AD-18): write the World Model (entities) instead. "
        f"New writers: {new}")
    gone = sorted(set(LEGACY_WRITERS) - set(writers))
    assert not gone, f"LEGACY_WRITERS entries that no longer write npcs/quests (delete them): {gone}"


def test_allowlist_only_shrinks():
    assert set(LEGACY_WRITERS) <= FROZEN_CEILING, (
        f"LEGACY_WRITERS grew past its frozen ceiling: {sorted(set(LEGACY_WRITERS) - FROZEN_CEILING)}")
    for rel, reason in {**LEGACY_WRITERS, **EXEMPT}.items():
        assert reason.strip(), f"{rel}: give a reason"
        assert (BACKEND / rel).is_file(), f"{rel} does not exist (delete its line)"


# ---- self-tests: the detector ----------------------------------------------

def test_detector_finds_each_kind_of_write():
    planted = '''
"""Docstring: INSERT INTO npcs is prose here, not a write."""
from sqlalchemy import update, text
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest

async def create(db):
    db.add(NpcEntry(name="x"))

async def bulk(db):
    await db.execute(update(Quest).values(title="t"))
    await db.execute(text("DELETE FROM quests WHERE id = :id"))

async def edit(db, quest: Quest):
    quest.title = "new"

async def remove(db, ctx, npc_id):
    npc = await scoped_get(db, NpcEntry, ctx, npc_id)
    setattr(npc, "name", "y")
    await db.delete(npc)
'''
    hits = legacy_writes(planted)
    assert any("NpcEntry(...)" in h for h in hits)
    assert any("update(<legacy model>)" in h for h in hits)
    assert any("DELETE FROM quests" in h for h in hits)
    assert any("quest.title = ..." in h for h in hits)
    assert any("setattr(npc" in h for h in hits)
    assert any(".delete(npc)" in h for h in hits)
    assert not any("prose" in h or "INSERT INTO npcs" in h for h in hits)


def test_detector_ignores_reads():
    reads = '''
from sqlalchemy import select
from app.db.models.npc import NpcEntry

async def names(db, ctx):
    rows = (await db.execute(select(NpcEntry.name))).scalars().all()
    other.name = "fine"
    return [r for r in rows]
'''
    assert legacy_writes(reads) == []
