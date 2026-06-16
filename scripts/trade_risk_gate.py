#!/usr/bin/env python3
"""Trade Risk Gate — enforce risk constraints on trade decisions.

This script validates trade decisions against risk policy rules.
First stage only allows APPROVED_FOR_RESEARCH.

Usage:
    python3 scripts/trade_risk_gate.py
    python3 scripts/trade_risk_gate.py --json

Output:
    Output/trade_decision/risk_gate.json
    Output/trade_decision/risk_gate.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRADE_DECISION_PATH = ROOT / "Output" / "trade_decision" / "latest.json"
POLICY_PATH = ROOT / "governance" / "risk_policy.yaml"
OUTPUT_DIR = ROOT / "Output" / "trade_decision"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def check_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Check trade decision against risk policy."""
    issues = []
    risk_level = "LOW"

    # Check decision level
    decision_type = decision.get("decision", "NO_TRADE")
    confidence = decision.get("confidence", "low")
    evidence_grade = decision.get("evidence_grade", "D")

    # Rule 1: Live execution not allowed
    # (This is always blocked in first stage)
    issues.append({
        "rule": "allow_live_execution",
        "status": "BLOCKED",
        "message": "Live execution not allowed in first stage",
    })

    # Rule 2: Paper sources required for active decisions
    if decision_type in ("RISK_REDUCE", "HEDGE", "TACTICAL_LONG", "TACTICAL_SHORT"):
        paper_sources = decision.get("paper_sources", [])
        if not paper_sources:
            issues.append({
                "rule": "require_paper_sources",
                "status": "FAIL",
                "message": "Active decision requires paper sources",
            })
            risk_level = "HIGH"

        # Check if any paper source is approved
        approved_sources = [s for s in paper_sources if s.get("review_status") == "approved"]
        if not approved_sources:
            issues.append({
                "rule": "paper_review_status",
                "status": "WARNING",
                "message": "No approved paper sources - using needs_review sources",
            })

    # Rule 3: System sources required
    system_sources = decision.get("system_sources", [])
    if not system_sources:
        issues.append({
            "rule": "require_system_sources",
            "status": "FAIL",
            "message": "System sources required",
        })
        risk_level = "HIGH"

    # Rule 4: Invalidation conditions required
    invalidation = decision.get("invalidation", [])
    if not invalidation:
        issues.append({
            "rule": "require_invalidation",
            "status": "FAIL",
            "message": "Invalidation conditions required",
        })
        risk_level = "HIGH"

    # Rule 5: Asset scope required
    asset_scope = decision.get("asset_scope", [])
    if not asset_scope:
        issues.append({
            "rule": "require_asset_scope",
            "status": "FAIL",
            "message": "Asset scope required",
        })
        risk_level = "HIGH"

    # Rule 6: Time horizon required
    time_horizon = decision.get("time_horizon")
    if not time_horizon:
        issues.append({
            "rule": "require_time_horizon",
            "status": "FAIL",
            "message": "Time horizon required",
        })
        risk_level = "HIGH"

    # Rule 7: Max decision without calibration
    if decision_type in ("TACTICAL_LONG", "TACTICAL_SHORT"):
        if evidence_grade in ("C", "D"):
            issues.append({
                "rule": "max_decision_without_calibration",
                "status": "FAIL",
                "message": f"TACTICAL decision requires evidence grade A/B, got {evidence_grade}",
            })
            risk_level = "HIGH"

    # Rule 8: Confidence requirements
    if decision_type in ("RISK_REDUCE", "HEDGE") and confidence == "low":
        issues.append({
            "rule": "min_confidence",
            "status": "WARNING",
            "message": "Low confidence for active decision",
        })

    # Determine overall status
    failed_rules = [i for i in issues if i["status"] == "FAIL"]
    if failed_rules:
        status = "BLOCKED"
    elif risk_level == "HIGH":
        status = "BLOCKED"
    else:
        status = "APPROVED_FOR_RESEARCH"

    # First stage: only allow research
    if status == "APPROVED_FOR_RESEARCH":
        # Check if live execution is requested (it shouldn't be)
        status = "APPROVED_FOR_RESEARCH"

    return {
        "status": status,
        "risk_level": risk_level,
        "issues": issues,
        "failed_rules": [i["rule"] for i in failed_rules],
        "warnings": [i for i in issues if i["status"] == "WARNING"],
    }


