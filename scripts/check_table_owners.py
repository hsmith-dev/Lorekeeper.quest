#!/usr/bin/env python3
"""CI-7 (AD-19): every table has exactly one owning epic.

Owners come from three places in the planning docs:

  * the spine's "Capability -> Architecture Map" table, column "Owns (tables)";
  * the AD-19 Foundation bullets (F1-core, F2-jobs-files, F3-world), which the
    map cites by name for E0-Access, E0-Jobs and E0-WorldCore;
  * epics.md "New tables and columns beyond the spine" (owner per row).

Backticked names are tables, except:
  * `table.column` (a column);
  * in AD-19 bullets, a group of names joined only by "," / "and" / "+" that
    holds a dotted name or is followed by "enum(s)", "column(s)",
    "uniqueness" or "index";
  * in epics.md rows, every name in a cell that names a column (`t.c`) or an
    index (those rows add columns to tables other epics own).

Fails when:
  * a table has two owning epics;
  * a migration (src/backend/migrations/versions/*.py) creates a table, by
    op.create_table(...), op.rename_table(old, new) or a CREATE TABLE string
    (found through the AST, so prose and docstrings never count), that no
    epic owns and that is not a pre-expansion table in
    scripts/table_owners_legacy.txt;
  * a legacy entry is also owned by an epic, or no migration creates it any
    more (remove it from the legacy list), or has no reason;
  * the map cites a Foundation revision that AD-19 gives to another epic.

scripts/test_check_table_owners.py freezes the legacy list (it only shrinks).

Run: python scripts/check_table_owners.py   (stdlib only; exit 0 clean, 1 on failure)
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPINE = REPO / "_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md"
EPICS = REPO / "_bmad-output/planning-artifacts/epics.md"
MIGRATIONS = REPO / "src/backend/migrations/versions"
LEGACY = REPO / "scripts/table_owners_legacy.txt"

MAP_HEADING = re.compile(r"^##\s+Capability\s.*Architecture Map", re.M)
AD19_HEADING = re.compile(r"^###\s+AD-19\b", re.M)
EPICS_HEADING = re.compile(r"^###\s+New tables and columns beyond the spine", re.M)
FOUNDATION_BULLET = re.compile(r"^\s*-\s+\*\*(F\d[\w-]*)\*\*\s*\(([^)]+)\)\s*:\s*(.+)$", re.M)
FOUNDATION_REF = re.compile(r"\b(F\d-[A-Za-z][\w-]*)\b")
TICK = re.compile(r"`([^`]+)`")
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
JOINER = re.compile(r"^\s*(,|\+|and|,\s*and|&)?\s*$")
NOT_TABLE_NEXT = re.compile(r"^\s*(enums?|columns?|uniqueness|index(es)?)\b", re.I)
INDEX_WORD = re.compile(r"\bindex(es)?\b", re.I)

# Applied only to string constants in a migration (not docstrings or
# comments): CREATE [UNLOGGED] TABLE [IF NOT EXISTS] [schema.]name (
CREATE_TABLE_SQL = re.compile(
    r"""\bCREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"""
    r"""(?:"?[A-Za-z_]\w*"?\s*\.\s*)?"?([A-Za-z_]\w*)"?\s*\(""", re.I)

Owners = dict[str, dict[str, str]]  # table -> {epic: where}


def section(text: str, heading: re.Pattern[str], what: str) -> str:
    m = heading.search(text)
    if not m:
        raise ValueError(f"heading for {what} not found; the parser needs it (update scripts/check_table_owners.py if it was renamed)")
    level = len(text[m.start():].split(None, 1)[0])  # number of '#'
    rest = text[m.end():]
    end = re.search(rf"^#{{1,{level}}}\s", rest, re.M)
    return rest[: end.start()] if end else rest


def split_row(line: str) -> list[str]:
    """Cells of a Markdown table row; `\\|` is a literal pipe."""
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip() for c in cells[1:-1]]


def table_rows(md: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in md.splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        raise ValueError("Markdown table not found")
    header = split_row(lines[0])
    rows = [split_row(l) for l in lines[2:]]
    return header, rows


def epic_id(cell: str) -> str:
    """'E0-Access (optional)' -> 'E0-Access'; 'E1 Extraction & Review' -> 'E1'."""
    return cell.replace("*", "").split()[0] if cell.strip() else ""


def tables_in(text: str, mode: str) -> list[str]:
    """Backticked table names in `text`, per the rules in the module docstring.

    mode "token": every undotted name is a table (spine map cells).
    mode "cell": as "token", but a cell naming any column (`t.c`) or an index
    lists no tables (epics.md additions rows describe columns and indexes).
    mode "group": the AD-19 grouping rule.
    """
    ticks = list(TICK.finditer(text))
    if mode == "cell" and (any("." in m.group(1) for m in ticks) or INDEX_WORD.search(text)):
        return []
    if mode in ("token", "cell"):
        return [m.group(1) for m in ticks if IDENT.match(m.group(1))]
    tables: list[str] = []
    group: list[re.Match[str]] = []

    def close(next_text: str) -> None:
        names = [g.group(1) for g in group]
        if not names:
            return
        if any("." in n for n in names) or NOT_TABLE_NEXT.match(next_text):
            return
        tables.extend(n for n in names if IDENT.match(n))

    for i, m in enumerate(ticks):
        if group and not JOINER.match(text[group[-1].end():m.start()]):
            close(text[group[-1].end():])
            group = []
        group.append(m)
    if group:
        close(text[group[-1].end():])
    return tables


def parse_foundation(spine: str) -> dict[str, tuple[str, list[str]]]:
    """AD-19 bullets: {revision: (owner epic, tables)}."""
    out: dict[str, tuple[str, list[str]]] = {}
    for m in FOUNDATION_BULLET.finditer(section(spine, AD19_HEADING, "AD-19")):
        out[m.group(1)] = (epic_id(m.group(2)), tables_in(m.group(3), "group"))
    if not out:
        raise ValueError("no Foundation bullets (- **F1-core** (E0-Access): ...) found under AD-19")
    return out


def add(owners: Owners, table: str, epic: str, where: str) -> None:
    owners.setdefault(table, {}).setdefault(epic, where)


def parse_owners(spine: str, epics: str) -> tuple[Owners, list[str]]:
    owners: Owners = {}
    errors: list[str] = []
    foundation = parse_foundation(spine)
    for rev, (epic, tables) in foundation.items():
        for t in tables:
            add(owners, t, epic, f"spine AD-19 {rev}")

    header, rows = table_rows(section(spine, MAP_HEADING, "the boundary map"))
    if "Owns (tables)" not in header:
        raise ValueError("boundary map has no 'Owns (tables)' column")
    col = header.index("Owns (tables)")
    for row in rows:
        if len(row) <= col:
            continue
        epic, cell = epic_id(row[0]), row[col]
        for rev in FOUNDATION_REF.findall(cell):
            if rev not in foundation:
                errors.append(f"spine boundary map: {epic} cites Foundation revision {rev}, which AD-19 does not define")
            elif foundation[rev][0] != epic:
                errors.append(f"spine boundary map: {epic} cites {rev}, but AD-19 gives {rev} to {foundation[rev][0]}; one owner per revision")
        for t in tables_in(cell, "token"):
            add(owners, t, epic, "spine boundary map")

    header, rows = table_rows(section(epics, EPICS_HEADING, "epics.md additions"))
    owner_col = header.index("Owner") if "Owner" in header else None
    table_col = next((i for i, h in enumerate(header) if h.lower().startswith("table")), None)
    if owner_col is None or table_col is None:
        raise ValueError("epics.md additions table needs an 'Owner' and a 'Table / column' column")
    for row in rows:
        if len(row) <= max(owner_col, table_col):
            continue
        epic = epic_id(row[owner_col])
        for t in tables_in(row[table_col], "cell"):
            add(owners, t, epic, "epics.md additions")
    return owners, errors


def _str_arg(call: ast.Call, pos: int, kw: str) -> str | None:
    node = call.args[pos] if len(call.args) > pos else next((k.value for k in call.keywords if k.arg == kw), None)
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def tables_created_in(source: str, filename: str = "<migration>") -> list[str]:
    """Tables a migration creates: op.create_table(name), the new name of
    op.rename_table(old, new), and CREATE TABLE ... ( in string constants."""
    try:
        tree = ast.parse(source, filename)
    except SyntaxError as exc:
        raise ValueError(f"{filename}: cannot parse ({exc.msg}, line {exc.lineno})") from None
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            name = None
            if func == "create_table":
                name = _str_arg(node, 0, "table_name")
            elif func == "rename_table":
                name = _str_arg(node, 1, "new_table_name")
            if name:
                names.append(name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            names += [m.group(1) for m in CREATE_TABLE_SQL.finditer(node.value)]
    return names


def created_tables(migrations: Path) -> dict[str, list[str]]:
    """{table: [migration file names]} for every table the migrations create."""
    out: dict[str, list[str]] = {}
    for path in sorted(migrations.glob("*.py")):
        for name in tables_created_in(path.read_text(), path.name):
            files = out.setdefault(name, [])
            if path.name not in files:
                files.append(path.name)
    return out


def load_legacy(path: Path) -> tuple[dict[str, str], list[str]]:
    """{table: reason} and format errors. Lines: `table: reason`."""
    entries: dict[str, str] = {}
    errors: list[str] = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reason = line.partition(":")
        name = name.strip()
        if not reason.strip():
            errors.append(f"{path.name}:{n}: '{name}' has no reason; write `{name}: <why it has no owner>`")
        if name in entries:
            errors.append(f"{path.name}:{n}: '{name}' is listed twice; keep one line")
        entries[name] = reason.strip()
    return entries, errors


def check(spine_path: Path = SPINE, epics_path: Path = EPICS, migrations: Path = MIGRATIONS,
          legacy_path: Path = LEGACY) -> tuple[list[str], Owners]:
    owners, errors = parse_owners(spine_path.read_text(), epics_path.read_text())
    legacy, legacy_errors = load_legacy(legacy_path)
    errors += legacy_errors
    created = created_tables(migrations)

    for table in sorted(owners):
        if len(owners[table]) > 1:
            who = "; ".join(f"{e} ({where})" for e, where in sorted(owners[table].items()))
            errors.append(f"table '{table}' has two owners: {who}. Keep it under one epic (AD-19)")
    for table in sorted(created):
        if table not in owners and table not in legacy:
            errors.append(
                f"{', '.join(created[table])}: creates table '{table}', which no epic owns. "
                "Add it to its epic's 'Owns (tables)' in the spine boundary map "
                "(or epics.md 'New tables and columns beyond the spine'), or rename it into a table its epic owns")
    for table in sorted(legacy):
        if table in owners:
            errors.append(
                f"{legacy_path.name}: legacy table '{table}' is now owned by "
                f"{', '.join(sorted(owners[table]))}; remove it from the legacy list")
        elif table not in created:
            errors.append(
                f"{legacy_path.name}: legacy table '{table}' is no longer created by any migration; "
                "remove it from the legacy list")
    return errors, owners


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--spine", type=Path, default=SPINE)
    ap.add_argument("--epics", type=Path, default=EPICS)
    ap.add_argument("--migrations", type=Path, default=MIGRATIONS)
    ap.add_argument("--legacy", type=Path, default=LEGACY)
    ap.add_argument("-v", "--verbose", action="store_true", help="print the owner of every table")
    args = ap.parse_args(argv)
    try:
        errors, owners = check(args.spine, args.epics, args.migrations, args.legacy)
    except ValueError as exc:
        print(f"ERROR could not parse the planning docs or migrations: {exc}", file=sys.stderr)
        return 1
    if args.verbose:
        for t in sorted(owners):
            print(f"  {t}: {', '.join(sorted(owners[t]))}")
    if errors:
        print("Table ownership (AD-19, CI-7):", file=sys.stderr)
        for e in errors:
            print(f"  ERROR {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(owners)} owned tables, each with one owner; every migration-created table is owned or legacy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
