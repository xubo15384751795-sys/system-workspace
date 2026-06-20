#!/usr/bin/env python3
"""Judgment Accuracy Report — aggregate calibration data from eval_log.

Reads Output/evaluations/eval_log.jsonl and produces rolling accuracy
statistics, confidence calibration curves, and decision-type hit rates.

Usage:
    python3 scripts/judgment_accuracy_report.py
    python3 scripts/judgment_accuracy_report.py --json

Output:
    Output/system_learning/latest/judgment_accuracy_report.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _runtime_io import ROOT, ensure_dir, write_json

EVAL_LOG = ROOT / "Output" / "evaluations" / "eval_log.jsonl"
SIGNALS_PATH = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"
OUTPUT_PATH = OUTPUT_DIR / "judgment_accuracy_report.json"


def load_evaluated_records() -> list[dict[str, Any]]:
    """Load eval_log records that have actual returns (not unverifiable)."""
    if not EVAL_LOG.exists():
        return []
    records = []
    for line in EVAL_LOG.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("outcome") != "unverifiable":
            records.append(r)
    return records


def compute_accuracy_by_decision(records: list[dict]) -> dict[str, dict]:
    """Compute accuracy metrics grouped by decision type."""
    by_decision: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_decision[r.get("decision", "unknown")].append(r)

    result = {}
    for decision, recs in sorted(by_decision.items()):
        outcomes = [r["outcome"] for r in recs]
        correct = sum(1 for o in outcomes if o == "correct")
        incorrect = sum(1 for o in outcomes if o == "incorrect")
        neutral = sum(1 for o in outcomes if o == "neutral")
        total = len(outcomes)

        spy_returns = [
            r["returns"]["SPY"]
            for r in recs
            if r.get("returns", {}).get("SPY") is not None
        ]
        avg_spy = sum(spy_returns) / len(spy_returns) if spy_returns else None

        result[decision] = {
            "total": total,
            "correct": correct,
            "incorrect": incorrect,
            "neutral": neutral,
            "accuracy": round(correct / total, 4) if total > 0 else None,
            "avg_spy_return_pct": round(avg_spy, 4) if avg_spy is not None else None,
        }
    return result


def compute_accuracy_by_confidence(records: list[dict]) -> dict[str, dict]:
    """Compute accuracy metrics grouped by confidence level."""
    by_conf: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_conf[r.get("confidence", "unknown")].append(r)

    result = {}
    for conf, recs in sorted(by_conf.items()):
        outcomes = [r["outcome"] for r in recs]
        correct = sum(1 for o in outcomes if o == "correct")
        incorrect = sum(1 for o in outcomes if o == "incorrect")
        total = len(outcomes)

        spy_returns = [
            r["returns"]["SPY"]
            for r in recs
            if r.get("returns", {}).get("SPY") is not None
        ]
        avg_spy = sum(spy_returns) / len(spy_returns) if spy_returns else None

        result[conf] = {
            "total": total,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": round(correct / total, 4) if total > 0 else None,
            "avg_spy_return_pct": round(avg_spy, 4) if avg_spy is not None else None,
        }
    return result


def compute_accuracy_by_window(records: list[dict]) -> dict[str, dict]:
    """Compute accuracy metrics grouped by evaluation window (1d/1w/1m)."""
    by_window: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_window[r.get("window", "unknown")].append(r)

    result = {}
    for window, recs in sorted(by_window.items()):
        outcomes = [r["outcome"] for r in recs]
        correct = sum(1 for o in outcomes if o == "correct")
        incorrect = sum(1 for o in outcomes if o == "incorrect")
        total = len(outcomes)

        spy_returns = [
            r["returns"]["SPY"]
            for r in recs
            if r.get("returns", {}).get("SPY") is not None
        ]
        avg_spy = sum(spy_returns) / len(spy_returns) if spy_returns else None

        result[window] = {
            "total": total,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": round(correct / total, 4) if total > 0 else None,
            "avg_spy_return_pct": round(avg_spy, 4) if avg_spy is not None else None,
        }
    return result


def compute_daily_accuracy_timeline(records: list[dict]) -> list[dict]:
    """Compute per-day accuracy for timeline visualization."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        eval_id = r.get("eval_id", "")
        parts = eval_id.split("_")
        date = parts[1] if len(parts) >= 3 else r.get("evaluated_at", "")[:10]
        by_date[date].append(r)

    timeline = []
    for date in sorted(by_date.keys()):
        recs = by_date[date]
        outcomes = [r["outcome"] for r in recs]
        correct = sum(1 for o in outcomes if o == "correct")
        incorrect = sum(1 for o in outcomes if o == "incorrect")
        total = len(outcomes)

        spy_returns = [
            r["returns"]["SPY"]
            for r in recs
            if r.get("returns", {}).get("SPY") is not None
        ]
        avg_spy = sum(spy_returns) / len(spy_returns) if spy_returns else None

        timeline.append({
            "date": date,
            "total": total,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": round(correct / total, 4) if total > 0 else None,
            "avg_spy_return_pct": round(avg_spy, 4) if avg_spy is not None else None,
        })
    return timeline


