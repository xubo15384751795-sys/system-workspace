"""WB-G2: MODULES.md path-existence guardrail.

Asserts every backtick-quoted path in MODULES.md resolves under the repo root.
This prevents the "agent navigates by MODULES.md and hits empty/broken paths"
failure (the 4 stale submodule gitlinks that pointed at empty dirs).

The test parses MODULES.md for backtick-quoted relative paths (e.g.
`packages/workbench/`, `scripts/`) and asserts each exists. Paths that are
clearly not file references (URLs, bare words) are skipped via heuristics.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES_MD = ROOT / "MODULES.md"

# Paths that are allowed to be referenced even if they are not on disk yet
# (e.g. planned-but-not-built, or external). Keep this list small and
# audited - every entry is a place where MODULES.md can lie without CI red.
ALLOWED_MISSING: set[str] = set()


def _extract_paths(text: str) -> list[str]:
    """Extract backtick-quoted relative paths from MODULES.md text."""
    paths = []
    for m in re.finditer(r"`([^`]+)`", text):
        candidate = m.group(1)
        # Heuristics: must look like a path (contains / or ends in known ext)
        # and not be a URL, command, or bare word.
        if "://" in candidate:
            continue
        if candidate.startswith("$"):
            continue
        # must contain a slash or be a known file, to avoid matching bare words
        if "/" not in candidate and not candidate.endswith((".md", ".py", ".yaml", ".json")):
            continue
        # skip glob-like patterns
        if "*" in candidate or "{" in candidate:
            continue
        # skip absolute/external paths (e.g. /90_Admin/Context/ under paper_root)
        if candidate.startswith("/"):
            continue
        # skip things that are clearly not paths (have spaces, colons after first char)
        if " " in candidate.strip():
            continue
        # skip narrative workspace-folder references (e.g. `System/` referring to
        # the workspace root folder name, not a repo-internal path)
        if candidate in ("System/",):
            continue
        paths.append(candidate)
    return paths


@pytest.fixture()
def modules_text() -> str:
    if not MODULES_MD.exists():
        pytest.skip("MODULES.md not found")
    return MODULES_MD.read_text(encoding="utf-8")


def test_no_stale_submodule_paths(modules_text: str) -> None:
    """WB-C: MODULES.md must not reference the deleted submodule gitlinks."""
    stale = ["Workbench/", "deformation-framework/", "structural-risk-harvester/", "system-learning-hub/"]
    found = [s for s in stale if s in modules_text]
    # Allow mentions in historical/narrative text only if not backtick-quoted as paths.
    # Check backtick-quoted occurrences specifically.
    for s in stale:
        if re.search(r"`[^`]*" + re.escape(s), modules_text):
            found = [s]
            break
    assert not found, (
        f"MODULES.md still references deleted submodule paths: {found}. "
        f"These are stale gitlinks (empty dirs removed in WB-C). Update to packages/*."
    )


def test_modules_paths_exist(modules_text: str) -> None:
    """WB-G2: every backtick-quoted path in MODULES.md must resolve on disk."""
    paths = _extract_paths(modules_text)
    assert paths, "no paths extracted from MODULES.md (parser may be broken)"

    missing = []
    for rel in paths:
        if rel in ALLOWED_MISSING:
            continue
        # Try as a path under ROOT
        p = ROOT / rel
        if not p.exists():
            missing.append(rel)

    assert not missing, (
        f"MODULES.md references paths that do not exist on disk: {missing}. "
        f"An agent navigating by MODULES.md will hit dead ends. Fix the paths "
        f"or remove the references."
    )


def test_packages_layout_has_core_modules() -> None:
    """WB-C: the packages/ monorepo must contain the 4 core module dirs."""
    required = ["workbench", "framework", "harvester", "learning_hub"]
    missing = [m for m in required if not (ROOT / "packages" / m).is_dir()]
    assert not missing, (
        f"packages/ is missing core module dirs: {missing}. "
        f"These replaced the stale submodule gitlinks."
    )
