#!/usr/bin/env python3
"""CI-14 (AD-7): the container memory limits fit the 16 GB Reference Box.

AD-7: the sum of all container limits stays at or below 14.5 GB, leaving at
least 1.5 GB for the OS and Docker. The limits live in .env.example as
`*_MEM_LIMIT` variables. Both forms count, since a commented line documents
the compose default:

    ML_MEM_LIMIT=2560m
    # ML_MEM_LIMIT=2560m

Sizes use Docker's binary units (b, k, m, g; 1g = 1024m), so the ceiling is
14.5 GiB, inclusive. With no limits declared the check passes vacuously.

Compose drift: every `${X_MEM_LIMIT:-default}` (or `${X_MEM_LIMIT}`) in a
docker-compose*.yml must be declared in .env.example, with the same default,
so the sum checked here is the one compose runs with.

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
LIMIT_BYTES = int(14.5 * 1024**3)

_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([bkmgt]?)b?\s*$", re.I)
_DECL = re.compile(r"^\s*(#\s*)?([A-Z][A-Z0-9_]*_MEM_LIMIT)\s*=\s*(\S*)")
_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*_MEM_LIMIT)(?::?-([^}]*))?\}")


def parse_size(value: str) -> int:
    """Docker memory size ('2560m', '5.25g', '768M', '1073741824') in bytes."""
    m = _SIZE.match(value.strip().strip("'\""))
    if not m:
        raise ValueError(f"not a memory size: {value!r} (use a number with b, k, m or g)")
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def fmt(n: int) -> str:
    return f"{n / 1024**3:.2f} GiB"


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


def check_compose(compose_files: list[Path], limits: dict[str, tuple[str, int, int]], env_name: str) -> list[str]:
    errors: list[str] = []
    for path in compose_files:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            for m in _REF.finditer(line):
                var, default = m.group(1), m.group(2)
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


def check(env_path: Path, compose_files: list[Path], limit: int = LIMIT_BYTES) -> tuple[list[str], list[str]]:
    """(report lines, errors)."""
    limits, errors = read_limits(env_path)
    errors += check_compose(compose_files, limits, env_path.name)
    total = sum(b for _, b, _ in limits.values())
    report = [f"  {var:<24} {raw:>8}  ({fmt(b)})" for var, (raw, b, _) in sorted(limits.items())]
    report.append(f"  {'sum':<24} {'':>8}  ({fmt(total)}; ceiling {fmt(limit)})")
    if not limits:
        report = [f"  no *_MEM_LIMIT in {env_path.name}; nothing to sum"]
    if total > limit:
        errors.append(
            f"the *_MEM_LIMIT sum is {fmt(total)}, over the AD-7 ceiling of {fmt(limit)} by "
            f"{fmt(total - limit)}; lower another limit in the same PR and re-run EV-5")
    return report, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", type=Path, default=ENV_EXAMPLE)
    ap.add_argument("--compose", type=Path, nargs="*", default=None,
                    help="compose files (default: docker-compose*.yml next to --env)")
    args = ap.parse_args(argv)
    compose = args.compose if args.compose is not None else sorted(args.env.parent.glob("docker-compose*.yml"))

    report, errors = check(args.env, compose)
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
