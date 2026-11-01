"""Static guard: every place that runs the backend installs WeasyPrint's apt set.

The campaign PDF export imports WeasyPrint at module top (E0-QA.9), so an image
or CI job without Pango fails at boot, and one without fonts-dejavu-extra loses
the italic meta lines. CI's PDF tests run on the workflows' own apt step, so
nothing else would notice a Dockerfile dropping a package. Runs without Docker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1] if len(BACKEND.parents) > 1 else None

WEASYPRINT_APT = {
    "libpango-1.0-0",
    "libpangoft2-1.0-0",
    "libharfbuzz0b",
    "fontconfig",
    "fonts-dejavu-core",
    "fonts-dejavu-extra",
}


def _apt_installed(text: str) -> set[str]:
    """Package names on every `apt-get install` line (continuations joined)."""
    joined = text.replace("\\\n", " ")
    names: set[str] = set()
    for line in joined.splitlines():
        if "apt-get install" not in line:
            continue
        after = line.split("apt-get install", 1)[1].split("&&", 1)[0]
        names |= {tok for tok in after.split() if not tok.startswith("-")}
    return names


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.prod"])
def test_dockerfiles_install_weasyprint_libs(name: str) -> None:
    missing = WEASYPRINT_APT - _apt_installed((BACKEND / name).read_text())
    assert not missing, f"{name} lacks WeasyPrint apt packages: {sorted(missing)}"


@pytest.mark.parametrize("name", ["backend-tests.yml", "gates.yml"])
def test_workflows_install_weasyprint_libs(name: str) -> None:
    path = REPO / ".github" / "workflows" / name if REPO else None
    if path is None or not path.exists():
        pytest.skip("repo root not mounted (src/backend alone)")
    missing = WEASYPRINT_APT - _apt_installed(path.read_text())
    assert not missing, f"{name} lacks WeasyPrint apt packages: {sorted(missing)}"
