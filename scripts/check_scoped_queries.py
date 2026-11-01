#!/usr/bin/env python3
"""CI-8 (AD-13): access-scoping checks over src/backend/app.

E0-Access.2 part, the system-ctx check (RC-6): `CampaignContext.as_system`
turns a ctx into a GM-level system ctx that sees every row. Only two writes
may use it:

  * app/services/journal_service.py :: delete_journal_entry  (E0-Journal.3)
  * app/services/world_service.py   :: merge_entities        (E0-WorldCore.9)

Any other reference to `as_system` (a call, an attribute read, a bare name,
an import, or `getattr(x, "as_system")`) under src/backend/app fails. The
method's own definition in app/access/context.py is exempt. So does building
a system ctx by hand outside app/access/ (`ACTOR_SYSTEM`, `actor="system"`,
or a `system_reason=` other than None). Tests are not
scanned.

E0-Access.3 part, reduced ctxs: any `read_only=` keyword outside
app/access/ fails, whatever its value. A read-only ctx is a reduced ctx
(`audience_ctx`, the only constructor), so building one by hand elsewhere
would bypass its narrowing rules, and `read_only=False` would turn a
reduced ctx (e.g. as_user(other)) back into a writable one.

E0-Access.5 part, the scoped-query ratchet. Outside app/access/, these
sites read registered rows without the registry and fail unless listed in
scripts/scoped_queries_baseline.txt:

  * `select(...)` naming a registered model anywhere in its arguments
    (`select(JournalEntry)`, `select(JournalEntry.shorthand)`,
    `select(func.count(Quest.id))`);
  * `<session>.get(<registered model>, ...)` (`db.get(NpcEntry, id)`);
  * raw SQL (`text(...)`, `exec_driver_sql(...)`) naming a registered table;
  * an inline owner check, `Campaign.user_id ==` (or `!=`).

Use `scoped_select` / `scoped_get` / `scoped_select_multi` and
`require_campaign("owner")` instead. The registered models are the keys of
`REGISTRY` in app/access/registry.py; their tables come from
`__tablename__` under app/db/models/. A baseline line is
`<path>::<function> <kind>:<target>` (one line per site; a function with two
identical sites has two lines). The baseline only shrinks: a site not in it
fails, a line no site matches fails (delete it), and
scripts/test_check_scoped_queries.py freezes its ceiling.

Also E0-Access.5: the deprecated helpers `get_campaign_with_access` and
`accessible_campaign_ids` are referenced nowhere under app/ (only the
deprecated definition of `get_campaign_with_access` in app/api/deps.py
stays); no baseline.

Run: python scripts/check_scoped_queries.py   (stdlib only; exit 0 clean, 1 on failure)
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections import Counter
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
# A system ctx built by hand instead of through as_system.
ACTOR_SYSTEM_NAME = "ACTOR_SYSTEM"
ACCESS_PREFIX = "app/access/"
DEFINITION_CLASS = "CampaignContext"
READ_ONLY_KEYWORD = "read_only"
READ_ONLY_HINT = ("a read-only (reduced) ctx is built only by `app.access.audience_ctx` (anon, member or "
                  "as_user); call it instead of setting `read_only=`")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    what: str
    hint: str | None = None

    def __str__(self) -> str:
        if self.hint is not None:
            return f"{self.path}:{self.line}: {self.what}. {self.hint}"
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
        # Only inside the module-level allowed function itself (closures in
        # it included); not a method or a nested def of the same name.
        return bool(self.functions) and not self.classes and (self.rel, self.functions[0]) in ALLOWED_SYSTEM_SITES

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
        if node.id == ACTOR_SYSTEM_NAME and not self.rel.startswith(ACCESS_PREFIX):
            self.found.append(Violation(self.rel, node.lineno, f"references `{ACTOR_SYSTEM_NAME}` (builds a system "
                                        "ctx without as_system)"))
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        # CampaignContext(..., actor="system") / dataclasses.replace(ctx, actor="system")
        if not self.rel.startswith(ACCESS_PREFIX):
            value = node.value.value if isinstance(node.value, ast.Constant) else ...
            if (node.arg == "actor" and value == "system") or (node.arg == "system_reason" and value is not None):
                self.found.append(Violation(self.rel, getattr(node, "lineno", 0) or 0,
                                            f"sets `{node.arg}=` (builds a system ctx without as_system)"))
            if node.arg == READ_ONLY_KEYWORD:
                self.found.append(Violation(self.rel, getattr(node, "lineno", 0) or 0,
                                            f"sets `{READ_ONLY_KEYWORD}=` (builds or widens a reduced ctx "
                                            "without audience_ctx)", READ_ONLY_HINT))
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


# ── E0-Access.5: deprecated helpers and the scoped-query ratchet ───────────

BASELINE = REPO / "scripts/scoped_queries_baseline.txt"
REGISTRY_FILE = "access/registry.py"   # relative to the app package
MODELS_DIR = "db/models"
DEPRECATED_HELPERS = frozenset({"get_campaign_with_access", "accessible_campaign_ids"})
DEPRECATED_DEFINITION = ("app/api/deps.py", "get_campaign_with_access")
DEPRECATED_HINT = ("use `require_campaign(min_role)` / `require_campaign_for(Model, id_param, min_role)` / "
                   "`ctx_for_request` for one Campaign, `role_map` + `scoped_select_multi` across Campaigns")
RATCHET_HINT = ("read registered rows through app.access (`scoped_select`, `scoped_get`, `scoped_select_multi`; "
                "owner checks: `require_campaign(\"owner\")`). Never add a line to scripts/scoped_queries_baseline.txt")
SELECT_NAMES = frozenset({"select"})
RAW_SQL_NAMES = frozenset({"text", "exec_driver_sql"})


def registered_models(app_dir: Path) -> dict[str, str | None]:
    """{model class name: table name} for the keys of REGISTRY in
    app/access/registry.py (empty when the file is missing)."""
    registry = app_dir / REGISTRY_FILE
    if not registry.is_file():
        return {}
    names: list[str] = []
    for node in ast.walk(ast.parse(registry.read_text(encoding="utf-8"))):
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None)
        if isinstance(target, ast.Name) and target.id == "REGISTRY" and isinstance(node.value, ast.Dict):
            names = [k.id for k in node.value.keys if isinstance(k, ast.Name)]
    tables: dict[str, str] = {}
    models = app_dir / MODELS_DIR
    for path in sorted(models.rglob("*.py")) if models.is_dir() else []:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if (isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__"
                                                         for t in stmt.targets)
                        and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)):
                    tables[node.name] = stmt.value.value
    return {name: tables.get(name) for name in names}


@dataclass(frozen=True, order=True)
class Site:
    path: str
    function: str
    kind: str     # select | get | raw_sql | owner_check
    target: str   # model, table or Campaign.user_id
    line: int = 0

    @property
    def key(self) -> str:
        return f"{self.path}::{self.function} {self.kind}:{self.target}"


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_campaign_user_id(node: ast.expr) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "user_id"
            and isinstance(node.value, ast.Name) and node.value.id == "Campaign")


class _RatchetVisitor(ast.NodeVisitor):
    def __init__(self, rel: str, models: dict[str, str | None]) -> None:
        self.rel = rel
        self.models = models
        self.tables = {t: re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in models.values() if t}
        self.scope: list[str] = []
        self.sites: list[Site] = []
        self.deprecated: list[Violation] = []

    def _add(self, node: ast.AST, kind: str, target: str) -> None:
        self.sites.append(Site(self.rel, ".".join(self.scope) or "<module>", kind, target,
                               getattr(node, "lineno", 0)))

    def _scoped(self, node: ast.AST) -> None:
        self.scope.append(node.name)  # type: ignore[attr-defined]
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name in DEPRECATED_HELPERS and (self.rel, node.name) != DEPRECATED_DEFINITION:
            self.deprecated.append(Violation(self.rel, node.lineno, f"defines the deprecated `{node.name}`",
                                             DEPRECATED_HINT))
        self._scoped(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]
    visit_ClassDef = _scoped  # type: ignore[assignment]

    def _deprecated_ref(self, node: ast.AST, name: str) -> None:
        if name in DEPRECATED_HELPERS:
            self.deprecated.append(Violation(self.rel, getattr(node, "lineno", 0),
                                             f"references the deprecated `{name}`", DEPRECATED_HINT))

    def visit_Name(self, node: ast.Name) -> None:
        self._deprecated_ref(node, node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._deprecated_ref(node, node.attr)
        self.generic_visit(node)

    def _visit_import(self, node: ast.Import | ast.ImportFrom) -> None:
        for alias in node.names:
            self._deprecated_ref(node, alias.name.rsplit(".", 1)[-1])

    visit_Import = _visit_import  # type: ignore[assignment]
    visit_ImportFrom = _visit_import  # type: ignore[assignment]

    def visit_Compare(self, node: ast.Compare) -> None:
        operands = [node.left, *node.comparators]
        for op, left, right in zip(node.ops, operands, operands[1:]):
            if isinstance(op, (ast.Eq, ast.NotEq)) and (_is_campaign_user_id(left) or _is_campaign_user_id(right)):
                self._add(node, "owner_check", "Campaign.user_id")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name in SELECT_NAMES:
            found: list[str] = []
            for arg in node.args:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Name) and sub.id in self.models and sub.id not in found:
                        found.append(sub.id)
            for model in found:
                self._add(node, "select", model)
        elif (name == "get" and isinstance(node.func, ast.Attribute) and node.args
              and isinstance(node.args[0], ast.Name) and node.args[0].id in self.models):
            self._add(node, "get", node.args[0].id)
        elif name in RAW_SQL_NAMES:
            text = " ".join(s.value for arg in node.args for s in ast.walk(arg)
                            if isinstance(s, ast.Constant) and isinstance(s.value, str))
            for table, pattern in sorted(self.tables.items()):
                if pattern.search(text):
                    self._add(node, "raw_sql", table)
        self.generic_visit(node)


def ratchet_sites(app_dir: Path = APP) -> tuple[list[Site], list[Violation]]:
    """Every scoped-query site outside app/access/, and every reference to a
    deprecated helper (always a violation)."""
    models = registered_models(app_dir)
    base = app_dir.parent
    sites: list[Site] = []
    deprecated: list[Violation] = []
    for path in sorted(app_dir.rglob("*.py")):
        rel = path.relative_to(base).as_posix()
        if rel.startswith(ACCESS_PREFIX):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError:
            continue  # check_source reports it
        visitor = _RatchetVisitor(rel, models)
        visitor.visit(tree)
        sites.extend(visitor.sites)
        deprecated.extend(visitor.deprecated)
    return sorted(sites), deprecated


def load_baseline(path: Path) -> tuple[list[str], list[str]]:
    """(baseline keys, format errors). Blank lines and `#` comments are skipped."""
    if not path.is_file():
        return [], [f"{path}: the scoped-query baseline is missing"]
    keys: list[str] = []
    errors: list[str] = []
    line_re = re.compile(r"^app/\S+\.py::\S+ (select|get|raw_sql|owner_check):\S+$")
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line_re.match(line):
            errors.append(f"{path.name}:{n}: not `<path>::<function> <kind>:<target>`: {line!r}")
            continue
        keys.append(line)
    return keys, errors


def check_ratchet(app_dir: Path = APP, baseline: Path = BASELINE) -> list[str]:
    """Error lines: deprecated-helper references, sites not in the baseline,
    and baseline lines no site matches any more."""
    sites, deprecated = ratchet_sites(app_dir)
    errors = [str(v) for v in deprecated]
    keys, format_errors = load_baseline(baseline)
    errors.extend(format_errors)
    allowed = Counter(keys)
    seen: Counter[str] = Counter()
    for site in sites:
        seen[site.key] += 1
        if seen[site.key] > allowed[site.key]:
            errors.append(f"{site.path}:{site.line}: {site.kind} `{site.target}` in {site.function} reads a "
                          f"registered row outside app/access/. {RATCHET_HINT}")
    for key, count in sorted(allowed.items()):
        if seen[key] < count:
            errors.append(f"{baseline.name}: `{key}` lists {count - seen[key]} site(s) that no longer exist; "
                          "delete the line (the baseline only shrinks)")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", type=Path, default=APP, help="the app package directory (default: src/backend/app)")
    parser.add_argument("--baseline", type=Path, default=BASELINE,
                        help="the scoped-query baseline (default: scripts/scoped_queries_baseline.txt)")
    args = parser.parse_args(argv)
    problems = [str(v) for v in check(args.app)] + check_ratchet(args.app, args.baseline)
    for p in problems:
        print(f"::error::{p}" if os.environ.get("GITHUB_ACTIONS") == "true" else p)
    if problems:
        print(f"check_scoped_queries: {len(problems)} violation(s)")
        return 1
    print("check_scoped_queries: ok (as_system used only at its allowed sites; no read_only= outside app/access/; "
          "no deprecated access helpers; scoped-query sites within the baseline)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