def compute_channel_signal_quality() -> dict[str, Any]:
    """Analyze channel signal quality using structural replay data."""
    try:
        import pandas as pd
    except ImportError:
        return {}

    if not SIGNALS_PATH.exists():
        return {"status": "signals_not_found"}

    signals = pd.read_parquet(SIGNALS_PATH)
    result = {}

    # Channel warning thresholds (from structural_replay_v2.py)
    thresholds = {
        "channel_M": 1.8,
        "channel_D_contraction": 2.2,
        "channel_K": 1.0,
        "channel_X_agg": 2.0,
    }

    for ch_col, threshold in thresholds.items():
        if ch_col not in signals.columns:
            continue
        ch_name = ch_col.replace("channel_", "")
        s = signals[ch_col].dropna()
        if len(s) < 100:
            continue

        # Days above warning
        above_warning = (s.abs() > threshold).sum()
        total = len(s)

        result[ch_name] = {
            "total_days": total,
            "days_above_warning": int(above_warning),
            "pct_above_warning": round(above_warning / total * 100, 2),
            "current_value": round(float(s.iloc[-1]), 4) if len(s) > 0 else None,
            "threshold": threshold,
        }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    records = load_evaluated_records()
    now = datetime.now(UTC).isoformat()

    if not records:
        report = {
            "schema_version": "judgment_accuracy_report.v1",
            "generated_at": now,
            "status": "no_evaluated_records",
            "total_evaluated": 0,
            "message": "No records with actual returns yet. Run evaluate_pending after panel refresh.",
        }
        ensure_dir(OUTPUT_DIR)
        write_json(OUTPUT_PATH, report)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("No evaluated records yet.")
        return

    # Compute all metrics
    by_decision = compute_accuracy_by_decision(records)
    by_confidence = compute_accuracy_by_confidence(records)
    by_window = compute_accuracy_by_window(records)
    timeline = compute_daily_accuracy_timeline(records)
    channel_quality = compute_channel_signal_quality()

    # Overall summary
    all_outcomes = [r["outcome"] for r in records]
    total = len(all_outcomes)
    correct = sum(1 for o in all_outcomes if o == "correct")
    incorrect = sum(1 for o in all_outcomes if o == "incorrect")
    neutral = sum(1 for o in all_outcomes if o == "neutral")

    all_spy = [
        r["returns"]["SPY"]
        for r in records
        if r.get("returns", {}).get("SPY") is not None
    ]

    report = {
        "schema_version": "judgment_accuracy_report.v1",
        "generated_at": now,
        "status": "ok",
        "summary": {
            "total_evaluated": total,
            "correct": correct,
            "incorrect": incorrect,
            "neutral": neutral,
            "accuracy": round(correct / total, 4) if total > 0 else None,
            "avg_spy_return_pct": round(sum(all_spy) / len(all_spy), 4) if all_spy else None,
            "evaluation_period": {
                "earliest": timeline[0]["date"] if timeline else None,
                "latest": timeline[-1]["date"] if timeline else None,
            },
        },
        "by_decision": by_decision,
        "by_confidence": by_confidence,
        "by_window": by_window,
        "daily_timeline": timeline,
        "channel_signal_quality": channel_quality,
        "notes": [
            "accuracy = correct / (correct + incorrect), excludes neutral",
            "WATCH_ONLY/NO_TRADE: correct if SPY <= 0, incorrect if SPY > 0.5%",
            "WATCH: always neutral (not a position)",
            "Data source: Output/evaluations/eval_log.jsonl",
        ],
    }

    ensure_dir(OUTPUT_DIR)
    write_json(OUTPUT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Judgment Accuracy Report")
        print(f"  Total evaluated: {total}")
        print(f"  Correct: {correct}, Incorrect: {incorrect}, Neutral: {neutral}")
        print(f"  Accuracy: {report['summary']['accuracy']}")
        print(f"  Avg SPY return: {report['summary']['avg_spy_return_pct']}%")
        print()
        print("By decision:")
        for d, m in by_decision.items():
            print(f"  {d}: {m['total']} records, accuracy={m['accuracy']}, avg_spy={m['avg_spy_return_pct']}%")
        print()
        print("By confidence:")
        for c, m in by_confidence.items():
            print(f"  {c}: {m['total']} records, accuracy={m['accuracy']}, avg_spy={m['avg_spy_return_pct']}%")
        print()
        print(f"Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
