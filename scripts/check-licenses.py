#!/usr/bin/env python3
"""Fail CI when a dependency's licence is incompatible with Lorekeeper's dual licensing.

Lorekeeper ships under AGPL-3.0 *and* is sold under a proprietary commercial
licence (COMMERCIAL-LICENSE.md). The commercial side means every dependency we
distribute must be permissive: copyleft (GPL/AGPL/LGPL), non-commercial
(CC-BY-NC), ethical-use (Hippocratic) and unknown licences all fail unless the
owner has recorded an explicit exception.

The policy (allowlist, aliases, deny patterns, exceptions) lives in
.github/license-policy.toml so new dependencies are checked automatically.

Usage:
  # inside the venv that has src/backend/requirements.txt installed:
  python scripts/check-licenses.py --python-env
  # frontend:
  npx license-checker-rseidelsohn --json --excludePrivatePackages > npm.json
  python scripts/check-licenses.py --npm npm.json
  (--python py.json also accepts `pip-licenses --format=json` output, but
  pip-licenses 5.0 ignores PEP 639 License-Expression, so prefer --python-env.)

Needs Python 3.11+ (tomllib).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

DEFAULT_POLICY = Path(__file__).resolve().parent.parent / ".github" / "license-policy.toml"


def norm_pkg(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class Policy:
    def __init__(self, path: Path):
        data = tomllib.loads(path.read_text())
        self.allowed = {s.lower() for s in data["allow"]["licenses"]}
        self.aliases = {k.lower(): v for k, v in data.get("aliases", {}).items()}
        self.deny = [re.compile(p, re.I) for p in data.get("deny", {}).get("patterns", [])]
        self.ignore = {
            eco: {norm_pkg(p) for p in pkgs} for eco, pkgs in data.get("ignore", {}).items()
        }
        self.exceptions: dict[tuple[str, str], dict] = {}
        for exc in data.get("exception", []):
            self.exceptions[(exc["ecosystem"], norm_pkg(exc["package"]))] = exc

    def canonical(self, token: str) -> str:
        t = token.strip().rstrip("*").strip()  # license-checker marks guessed licences with '*'
        while t.startswith("(") and t.endswith(")"):
            t = t[1:-1].strip()
        return self.aliases.get(t.lower(), t)

    def term_ok(self, term: str) -> bool:
        """Evaluate an SPDX-ish expression; OR needs one allowed side, AND needs all."""
        term = term.strip()
        while term.startswith("(") and term.endswith(")"):
            term = term[1:-1].strip()
        if not term:
            return False
        alias = self.aliases.get(term.lower())
        if alias:
            term = alias
        ors = re.split(r"\s+OR\s+|\s*/\s*", term)
        if len(ors) > 1:
            return any(self.term_ok(t) for t in ors)
        ands = re.split(r"\s+AND\s+", term)
        if len(ands) > 1:
            return all(self.term_ok(t) for t in ands)
        # "X WITH <exception>" only ever relaxes X (e.g. Apache-2.0 WITH LLVM-exception).
        term = re.split(r"\s+WITH\s+", term)[0]
        return self.canonical(term).lower() in self.allowed

    def license_ok(self, license_str: str) -> bool:
        # pip-licenses joins multiple trove classifiers with "; ". In practice
        # that means a choice of licences (e.g. cryptography: Apache OR BSD),
        # so any one allowed alternative is enough.
        parts = [p for p in re.split(r"\s*;\s*", license_str) if p.strip()]
        return any(self.term_ok(p) for p in parts) if parts else False

    def denied_reason(self, license_str: str) -> str:
        hits = [p.pattern for p in self.deny if p.search(license_str)]
        return f"matches deny pattern {hits}" if hits else "not on allowlist / unknown"


def load_python(path: Path) -> list[tuple[str, str, str]]:
    rows = json.loads(path.read_text())
    return [(r["Name"], r["Version"], r.get("License") or "UNKNOWN") for r in rows]


def python_license(meta) -> str:
    """Best licence string for an installed distribution.

    Order: PEP 639 License-Expression (pip-licenses 5.0 ignores this, which is
    why we read metadata ourselves), then trove classifiers, then the free-text
    License field (first line only: some packages paste the whole licence).
    """
    expr = meta.get("License-Expression")
    if expr:
        return expr.strip()
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers)
    text = (meta.get("License") or "").strip()
    return text.splitlines()[0].strip() if text else "UNKNOWN"


def load_python_env() -> list[tuple[str, str, str]]:
    """Every distribution installed in the interpreter running this script."""
    from importlib.metadata import distributions

    seen, out = set(), []
    for dist in distributions():
        name = dist.metadata["Name"]
        if not name or norm_pkg(name) in seen or norm_pkg(name) in {"pip", "setuptools", "wheel"}:
            continue
        seen.add(norm_pkg(name))
        out.append((name, dist.version, python_license(dist.metadata)))
    return out


def load_npm(path: Path) -> list[tuple[str, str, str]]:
    rows = json.loads(path.read_text())
    out = []
    for key, info in rows.items():
        name, _, version = key.rpartition("@")
        lic = info.get("licenses", "UNKNOWN")
        if isinstance(lic, list):
            lic = " OR ".join(lic) if len(lic) > 1 else lic[0]
        out.append((name, version, lic or "UNKNOWN"))
    return out


def check(policy: Policy, eco: str, deps: list[tuple[str, str, str]]) -> tuple[list, list]:
    failures, excepted = [], []
    for name, version, lic in sorted(deps, key=lambda d: d[0].lower()):
        if norm_pkg(name) in policy.ignore.get(eco, set()):
            continue
        if policy.license_ok(lic):
            continue
        exc = policy.exceptions.get((eco, norm_pkg(name)))
        if exc:
            expected = exc.get("license")
            if expected is None or expected == lic:
                excepted.append((name, version, lic, exc["reason"]))
                continue
            failures.append((name, version, lic, f"exception recorded for licence {expected!r}, "
                             f"but it now reports {lic!r}: re-review"))
            continue
        failures.append((name, version, lic, policy.denied_reason(lic)))
    return failures, excepted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--python-env", action="store_true",
                    help="check every package installed in the interpreter running this script")
    ap.add_argument("--python", type=Path, help="pip-licenses --format=json output (alternative)")
    ap.add_argument("--npm", type=Path, help="license-checker(-rseidelsohn) --json output")
    args = ap.parse_args()
    if not (args.python_env or args.python or args.npm):
        ap.error("give --python-env, --python and/or --npm")

    policy = Policy(args.policy)
    total_fail = 0
    sources = []
    if args.python_env:
        sources.append(("python", load_python_env()))
    if args.python:
        sources.append(("python", load_python(args.python)))
    if args.npm:
        sources.append(("npm", load_npm(args.npm)))
    for eco, deps in sources:
        failures, excepted = check(policy, eco, deps)
        print(f"== {eco}: {len(deps)} packages, {len(failures)} violation(s), {len(excepted)} exception(s)")
        for name, version, lic, reason in excepted:
            print(f"  EXCEPTION {name}=={version}  [{lic}]  -- {reason}")
        for name, version, lic, reason in failures:
            print(f"  FAIL      {name}=={version}  [{lic}]  -- {reason}")
            if "GITHUB_ACTIONS" in os.environ:
                print(f"::error title=Licence policy ({eco})::{name} {version} is licensed {lic!r} ({reason})")
        total_fail += len(failures)

    if total_fail:
        print(f"\n{total_fail} dependency licence violation(s). Replace the dependency, or, if it is "
              "genuinely compatible (e.g. LGPL used only via dynamic linking), add an [[exception]] "
              "with a reason to .github/license-policy.toml.")
        return 1
    print("\nAll dependency licences comply with the policy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
