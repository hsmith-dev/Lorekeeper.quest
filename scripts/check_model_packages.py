#!/usr/bin/env python3
"""CI-3 (AD-1, AD-16): the web/worker image installs no model package.

Every ML model runs in a sidecar (src/services/ml, stt, tts) reached through
app/clients. The backend image (src/backend: web and worker roles) therefore
never installs torch, spaCy, sentence-transformers, whisper, easyocr,
onnxruntime or any TTS package. This scans what that image installs:

  * src/backend/requirements.txt (and any file it pulls in with -r);
  * every `pip install` in src/backend/Dockerfile and Dockerfile.prod.

Names are compared in PEP 503 normalized form, so `Sentence_Transformers` and
`sentence-transformers` are the same package.

Today's image still carries five of them; they are listed, with a reason, in
scripts/model_packages_baseline.txt. That baseline only shrinks:
  * a forbidden package not in the baseline fails (fix: move the model into a
    sidecar and call it through app/clients);
  * a baseline entry nothing installs any more fails (fix: remove it from the
    baseline), as does an entry without a reason;
  * scripts/test_check_model_packages.py freezes the baseline's ceiling.

Run: python scripts/check_model_packages.py   (stdlib only; exit 0 clean, 1 on failure)
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "scripts" / "model_packages_baseline.txt"
REQUIREMENTS = [REPO / "src/backend/requirements.txt"]
DOCKERFILES = [REPO / "src/backend/Dockerfile", REPO / "src/backend/Dockerfile.prod"]

# PEP 503 names. AD-1 / spine "Design Paradigm" list, the E0-QA.10 AC list,
# and AD-16's TTS packages (kokoro, kokoro-onnx, misaki, phonemizer,
# espeakng-loader; TTS is Coqui). transformers and ctranslate2 are the engines
# under sentence-transformers and faster-whisper.
FORBIDDEN = frozenset({
    "torch",
    "transformers",
    "sentence-transformers",
    "spacy",
    "openai-whisper",
    "faster-whisper",
    "ctranslate2",
    "easyocr",
    "onnxruntime",
    "onnxruntime-gpu",
    "kokoro",
    "kokoro-onnx",
    "misaki",
    "phonemizer",
    "espeakng-loader",
    "tts",
})

FIX = ("move the model into a sidecar (src/services/ml or stt) and call it "
       "through app/clients (AD-1, AD-6)")

# pip options that take a separate value (`-r file`, `--index-url URL`).
_PIP_OPTS_WITH_VALUE = frozenset({
    "-r", "--requirement", "-c", "--constraint", "-e", "--editable",
    "-i", "--index-url", "--extra-index-url", "-f", "--find-links",
    "-t", "--target", "--prefix", "--root", "--trusted-host", "--platform",
    "--python-version", "--implementation", "--abi", "--src", "--cache-dir",
    "--progress-bar", "--log", "--proxy", "--retries", "--timeout",
    "--upgrade-strategy", "--only-binary", "--no-binary", "--config-settings",
    "-C", "--global-option", "--report", "--python",
})
_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    """PEP 503 normalized project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_name(spec: str) -> str | None:
    """Project name of a requirement specifier, or None for paths and URLs."""
    spec = spec.strip().strip("'\"")
    if not spec or "/" in spec or spec.startswith((".", "-")) or "://" in spec:
        return None
    m = _NAME_RE.match(spec)
    return normalize(m.group(1)) if m else None


@dataclass(frozen=True)
class Hit:
    package: str  # normalized
    path: Path
    line: int

    def where(self, root: Path = REPO) -> str:
        try:
            rel = self.path.resolve().relative_to(root.resolve())
        except ValueError:
            rel = self.path
        return f"{rel}:{self.line}"


