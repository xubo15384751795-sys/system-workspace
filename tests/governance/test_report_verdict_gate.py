from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.report


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.report_gate import ReportGateError, validate_report_verdict


def test_report_without_verdict_fails(tmp_path) -> None:
    report = tmp_path / "report.md"
    report.write_text(
        """
# Evaluation Report
Warnings:
- FAMILY_MONOCULTURE detected.
""",
        encoding="utf-8",
    )

    with pytest.raises(ReportGateError):
        validate_report_verdict(report)


def test_report_with_actionable_verdict_passes(tmp_path) -> None:
    report = tmp_path / "report.md"
    report.write_text(
        """
# Evaluation Report

## Actionable Verdict
- Verdict: ACTION_REQUIRED
- Severity: MEDIUM
- Owner: governance
- Required Action: Review proxy reduction.
""",
        encoding="utf-8",
    )

    assert validate_report_verdict(report)["verdict"] == "ACTION_REQUIRED"


def test_report_gate_reads_actionable_verdict_not_claim_verdict(tmp_path) -> None:
    report = tmp_path / "report.md"
    report.write_text(
        """
# Evaluation Report

## Claim
- Claim Verdict: INSUFFICIENT_DATA

## Actionable Verdict
- Verdict: BLOCK
- Severity: HIGH
- Owner: governance
- Required Action: Re-run validation loop before promotion.
""",
        encoding="utf-8",
    )

    assert validate_report_verdict(report)["verdict"] == "BLOCK"
