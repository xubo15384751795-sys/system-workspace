"""Benchmark gate: control whether benchmark results may enter downstream systems.

The gate checks that all required artifacts exist and that the benchmark
passed isolation validation before allowing a Learning Hub event.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from benchmarks.experiment_protocol import validate_result
from workbench.paths import workspace_root as _workspace_root

BENCHMARKS_ROOT = cast(Path, _workspace_root() / "Output" / "benchmarks" / "market_feedback")

REQUIRED_ARTIFACTS = [
    "benchmark_manifest.json",
    "sandbox_input/sandbox_input_manifest.json",
    "qlib_job_spec.json",
    "qlib_output/qlib_run_manifest.json",
    "feedback/metrics_summary.json",
    "feedback/feedback_decision.json",
]


def check_benchmark_gate(benchmark_id: str) -> dict:
    """Verify all required artifacts are present and valid."""
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id

    job_spec = {}
    job_spec_path = benchmark_dir / "qlib_job_spec.json"
    if job_spec_path.exists():
        try:
            loaded_job_spec = json.loads(job_spec_path.read_text(encoding="utf-8"))
            if isinstance(loaded_job_spec, dict):
                job_spec = loaded_job_spec
        except (OSError, json.JSONDecodeError):
            job_spec = {}
    protocol_backed = isinstance(job_spec.get("experiment_spec"), dict)
    required_artifacts = list(REQUIRED_ARTIFACTS)
    if protocol_backed:
        required_artifacts.append("experiment_result.json")

    checks = []
    for artifact in required_artifacts:
        path = benchmark_dir / artifact
        checks.append({
            "artifact": artifact,
            "present": path.exists(),
        })

    missing = [c["artifact"] for c in checks if not c["present"]]

    # Check for failure marker
    failure_marker = benchmark_dir / "qlib_output" / "failure_marker.json"
    has_failed = failure_marker.exists()
    if has_failed:
        json.loads(failure_marker.read_text(encoding="utf-8"))

    # Check isolation audit
    audit_path = benchmark_dir / "isolation_audit.json"
    audit_passed = False
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit_passed = audit.get("isolation_status") == "passed"

    decision_path = benchmark_dir / "feedback" / "feedback_decision.json"
    feedback_decision = {}
    if decision_path.exists():
        feedback_decision = json.loads(decision_path.read_text(encoding="utf-8"))
    feedback_type = feedback_decision.get("feedback_type")
    feedback_usable = isinstance(feedback_type, str) and feedback_type != "inconclusive"

    result_artifact_errors: list[str] = []
    result_artifact = {}
    if protocol_backed:
        result_path = benchmark_dir / "experiment_result.json"
        if result_path.exists():
            try:
                result_artifact = json.loads(result_path.read_text(encoding="utf-8"))
                result_artifact_errors = validate_result(result_artifact)
            except (OSError, json.JSONDecodeError) as exc:
                result_artifact_errors = [f"Cannot parse experiment_result.json: {exc}"]
        else:
            result_artifact_errors = ["experiment_result.json not found"]
        if not result_artifact_errors:
            feedback_usable = feedback_usable and bool(
                result_artifact.get("governance", {}).get("feedback_usable")
            )

    gate_result = {
        "benchmark_id": benchmark_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "all_artifacts_present": len(missing) == 0,
        "missing_artifacts": missing,
        "has_failed": has_failed,
        "isolation_audit_passed": audit_passed,
        "feedback_decision_type": feedback_type,
        "feedback_usable": feedback_usable,
        "experiment_protocol_backed": protocol_backed,
        "experiment_result_artifact_valid": protocol_backed and not result_artifact_errors
        if protocol_backed
        else None,
        "experiment_result_artifact_errors": result_artifact_errors,
        "gate_passed": (
            len(missing) == 0
            and not has_failed
            and audit_passed
            and feedback_usable
            and not result_artifact_errors
        ),
    }

    # Write gate result
    gate_path = benchmark_dir / "gate_result.json"
    gate_path.write_text(json.dumps(gate_result, indent=2, ensure_ascii=False), encoding="utf-8")

    return gate_result


def gate_allows_learning_hub(gate_result: dict) -> bool:
    return bool(gate_result.get("gate_passed", False))
