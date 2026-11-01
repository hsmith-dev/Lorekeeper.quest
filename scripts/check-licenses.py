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

Register mode (licenses/register.yaml, the inventory of everything shipped):
  python scripts/check-licenses.py --python-env --register licenses/register.yaml \
      [--edition agpl|commercial] [--artifact backend]
  python scripts/check-licenses.py --npm npm.json --register licenses/register.yaml
  python scripts/check-licenses.py --check-artifacts --register licenses/register.yaml
  Every scanned package then needs a register entry whose licence matches the
  scan, and edition rules apply: `commercial` (the default, or
  $LOREKEEPER_EDITION) is strict; `agpl` additionally allows GPL-family entries
  that ship only in the AGPL-only `tts` image. --emit-missing prints YAML stubs
  for unregistered packages. Register mode needs pyyaml (requirements-dev.txt).

Needs Python 3.11+ (tomllib).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY = REPO_ROOT / ".github" / "license-policy.toml"
EDITIONS = ("agpl", "commercial")
KINDS = ("python", "npm", "image", "apt", "model", "voice", "font")
ARTIFACT_KINDS = ("model", "voice", "font")
REQUIRED_FIELDS = ("name", "kind", "version", "license", "source_url", "editions", "notes")


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
        # Register mode only (--register); the plain scan never reads these.
        strict = data.get("strict", {})
        self.gpl_patterns = [re.compile(p, re.I) for p in strict.get("gpl_patterns", [])]
        self.bad_patterns = [re.compile(p, re.I) for p in strict.get("bad_patterns", [])]
        self.lgpl_patterns = [re.compile(p, re.I) for p in strict.get("lgpl_patterns", [])]
        self.system_libs = [re.compile(p, re.I) for p in strict.get("system_lib_allowlist", [])]
        self.agpl_only_images = set(strict.get("agpl_only_images", []))
        self.denied_packages = {
            eco: {norm_pkg(p) for p in pkgs}
            for eco, pkgs in data.get("deny", {}).get("packages", {}).items()
        }
        arts = data.get("artifacts", {})
        self.artifact_exts = {e.lower() for e in arts.get("extensions", [])}
        self.artifact_roots = list(arts.get("roots", []))

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


