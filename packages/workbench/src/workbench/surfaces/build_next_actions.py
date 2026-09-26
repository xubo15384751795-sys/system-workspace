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
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from verity.runtime.runtime_io import ROOT, current_dir, ensure_dir, load_json
from workbench.surfaces.build_current_status import gather_status

logger = logging.getLogger(__name__)

OUTPUT_DIR = current_dir()
IMPROVEMENT_LEDGER = ROOT / "Data" / "system_learning" / "ledgers" / "improvement_queue.parquet"
ACTIVE_IMPROVEMENT_STATES = frozenset({"proposed", "approved", "open", "in_progress"})

_PATH_KEYS = ("output", "improvement_ledger")


def _default_paths() -> dict[str, Path]:
    """Return legacy-compatible input/output path bindings."""
    return {
        "output": OUTPUT_DIR,
        "improvement_ledger": IMPROVEMENT_LEDGER,
    }


def _resolve_paths(paths: Mapping[str, Path] | None = None) -> dict[str, Path]:
    """Resolve explicit generation paths without changing no-arg behavior."""
    resolved = _default_paths()
    if paths is None:
        return resolved
    unknown = sorted(set(paths) - set(_PATH_KEYS))
    if unknown:
        raise ValueError(f"unknown next-actions path keys: {', '.join(unknown)}")
    resolved.update({key: Path(value) for key, value in paths.items()})
    return resolved


def _write_text_file(path: Path, content: str) -> None:
    if path.is_symlink():
        path.unlink()
    path.write_text(content, encoding="utf-8")


def _load_open_improvements(ledger_path: Path | None = None) -> pd.DataFrame:
    ledger = ledger_path or IMPROVEMENT_LEDGER
    if not ledger.is_file():
        return pd.DataFrame()
    frame = pd.read_parquet(ledger)
    if frame.empty or "lifecycle_state" not in frame.columns:
        return frame
    return frame[frame["lifecycle_state"].astype(str).isin(ACTIVE_IMPROVEMENT_STATES)]


def _load_current_status(output_dir: Path | None = None) -> dict[str, Any]:
    """Read the status snapshot produced by the same pipeline run.

    ``status.json`` is the canonical hand-off from ``current_status`` to
    ``next_actions``.  Falling back to source aggregation keeps the standalone
    command useful before the first status snapshot exists, while the scheduled
    pipeline uses the explicit registry edge and therefore cannot silently read
    a different set of source files.
    """
    status = load_json((output_dir or OUTPUT_DIR) / "status.json")
    if isinstance(status, dict):
        return status
    return gather_status()


def determine_next_actions(
    status: dict[str, Any],
    *,
    improvement_ledger: Path | None = None,
) -> list[dict[str, str]]:
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
            "module": "packages/framework_v1_archive",
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
    open_items = _load_open_improvements(improvement_ledger)
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

    # Phase 2.2: external indicator health. Indicators failing >= 7 consecutive
    # days surface as HIGH-priority actions so a stale external feed (the
    # OFR/CISS 73-day-blind-spot failure mode) is visible within a week.
    try:
        from verity.runtime._external_indicator_health import failing_indicators

        for ind in failing_indicators():
            actions.append({
                "priority": "HIGH",
                "action": f"Restore external indicator: {ind['name']}",
                "reason": (
                    f"{ind['name']} failed {ind['consecutive_failures']} consecutive days; "
                    f"last success {ind.get('last_success') or 'never'}. "
                    f"Error: {ind.get('last_error', '')[:120]}"
                ),
                "command": f"Investigate {ind['name']} provider; check Data/harvester/raw/",
                "module": "packages/harvester",
            })
    except Exception:
        logger.warning("Unable to inspect improvement ledger for next actions", exc_info=True)

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


def build_next_actions(
    paths: Mapping[str, Path] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build next actions against legacy or explicit generation paths."""
    resolved = _resolve_paths(paths)
    status = _load_current_status(resolved["output"])
    actions = determine_next_actions(
        status,
        improvement_ledger=resolved["improvement_ledger"],
    )
    return status, actions


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


def write_next_actions(
    status: dict[str, Any],
    actions: list[dict[str, str]],
    *,
    output_path: Path | None = None,
) -> Path:
    """Write NEXT_ACTIONS.md to an explicit current-output surface."""
    target = output_path or (OUTPUT_DIR / "NEXT_ACTIONS.md")
    ensure_dir(target.parent)
    _write_text_file(target, build_next_actions_md(status, actions))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build NEXT_ACTIONS.md.")
    parser.add_argument("--json", action="store_true", help="Print status JSON to stdout.")
    args = parser.parse_args()

    status, actions = build_next_actions()
    next_actions_path = write_next_actions(status, actions)

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
