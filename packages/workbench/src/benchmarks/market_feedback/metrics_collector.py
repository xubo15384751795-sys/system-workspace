"""Collect raw Qlib output metrics and produce structured summaries.

Reads ONLY from the qlib_output/ directory — never from qlib_workspace/ internals.
Produces feedback/metrics_summary.json and feedback/comparison_metrics.csv.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

BENCHMARKS_ROOT = _workspace_root() / "Output" / "benchmarks" / "market_feedback"

EXPECTED_METRIC_KEYS = [
    "rank_ic",
    "rank_icir",
    "sharpe",
    "max_drawdown",
    "annual_return",
    "information_ratio",
]


def collect_metrics(benchmark_id: str) -> dict:
    """Read raw_metrics.json from qlib_output and produce structured summaries."""
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id
    qlib_output_dir = benchmark_dir / "qlib_output"
    feedback_dir = benchmark_dir / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)

    raw_metrics_path = qlib_output_dir / "raw_metrics.json"

    if not raw_metrics_path.exists():
        return _write_inconclusive(benchmark_id, feedback_dir, "raw_metrics.json not found in qlib_output")

    try:
        raw = json.loads(raw_metrics_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        return _write_inconclusive(benchmark_id, feedback_dir, f"Failed to parse raw_metrics.json: {e}")

    baseline = raw.get("baseline", {})
    treatment = raw.get("treatment", {})

    if not baseline or not treatment:
        return _write_inconclusive(benchmark_id, feedback_dir, "Missing baseline or treatment in raw_metrics")

    # Compute deltas
    metric_deltas = {}
    for key in EXPECTED_METRIC_KEYS:
        b_val = baseline.get(key)
        t_val = treatment.get(key)
        if b_val is not None and t_val is not None:
            metric_deltas[f"{key}_delta"] = round(t_val - b_val, 6)

    summary = {
        "benchmark_id": benchmark_id,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "baseline_metrics": {k: baseline.get(k) for k in EXPECTED_METRIC_KEYS if k in baseline},
        "treatment_metrics": {k: treatment.get(k) for k in EXPECTED_METRIC_KEYS if k in treatment},
        "metric_deltas": metric_deltas,
        "experiments_present": list(raw.keys()),
    }

    summary_path = feedback_dir / "metrics_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write comparison CSV
    _write_comparison_csv(feedback_dir, baseline, treatment, EXPECTED_METRIC_KEYS)

    return {"status": "collected", "benchmark_id": benchmark_id, "deltas": metric_deltas}


def _write_comparison_csv(
    feedback_dir: Path,
    baseline: dict,
    treatment: dict,
    metric_keys: list[str],
) -> None:
    rows = ["metric,baseline,treatment,delta"]
    for key in metric_keys:
        b = baseline.get(key)
        t = treatment.get(key)
        if b is not None and t is not None:
            delta = round(t - b, 6)
            rows.append(f"{key},{b},{t},{delta}")
    csv_path = feedback_dir / "comparison_metrics.csv"
    csv_path.write_text("\n".join(rows), encoding="utf-8")


def _write_inconclusive(benchmark_id: str, feedback_dir: Path, reason: str) -> dict:
    summary = {
        "benchmark_id": benchmark_id,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "status": "inconclusive",
        "reason": reason,
    }
    (feedback_dir / "metrics_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"status": "inconclusive", "benchmark_id": benchmark_id, "reason": reason}