# --------------------------------------------------------------------------
# Register mode
# --------------------------------------------------------------------------

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Register:
    """licenses/register.yaml: `entries` (everything shipped) and `rejected`."""

    def __init__(self, path: Path):
        try:
            import yaml
        except ImportError:  # pragma: no cover - depends on the environment
            raise SystemExit("register mode needs pyyaml: pip install -r src/backend/requirements-dev.txt")
        data = yaml.safe_load(path.read_text()) or {}
        self.path = path
        raw = list(data.get("entries") or [])
        self.entries: list[dict] = []  # only entries usable by the checks below
        self.rejected: list[dict] = list(data.get("rejected") or [])
        self.errors: list[str] = []
        self.index: dict[tuple[str, str], list[dict]] = {}
        seen = set()
        for i, e in enumerate(raw):
            if not isinstance(e, dict):
                self.errors.append(f"entries[{i}] is not a mapping")
                continue
            kind, name = e.get("kind"), e.get("name")
            label = (f"{kind if isinstance(kind, str) else '?'}:"
                     f"{name if isinstance(name, str) else f'entries[{i}]'}")
            missing = [f for f in REQUIRED_FIELDS if e.get(f) is None]
            if missing:
                self.errors.append(f"{label}: missing field(s) {missing}")
            # Unquoted YAML (version: 1.10 -> float 1.1) is an error, not coerced.
            wrong = [f for f in ("name", "kind", "version", "license", "source_url", "notes")
                     if e.get(f) is not None and not isinstance(e[f], str)]
            if wrong:
                self.errors.append(f"{label}: field(s) {wrong} must be strings (quote them in YAML)")
            if kind not in KINDS:
                self.errors.append(f"{label}: kind must be one of {list(KINDS)}")
            usable = (isinstance(name, str) and name and isinstance(kind, str) and kind in KINDS
                      and isinstance(e.get("license"), str) and e["license"]
                      and isinstance(e.get("version"), str))
            eds = e.get("editions")
            if not isinstance(eds, list) or not eds or not set(eds) <= set(EDITIONS):
                self.errors.append(f"{label}: editions must be a non-empty subset of {list(EDITIONS)}")
                e["editions"] = [x for x in eds or [] if x in EDITIONS] if isinstance(eds, list) else []
            imgs = e.get("images")
            if imgs is not None and (not isinstance(imgs, list) or not all(isinstance(x, str) for x in imgs)):
                self.errors.append(f"{label}: images must be a list of image names")
                e["images"] = []
            if e.get("kind") in ARTIFACT_KINDS:
                if not (e.get("artifact") or e.get("download")):
                    self.errors.append(f"{label}: {e['kind']} entries need `artifact` (repo path) or `download` (URL)")
                if not SHA256_RE.match(str(e.get("sha256") or "").lower()):
                    self.errors.append(f"{label}: {e['kind']} entries need a 64-hex `sha256`")
            if e.get("pip_package") is not None and not isinstance(e["pip_package"], str):
                self.errors.append(f"{label}: pip_package must be a string")
                e["pip_package"] = None
            if not usable:
                continue  # schema error recorded above; never indexed or checked
            key = (kind, norm_pkg(name), e["version"])
            if key in seen:
                self.errors.append(f"{label}: duplicate entry for version {e['version']}")
            seen.add(key)
            self.entries.append(e)
            self.index.setdefault((kind, norm_pkg(name)), []).append(e)
            if e.get("pip_package"):
                self.index.setdefault(("python", norm_pkg(e["pip_package"])), []).append(e)
        for i, r in enumerate(self.rejected):
            if not isinstance(r, dict) or not r.get("name") or not r.get("reason"):
                self.errors.append(f"rejected[{i}]: needs `name` and `reason`")

    def find(self, eco: str, name: str, version: str, match=None) -> dict | None:
        """Entry for a scanned package: exact version (`version` may list several,
        comma-separated), else one whose licence `match`es, else the first."""
        cands = self.index.get((eco, norm_pkg(name)), [])
        for e in cands:
            if version in versions_of(e):
                return e
        for e in cands:
            if match and match(e):
                return e
        return cands[0] if cands else None


def versions_of(entry: dict) -> list[str]:
    return [v.strip() for v in str(entry.get("version", "")).split(",")]


def label(e: dict) -> str:
    return f"{e.get('kind', '?')}:{e.get('name', '?')}"


def normalise_license(policy: Policy, lic: str) -> str:
    """Scan string -> SPDX-ish expression: pip's "; " alternatives become OR, aliases applied."""
    parts = [p for p in re.split(r"\s*;\s*", lic) if p.strip()]
    expr = " OR ".join(policy.canonical(p) for p in parts) if parts else "UNKNOWN"
    return re.sub(r"\s+", " ", expr).strip()


def license_matches(policy: Policy, entry: dict, lic: str) -> tuple[bool, str]:
    if entry.get("scanned_license") is not None:
        expected = str(entry["scanned_license"]).strip()
        return lic.strip() == expected, expected
    expected = normalise_license(policy, entry["license"])
    return normalise_license(policy, lic).lower() == expected.lower(), expected


def classify(policy: Policy, lic: str) -> str:
    """ok | lgpl | gpl | bad (non-commercial, ethical-use, proprietary, unknown...)."""
    if policy.license_ok(lic):
        return "ok"
    if any(p.search(lic) for p in policy.bad_patterns):
        return "bad"
    if any(p.search(lic) for p in policy.gpl_patterns):
        rest = lic
        for p in policy.lgpl_patterns:
            rest = p.sub(" ", rest)
        return "gpl" if any(p.search(rest) for p in policy.gpl_patterns) else "lgpl"
    return "bad"


