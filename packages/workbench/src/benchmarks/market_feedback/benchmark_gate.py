"""Benchmark gate: control whether benchmark results may enter downstream systems.

The gate checks that all required artifacts exist and that the benchmark
passed isolation validation before allowing a Learning Hub event.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

BENCHMARKS_ROOT = _workspace_root() / "Output" / "benchmarks" / "market_feedback"

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

    checks = []
    for artifact in REQUIRED_ARTIFACTS:
        path = benchmark_dir / artifact
        checks.append({
            "artifact": artifact,
            "present": path.exists(),
        })

    missing = [c["artifact"] for c in checks if not c["present"]]

    # Check for failure marker
    failure_marker = benchmark_dir / "qlib_output" / "failure_marker.json"
    has_failed = failure_marker.exists()
    failure_info = None
    if has_failed:
        failure_info = json.loads(failure_marker.read_text(encoding="utf-8"))

    # Check isolation audit
    audit_path = benchmark_dir / "isolation_audit.json"
    audit_passed = False
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit_passed = audit.get("isolation_status") == "passed"

    gate_result = {
        "benchmark_id": benchmark_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "all_artifacts_present": len(missing) == 0,
        "missing_artifacts": missing,
        "has_failed": has_failed,
        "isolation_audit_passed": audit_passed,
        "gate_passed": len(missing) == 0 and not has_failed and audit_passed,
    }

    # Write gate result
    gate_path = benchmark_dir / "gate_result.json"
    gate_path.write_text(json.dumps(gate_result, indent=2, ensure_ascii=False), encoding="utf-8")

    return gate_result


def gate_allows_learning_hub(gate_result: dict) -> bool:
    return gate_result.get("gate_passed", False)
