"""WB-G3 + WB-G4: Home-page consistency and freshness self-check guardrails.

These tests are the regression-prevention mechanism for the WB-A bug fixes:

  WB-G3 (home-page consistency): parse 00_READ_ME_FIRST.md and assert
    - single decision dialect (Trade Decision == Position Decision)
    - blocker vs evidence grade has no contradiction (no `evidence_grade_d`
      blocker when the on-screen grade is B, etc.)
    - no v1 position_intent field residue (hold_flat schema, 0% hardcode)
    - Freshness FAIL names the failing item (never a bare "FAIL")

  WB-G4 (freshness self-check): every artifact path the freshness_validator
    monitors must resolve under the configured ROOT - the monitor itself must
    not point at non-existent paths (the "checker checks wrong paths" failure).

Constitution reference: PRODUCT_FRAMEWORK_BOUNDARY "basic layer must not
require framework concepts" and the WB-A fix discipline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"


def _readme_path() -> Path:
    return CURRENT / "00_READ_ME_FIRST.md"


@pytest.fixture()
def readme_text() -> str:
    p = _readme_path()
    if not p.exists():
        pytest.skip("00_READ_ME_FIRST.md not found")
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# WB-G3: Home-page consistency (regression guard for WB-A1 / WB-A2)
# ---------------------------------------------------------------------------

def _extract_field(text: str, label: str, section: str | None = None) -> str | None:
    """Extract a bold-labeled field value, optionally within a section."""
    haystack = text.split(f"## {section}")[1] if section else text
    m = re.search(rf"\*\*{re.escape(label)}:\*\*\s*(\S+)", haystack)
    return m.group(1) if m else None


def test_single_decision_dialect(readme_text: str) -> None:
    """WB-A1: Trade Decision (System Status) must equal Position Decision.

    The home page must present ONE decision dialect. The old bug showed
    Trade Decision: RISK_ON alongside Position Decision: WATCH (hold_flat, 0%)
    because position translation read the stale v1 position_intent file.
    """
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
        f"Position Decision={pos_decision}. Position translation may be reading "
        f"the stale v1 position_intent file instead of trade_decision.v3."
    )


def test_no_v1_position_residue(readme_text: str) -> None:
    """WB-A1: no v1 position_intent schema markers on the home page."""
    v1_markers = ["position_intent.v1", "schema_version.*v1", "hold_flat"]
    for marker in v1_markers:
        assert not re.search(marker, readme_text, re.IGNORECASE), (
            f"v1 position residue found on home page: {marker!r}. "
            f"Position translation should derive from trade_decision.v3."
        )


def test_blocker_grade_no_contradiction(readme_text: str) -> None:
    """WB-A2: blockers must not contradict the on-screen evidence grade.

    The old bug: Blockers listed `evidence_grade_d` while Structural evidence
    grade showed B (the d-grade was stale from a 2026-06-18 v1 file).
    """
    grade = _extract_field(readme_text, "Structural evidence grade", "System Status")
    blockers_line = re.search(r"\*\*Blockers:\*\*\s*(.+)", readme_text)

    if not blockers_line or blockers_line.group(1).strip().lower() == "none":
        return  # no blockers -> no contradiction possible

    blockers = blockers_line.group(1)
    if grade:
        # If a blocker asserts a specific evidence grade, it must match the screen.
        blocker_grade_match = re.search(r"evidence_grade_([a-e])", blockers, re.IGNORECASE)
        if blocker_grade_match:
            blocker_grade = blocker_grade_match.group(1).upper()
            assert blocker_grade == grade.upper(), (
                f"Blocker-grade contradiction: blockers say evidence_grade_{blocker_grade} "
                f"but screen shows grade {grade}. Blockers are reading a stale source."
            )


def test_freshness_fail_names_item(readme_text: str) -> None:
    """WB-A3: Freshness FAIL must name the failing item, never a bare 'FAIL'."""
    m = re.search(r"\*\*Freshness:\*\*\s*(.+)", readme_text)
    assert m, "Freshness field missing from home page"
    freshness = m.group(1).strip()
    if freshness.startswith("FAIL"):
        assert "(" in freshness and ")" in freshness, (
            f"Freshness shows bare 'FAIL' without naming the failing item: {freshness!r}. "
            f"Must be 'FAIL (item_name)' so the operator knows what broke."
        )


# ---------------------------------------------------------------------------
# WB-G4: Freshness self-check (the monitor must not point at bad paths)
# ---------------------------------------------------------------------------

def test_freshness_monitored_paths_exist() -> None:
    """WB-A3/G4: every path the freshness_validator monitors must resolve.

    The monitor itself was reporting MISSING for files that existed because it
    checked wrong paths (e.g. learning_summary.json vs comprehensive_summary.json).
    This test imports the path table and asserts each resolves under ROOT.
    """
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from freshness_validator import CONTENT_FRESHNESS  # noqa: E402

    # Artifact mtime paths are built in build_freshness_report; reconstruct the
    # same path tuples the validator uses. We check the CONTENT_FRESHNESS table
    # (explicit paths) and the known artifact paths.
    missing = []
    for name, cfg in CONTENT_FRESHNESS.items():
        p = ROOT / cfg["path"]
        if not p.exists():
            missing.append(f"{name}: {cfg['path']}")

    # Spot-check the core artifact paths the validator monitors by name.
    artifact_paths = {
        "readme_first": CURRENT / "00_READ_ME_FIRST.md",
        "signal_card": CURRENT / "signal_card.json",
        "work_brief": CURRENT / "work_brief.json",
        "learning_summary": ROOT / "Output" / "system_learning" / "latest" / "comprehensive_summary.json",
        "system_index": ROOT / "Data" / "system_index" / "latest.json",
        "trade_decision": ROOT / "Output" / "trade_decision" / "latest.json",
    }
    for name, p in artifact_paths.items():
        if not p.exists():
            missing.append(f"{name}: {p.relative_to(ROOT)}")

    assert not missing, (
        "freshness_validator monitors paths that do not exist (monitor itself "
        f"is misconfigured): {missing}"
    )


def test_freshness_report_no_false_missing() -> None:
    """WB-A3: the generated freshness report must not list MISSING for files
    that actually exist on disk (the false-positive failure mode)."""
    report_path = ROOT / "Output" / "quality" / "freshness_report.json"
    if not report_path.exists():
        pytest.skip("freshness_report.json not found")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    missing = report.get("missing_artifacts", [])
    # Map artifact names to their expected disk paths.
    path_map = {
        "readme_first": CURRENT / "00_READ_ME_FIRST.md",
        "signal_card": CURRENT / "signal_card.json",
        "signal_consensus": CURRENT / "signal_consensus.json",
        "work_brief": CURRENT / "work_brief.json",
        "learning_summary": ROOT / "Output" / "system_learning" / "latest" / "comprehensive_summary.json",
    }
    false_missing = [name for name in missing if name in path_map and path_map[name].exists()]
    assert not false_missing, (
        f"freshness report lists MISSING for files that exist: {false_missing}. "
        f"The freshness_validator is checking wrong paths (regression of WB-A3)."
    )
