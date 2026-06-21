#!/usr/bin/env python3
"""Export mechanism calibration suggestions to Paper review inbox.

Only writes drafts when mechanism_calibration_gate allows paper export
(achieved_level >= paper_draft).

Usage:
    python3 scripts/suggest_paper_updates.py
    python3 scripts/suggest_paper_updates.py --dry-run
    python3 scripts/suggest_paper_updates.py --json

Output:
    Paper/40_Review/_inbox/mechanism-weight-suggestion-YYYY-MM-DD.md
    Output/caselab_runtime/paper_suggestion_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from _workspace_imports import add_root, add_scripts
add_root()
add_scripts()

from caselab_context.paper_paths import paper_root  # noqa: E402

from _runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json  # noqa: E402

GATE_PATH = ROOT / "Output" / "caselab" / "causal" / "mechanism_calibration_gate.json"
WEIGHTS_PATH = ROOT / "Data" / "nlp" / "caselab_calibration" / "weight_adjustments.json"
CALIBRATION_PATH = ROOT / "Data" / "nlp" / "caselab_calibration" / "calibration_report.json"
REPORT_PATH = ROOT / "Output" / "caselab_runtime" / "paper_suggestion_report.json"


def _render_suggestion_draft(
    date_str: str,
    gate: dict,
    recommendations: list[dict],
    calibration: dict | None,
) -> str:
    holdout = gate.get("holdout_metrics") or {}
    lines = [
        "---",
        "type: weight_suggestion",
        f"review_status: needs_review",
        f"exported_at: {datetime.now(UTC).isoformat()}",
        "source: system/mechanism_calibration",
        f"gate_level: {gate.get('achieved_level', 'none')}",
        "tags:",
        "  - feedback-inbox",
        "  - mechanism-calibration",
        "---",
        "",
        f"# Mechanism Weight Suggestions — {date_str}",
        "",
        "## Gate status",
        "",
        f"- Achieved level: `{gate.get('achieved_level')}`",
        f"- Hold-out direction accuracy: {holdout.get('direction_accuracy')}",
        f"- Hold-out MAE: {holdout.get('mean_absolute_error')}",
        "",
        "## Recommendations",
        "",
    ]
    for rec in recommendations:
        lines.append(f"### {rec.get('type', 'item')}")
        lines.append("")
        lines.append(rec.get("description", ""))
        if rec.get("scale_factor") is not None:
            lines.append(f"- scale_factor: {rec['scale_factor']}")
        if rec.get("dimension"):
            lines.append(f"- dimension: {rec['dimension']}")
        lines.append("")

    if calibration:
        split = calibration.get("split", {}).get("holdout", {})
        lines.extend([
            "## Hold-out episodes",
            "",
            ", ".join(split.get("episode_ids", []) or ["none"]),
            "",
            "## Review instructions",
            "",
            "1. Verify recommendations against Paper mechanisms.",
            "2. Set `review_status: approved` to allow promote_paper_inbox.",
            "3. Optionally set `target_path: 03_Mechanisms/<file>.md` for merge.",
            "",
        ])
    return "\n".join(lines)


def suggest_paper_updates(
    paper_dir: Path | None = None,
    *,
    dry_run: bool = False,
) -> dict:
    paper_dir = paper_dir or paper_root()
    gate = load_json(GATE_PATH) or {}
    recommendations = load_json(WEIGHTS_PATH) or []
    if isinstance(recommendations, dict):
        recommendations = recommendations.get("recommendations", [])
    calibration = load_json(CALIBRATION_PATH)

    allow_export = bool(gate.get("allow_paper_export"))
    achieved = gate.get("achieved_level", "none")
    min_level = "paper_draft"

    report: dict = {
        "exported_at": utc_now().isoformat(),
        "gate_level": achieved,
        "allow_paper_export": allow_export,
        "exported": False,
        "reason": "",
    }

    if not allow_export:
        report["reason"] = (
            f"Gate level '{achieved}' does not allow Paper export "
            f"(requires {min_level} per governance/mechanism_calibration_gate.yaml)"
        )
        if not dry_run:
            write_json(REPORT_PATH, report)
        return report

    if not recommendations:
        report["reason"] = "No weight adjustments available"
        if not dry_run:
            write_json(REPORT_PATH, report)
        return report

    date_str = utc_now().strftime("%Y-%m-%d")
    inbox = paper_dir / "40_Review" / "_inbox"
    target = inbox / f"mechanism-weight-suggestion-{date_str}.md"
    content = _render_suggestion_draft(date_str, gate, recommendations, calibration)

    if not dry_run:
        ensure_dir(inbox)
        target.write_text(content, encoding="utf-8")
        write_json(REPORT_PATH, report)

    report.update({
        "exported": True,
        "path": str(target),
        "recommendation_count": len(recommendations),
        "dry_run": dry_run,
    })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Export mechanism weight suggestions to Paper inbox.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paper_dir = paper_root()
    if not paper_dir.exists() and not args.dry_run:
        print(f"Paper directory not found: {paper_dir}")
        sys.exit(1)

    report = suggest_paper_updates(paper_dir, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    if report.get("exported"):
        print(f"Exported suggestion draft: {report.get('path')}")
    else:
        print(f"No export: {report.get('reason')}")


if __name__ == "__main__":
    main()
