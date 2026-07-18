#!/usr/bin/env python3
"""Operator Registry Audit — verify all operators are registered and compliant.

This script checks that:
1. All daily_run steps have registered operators
2. Each operator has required fields
3. No operator violates its constraints

Usage:
    python3 scripts/commands/weekly/operator_registry_audit.py
    python3 scripts/commands/weekly/operator_registry_audit.py --json

Output:
    Output/quality/operator_registry_audit.json
    Output/quality/operator_registry_audit.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT, ensure_dir, load_yaml, utc_now, write_json

REGISTRY_PATH = ROOT / "governance" / "operator_registry.yaml"
CONSTITUTION_PATH = ROOT / "governance" / "system_constitution.yaml"
DAILY_RUN_PATH = ROOT / "scripts" / "daily_run.py"
OUTPUT_DIR = ROOT / "Output" / "quality"


def extract_daily_run_steps() -> list[str]:
    """Extract step names from daily_run.py."""
    content = DAILY_RUN_PATH.read_text(encoding="utf-8")
    # Look for run_step calls
    matches = re.findall(r'run_step\("([^"]+)"', content)
    return list(set(matches))


def check_operator_completeness(registry: dict[str, Any], daily_steps: list[str]) -> list[dict[str, Any]]:
    """Check that all daily_run steps have registered operators."""
    issues = []
    registered = set(registry.get("operators", {}).keys())

    # Map daily_run step names to operator names
    step_to_operator = {
        "harvester": "harvester",
        "etf_refresh": None,  # Not an operator
        "paper_sync": "sync_paper_world_model",
        "horizon_events": "horizon_event_adapter",
        "structural_replay": "structural_replay",
        "bridge": None,  # Part of structural_replay
        "quality_validation": None,  # Part of freshness
        "regime_detection": "regime_detection",
        "hmm_stability_audit": "hmm_stability_audit",
        "k_measurement_gate": "k_measurement_gate",
        "x_measurement_gate": "x_measurement_gate",
        "caselab_signal": "caselab_daily_signal",
        "judgment_layer": "judgment_layer",
        "judgment_replay_audit": None,  # Part of calibration
        "judgment_promotion_gate": "judgment_promotion_gate",
        "probabilistic_context": "gluonts_probabilistic_context",
        "trade_decision": "trade_decision_layer",
        "risk_gate": "trade_risk_gate",
        "record_trade_decision": None,  # Part of trade_decision
        "market_feedback": "market_feedback",
        "learning_summary": "learning_hub_comprehensive_summary",
        "freshness_validator": "freshness_validator",
        "system_index": "build_system_index",
        "readme_first": "build_readme_first",
        "next_actions": "build_next_actions",
    }

    for step in daily_steps:
        operator = step_to_operator.get(step)
        if operator and operator not in registered:
            issues.append({
                "type": "missing_registration",
                "step": step,
                "operator": operator,
                "message": f"Step '{step}' maps to operator '{operator}' which is not registered",
            })

    return issues


def check_operator_fields(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Check that each operator has required fields."""
    issues = []
    required_fields = ["type", "description", "inputs", "outputs", "claim_ceiling"]

    for name, op in registry.get("operators", {}).items():
        for field in required_fields:
            if field not in op:
                issues.append({
                    "type": "missing_field",
                    "operator": name,
                    "field": field,
                    "message": f"Operator '{name}' missing required field '{field}'",
                })

    return issues


def check_role_compliance(registry: dict[str, Any], constitution: dict[str, Any]) -> list[dict[str, Any]]:
    """Check that operators comply with role constraints."""
    issues = []
    module_roles = constitution.get("module_roles", {})

    for name, op in registry.get("operators", {}).items():
        op_type = op.get("type", "")
        cannot_create = op.get("cannot_create", [])

        # Check if operator type matches constitution
        if op_type in ("measurement_operator", "measurement_gate"):
            role_def = module_roles.get("proxy", {})
            forbidden = role_def.get("forbidden_outputs", [])
            for f in forbidden:
                if f not in cannot_create:
                    issues.append({
                        "type": "role_violation",
                        "operator": name,
                        "message": f"Operator '{name}' should forbid '{f}' but doesn't",
                    })

        elif op_type == "state_recognition":
            role_def = module_roles.get("uncertainty", {})
            forbidden = role_def.get("forbidden_outputs", [])
            for f in forbidden:
                if f not in cannot_create:
                    issues.append({
                        "type": "role_violation",
                        "operator": name,
                        "message": f"Operator '{name}' should forbid '{f}' but doesn't",
                    })

    return issues


def build_audit_report(registry: dict[str, Any], constitution: dict[str, Any]) -> dict[str, Any]:
    """Build complete audit report."""
    daily_steps = extract_daily_run_steps()

    completeness_issues = check_operator_completeness(registry, daily_steps)
    field_issues = check_operator_fields(registry)
    role_issues = check_role_compliance(registry, constitution)

    all_issues = completeness_issues + field_issues + role_issues

    return {
        "schema_version": "operator_registry_audit.v1",
        "generated_at": utc_now().isoformat(),
        "total_operators": len(registry.get("operators", {})),
        "total_daily_steps": len(daily_steps),
        "issues": all_issues,
        "issue_counts": {
            "missing_registration": len(completeness_issues),
            "missing_field": len(field_issues),
            "role_violation": len(role_issues),
        },
        "status": "PASS" if not all_issues else "FAIL",
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Operator Registry Audit",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Status:** {report['status']}",
        f"**Total operators:** {report['total_operators']}",
        f"**Total daily steps:** {report['total_daily_steps']}",
        "",
        "---",
        "",
        "## Issues",
        "",
    ]

    if report["issues"]:
        for issue in report["issues"]:
            lines.append(f"- [{issue['type']}] {issue['message']}")
    else:
        lines.append("- No issues found")

    lines += [
        "",
        "## Issue Counts",
        "",
        f"- Missing registration: {report['issue_counts']['missing_registration']}",
        f"- Missing field: {report['issue_counts']['missing_field']}",
        f"- Role violation: {report['issue_counts']['role_violation']}",
    ]

    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    ensure_dir(OUTPUT_DIR)

    json_path = OUTPUT_DIR / "operator_registry_audit.json"
    md_path = OUTPUT_DIR / "operator_registry_audit.md"

    write_json(json_path, report)
    md_path.write_text(format_markdown(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit operator registry.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    registry = load_yaml(REGISTRY_PATH)
    constitution = load_yaml(CONSTITUTION_PATH)

    if not registry:
        print(f"Operator registry not found: {REGISTRY_PATH}")
        return

    if not constitution:
        print(f"System constitution not found: {CONSTITUTION_PATH}")
        return

    report = build_audit_report(registry, constitution)
    write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Operator registry audit: {report['status']}")
        print(f"Total operators: {report['total_operators']}")
        print(f"Issues: {len(report['issues'])}")
        for issue in report["issues"]:
            print(f"  - [{issue['type']}] {issue['message']}")


if __name__ == "__main__":
    main()