def scan_requirements(path: Path, _seen: set[Path] | None = None) -> list[Hit]:
    """Every requirement in `path`, following -r includes."""
    seen = _seen if _seen is not None else set()
    path = path.resolve()
    if path in seen:
        return []
    seen.add(path)
    hits: list[Hit] = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split(" #", 1)[0].split("\t#", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(?:-r|--requirement)(?:\s+|=)(\S+)", line)
        if m:
            hits += scan_requirements(path.parent / m.group(1), seen)
            continue
        if line.startswith("-"):
            continue
        name = requirement_name(line)
        if name:
            hits.append(Hit(name, path, n))
    return hits


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Dockerfile lines with backslash continuations joined (first line number kept)."""
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 0
    for n, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if buf and stripped.startswith("#"):
            continue  # comment lines inside a continued instruction
        if not buf:
            start = n
        if stripped.endswith("\\"):
            buf.append(stripped[:-1])
            continue
        buf.append(stripped)
        out.append((start, " ".join(buf)))
        buf = []
    if buf:
        out.append((start, " ".join(buf)))
    return out


def pip_install_packages(command: str) -> list[str]:
    """Package names installed by the `pip install` commands in a shell command."""
    names: list[str] = []
    for segment in re.split(r"&&|\|\||;|\|", command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        for i in range(len(tokens) - 1):
            if tokens[i] in ("pip", "pip3") or re.fullmatch(r"(.*/)?pip3?(\.\d+)?", tokens[i]):
                if tokens[i + 1] == "install":
                    names += _install_args(tokens[i + 2:])
                    break
    return names


def _install_args(args: list[str]) -> list[str]:
    names: list[str] = []
    skip = False
    for tok in args:
        if skip:
            skip = False
            continue
        if tok.startswith("-"):
            if "=" not in tok and tok in _PIP_OPTS_WITH_VALUE:
                skip = True
            continue
        name = requirement_name(tok)
        if name:
            names.append(name)
    return names


def scan_dockerfile(path: Path) -> list[Hit]:
    hits: list[Hit] = []
    for n, line in _logical_lines(path.read_text()):
        m = re.match(r"^RUN\s+(.*)$", line, re.IGNORECASE)
        if m:
            hits += [Hit(p, path, n) for p in pip_install_packages(m.group(1))]
    return hits


def load_baseline(path: Path) -> tuple[dict[str, str], list[str]]:
    """{package: reason} and format errors. Lines: `package: reason`."""
    entries: dict[str, str] = {}
    errors: list[str] = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reason = line.partition(":")
        pkg = normalize(name.strip())
        if not reason.strip():
            errors.append(f"{path.name}:{n}: '{pkg}' has no reason; write `{pkg}: <why it is still here, which story removes it>`")
        if pkg in entries:
            errors.append(f"{path.name}:{n}: '{pkg}' is listed twice; keep one line")
        if pkg not in FORBIDDEN:
            errors.append(f"{path.name}:{n}: '{pkg}' is not a forbidden model package; remove it from the baseline")
        entries[pkg] = reason.strip()
    return entries, errors


def check(requirements: list[Path], dockerfiles: list[Path], baseline_path: Path,
          root: Path = REPO) -> list[str]:
    hits: list[Hit] = []
    for p in requirements:
        hits += scan_requirements(p)
    for p in dockerfiles:
        hits += scan_dockerfile(p)
    baseline, errors = load_baseline(baseline_path)

    found: dict[str, list[Hit]] = {}
    for h in hits:
        if h.package in FORBIDDEN:
            found.setdefault(h.package, []).append(h)

    for pkg in sorted(found):
        if pkg not in baseline:
            for h in found[pkg]:
                errors.append(f"{h.where(root)}: installs model package '{pkg}' in the web/worker image; {FIX}")
    for pkg in sorted(set(baseline) - set(found)):
        if pkg in FORBIDDEN:
            errors.append(
                f"{baseline_path.name}: '{pkg}' is no longer installed by the web/worker image; "
                f"remove it from the baseline ({baseline_path.name}) so it cannot come back")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--requirements", type=Path, nargs="*", default=REQUIREMENTS)
    ap.add_argument("--dockerfile", type=Path, nargs="*", default=DOCKERFILES)
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    args = ap.parse_args(argv)

    errors = check(args.requirements, args.dockerfile, args.baseline)
    if errors:
        print("Model packages in the web/worker image (AD-1, CI-3):", file=sys.stderr)
        for e in errors:
            print(f"  ERROR {e}", file=sys.stderr)
        return 1
    baseline, _ = load_baseline(args.baseline)
    print(f"OK: no model package outside the baseline ({len(baseline)} baselined: {', '.join(sorted(baseline))}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
