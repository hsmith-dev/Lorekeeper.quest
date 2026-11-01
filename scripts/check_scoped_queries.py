#!/usr/bin/env python3
"""CI-8 (AD-13): access-scoping checks over src/backend/app.

E0-Access.2 part, the system-ctx check (RC-6): `CampaignContext.as_system`
turns a ctx into a GM-level system ctx that sees every row. Only two writes
may use it:

  * app/services/journal_service.py :: delete_journal_entry  (E0-Journal.3)
  * app/services/world_service.py   :: merge_entities        (E0-WorldCore.9)

Any other reference to `as_system` (a call, an attribute read, a bare name,
an import, or `getattr(x, "as_system")`) under src/backend/app fails. The
method's own definition in app/access/context.py is exempt. Tests are not
scanned.

E0-Access.5 adds the scoped-query ratchet here (`select(<registered
model>)`, `db.get(<registered model>)`, raw SQL on registered tables and
inline owner checks outside app/access/, against
scripts/scoped_queries_baseline.txt, shrink-only).

Run: python scripts/check_scoped_queries.py   (stdlib only; exit 0 clean, 1 on failure)
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "src/backend/app"

SYSTEM_NAME = "as_system"
# (path relative to the app package's parent, enclosing function name)
ALLOWED_SYSTEM_SITES = frozenset({
    ("app/services/journal_service.py", "delete_journal_entry"),
    ("app/services/world_service.py", "merge_entities"),
})
DEFINITION_FILE = "app/access/context.py"
DEFINITION_CLASS = "CampaignContext"


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    what: str

    def __str__(self) -> str:
        allowed = ", ".join(f"{p}::{f}" for p, f in sorted(ALLOWED_SYSTEM_SITES))
        return (f"{self.path}:{self.line}: {self.what}. `as_system` (a GM-level system ctx, RC-6) is allowed "
                f"only in {allowed}; use the request's own ctx (require_campaign / ctx_for) instead")


class _SystemVisitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.functions: list[str] = []
        self.classes: list[str] = []
        self.found: list[Violation] = []

    def _allowed(self) -> bool:
        return any((self.rel, fn) in ALLOWED_SYSTEM_SITES for fn in self.functions)

    def _flag(self, node: ast.AST, what: str) -> None:
        if not self._allowed():
            self.found.append(Violation(self.rel, getattr(node, "lineno", 0), what))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.name == SYSTEM_NAME:
            is_definition = self.rel == DEFINITION_FILE and self.classes[-1:] == [DEFINITION_CLASS] \
                and not self.functions
            if not is_definition:
                self._flag(node, f"defines `{SYSTEM_NAME}` outside {DEFINITION_FILE}::{DEFINITION_CLASS}")
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == SYSTEM_NAME:
            self._flag(node, f"references `.{SYSTEM_NAME}`")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == SYSTEM_NAME:
            self._flag(node, f"references `{SYSTEM_NAME}`")
        self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> None:
        if node.name.rsplit(".", 1)[-1] == SYSTEM_NAME or node.asname == SYSTEM_NAME:
            self._flag(node, f"imports `{SYSTEM_NAME}`")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"getattr", "hasattr", "setattr"} and len(node.args) >= 2:
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and arg.value == SYSTEM_NAME:
                self._flag(node, f"reaches `{SYSTEM_NAME}` through {func.id}()")
        self.generic_visit(node)


def check_source(text: str, rel: str) -> list[Violation]:
    """Every disallowed `as_system` reference in one module's source."""
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        return [Violation(rel, exc.lineno or 0, f"cannot be parsed ({exc.msg})")]
    visitor = _SystemVisitor(rel)
    visitor.visit(tree)
    return visitor.found


def check(app_dir: Path = APP) -> list[Violation]:
    """Scan every .py file under `app_dir` (the `app` package)."""
    if not app_dir.is_dir():
        return [Violation(str(app_dir), 0, "is not a directory")]
    base = app_dir.parent
    out: list[Violation] = []
    for path in sorted(app_dir.rglob("*.py")):
        rel = path.relative_to(base).as_posix()
        out.extend(check_source(path.read_text(encoding="utf-8"), rel))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", type=Path, default=APP, help="the app package directory (default: src/backend/app)")
    args = parser.parse_args(argv)
    violations = check(args.app)
    for v in violations:
        print(f"::error::{v}" if os.environ.get("GITHUB_ACTIONS") == "true" else str(v))
    if violations:
        print(f"check_scoped_queries: {len(violations)} violation(s)")
        return 1
    print("check_scoped_queries: ok (as_system used only at its allowed sites)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
