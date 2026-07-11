#!/usr/bin/env python3
"""Market Feedback — Qlib/replay calibration feedback.

This script reads market feedback from Qlib benchmarks and replay
calibration to provide incremental explanation power assessment.

Usage:
    python3 scripts/market_feedback.py
    python3 scripts/market_feedback.py --json
    python3 scripts/market_feedback.py --sample  # Generate sample feedback

Output:
    Output/market_feedback/feedback_decision.json
    Output/market_feedback/feedback_decision.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json

QLIB_OUTPUT_DIR = ROOT / "ExternalTools" / "qlib_benchmark_runner" / "qlib_output"
TRADE_LEDGER_PATH = ROOT / "Output" / "trade_ledger" / "decisions.jsonl"
CALIBRATION_REPORT_PATH = ROOT / "Output" / "trade_ledger" / "calibration_report.json"
OUTPUT_DIR = ROOT / "Output" / "market_feedback"


def read_qlib_feedback() -> dict[str, Any] | None:
    """Read feedback from Qlib benchmark runner."""
    feedback_path = QLIB_OUTPUT_DIR / "feedback_decision.json"
    if feedback_path.exists():
        return load_json(feedback_path)
    return None


def read_calibration_feedback() -> dict[str, Any] | None:
    """Read feedback from trade decision calibration."""
    return load_json(CALIBRATION_REPORT_PATH)


def generate_sample_feedback() -> dict[str, Any]:
    """Generate sample feedback for testing."""
    now = utc_now()

    return {
        "schema_version": "market_feedback.v1",
        "generated_at": now.isoformat(),
        "feedback_type": "replay_calibration",
        "source": "sample",
        "source_note": "SAMPLE / NOT VALIDATION — generated for testing only",
        "summary": {
            "incremental_explanation_power": 0.15,
            "mechanism_usefulness_score": 0.62,
            "feature_promotion_candidates": ["M_anchor_geometry", "D_path_geometry"],
            "gate_threshold_adjustments": {
                "confidence_threshold": 0.6,
                "evidence_grade_threshold": "B",
            },
        },
        "details": [
            {
                "item_id": "structural_variables",
                "description": "Structural variables (M/D) show incremental explanation power",
                "metric": "incremental_r2",
                "value": 0.15,
                "interpretation": "M/D variables add 15% incremental R-squared beyond market factors",
                "action_implication": "Consider promoting M/D to higher confidence tier",
            },
            {
                "item_id": "mechanism_usefulness",
                "description": "Paper mechanisms show moderate usefulness",
                "metric": "hit_rate",
                "value": 0.62,
                "interpretation": "62% of Paper mechanisms correctly predicted direction",
                "action_implication": "Continue using Paper mechanisms as hypothesis source",
            },
            {
                "item_id": "k_gate_contribution",
                "description": "K gate shows positive contribution",
                "metric": "sharpe_ratio",
                "value": 0.85,
                "interpretation": "K gate filtering improves Sharpe ratio by 0.85",
                "action_implication": "Maintain K gate as quality filter",
            },
        ],
    }


def build_market_feedback(sample: bool = False) -> dict[str, Any]:
    """Build market feedback from available sources."""
    if sample:
        return generate_sample_feedback()

    now = utc_now()

    # Try to read Qlib feedback
    qlib_feedback = read_qlib_feedback()

    # Try to read calibration feedback
    calibration_feedback = read_calibration_feedback()

    if qlib_feedback:
        # Add source field if not present
        qlib_feedback["source"] = qlib_feedback.get("source", "qlib")
        return qlib_feedback

    if calibration_feedback:
        # Convert calibration report to feedback format
        summary = calibration_feedback.get("summary", {})
        return {
            "schema_version": "market_feedback.v1",
            "generated_at": now.isoformat(),
            "feedback_type": "replay_calibration",
            "source": "replay",
            "source_note": "Replay feedback from trade decision calibration",
            "summary": {
                "incremental_explanation_power": None,
                "mechanism_usefulness_score": None,
                "feature_promotion_candidates": [],
                "gate_threshold_adjustments": {},
            },
            "details": [
                {
                    "item_id": "calibration_sample_size",
                    "description": "Number of evaluated decisions",
                    "metric": "count",
                    "value": summary.get("evaluated_decisions", 0),
                    "interpretation": f"{summary.get('evaluated_decisions', 0)} decisions evaluated",
                    "action_implication": "Need more samples for reliable calibration",
                },
                {
                    "item_id": "avg_spy_1w_return",
                    "description": "Average SPY 1-week return after decisions",
                    "metric": "return_pct",
                    "value": summary.get("avg_spy_1w_return_pct"),
                    "interpretation": f"Average return: {summary.get('avg_spy_1w_return_pct', 'N/A')}%",
                    "action_implication": "Monitor for decision quality",
                },
            ],
        }

    # No feedback available
    return {
        "schema_version": "market_feedback.v1",
        "generated_at": now.isoformat(),
        "feedback_type": "replay_calibration",
        "source": "none",
        "source_note": "No feedback data available",
        "summary": {
            "incremental_explanation_power": None,
            "mechanism_usefulness_score": None,
            "feature_promotion_candidates": [],
            "gate_threshold_adjustments": {},
        },
        "details": [],
    }


def format_markdown(feedback: dict[str, Any]) -> str:
    """Format market feedback as markdown."""
    source = feedback.get("source", "unknown")
    source_note = feedback.get("source_note", "")

    lines = [
        "# Market Feedback",
        "",
        f"**Generated:** {feedback['generated_at']}",
        f"**Type:** {feedback['feedback_type']}",
        f"**Source:** {source}",
    ]

    if source_note:
        lines.append(f"**Note:** {source_note}")

    lines += [
        "",
        "---",
        "",
        "## Summary",
        "",
    ]

    summary = feedback.get("summary", {})
    if summary.get("incremental_explanation_power") is not None:
        lines.append(f"- **Incremental Explanation Power:** {summary['incremental_explanation_power']:.2%}")
    if summary.get("mechanism_usefulness_score") is not None:
        lines.append(f"- **Mechanism Usefulness Score:** {summary['mechanism_usefulness_score']:.2%}")
    if summary.get("feature_promotion_candidates"):
        lines.append(f"- **Feature Promotion Candidates:** {', '.join(summary['feature_promotion_candidates'])}")

    lines += [
        "",
        "## Details",
        "",
    ]

    for detail in feedback.get("details", []):
        lines.append(f"### {detail.get('item_id', 'unknown')}")
        lines.append(f"- **Description:** {detail.get('description', 'N/A')}")
        lines.append(f"- **Metric:** {detail.get('metric', 'N/A')}")
        lines.append(f"- **Value:** {detail.get('value', 'N/A')}")
        lines.append(f"- **Interpretation:** {detail.get('interpretation', 'N/A')}")
        lines.append(f"- **Action Implication:** {detail.get('action_implication', 'N/A')}")
        lines.append("")

    lines += [
        "## Usage",
        "",
        "- This feedback can adjust confidence calibration",
        "- It can promote/demote features",
        "- It CANNOT directly change current judgment",
        "- It feeds into Learning Hub for long-term improvement",
        "",
        "---",
        "",
        "*This is market feedback, not a trading signal.*",
    ]

    return "\n".join(lines) + "\n"


def write_outputs(feedback: dict[str, Any]) -> dict[str, Path]:
    """Write market feedback outputs."""
    ensure_dir(OUTPUT_DIR)

    json_path = OUTPUT_DIR / "feedback_decision.json"
    md_path = OUTPUT_DIR / "feedback_decision.md"

    write_json(json_path, feedback)
    md_path.write_text(format_markdown(feedback), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate market feedback.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--sample", action="store_true", help="Generate sample feedback.")
    args = parser.parse_args()

    feedback = build_market_feedback(sample=args.sample)
    paths = write_outputs(feedback)

    if args.json:
        print(json.dumps(feedback, indent=2, ensure_ascii=False))
    else:
        print(f"Market feedback: {paths['markdown']}")
        print(f"Type: {feedback['feedback_type']}")
        print(f"Details: {len(feedback['details'])}")


if __name__ == "__main__":
    main()