CLASS_REASON = {
    "gpl": "GPL/AGPL licence",
    "lgpl": "LGPL licence (only dynamically linked apt system libraries on the allowlist may be LGPL)",
    "bad": "non-commercial / ethical-use / proprietary / unknown licence",
}


def is_system_lib(policy: Policy, kind: str, name: str) -> bool:
    return kind == "apt" and any(p.search(name) for p in policy.system_libs)


def exception_for(policy: Policy, eco: str, name: str, licences: set[str]) -> dict | None:
    exc = policy.exceptions.get((eco, norm_pkg(name)))
    if exc and (exc.get("license") is None or exc["license"] in licences):
        return exc
    return None


def agpl_tts_only(policy: Policy, entry: dict) -> bool:
    imgs = set(entry.get("images") or [])
    return set(entry["editions"]) == {"agpl"} and bool(imgs) and imgs <= policy.agpl_only_images


def check_register_scan(policy: Policy, reg: Register, eco: str, deps, edition: str,
                        artifact: str | None):
    """Scanned packages against the register. Returns failures, excepted, matched, missing, drift."""
    failures, excepted, missing = [], [], []
    matched: set[int] = set()
    drift = 0
    in_tts = artifact in policy.agpl_only_images
    where = f"artifact {artifact!r}" if artifact else "this artifact"
    for name, version, lic in sorted(deps, key=lambda d: d[0].lower()):
        n = norm_pkg(name)
        if n in policy.ignore.get(eco, set()):
            continue
        if n in policy.denied_packages.get(eco, set()):
            failures.append((name, version, lic, "denied package (.github/license-policy.toml [deny.packages])"))
            continue
        entry = reg.find(eco, name, version, lambda e, lic=lic: license_matches(policy, e, lic)[0])
        if entry is None:
            cls = classify(policy, lic)
            also = "" if cls == "ok" else f"; also {CLASS_REASON[cls]}"
            failures.append((name, version, lic, "no register entry in licenses/register.yaml "
                                                 f"(--emit-missing prints a stub){also}"))
            missing.append((name, version, lic))
            continue
        matched.add(id(entry))
        if version not in versions_of(entry):
            drift += 1
        ok, expected = license_matches(policy, entry, lic)
        if not ok:
            failures.append((name, version, lic, f"register says {expected!r}, scan says {lic!r}"))
            continue
        eds = set(entry["editions"])
        if edition == "commercial" and "commercial" not in eds:
            failures.append((name, version, lic, f"register editions {sorted(eds)} exclude commercial, "
                                                 f"but it is present in {where} of the commercial build"))
            continue
        if "commercial" not in eds and not in_tts:
            failures.append((name, version, lic, f"AGPL-only entry present in {where}; only allowed in "
                                                 f"{sorted(policy.agpl_only_images)}"))
            continue
        if edition not in eds:
            failures.append((name, version, lic, f"register editions {sorted(eds)} exclude {edition}"))
            continue
        cls = classify(policy, lic)
        if cls == "ok":
            continue
        if cls == "lgpl" and is_system_lib(policy, eco, name):
            continue
        exc = exception_for(policy, eco, name, {lic})
        if exc:
            excepted.append((name, version, lic, exc["reason"]))
            continue
        if edition == "agpl" and cls in ("gpl", "lgpl") and in_tts and eds == {"agpl"}:
            continue
        failures.append((name, version, lic, CLASS_REASON[cls] + f" in the {edition} edition"))
    return failures, excepted, matched, missing, drift


