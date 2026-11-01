#!/usr/bin/env python3
"""CI-14 (AD-7): the container memory limits fit the 16 GB Reference Box.

AD-7: the sum of all container limits stays at or below 14.5 GB, leaving at
least 1.5 GB for the OS and Docker. The limits live in .env.example as
`*_MEM_LIMIT` variables. Both forms count, since a commented line documents
the compose default:

    ML_MEM_LIMIT=2560m
    # ML_MEM_LIMIT=2560m

Only these `*_MEM_LIMIT` variables are summed. With none declared the sum
passes vacuously.

Units: AD-7's "14.5 GB" is read as 14.5 GiB on purpose. The limits are Docker
sizes, and Docker's suffixes are binary (b, k, m, g; 1g = 1024m = 1024**3
bytes), so AD-7's own table (5.25g + 2.5g + 2.5g + ... = 14.5g) sums to
exactly 14.5 GiB. Do not "fix" the ceiling to 14.5e9 bytes: the AD-7 table
itself would then fail. The ceiling is inclusive.

Compose drift: every reference to a `*_MEM_LIMIT` in a compose file
(docker-compose*.yml/.yaml, compose*.yml/.yaml) must be declared in
.env.example. `${X}`, `$X`, `${X:?msg}` and `${X:+alt}` only need the
declaration; `${X:-default}`, `${X-default}` and `${X:=default}` must also
use the same default, so the sum checked here is the one compose runs with.

Literal limits: a hard-coded `memory:` under `deploy.resources.limits`, or a
`mem_limit:`, is outside the sum, so each one must be listed in
scripts/memory_literal_limits_baseline.txt with a reason. That baseline only
shrinks (E0-Platform.7 moves today's literals to *_MEM_LIMIT variables): a
literal not in it fails, and an entry that matches no literal fails (remove
it). scripts/test_check_memory_budget.py freezes its ceiling.

To raise one limit, lower another in the same PR and re-run EV-5 (AD-7).

Run: python scripts/check_memory_budget.py   (stdlib only; exit 0 clean, 1 on failure)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO / ".env.example"
LITERAL_BASELINE = REPO / "scripts" / "memory_literal_limits_baseline.txt"
COMPOSE_GLOBS = ("docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml")
LIMIT_BYTES = int(14.5 * 1024**3)  # 14.5 GiB: Docker's `g` is binary (see the docstring)

_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([bkmgt]?)b?\s*$", re.I)
_DECL = re.compile(r"^\s*(#\s*)?([A-Z][A-Z0-9_]*_MEM_LIMIT)\s*=\s*(\S*)")
# ${X}, ${X:-d}, ${X-d}, ${X:=d}, ${X=d}, ${X:?msg}, ${X?msg}, ${X:+alt}, ${X+alt}, and bare $X.
_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*_MEM_LIMIT)(?:(:?[-=?+])([^}]*))?\}|\$([A-Z][A-Z0-9_]*_MEM_LIMIT)\b")
_KEY = re.compile(r"^(\s*)(-\s+)?([A-Za-z0-9_.-]+)\s*:\s*(.*?)\s*$")


def parse_size(value: str) -> int:
    """Docker memory size ('2560m', '5.25g', '768M', '1073741824') in bytes."""
    m = _SIZE.match(value.strip().strip("'\""))
    if not m:
        raise ValueError(f"not a memory size: {value!r} (use a number with b, k, m or g)")
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def fmt(n: int) -> str:
    return f"{n / 1024**3:.2f} GiB"


def compose_files(root: Path) -> list[Path]:
    return sorted({p for g in COMPOSE_GLOBS for p in root.glob(g)})


def read_limits(env_path: Path) -> tuple[dict[str, tuple[str, int, int]], list[str]]:
    """{VAR: (raw value, bytes, line)} from .env.example, and errors."""
    limits: dict[str, tuple[str, int, int]] = {}
    errors: list[str] = []
    for n, line in enumerate(env_path.read_text().splitlines(), 1):
        m = _DECL.match(line)
        if not m:
            continue
        var, raw = m.group(2), m.group(3).split("#", 1)[0]
        if var in limits:
            errors.append(f"{env_path.name}:{n}: {var} is declared twice (also line {limits[var][2]}); keep one line")
            continue
        try:
            limits[var] = (raw, parse_size(raw), n)
        except ValueError as exc:
            errors.append(f"{env_path.name}:{n}: {var}: {exc}")
    return limits, errors


def check_compose(compose: list[Path], limits: dict[str, tuple[str, int, int]], env_name: str) -> list[str]:
    errors: list[str] = []
    for path in compose:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for m in _REF.finditer(line):
                var = m.group(1) or m.group(4)
                op, arg = m.group(2), m.group(3)
                default = arg if op and op.lstrip(":") in ("-", "=") else None
                where = f"{path.name}:{n}"
                if var not in limits:
                    errors.append(f"{where}: {var} is used but not declared in {env_name}; add `# {var}={default or '<size>'}` there so the AD-7 sum counts it")
                    continue
                if default is None:
                    continue
                try:
                    same = parse_size(default) == limits[var][1]
                except ValueError as exc:
                    errors.append(f"{where}: {var} default: {exc}")
                    continue
                if not same:
                    errors.append(f"{where}: {var} defaults to {default} but {env_name} declares {limits[var][0]}; make them match")
    return errors


def literal_limits(path: Path) -> list[tuple[str, str, int]]:
    """[(service, value, line)] for hard-coded memory limits in a compose file.

    Counts `memory:` directly under a `limits:` key, and `mem_limit:`, inside
    `services:`, when the value is not a variable reference. Indentation
    based, so no YAML library is needed.
    """
    out: list[tuple[str, str, int]] = []
    stack: list[tuple[int, str]] = []  # (indent, key) of the enclosing mappings
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _KEY.match(line)
        if not m:
            continue
        indent = len(m.group(1)) + len(m.group(2) or "")
        key, value = m.group(3), m.group(4).split(" #", 1)[0].strip().strip("'\"")
        while stack and stack[-1][0] >= indent:
            stack.pop()
        keys = [k for _, k in stack]
        if value and "$" not in value and len(keys) >= 2 and keys[0] == "services":
            if key == "mem_limit" or (key == "memory" and keys[-1] == "limits"):
                out.append((keys[1], value, n))
        stack.append((indent, key))
    return out


def load_literal_baseline(path: Path) -> tuple[dict[tuple[str, str, str], str], list[str]]:
    """{(compose file, service, value): reason}. Lines: `<file> <service> <value>  # reason`."""
    entries: dict[tuple[str, str, str], str] = {}
    errors: list[str] = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        body, _, reason = line.partition("#")
        parts = body.split()
        if len(parts) != 3:
            errors.append(f"{path.name}:{n}: expected `<compose file> <service> <value>  # reason`")
            continue
        key = (parts[0], parts[1], parts[2].lower())
        if not reason.strip():
            errors.append(f"{path.name}:{n}: '{' '.join(parts)}' has no reason; add `  # <why, which story removes it>`")
        if key in entries:
            errors.append(f"{path.name}:{n}: '{' '.join(parts)}' is listed twice; keep one line")
        entries[key] = reason.strip()
    return entries, errors


def check_literals(compose: list[Path], baseline_path: Path | None) -> tuple[list[str], list[str]]:
    """(report lines, errors) for hard-coded compose limits."""
    baseline, errors = load_literal_baseline(baseline_path) if baseline_path else ({}, [])
    name = baseline_path.name if baseline_path else LITERAL_BASELINE.name
    report: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for path in compose:
        for service, value, n in literal_limits(path):
            key = (path.name, service, value.lower())
            seen.add(key)
            if key in baseline:
                report.append(f"  {path.name}:{n} {service} {value}  (literal, baselined, NOT in the sum)")
            else:
                var = re.sub(r"\W", "_", service).upper() + "_MEM_LIMIT"
                errors.append(
                    f"{path.name}:{n}: service '{service}' has a hard-coded memory limit {value}, outside the "
                    f"AD-7 sum; use `${{{var}:-{value}}}` and declare `# {var}={value}` in .env.example")
    for key in sorted(set(baseline) - seen):
        errors.append(f"{name}: '{' '.join(key)}' matches no literal limit any more; remove it from the baseline")
    return report, errors


def check(env_path: Path, compose: list[Path], limit: int = LIMIT_BYTES,
          literal_baseline: Path | None = None) -> tuple[list[str], list[str]]:
    """(report lines, errors). literal_baseline=None: no literal limit is baselined."""
    limits, errors = read_limits(env_path)
    errors += check_compose(compose, limits, env_path.name)
    total = sum(b for _, b, _ in limits.values())
    report = [f"  {var:<24} {raw:>8}  ({fmt(b)})" for var, (raw, b, _) in sorted(limits.items())]
    report.append(f"  {'sum':<24} {'':>8}  ({fmt(total)}; ceiling {fmt(limit)}, binary units)")
    if not limits:
        report = [f"  no *_MEM_LIMIT in {env_path.name}; nothing to sum"]
    if total > limit:
        errors.append(
            f"the *_MEM_LIMIT sum is {fmt(total)}, over the AD-7 ceiling of {fmt(limit)} by "
            f"{fmt(total - limit)} (AD-7's 14.5 GB is 14.5 GiB, as Docker's g is binary); "
            "lower another limit in the same PR and re-run EV-5")
    literal_report, literal_errors = check_literals(compose, literal_baseline)
    return report + literal_report, errors + literal_errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", type=Path, default=ENV_EXAMPLE)
    ap.add_argument("--compose", type=Path, nargs="*", default=None,
                    help="compose files (default: docker-compose*/compose* .yml/.yaml next to --env)")
    ap.add_argument("--literal-baseline", type=Path, default=LITERAL_BASELINE)
    args = ap.parse_args(argv)
    compose = args.compose if args.compose is not None else compose_files(args.env.parent)

    report, errors = check(args.env, compose, literal_baseline=args.literal_baseline)
    print("Container memory limits (AD-7, CI-14):")
    print("\n".join(report))
    if errors:
        for e in errors:
            print(f"  ERROR {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