def build_risk_gate_report(decision: dict[str, Any], risk_check: dict[str, Any]) -> dict[str, Any]:
    """Build complete risk gate report."""
    return {
        "schema_version": "trade_risk_gate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "date": decision.get("date", datetime.now(UTC).strftime("%Y-%m-%d")),
        "decision_type": decision.get("decision", "NO_TRADE"),
        "decision_confidence": decision.get("confidence", "low"),
        "decision_evidence_grade": decision.get("evidence_grade", "D"),
        "risk_check": risk_check,
        "allowed_actions": {
            "live_execution": False,
            "paper_trading": risk_check["status"] == "APPROVED_FOR_RESEARCH",
            "research_only": True,
        },
        "notes": [
            "First stage: only research judgments allowed",
            "Paper trading requires APPROVED_FOR_RESEARCH status",
            "Live execution blocked until calibration and backtesting complete",
        ],
    }


def format_markdown(report: dict[str, Any]) -> str:
    """Format risk gate report as markdown."""
    risk_check = report["risk_check"]

    lines = [
        f"# Trade Risk Gate — {report['date']}",
        "",
        f"**Generated:** {report['generated_at']}",
        "",
        "---",
        "",
        "## Decision Under Review",
        "",
        f"- **Type:** {report['decision_type']}",
        f"- **Confidence:** {report['decision_confidence']}",
        f"- **Evidence Grade:** {report['decision_evidence_grade']}",
        "",
        "## Risk Check",
        "",
        f"- **Status:** {risk_check['status']}",
        f"- **Risk Level:** {risk_check['risk_level']}",
        "",
        "## Issues",
        "",
    ]

    if risk_check["issues"]:
        for issue in risk_check["issues"]:
            icon = "❌" if issue["status"] == "FAIL" else "⚠️" if issue["status"] == "WARNING" else "ℹ️"
            lines.append(f"- {icon} [{issue['rule']}] {issue['message']}")
    else:
        lines.append("- No issues found")

    lines += [
        "",
        "## Allowed Actions",
        "",
        f"- **Live Execution:** {'✅' if report['allowed_actions']['live_execution'] else '❌'}",
        f"- **Paper Trading:** {'✅' if report['allowed_actions']['paper_trading'] else '❌'}",
        f"- **Research Only:** {'✅' if report['allowed_actions']['research_only'] else '❌'}",
        "",
        "## Notes",
        "",
    ]

    for note in report["notes"]:
        lines.append(f"- {note}")

    lines += [
        "",
        "---",
        "",
        "*This gate enforces risk constraints. First stage only allows research judgments.*",
    ]

    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    """Write risk gate outputs."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "risk_gate.json"
    md_path = OUTPUT_DIR / "risk_gate.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run trade risk gate.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    # Load trade decision
    decision = load_json(TRADE_DECISION_PATH)
    if not decision:
        print("No trade decision found. Run trade_decision_layer.py first.")
        return

    # Run risk check
    risk_check = check_decision(decision)

    # Build report
    report = build_risk_gate_report(decision, risk_check)

    # Write outputs
    paths = write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Risk gate: {paths['markdown']}")
        print(f"Status: {risk_check['status']}")
        print(f"Risk Level: {risk_check['risk_level']}")
        print(f"Failed Rules: {len(risk_check['failed_rules'])}")
        print(f"Warnings: {len(risk_check['warnings'])}")


if __name__ == "__main__":
    main()
