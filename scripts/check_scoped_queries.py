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

Owner infrastructure (OWNER_INFRA): a package may read and write the
system-bookkeeping tables its own epic owns without a baseline line. Today
only app/jobs/** may touch `Job` and `DataBackfill` (E0-Jobs owns `jobs` and
`data_backfills`; the worker, outbox and reaper manage those rows by id with
no user ctx). The allowance is one dict here, pinned in
scripts/test_check_scoped_queries.py, and each entry is cross-checked against
the CI-7 table-owner map (scripts/check_table_owners.py): a model whose table
that epic does not own alone fails. Anything else reading `Job` (a route
serving a Player the Jobs they started, say) still goes through app.access.

Also E0-Access.5: the deprecated helpers `get_campaign_with_access` and
`accessible_campaign_ids` are referenced nowhere under app/ (only the
deprecated definition of `get_campaign_with_access` in app/api/deps.py
stays); no baseline.

E0-Access.9 part, the one Visibility writer (AD-13): outside app/access/,
nothing writes a `visibility`, `field_visibility` or `visibility_floor`
column. These fail:

  * an assignment to the attribute (`x.visibility = ...`, `x.visibility_floor
    += ...`, `a.visibility, b.visibility = ...`), an item assignment or
    delete under `.field_visibility` (`x.field_visibility["k"] = ...`), or an
    in-place mutation of it (`x.field_visibility.update(...)`);
  * `setattr(x, "visibility", ...)` (and the other two names);
  * `.values(visibility=...)`, `.values({"visibility": ...})`,
    `.values({Model.visibility: ...})`, and `set_=` of `on_conflict_do_update`
    likewise;
  * raw SQL (`text(...)`, `exec_driver_sql(...)`) whose `UPDATE ... SET`
    clause sets one of them.

Constructor keywords (`Model(visibility=...)`) are a create's initial value,
which `check_create` gates; they are not a change and pass. The one allowed
site is VISIBILITY_WRITE_ALLOWED: `world_service.apply_change` may write
`visibility_floor` (the merge, AD-10, Decision B3-D7), inside that
module-level function only. It is a separate allowance from OWNER_INFRA, has
no baseline, and scripts/test_check_scoped_queries.py freezes it. Use
`app.access.set_visibility` instead.

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

# Package prefix (relative to the app package's parent) -> (the epic that owns
# the tables, the system-bookkeeping models that package may read and write
# without app.access). Never widen it to make a gate pass: a new entry needs
# the table-owner map to agree, and the frozen test to change.
OWNER_INFRA: dict[str, tuple[str, frozenset[str]]] = {
    # The Job runtime (enqueue, outbox, worker, reaper) manages Job rows by id
    # with no request; a handler gets its own ctx through ctx_for.
    "app/jobs/": ("E0-Jobs", frozenset({"Job", "DataBackfill"})),
}


def _infra_models(rel: str) -> frozenset[str]:
    """The models `rel` (a module path) may touch as owner infrastructure."""
    out: frozenset[str] = frozenset()
    for prefix, (_epic, models) in OWNER_INFRA.items():
        if rel.startswith(prefix):
            out |= models
    return out


def check_owner_infra(app_dir: Path = APP, owners: dict[str, dict[str, str]] | None = None) -> list[str]:
    """Each OWNER_INFRA model is registered, has a table, and that table is
    owned by the entry's epic alone in the CI-7 table-owner map."""
    if owners is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("check_table_owners", REPO / "scripts/check_table_owners.py")
        cto = importlib.util.module_from_spec(spec)
        sys.modules.setdefault(spec.name, cto)
        spec.loader.exec_module(cto)
        owners, errors = cto.parse_owners(cto.SPINE.read_text(encoding="utf-8"), cto.EPICS.read_text(encoding="utf-8"))
        if errors:
            return [f"OWNER_INFRA: the table-owner map does not parse: {e}" for e in errors]
    models = registered_models(app_dir)
    problems = []
    for prefix, (epic, names) in sorted(OWNER_INFRA.items()):
        for name in sorted(names):
            table = models.get(name)
            if table is None:
                problems.append(f"OWNER_INFRA[{prefix!r}]: {name} is not a registered model with a table")
                continue
            owned_by = set(owners.get(table, {}))
            if owned_by != {epic}:
                problems.append(f"OWNER_INFRA[{prefix!r}]: table {table} ({name}) is owned by "
                                f"{sorted(owned_by) or 'nobody'} in the table-owner map, not {epic} alone")
    return problems


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
                targets = stmt.targets if isinstance(stmt, ast.Assign) else (
                    [stmt.target] if isinstance(stmt, ast.AnnAssign) else [])
                value = getattr(stmt, "value", None)
                if (any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in targets)
                        and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    tables[node.name] = value.value
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
        infra = _infra_models(rel)
        # Owner infrastructure (OWNER_INFRA) is not a scoped-query site here.
        models = {m: t for m, t in models.items() if m not in infra}
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


# ── E0-Access.9: the one Visibility writer ────────────────────────────────

VISIBILITY_COLUMNS = frozenset({"visibility", "field_visibility", "visibility_floor"})
FIELD_VISIBILITY = "field_visibility"
# (path relative to the app package's parent, module-level function) -> the
# columns it may write. Never widen it to make a gate pass: the frozen test
# in scripts/test_check_scoped_queries.py must change with it.
VISIBILITY_WRITE_ALLOWED: dict[tuple[str, str], frozenset[str]] = {
    ("app/services/world_service.py", "apply_change"): frozenset({"visibility_floor"}),
}
VISIBILITY_HINT = ("change Visibility only through `app.access.set_visibility` / `set_visibility_many` "
                   "(the one writer, AD-13); the only other write is world_service.apply_change's merge "
                   "`visibility_floor`")
_MUTATING_METHODS = frozenset({"update", "setdefault", "pop", "popitem", "clear", "__setitem__", "__delitem__"})
_SQL_SET_RE = re.compile(r"\bUPDATE\b.*?\bSET\b(?P<set>.*?)(?:\bWHERE\b|\bFROM\b|\bRETURNING\b|;|$)",
                         re.IGNORECASE | re.DOTALL)
_SQL_COLUMN_RE = re.compile(r"(?:^|[\s,(])\"?(field_visibility|visibility_floor|visibility)\"?\s*=(?!=)",
                            re.IGNORECASE)


def _key_column(node: ast.expr) -> str | None:
    """The Visibility column a `.values()` key names: "visibility" or
    Model.visibility."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in VISIBILITY_COLUMNS:
        return node.value
    if isinstance(node, ast.Attribute) and node.attr in VISIBILITY_COLUMNS:
        return node.attr
    return None


def sql_visibility_writes(text: str) -> list[str]:
    """The Visibility columns an UPDATE ... SET in `text` assigns."""
    out: list[str] = []
    for m in _SQL_SET_RE.finditer(text):
        for col in _SQL_COLUMN_RE.findall(m.group("set")):
            if col.lower() not in out:
                out.append(col.lower())
    return out


class _VisibilityVisitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.functions: list[str] = []
        self.classes: list[str] = []
        self.found: list[Violation] = []

    def _allowed(self, column: str) -> bool:
        # Only inside the module-level allowed function itself (closures in
        # it included); not a method or a nested def of the same name.
        if not self.functions or self.classes:
            return False
        return column in VISIBILITY_WRITE_ALLOWED.get((self.rel, self.functions[0]), frozenset())

    def _flag(self, node: ast.AST, column: str, how: str) -> None:
        if not self._allowed(column):
            self.found.append(Violation(self.rel, getattr(node, "lineno", 0) or 0,
                                        f"writes `{column}` outside app/access/ ({how})", VISIBILITY_HINT))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def _target(self, target: ast.expr, how: str) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._target(elt, how)
        elif isinstance(target, ast.Starred):
            self._target(target.value, how)
        elif isinstance(target, ast.Attribute) and target.attr in VISIBILITY_COLUMNS:
            self._flag(target, target.attr, how)
        elif isinstance(target, ast.Subscript):
            base = target.value
            if isinstance(base, ast.Attribute) and base.attr in VISIBILITY_COLUMNS:
                self._flag(target, base.attr, f"item {how}")

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._target(target, "assignment")
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._target(node.target, "assignment")
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._target(node.target, "assignment")
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._target(target, "delete")
        self.generic_visit(node)

    def _mapping(self, node: ast.expr, how: str) -> None:
        if isinstance(node, ast.Dict):
            for key in node.keys:
                column = _key_column(key) if key is not None else None
                if column:
                    self._flag(node, column, how)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = _call_name(func)
        if (isinstance(func, ast.Name) and func.id == "setattr" and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant) and node.args[1].value in VISIBILITY_COLUMNS):
            self._flag(node, node.args[1].value, "setattr()")
        elif name == "values" and isinstance(func, ast.Attribute):
            for kw in node.keywords:
                if kw.arg in VISIBILITY_COLUMNS:
                    self._flag(node, kw.arg, ".values()")
            for arg in node.args:
                self._mapping(arg, ".values()")
        elif (name in _MUTATING_METHODS and isinstance(func, ast.Attribute)
              and isinstance(func.value, ast.Attribute) and func.value.attr == FIELD_VISIBILITY):
            self._flag(node, FIELD_VISIBILITY, f".{name}()")
        elif name in RAW_SQL_NAMES:
            text = " ".join(s.value for arg in node.args for s in ast.walk(arg)
                            if isinstance(s, ast.Constant) and isinstance(s.value, str))
            for column in sql_visibility_writes(text):
                self._flag(node, column, "raw SQL UPDATE ... SET")
        if name == "on_conflict_do_update":
            for kw in node.keywords:
                if kw.arg == "set_":
                    self._mapping(kw.value, "on_conflict_do_update(set_=)")
                    if isinstance(kw.value, ast.Call) and _call_name(kw.value.func) == "dict":
                        for inner in kw.value.keywords:
                            if inner.arg in VISIBILITY_COLUMNS:
                                self._flag(node, inner.arg, "on_conflict_do_update(set_=)")
        self.generic_visit(node)


def check_visibility_source(text: str, rel: str) -> list[Violation]:
    """Every Visibility write in one module's source (app/access/ is exempt)."""
    if rel.startswith(ACCESS_PREFIX):
        return []
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError:
        return []  # check_source reports it
    visitor = _VisibilityVisitor(rel)
    visitor.visit(tree)
    return visitor.found


def check_visibility_writes(app_dir: Path = APP) -> list[Violation]:
    """Scan every .py file under `app_dir` for Visibility writes outside app/access/."""
    if not app_dir.is_dir():
        return [Violation(str(app_dir), 0, "is not a directory", VISIBILITY_HINT)]
    base = app_dir.parent
    out: list[Violation] = []
    for path in sorted(app_dir.rglob("*.py")):
        rel = path.relative_to(base).as_posix()
        out.extend(check_visibility_source(path.read_text(encoding="utf-8"), rel))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", type=Path, default=APP, help="the app package directory (default: src/backend/app)")
    parser.add_argument("--baseline", type=Path, default=BASELINE,
                        help="the scoped-query baseline (default: scripts/scoped_queries_baseline.txt)")
    args = parser.parse_args(argv)
    problems = [str(v) for v in check(args.app)] + check_ratchet(args.app, args.baseline)
    problems += [str(v) for v in check_visibility_writes(args.app)]
    if args.app == APP:  # the cross-check reads the real table-owner map
        problems += check_owner_infra(args.app)
    for p in problems:
        print(f"::error::{p}" if os.environ.get("GITHUB_ACTIONS") == "true" else p)
    if problems:
        print(f"check_scoped_queries: {len(problems)} violation(s)")
        return 1
    print("check_scoped_queries: ok (as_system used only at its allowed sites; no read_only= outside app/access/; "
          "no deprecated access helpers; scoped-query sites within the baseline; OWNER_INFRA "
          "matches the table-owner map; no Visibility write outside app/access/ but the allowed merge floor)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
