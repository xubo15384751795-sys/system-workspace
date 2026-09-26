"""Classify benchmark results into feedback decisions.

Reads metrics_summary.json from feedback/ and produces a structured
feedback_decision.json — the ONLY artifact that may enter the Learning Hub.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

BENCHMARKS_ROOT = _workspace_root() / "Output" / "state" / "benchmarks" / "market_feedback"

FEEDBACK_TYPES = [
    "positive_increment",
    "risk_only_increment",
    "regime_specific_increment",
    "no_increment",
    "negative_increment",
    "inconclusive",
]


def classify_feedback(benchmark_id: str) -> dict:
    """Classify benchmark outcome from metrics_summary.json."""
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id
    feedback_dir = benchmark_dir / "feedback"
    summary_path = feedback_dir / "metrics_summary.json"

    if not summary_path.exists():
        return _write_decision(
            feedback_dir, benchmark_id, "inconclusive",
            "metrics_summary.json not found", {}
        )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    if summary.get("status") == "inconclusive":
        return _write_decision(
            feedback_dir, benchmark_id, "inconclusive",
            summary.get("reason", "Unknown reason"), {}
        )

    deltas = summary.get("metric_deltas", {})
    if not deltas:
        return _write_decision(
            feedback_dir, benchmark_id, "inconclusive",
            "No metric deltas to evaluate", {}
        )

    # Classification logic
    ic_delta = deltas.get("rank_ic_delta", 0)
    sharpe_delta = deltas.get("sharpe_delta", 0)
    drawdown_delta = deltas.get("max_drawdown_delta", 0)

    if ic_delta > 0.005 and sharpe_delta > 0.05:
        feedback_type = "positive_increment"
        recommended_action = ["consider promoting deformation feature to alpha signal"]
    elif ic_delta > 0.005 and sharpe_delta <= 0.05:
        feedback_type = "risk_only_increment"
        recommended_action = ["keep deformation_state as regime overlay", "do not promote as direct alpha feature"]
    elif drawdown_delta > 0 and ic_delta <= 0.005:
        feedback_type = "regime_specific_increment"
        recommended_action = ["use deformation feature for regime detection only"]
    elif abs(ic_delta) <= 0.003 and abs(sharpe_delta) <= 0.03 and abs(drawdown_delta) <= 0.05:
        feedback_type = "no_increment"
        recommended_action = ["deformation feature provides no measurable edge in this benchmark"]
    elif ic_delta < -0.005:
        feedback_type = "negative_increment"
        recommended_action = ["review deformation feature for potential noise amplification"]
    else:
        feedback_type = "inconclusive"
        recommended_action = ["collect more data", "review benchmark configuration"]

    return _write_decision(
        feedback_dir, benchmark_id, feedback_type,
        f"Rank IC delta: {ic_delta}, Sharpe delta: {sharpe_delta}", deltas,
        recommended_action=recommended_action,
    )


def _write_decision(
    feedback_dir: Path,
    benchmark_id: str,
    feedback_type: str,
    summary: str,
    metric_deltas: dict,
    recommended_action: Optional[list[str]] = None,
) -> dict:
    decision = {
        "benchmark_id": benchmark_id,
        "feedback_type": feedback_type,
        "summary": summary,
        "metric_deltas": metric_deltas,
        "recommended_action": recommended_action or [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    decision_path = feedback_dir / "feedback_decision.json"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8")

    return decision
