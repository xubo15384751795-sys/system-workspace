from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.report_gate import ReportGateError, validate_report_verdict


def test_fake_report_without_verdict_is_rejected(tmp_path) -> None:
    report = tmp_path / "fake_report.md"
    report.write_text(
        """
# Audit Report
## Findings
- Warning detected.
- Risk is high.
""",
        encoding="utf-8",
    )

    with pytest.raises(ReportGateError):
        validate_report_verdict(report)


def test_fake_report_with_placeholder_verdict_fields_is_rejected(tmp_path) -> None:
    report = tmp_path / "fake_report.md"
    report.write_text(
        """
# Audit Report

## Actionable Verdict
- Verdict: ACTION_REQUIRED
- Severity: HIGH
- Owner: TBD
- Required Action: TODO
""",
        encoding="utf-8",
    )

    with pytest.raises(ReportGateError, match="placeholder"):
        validate_report_verdict(report)


def test_high_severity_display_only_report_is_rejected(tmp_path) -> None:
    report = tmp_path / "fake_report.md"
    report.write_text(
        """
# Audit Report

## Actionable Verdict
- Verdict: DISPLAY_ONLY
- Severity: HIGH
- Owner: governance
- Required Action: Review the blocker before promotion.
""",
        encoding="utf-8",
    )

    with pytest.raises(ReportGateError, match="DISPLAY_ONLY"):
        validate_report_verdict(report)
