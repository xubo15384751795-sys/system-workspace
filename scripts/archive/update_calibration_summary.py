#!/usr/bin/env python3
"""Update Calibration Summary — aggregate evaluation results.

Reads Output/evaluations/eval_log.jsonl and aggregates by source and
decision type: correct/incorrect/neutral counts, average SPY returns,
and hit rates. Outputs to Output/calibration_summary/.

This script does NOT modify current judgments — it only produces a
summary report for the Learning Hub.

Usage:
    python3 scripts/update_calibration_summary.py
    python3 scripts/update_calibration_summary.py --json

Output:
    Output/calibration_summary/latest.json
    Output/calibration_summary/latest.md
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "Output" / "evaluations"
EVAL_LOG_PATH = EVAL_DIR / "eval_log.jsonl"
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


def _empty_bucket() -> dict[str, Any]:
    return {
        "total": 0,
        "correct": 0,
        "incorrect": 0,
        "neutral": 0,
        "unverifiable": 0,
        "spy_returns": [],
        "hyg_returns": [],
        "tlt_returns": [],
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    """Compute derived metrics from raw counts."""
    total = bucket["total"]
    correct = bucket["correct"]
    verifiable = correct + bucket["incorrect"] + bucket["neutral"]

    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    return {
        "total": total,
        "correct": correct,
        "incorrect": bucket["incorrect"],
        "neutral": bucket["neutral"],
        "unverifiable": bucket["unverifiable"],
        "hit_rate": round(correct / verifiable, 4) if verifiable > 0 else None,
        "avg_spy_return_pct": _avg(bucket["spy_returns"]),
        "avg_hyg_return_pct": _avg(bucket["hyg_returns"]),
        "avg_tlt_return_pct": _avg(bucket["tlt_returns"]),
    }


def aggregate_by_source_and_decision(
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate eval log entries by source and decision type."""
    # source → decision → bucket
    by_source: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(_empty_bucket))
    # Also aggregate by window
    by_window: dict[str, dict] = defaultdict(_empty_bucket)
    # Overall
    overall = _empty_bucket()

    for entry in entries:
        source = entry.get("source", "unknown")
        decision = entry.get("decision", "UNKNOWN")
        window = entry.get("window", "unknown")
        outcome = entry.get("outcome", "unverifiable")
        returns = entry.get("returns", {})

        # Per-source-per-decision
        bucket = by_source[source][decision]
        bucket["total"] += 1
        bucket[outcome] = bucket.get(outcome, 0) + 1
        if returns.get("SPY") is not None:
            bucket["spy_returns"].append(returns["SPY"])
        if returns.get("HYG") is not None:
            bucket["hyg_returns"].append(returns["HYG"])
        if returns.get("TLT") is not None:
            bucket["tlt_returns"].append(returns["TLT"])

        # Per-window
        wb = by_window[window]
        wb["total"] += 1
        wb[outcome] = wb.get(outcome, 0) + 1
        if returns.get("SPY") is not None:
            wb["spy_returns"].append(returns["SPY"])

        # Overall
        overall["total"] += 1
        overall[outcome] = overall.get(outcome, 0) + 1
        if returns.get("SPY") is not None:
            overall["spy_returns"].append(returns["SPY"])
        if returns.get("HYG") is not None:
            overall["hyg_returns"].append(returns["HYG"])
        if returns.get("TLT") is not None:
            overall["tlt_returns"].append(returns["TLT"])

    # Finalize
    result_by_source: dict[str, Any] = {}
    for source, decisions in by_source.items():
        result_by_source[source] = {
            decision: _finalize_bucket(bucket)
            for decision, bucket in sorted(decisions.items())
        }

    result_by_window = {
        window: _finalize_bucket(bucket)
        for window, bucket in sorted(by_window.items())
    }

    return {
        "by_source": result_by_source,
        "by_window": result_by_window,
        "overall": _finalize_bucket(overall),
    }


def build_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the full calibration summary."""
    now = datetime.now(UTC)
    aggregated = aggregate_by_source_and_decision(entries)

    return {
        "schema_version": "calibration_summary.v1",
        "generated_at": now.isoformat(),
        "total_evaluations": len(entries),
        "summary": aggregated["overall"],
        "by_source": aggregated["by_source"],
        "by_window": aggregated["by_window"],
    }


def format_markdown(summary: dict[str, Any]) -> str:
    """Format calibration summary as markdown."""
    lines = [
        "# Calibration Summary",
        "",
        f"**Generated:** {summary['generated_at']}",
        f"**Total evaluations:** {summary['total_evaluations']}",
        "",
    ]

    overall = summary["summary"]
    lines += [
        "## Overall",
        "",
        f"- **Hit rate:** {overall['hit_rate']}",
        f"- **Correct:** {overall['correct']} / {overall['total']}",
        f"- **Incorrect:** {overall['incorrect']}",
        f"- **Neutral:** {overall['neutral']}",
        f"- **Unverifiable:** {overall['unverifiable']}",
        f"- **Avg SPY return:** {overall['avg_spy_return_pct']}%",
        "",
    ]

    # By source
    lines += ["## By Source", ""]
    for source, decisions in summary.get("by_source", {}).items():
        lines.append(f"### {source}")
        lines.append("")
        lines.append("| Decision | Total | Hit Rate | Correct | Avg SPY% |")
        lines.append("|----------|-------|----------|---------|----------|")
        for decision, stats in decisions.items():
            lines.append(
                f"| {decision} | {stats['total']} | "
                f"{stats['hit_rate'] or 'N/A'} | "
                f"{stats['correct']} | "
                f"{stats['avg_spy_return_pct'] or 'N/A'} |"
            )
        lines.append("")

    # By window
    lines += ["## By Window", ""]
    lines.append("| Window | Total | Hit Rate | Correct | Avg SPY% |")
    lines.append("|--------|-------|----------|---------|----------|")
    for window, stats in summary.get("by_window", {}).items():
        lines.append(
            f"| {window} | {stats['total']} | "
            f"{stats['hit_rate'] or 'N/A'} | "
            f"{stats['correct']} | "
            f"{stats['avg_spy_return_pct'] or 'N/A'} |"
        )
    lines.append("")

    lines += [
        "---",
        "",
        "*This summary is read-only. It does not modify current judgments.*",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(summary: dict[str, Any]) -> dict[str, Path]:
    """Write calibration summary outputs."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "latest.json"
    md_path = OUTPUT_DIR / "latest.md"

    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(summary), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Update calibration summary from eval log.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    entries = load_eval_log()
    summary = build_summary(entries)
    paths = write_outputs(summary)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Calibration summary: {paths['markdown']}")
        print(f"Total evaluations: {summary['total_evaluations']}")
        overall = summary["summary"]
        print(f"Hit rate: {overall['hit_rate']}")
        print(f"By source: {list(summary['by_source'].keys())}")


if __name__ == "__main__":
    main()
