#!/usr/bin/env python3
"""Build NEXT_ACTIONS.md — agent-readable next steps.

Reads judgment card, promotion gate, and system index to generate
a file that tells any agent exactly what to do next.

Usage:
    python3 scripts/build_next_actions.py
    python3 scripts/build_next_actions.py --json

Output:
    Output/current/NEXT_ACTIONS.md
    Output/current/status.json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from _runtime_io import load_json

ROOT = Path(__file__).resolve().parents[1]
JUDGMENT_PATH = ROOT / "Output" / "judgment" / "latest.json"
PROMOTION_GATE_PATH = ROOT / "Output" / "judgment" / "promotion_gate.json"
INDEX_PATH = ROOT / "Data" / "system_index" / "latest.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
HMM_AUDIT_PATH = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
OUTPUT_DIR = ROOT / "Output" / "current"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def gather_status() -> dict[str, Any]:
    """Gather current system status."""
    now = datetime.now(UTC).isoformat()
    date_str = now[:10]

    judgment = load_json(JUDGMENT_PATH)
    promotion_gate = load_json(PROMOTION_GATE_PATH)
    index = load_json(INDEX_PATH)
    k_gate = load_json(K_GATE_PATH)
    x_gate = load_json(X_GATE_PATH)
    hmm_audit = load_json(HMM_AUDIT_PATH)
    caselab = load_json(CASELAB_DIR / f"{date_str}.json")

    return {
        "generated_at": now,
        "date": date_str,
        "judgment": {
            "decision": (judgment or {}).get("decision"),
            "confidence": ((judgment or {}).get("confidence") or {}).get("level"),
            "claim_ceiling": (judgment or {}).get("claim_ceiling"),
        },
        "promotion_gate": {
            "status": (promotion_gate or {}).get("overall_status"),
            "blocked_gates": (promotion_gate or {}).get("blocked_gates", []),
            "blocking_reasons": (promotion_gate or {}).get("blocking_reasons", []),
            "forbidden_language": (promotion_gate or {}).get("forbidden_language", []),
            "allowed_language": (promotion_gate or {}).get("allowed_language", []),
            "claim_ceiling": (promotion_gate or {}).get("claim_ceiling"),
        },
        "signals": {
            "k_gate": {
                "verdict": (k_gate or {}).get("gate_verdict"),
                "current_role": "diagnostic_rebuild",
            },
            "x_gate": {
                "verdict": (x_gate or {}).get("gate_verdict"),
                "background_allowed": (x_gate or {}).get("usage", {}).get("usable_as_background", False),
                "daily_trigger_allowed": False,
            },
            "hmm": {
                "stability_grade": (hmm_audit or {}).get("stability_grade"),
                "sample_days": (hmm_audit or {}).get("sample_days"),
            },
            "caselab": {
                "top_score": ((caselab or {}).get("match_quality") or {}).get("top_score"),
                "label": ((caselab or {}).get("match_quality") or {}).get("label"),
            },
        },
    }


def determine_next_actions(status: dict[str, Any]) -> list[dict[str, str]]:
    """Determine next actions based on current status."""
    actions = []

    # Check promotion gate blockers
    blocked = status["promotion_gate"].get("blocked_gates", [])
    reasons = status["promotion_gate"].get("blocking_reasons", [])

    if "confidence" in blocked:
        actions.append({
            "priority": "HIGH",
            "action": "Improve measurement quality",
            "reason": "Confidence is low due to proxy-reduced channels",
            "command": "Check framework_output.json quality_status",
            "module": "Structural Deformation Research System",
        })

    if "caselab" in blocked:
        actions.append({
            "priority": "MEDIUM",
            "action": "Wait for better historical analogy",
            "reason": f"CaseLab top score too low ({status['signals']['caselab'].get('top_score', 'N/A')})",
            "command": "No action needed — CaseLab will improve as more cases are added",
            "module": "Workbench/src/nlp/caselab/",
        })

    if "hmm" in blocked:
        actions.append({
            "priority": "MEDIUM",
            "action": "Improve HMM stability",
            "reason": f"HMM stability: {status['signals']['hmm'].get('stability_grade', 'N/A')}",
            "command": "Run more HMM fits to build history for rolling refit",
            "module": "Workbench/src/ml/",
        })

    if "k_gate" in blocked:
        actions.append({
            "priority": "LOW",
            "action": "Improve K measurement gate",
            "reason": f"K gate: {status['signals']['k_gate'].get('verdict', 'N/A')}",
            "command": "Review K component coverage and rolling stability",
            "module": "Workbench/src/workbench/signals/",
        })

    if "x_gate" in blocked:
        actions.append({
            "priority": "LOW",
            "action": "Improve X measurement gate",
            "reason": f"X gate: {status['signals']['x_gate'].get('verdict', 'N/A')}",
            "command": "Review X_agg frequency split and VIX correlation",
            "module": "Workbench/src/workbench/signals/",
        })

    # If no blockers, suggest monitoring
    if not actions:
        actions.append({
            "priority": "LOW",
            "action": "Continue monitoring",
            "reason": "All gates passing",
            "command": "python3 scripts/daily_run.py",
            "module": "N/A",
        })

    return actions


def build_next_actions_md(status: dict[str, Any], actions: list[dict[str, str]]) -> str:
    """Build NEXT_ACTIONS.md content."""
    judgment = status["judgment"]
    gate = status["promotion_gate"]

    lines = [
        f"# Next Actions — {status['date']}",
        "",
        f"**Generated:** {status['generated_at']}",
        "",
        "---",
        "",
        "## Current State",
        "",
        f"- **Decision:** {judgment.get('decision', 'N/A')}",
        f"- **Confidence:** {judgment.get('confidence', 'N/A')}",
        f"- **Claim ceiling:** {judgment.get('claim_ceiling', 'N/A')}",
        f"- **Promotion gate:** {gate.get('status', 'N/A')}",
        "",
        "## Blocked By",
        "",
    ]

    if gate.get("blocked_gates"):
        for g in gate["blocked_gates"]:
            lines.append(f"- {g}")
    else:
        lines.append("- None")

    lines += [
        "",
        "## Forbidden Language",
        "",
    ]

    if gate.get("forbidden_language"):
        for term in gate["forbidden_language"]:
            lines.append(f"- ❌ {term}")
    else:
        lines.append("- None")

    lines += [
        "",
        "## Allowed Language",
        "",
    ]

    if gate.get("allowed_language"):
        for term in gate["allowed_language"]:
            lines.append(f"- ✅ {term}")

    lines += [
        "",
        "## Next Actions",
        "",
        "| Priority | Action | Reason | Command | Module |",
        "|---|---|---|---|---|",
    ]

    for a in actions:
        lines.append(f"| {a['priority']} | {a['action']} | {a['reason']} | `{a['command']}` | {a['module']} |")

    lines += [
        "",
        "## Quick Commands",
        "",
        "```bash",
        "# Refresh current state",
        "python3 scripts/refresh_output_current.py",
        "",
        "# Run daily pipeline",
        "python3 scripts/daily_run.py",
        "",
        "# Check system index",
        "python3 scripts/list_latest.py",
        "",
        "# Run governance audit",
        "PYTHONPATH=system-learning-hub/src python3 -m system_learning governance-audit",
        "```",
        "",
        "---",
        "",
        "*This file is auto-generated. It tells any agent what to do next.*",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build NEXT_ACTIONS.md and status.json.")
    parser.add_argument("--json", action="store_true", help="Print status JSON to stdout.")
    args = parser.parse_args()

    status = gather_status()
    actions = determine_next_actions(status)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Write status.json
    status_path = OUTPUT_DIR / "status.json"
    status_path.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Write NEXT_ACTIONS.md
    next_actions_md = build_next_actions_md(status, actions)
    next_actions_path = OUTPUT_DIR / "NEXT_ACTIONS.md"
    next_actions_path.write_text(next_actions_md, encoding="utf-8")

    if args.json:
        print(json.dumps({"status": status, "actions": actions}, indent=2, ensure_ascii=False))
    else:
        print(f"Status: {status_path}")
        print(f"Next actions: {next_actions_path}")
        print(f"\nCurrent state:")
        print(f"  Decision: {status['judgment'].get('decision')}")
        print(f"  Confidence: {status['judgment'].get('confidence')}")
        print(f"  Promotion gate: {status['promotion_gate'].get('status')}")
        print(f"\nTop actions:")
        for a in actions[:3]:
            print(f"  [{a['priority']}] {a['action']}")


if __name__ == "__main__":
    main()