#!/usr/bin/env python3
"""Build NEXT_ACTIONS.md — agent-readable next steps.

Reads judgment card, promotion gate, and system index to generate
a file that tells any agent exactly what to do next.

Usage:
    python3 scripts/commands/weekly/build_next_actions.py
    python3 scripts/commands/weekly/build_next_actions.py --json

Output:
    Output/current/NEXT_ACTIONS.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._runtime_io import ROOT, current_dir, ensure_dir
from scripts.build_current_status import gather_status

OUTPUT_DIR = current_dir()
IMPROVEMENT_LEDGER = ROOT / "Data" / "system_learning" / "ledgers" / "improvement_queue.parquet"
ACTIVE_IMPROVEMENT_STATES = frozenset({"proposed", "approved", "open", "in_progress"})


def _write_text_file(path: Path, content: str) -> None:
    if path.is_symlink():
        path.unlink()
    path.write_text(content, encoding="utf-8")


def _load_open_improvements() -> pd.DataFrame:
    if not IMPROVEMENT_LEDGER.is_file():
        return pd.DataFrame()
    frame = pd.read_parquet(IMPROVEMENT_LEDGER)
    if frame.empty or "lifecycle_state" not in frame.columns:
        return frame
    return frame[frame["lifecycle_state"].astype(str).isin(ACTIVE_IMPROVEMENT_STATES)]


def determine_next_actions(status: dict[str, Any]) -> list[dict[str, str]]:
    """Determine next actions based on current status."""
    actions = []

    # Check promotion gate blockers
    blocked = status["promotion_gate"].get("blocked_gates", [])

    if "confidence" in blocked:
        actions.append({
            "priority": "HIGH",
            "action": "Improve measurement quality",
            "reason": "Confidence is low due to proxy-reduced channels",
            "command": "Check framework_output.json quality_status",
            "module": "packages/framework",
        })

    if "caselab" in blocked:
        actions.append({
            "priority": "MEDIUM",
            "action": "Wait for better historical analogy",
            "reason": f"CaseLab top score too low ({status['signals']['caselab'].get('top_score', 'N/A')})",
            "command": "No action needed — CaseLab will improve as more cases are added",
            "module": "packages/workbench/src/nlp/caselab/",
        })

    if "hmm" in blocked:
        actions.append({
            "priority": "MEDIUM",
            "action": "Improve HMM stability",
            "reason": f"HMM stability: {status['signals']['hmm'].get('stability_grade', 'N/A')}",
            "command": "Run more HMM fits to build history for rolling refit",
            "module": "packages/workbench/src/ml/",
        })

    if "k_gate" in blocked:
        actions.append({
            "priority": "LOW",
            "action": "Improve K measurement gate",
            "reason": f"K gate: {status['signals']['k_gate'].get('verdict', 'N/A')}",
            "command": "Review K component coverage and rolling stability",
            "module": "packages/workbench/src/workbench/signals/",
        })

    if "x_gate" in blocked:
        actions.append({
            "priority": "LOW",
            "action": "Improve X measurement gate",
            "reason": f"X gate: {status['signals']['x_gate'].get('verdict', 'N/A')}",
            "command": "Review X_agg frequency split and VIX correlation",
            "module": "packages/workbench/src/workbench/signals/",
        })

    # Learning Hub improvement queue — read parquet ledger (not stale markdown)
    open_items = _load_open_improvements()
    if not open_items.empty:
        top = open_items.iloc[0]
        subsystem = top.get("subsystem", "unknown")
        issue = top.get("issue_family", "improvement")
        actions.append({
            "priority": "MEDIUM",
            "action": "Review Learning Hub improvement queue",
            "reason": (
                f"{len(open_items)} open item(s); top: {subsystem} — {issue}"
            ),
            "command": "python3 scripts/refresh_improvement_queue_report.py",
            "module": "packages/learning_hub",
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

    if gate.get("watch_gates"):
        lines += ["", "## Watch Gates", ""]
        for g in gate["watch_gates"]:
            lines.append(f"- {g}")

    if gate.get("blocking_reasons") or gate.get("watch_reasons"):
        lines += ["", "## Promotion Reasons", ""]
        for item in gate.get("blocking_reasons", []):
            if isinstance(item, dict):
                lines.append(f"- BLOCKED `{item.get('id')}`: {item.get('reason')}")
            else:
                lines.append(f"- BLOCKED: {item}")
        for item in gate.get("watch_reasons", []):
            if isinstance(item, dict):
                lines.append(f"- WATCH `{item.get('id')}`: {item.get('reason')}")
            else:
                lines.append(f"- WATCH: {item}")

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
        "PYTHONPATH=packages/learning_hub/src python3 -m system_learning governance-audit",
        "```",
        "",
        "---",
        "",
        "*This file is auto-generated. It tells any agent what to do next.*",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build NEXT_ACTIONS.md.")
    parser.add_argument("--json", action="store_true", help="Print status JSON to stdout.")
    args = parser.parse_args()

    status = gather_status()
    actions = determine_next_actions(status)

    ensure_dir(OUTPUT_DIR)

    # Write NEXT_ACTIONS.md
    next_actions_md = build_next_actions_md(status, actions)
    next_actions_path = OUTPUT_DIR / "NEXT_ACTIONS.md"
    _write_text_file(next_actions_path, next_actions_md)

    if args.json:
        print(json.dumps({"status": status, "actions": actions}, indent=2, ensure_ascii=False))
    else:
        print(f"Next actions: {next_actions_path}")
        print("\nCurrent state:")
        print(f"  Decision: {status['judgment'].get('decision')}")
        print(f"  Confidence: {status['judgment'].get('confidence')}")
        print(f"  Promotion gate: {status['promotion_gate'].get('status')}")
        print("\nTop actions:")
        for a in actions[:3]:
            print(f"  [{a['priority']}] {a['action']}")


if __name__ == "__main__":
    main()