def check_register_entries(policy: Policy, reg: Register, edition: str, skip: set[int]):
    """Edition rules on register entries themselves (images, models, fonts, unscanned packages)."""
    failures, excepted = [], []
    for e in reg.entries:
        if id(e) in skip or not isinstance(e, dict) or not e.get("license") or not e.get("kind"):
            continue
        eds = set(e["editions"])
        imgs = list(e.get("images") or [])
        row = (label(e), e.get("version", "?"), e["license"])
        if norm_pkg(e["name"]) in policy.denied_packages.get(e["kind"], set()):
            failures.append((*row, "denied package (.github/license-policy.toml [deny.packages])"))
            continue
        if edition == "commercial":
            if "commercial" not in eds:
                leaked = [i for i in imgs if i not in policy.agpl_only_images]
                if leaked:
                    failures.append((*row, f"register editions {sorted(eds)} exclude commercial, but "
                                           f"`images` puts it in commercial image(s) {leaked}"))
                continue
        elif "agpl" not in eds:
            continue
        cls = classify(policy, e["license"])
        if cls == "ok":
            continue
        if cls == "lgpl" and is_system_lib(policy, e["kind"], e["name"]):
            continue
        exc = exception_for(policy, e["kind"], e["name"],
                            {e["license"], str(e.get("scanned_license", e["license"]))})
        if exc:
            excepted.append((*row, exc["reason"]))
            continue
        if edition == "agpl" and cls in ("gpl", "lgpl") and agpl_tts_only(policy, e):
            continue
        hint = (" (GPL-family entries need editions: [agpl] and images: [tts])"
                if edition == "agpl" and cls in ("gpl", "lgpl") else "")
        failures.append((*row, CLASS_REASON[cls] + f" in the {edition} edition{hint}"))
    return failures, excepted


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
        return [p for p in out.stdout.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", ".venv", "__pycache__"}]
            files += [os.path.relpath(os.path.join(dirpath, f), root) for f in filenames]
        return files


def check_artifacts(policy: Policy, reg: Register, root: Path):
    """Register-vs-artifacts: hashes of tracked artifacts, and no baked artifact without an entry."""
    failures = []
    registered = set()
    for e in reg.entries:
        if not isinstance(e, dict) or e.get("kind") not in ARTIFACT_KINDS:
            continue
        art = e.get("artifact")
        if not art:
            continue  # download-only: the sha256 pins what the installer must fetch
        registered.add(Path(art).as_posix())
        path = root / art
        row = (label(e), e.get("version", "?"), e.get("license", "?"))
        if not path.is_file():
            failures.append((*row, f"artifact {art!r} does not exist"))
            continue
        actual = sha256_file(path)
        if actual != str(e.get("sha256", "")).lower():
            failures.append((*row, f"sha256 mismatch for {art}: register {e.get('sha256')!r}, file {actual}"))
    roots = [r.rstrip("/") + "/" for r in policy.artifact_roots]
    baked = [f for f in tracked_files(root)
             if Path(f).suffix.lower() in policy.artifact_exts
             and (not roots or any(f.startswith(r) for r in roots))]
    for f in sorted(baked):
        if Path(f).as_posix() not in registered:
            failures.append((f, "-", "?", "baked artifact has no register entry (add a model/voice/font "
                                          "entry with `artifact` and `sha256`)"))
    return failures, len(baked)


def emit_stub(eco: str, name: str, version: str, lic: str, policy: Policy) -> str:
    url = (f"https://pypi.org/project/{name}/" if eco == "python"
           else f"https://www.npmjs.com/package/{name}")
    spdx = normalise_license(policy, lic)
    parts = [f"name: {json.dumps(name)}", f"kind: {eco}", f"version: {json.dumps(version)}",
             f"license: {json.dumps(spdx)}", f"source_url: {json.dumps(url)}",
             "editions: [agpl, commercial]", 'notes: ""']
    return "  - {" + ", ".join(parts) + "}"


def report(title: str, failures, excepted, extra: str = "") -> None:
    print(f"== {title}: {len(failures)} violation(s), {len(excepted)} exception(s){extra}")
    for name, version, lic, reason in excepted:
        print(f"  EXCEPTION {name}=={version}  [{lic}]  -- {reason}")
    for name, version, lic, reason in failures:
        print(f"  FAIL      {name}=={version}  [{lic}]  -- {reason}")
        if "GITHUB_ACTIONS" in os.environ:
            print(f"::error title=Licence register ({title})::{name} {version} [{lic}]: {reason}")


def run_register(args, policy: Policy, sources) -> int:
    reg = Register(args.register)
    total = 0
    print(f"Licence register {args.register} ({len(reg.entries)} entries, {len(reg.rejected)} rejected); "
          f"edition: {args.edition}; artifact: {args.artifact or '-'}")
    if reg.errors:
        print(f"== register schema: {len(reg.errors)} error(s)")
        for err in reg.errors:
            print(f"  FAIL      {err}")
            if "GITHUB_ACTIONS" in os.environ:
                print(f"::error title=Licence register schema::{err}")
        total += len(reg.errors)
    matched: set[int] = set()
    stubs = []
    for eco, deps in sources:
        failures, excepted, hit, missing, drift = check_register_scan(
            policy, reg, eco, deps, args.edition, args.artifact)
        matched |= hit
        stubs += [(eco, *m) for m in missing]
        report(f"{eco} ({args.edition})", failures, excepted,
               f"; {len(deps)} packages, {drift} version difference(s) vs register (informational)")
        total += len(failures)
    failures, excepted = check_register_entries(policy, reg, args.edition, matched)
    report(f"register entries ({args.edition})", failures, excepted)
    total += len(failures)
    if args.check_artifacts:
        failures, n = check_artifacts(policy, reg, args.repo_root)
        report("artifacts", failures, [], f"; {n} tracked artifact file(s)")
        total += len(failures)
    if args.emit_missing and stubs:
        print("\n# --emit-missing: stubs for licenses/register.yaml `entries:` (check each licence by hand)")
        for eco, name, version, lic in stubs:
            print(emit_stub(eco, name, version, lic, policy))
    if total:
        print(f"\n{total} licence register violation(s). Add or correct the entry in licenses/register.yaml "
              "(same PR as the dependency), replace the dependency, or record an owner-approved "
              "[[exception]] in .github/license-policy.toml.")
        return 1
    print(f"\nEverything scanned is registered and complies with the {args.edition} edition rules.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--python-env", action="store_true",
                    help="check every package installed in the interpreter running this script")
    ap.add_argument("--python", type=Path, help="pip-licenses --format=json output (alternative)")
    ap.add_argument("--npm", type=Path, help="license-checker(-rseidelsohn) --json output")
    ap.add_argument("--register", type=Path,
                    help="licenses/register.yaml: require an entry per scanned package and apply edition rules")
    ap.add_argument("--edition", choices=EDITIONS,
                    help="edition rules for --register (default: $LOREKEEPER_EDITION, else commercial)")
    ap.add_argument("--artifact",
                    help="name of the image/artifact being scanned (e.g. backend, tts, frontend)")
    ap.add_argument("--check-artifacts", action="store_true",
                    help="with --register: verify model/voice/font artifacts and hashes against the repo")
    ap.add_argument("--emit-missing", action="store_true",
                    help="with --register: print YAML stubs for scanned packages with no entry")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.register is None:
        if args.check_artifacts or args.emit_missing:
            ap.error("--check-artifacts and --emit-missing need --register")
    else:
        if args.edition is None:
            args.edition = os.environ.get("LOREKEEPER_EDITION") or "commercial"
            if args.edition not in EDITIONS:
                ap.error(f"LOREKEEPER_EDITION must be one of {', '.join(EDITIONS)} (got {args.edition!r})")
    if not (args.python_env or args.python or args.npm or (args.register and args.check_artifacts)):
        ap.error("give --python-env, --python and/or --npm" +
                 (" (or --check-artifacts)" if args.register else ""))

    policy = Policy(args.policy)
    total_fail = 0
    sources = []
    if args.python_env:
        sources.append(("python", load_python_env()))
    if args.python:
        sources.append(("python", load_python(args.python)))
    if args.npm:
        sources.append(("npm", load_npm(args.npm)))
    if args.register is not None:
        return run_register(args, policy, sources)
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
