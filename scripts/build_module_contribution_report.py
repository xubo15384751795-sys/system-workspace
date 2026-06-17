#!/usr/bin/env python3
"""Build Module Contribution Report — long-term module effectiveness.

Reads Output/evaluations/eval_log.jsonl and aggregates evaluation outcomes
by contributing module (Workbench, ML Signals, CaseLab Context, etc.).
Answers: which modules consistently contribute to correct judgments,
and which have low or no contribution.

Usage:
    python3 scripts/build_module_contribution_report.py
    python3 scripts/build_module_contribution_report.py --json

Output:
    Output/calibration_summary/module_contribution.json
    Output/calibration_summary/module_contribution.md
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_LOG_PATH = ROOT / "Output" / "evaluations" / "eval_log.jsonl"
OUTPUT_DIR = ROOT / "Output" / "calibration_summary"


def load_eval_log() -> list[dict[str, Any]]:
    """Load all evaluation log entries."""
    if not EVAL_LOG_PATH.exists():
        return []
    entries = []
    with EVAL_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _empty_module_stats() -> dict[str, Any]:
    return {
        "total": 0,
        "correct": 0,
        "incorrect": 0,
        "neutral": 0,
        "unverifiable": 0,
        "spy_returns": [],
        "windows": defaultdict(int),
        "decisions": defaultdict(int),
    }


def _finalize_module(name: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Compute derived metrics for a module."""
    total = stats["total"]
    correct = stats["correct"]
    incorrect = stats["incorrect"]
    neutral = stats["neutral"]
    verifiable = correct + incorrect + neutral

    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    # Effectiveness score: hit_rate weighted by volume
    hit_rate = round(correct / verifiable, 4) if verifiable > 0 else None

    # Grade: A/B/C/D based on hit_rate and volume
    grade = "N/A"
    if hit_rate is not None and total >= 3:
        if hit_rate >= 0.7:
            grade = "A"
        elif hit_rate >= 0.5:
            grade = "B"
        elif hit_rate >= 0.3:
            grade = "C"
        else:
            grade = "D"
    elif total > 0:
        grade = "insufficient_data"

    return {
        "module": name,
        "total_contributions": total,
        "correct": correct,
        "incorrect": incorrect,
        "neutral": neutral,
        "unverifiable": stats["unverifiable"],
        "hit_rate": hit_rate,
        "avg_spy_return_pct": _avg(stats["spy_returns"]),
        "grade": grade,
        "by_window": dict(stats["windows"]),
        "by_decision": dict(stats["decisions"]),
    }


def aggregate_by_module(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate evaluation outcomes by contributing module."""
    modules: dict[str, dict] = defaultdict(_empty_module_stats)

    for entry in entries:
        contributing = entry.get("contributing_modules", [])
        outcome = entry.get("outcome", "unverifiable")
        returns = entry.get("returns", {})
        window = entry.get("window", "unknown")
        decision = entry.get("decision", "UNKNOWN")
        spy_return = returns.get("SPY")

        # Each contributing module gets credit/blame for this evaluation
        for module in contributing:
            mod = modules[module]
            mod["total"] += 1
            mod[outcome] = mod.get(outcome, 0) + 1
            if spy_return is not None:
                mod["spy_returns"].append(spy_return)
            mod["windows"][window] += 1
            mod["decisions"][decision] += 1

    # Finalize and sort by total contributions descending
    result = [_finalize_module(name, stats) for name, stats in modules.items()]
    result.sort(key=lambda m: m["total_contributions"], reverse=True)
    return result


def build_report(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the full module contribution report."""
    now = datetime.now(UTC)
    modules = aggregate_by_module(entries)

    # Compute system-wide stats for comparison
    total_evaluations = len(entries)
    all_outcomes = defaultdict(int)
    for e in entries:
        all_outcomes[e.get("outcome", "unverifiable")] += 1

    return {
        "schema_version": "module_contribution.v1",
        "generated_at": now.isoformat(),
        "total_evaluations": total_evaluations,
        "system_outcomes": dict(all_outcomes),
        "modules": modules,
    }


def format_markdown(report: dict[str, Any]) -> str:
    """Format module contribution report as markdown."""
    lines = [
        "# Module Contribution Effectiveness",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Total evaluations:** {report['total_evaluations']}",
        "",
        "## Module Rankings",
        "",
        "| Module | Contributions | Hit Rate | Correct | Incorrect | Grade |",
        "|--------|---------------|----------|---------|-----------|-------|",
    ]

    for mod in report["modules"]:
        lines.append(
            f"| {mod['module']} "
            f"| {mod['total_contributions']} "
            f"| {mod['hit_rate'] or 'N/A'} "
            f"| {mod['correct']} "
            f"| {mod['incorrect']} "
            f"| {mod['grade']} |"
        )

    lines += [""]

    # Detailed per-module breakdown
    lines += ["## Detailed Breakdown", ""]
    for mod in report["modules"]:
        lines.append(f"### {mod['module']} (Grade: {mod['grade']})")
        lines.append("")
        lines.append(f"- **Total contributions:** {mod['total_contributions']}")
        lines.append(f"- **Hit rate:** {mod['hit_rate']}")
        lines.append(f"- **Avg SPY return:** {mod['avg_spy_return_pct']}%")

        if mod["by_window"]:
            lines.append("- **By window:**")
            for window, count in sorted(mod["by_window"].items()):
                lines.append(f"  - {window}: {count}")

        if mod["by_decision"]:
            lines.append("- **By decision:**")
            for decision, count in sorted(mod["by_decision"].items()):
                lines.append(f"  - {decision}: {count}")

        lines.append("")

    # Interpretation
    lines += [
        "## Interpretation",
        "",
        "- **Grade A** (hit_rate ≥ 0.7): module consistently contributes to correct outcomes",
        "- **Grade B** (hit_rate ≥ 0.5): module has positive contribution",
        "- **Grade C** (hit_rate ≥ 0.3): module contribution is marginal",
        "- **Grade D** (hit_rate < 0.3): module may be introducing noise",
        "- **insufficient_data**: fewer than 3 evaluations — not yet reliable",
        "",
        "*This report does NOT modify current judgments. It informs long-term governance decisions.*",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    """Write module contribution report."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "module_contribution.json"
    md_path = OUTPUT_DIR / "module_contribution.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build module contribution effectiveness report.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    entries = load_eval_log()
    report = build_report(entries)
    paths = write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Module contribution report: {paths['markdown']}")
        print(f"Total evaluations: {report['total_evaluations']}")
        print(f"Modules tracked: {len(report['modules'])}")
        for mod in report["modules"]:
            print(f"  {mod['module']}: {mod['grade']} ({mod['total_contributions']} contributions)")


if __name__ == "__main__":
    main()
