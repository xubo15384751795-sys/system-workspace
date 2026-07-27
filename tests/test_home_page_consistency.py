"""Home-page consistency (hermetic fixture surface).

Operator path-existence / live freshness-report checks live in
test_home_page_consistency_operator.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_README = ROOT / "tests" / "fixtures" / "current_chain" / "00_READ_ME_FIRST.md"


@pytest.fixture()
def readme_text() -> str:
    return FIXTURE_README.read_text(encoding="utf-8")


def _extract_field(text: str, label: str, section: str | None = None) -> str | None:
    haystack = text.split(f"## {section}")[1] if section else text
    m = re.search(rf"\*\*{re.escape(label)}:\*\*\s*(\S+)", haystack)
    return m.group(1) if m else None


def test_single_decision_dialect(readme_text: str) -> None:
    trade_decision = _extract_field(readme_text, "Trade Decision", "System Status")
    pos_section = readme_text.split("## Position Translation")
    pos_decision = None
    if len(pos_section) > 1:
        m = re.search(r"\*\*Decision:\*\*\s*(\S+)", pos_section[1])
        pos_decision = m.group(1) if m else None

    assert trade_decision is not None, "Trade Decision field missing from home page"
    assert pos_decision is not None, "Position Decision field missing from home page"
    assert trade_decision == pos_decision, (
        f"Decision dialect contradiction: Trade Decision={trade_decision} vs "
        f"Position Decision={pos_decision}."
    )


def test_no_v1_position_residue(readme_text: str) -> None:
    v1_markers = ["position_intent.v1", "hold_flat"]
    for marker in v1_markers:
        assert not re.search(marker, readme_text, re.IGNORECASE), (
            f"v1 position residue found on home page: {marker!r}."
        )


def test_blocker_grade_no_contradiction(readme_text: str) -> None:
    grade = _extract_field(readme_text, "Structural evidence grade", "System Status")
    blockers_line = re.search(r"\*\*Blockers:\*\*\s*(.+)", readme_text)

    if not blockers_line or blockers_line.group(1).strip().lower() == "none":
        return

    blockers = blockers_line.group(1)
    if grade:
        blocker_grade_match = re.search(r"evidence_grade_([a-e])", blockers, re.IGNORECASE)
        if blocker_grade_match:
            blocker_grade = blocker_grade_match.group(1).upper()
            assert blocker_grade == grade.upper(), (
                f"Blocker-grade contradiction: blockers say evidence_grade_{blocker_grade} "
                f"but screen shows grade {grade}."
            )


def test_freshness_fail_names_item(readme_text: str) -> None:
    m = re.search(r"\*\*Freshness:\*\*\s*(.+)", readme_text)
    assert m, "Freshness field missing from home page"
    freshness = m.group(1).strip()
    if freshness.startswith("FAIL"):
        assert "(" in freshness and ")" in freshness, (
            f"Freshness shows bare 'FAIL' without naming the failing item: {freshness!r}."
        )


def test_freshness_content_table_paths_are_relative() -> None:
    """Config shape check: CONTENT_FRESHNESS entries must be relative paths."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from freshness_validator import CONTENT_FRESHNESS

    for name, cfg in CONTENT_FRESHNESS.items():
        path = cfg["path"]
        assert not Path(path).is_absolute(), f"{name} path must be relative: {path}"
        assert ".." not in Path(path).parts, f"{name} path escapes root: {path}"
