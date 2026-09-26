"""Collect raw Qlib output metrics and produce structured summaries.

Reads ONLY from the qlib_output/ directory — never from qlib_workspace/ internals.
Produces feedback/metrics_summary.json and feedback/comparison_metrics.csv.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.experiment_protocol import (
    ExperimentProtocolError,
    build_result_artifact,
    validate_spec,
    write_result,
)
from workbench.paths import workspace_root as _workspace_root

BENCHMARKS_ROOT = _workspace_root() / "Output" / "state" / "benchmarks" / "market_feedback"

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

    experiment_spec, protocol_errors, protocol_declared = _load_protocol_spec(benchmark_dir)
    if protocol_errors:
        return _write_inconclusive(
            benchmark_id,
            feedback_dir,
            "Invalid embedded Experiment Spec: " + "; ".join(protocol_errors),
            protocol_declared=True,
            protocol_errors=protocol_errors,
        )

    raw_metrics_path = qlib_output_dir / "raw_metrics.json"

    if not raw_metrics_path.exists():
        return _write_inconclusive(
            benchmark_id,
            feedback_dir,
            "raw_metrics.json not found in qlib_output",
            experiment_spec=experiment_spec,
            protocol_declared=protocol_declared,
        )

    try:
        raw = json.loads(raw_metrics_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        return _write_inconclusive(
            benchmark_id,
            feedback_dir,
            f"Failed to parse raw_metrics.json: {e}",
            experiment_spec=experiment_spec,
            protocol_declared=protocol_declared,
        )

    if not isinstance(raw, dict):
        return _write_inconclusive(
            benchmark_id,
            feedback_dir,
            "raw_metrics.json must contain an object",
            experiment_spec=experiment_spec,
            protocol_declared=protocol_declared,
        )

    baseline = raw.get("baseline", {})
    treatment = raw.get("treatment", {})

    if not isinstance(baseline, dict) or not isinstance(treatment, dict) or not baseline or not treatment:
        return _write_inconclusive(
            benchmark_id,
            feedback_dir,
            "Missing baseline or treatment in raw_metrics",
            experiment_spec=experiment_spec,
            protocol_declared=protocol_declared,
            raw_metrics=raw,
        )

    result_path = None
    result_errors: list[str] = []
    if experiment_spec is not None:
        result_path, result_errors = _write_protocol_result(
            benchmark_dir,
            experiment_spec,
            {"baseline": baseline, "treatment": treatment},
        )
        if result_errors:
            return _write_inconclusive(
                benchmark_id,
                feedback_dir,
                "Could not write Experiment Result Artifact: " + "; ".join(result_errors),
                experiment_spec=experiment_spec,
                protocol_declared=protocol_declared,
                raw_metrics=raw,
                result_errors=result_errors,
            )

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
    if protocol_declared:
        summary["experiment_protocol"] = {
            "status": "result_written" if result_path else "declared_without_result",
            "result_artifact": result_path.relative_to(benchmark_dir).as_posix() if result_path else None,
        }

    blocked_experiments = []
    for experiment_name, metrics in (("baseline", baseline), ("treatment", treatment)):
        if metrics.get("feedback_blocked"):
            blocked_experiments.append(
                {
                    "experiment": experiment_name,
                    "reasons": metrics.get("feedback_block_reasons", []),
                }
            )
    if blocked_experiments:
        summary.update(
            {
                "status": "inconclusive",
                "reason": "benchmark feedback is blocked by executor diagnostics",
                "feedback_blocked_experiments": blocked_experiments,
            }
        )

    summary_path = feedback_dir / "metrics_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write comparison CSV
    _write_comparison_csv(feedback_dir, baseline, treatment, EXPECTED_METRIC_KEYS)

    if blocked_experiments:
        return {
            "status": "inconclusive",
            "benchmark_id": benchmark_id,
            "reason": "benchmark feedback is blocked by executor diagnostics",
        }
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


def _write_inconclusive(
    benchmark_id: str,
    feedback_dir: Path,
    reason: str,
    *,
    experiment_spec: dict[str, Any] | None = None,
    protocol_declared: bool = False,
    protocol_errors: list[str] | None = None,
    raw_metrics: dict[str, Any] | None = None,
    result_errors: list[str] | None = None,
) -> dict:
    summary = {
        "benchmark_id": benchmark_id,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "status": "inconclusive",
        "reason": reason,
    }
    benchmark_dir = feedback_dir.parent
    if protocol_declared:
        protocol_info: dict[str, Any] = {
            "status": "invalid" if protocol_errors else "result_failed",
            "result_artifact": None,
        }
        if protocol_errors:
            protocol_info["errors"] = protocol_errors
        if result_errors:
            protocol_info["errors"] = result_errors
        if experiment_spec is not None and not protocol_errors:
            result_path, artifact_errors = _write_protocol_result(
                benchmark_dir,
                experiment_spec,
                raw_metrics or {},
                limitations=[reason],
            )
            if result_path:
                protocol_info["result_artifact"] = result_path.relative_to(benchmark_dir).as_posix()
            if artifact_errors:
                protocol_info["errors"] = artifact_errors
        summary["experiment_protocol"] = protocol_info
    (feedback_dir / "metrics_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"status": "inconclusive", "benchmark_id": benchmark_id, "reason": reason}


def _load_protocol_spec(benchmark_dir: Path) -> tuple[dict[str, Any] | None, list[str], bool]:
    """Read the optional embedded System Experiment Spec from the job file."""
    job_spec_path = benchmark_dir / "qlib_job_spec.json"
    if not job_spec_path.exists():
        return None, [], False
    try:
        job_spec = json.loads(job_spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"Cannot parse qlib_job_spec.json: {exc}"], True
    if not isinstance(job_spec, dict) or "experiment_spec" not in job_spec:
        return None, [], False
    spec = job_spec.get("experiment_spec")
    if not isinstance(spec, dict):
        return None, ["experiment_spec must be an object"], True
    errors = validate_spec(spec)
    return (spec if not errors else None), errors, True


def _write_protocol_result(
    benchmark_dir: Path,
    experiment_spec: dict[str, Any],
    raw_metrics: dict[str, Any],
    *,
    limitations: list[str] | None = None,
) -> tuple[Path | None, list[str]]:
    """Create the evidence-only Result Artifact for a protocol-backed run."""
    result_path = benchmark_dir / "experiment_result.json"
    try:
        result = build_result_artifact(
            experiment_spec,
            raw_metrics,
            limitations=limitations or (),
        )
        write_result(result_path, result)
    except (ExperimentProtocolError, OSError) as exc:
        return None, [str(exc)]
    return result_path, []
