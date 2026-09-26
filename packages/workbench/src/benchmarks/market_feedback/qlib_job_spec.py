"""Generate and validate qlib_job_spec.json.

The job spec is the ONLY document the external Qlib runner reads. It must
contain only sandbox paths — never paths to main system internals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, cast

from benchmarks.experiment_protocol import load_registry, validate_spec
from workbench.paths import workspace_root as _workspace_root

BENCHMARKS_ROOT = _workspace_root() / "Output" / "state" / "benchmarks" / "market_feedback"

FORBIDDEN_IN_JOB_SPEC = [
    "Data/",
    "packages/workbench/src",
    "Output/deformation_runs",
    "Output/system_learning",
    "configs/",
    "canonical/",
    "protocols/",
]


def generate_job_spec(
    benchmark_id: str,
    experiments: Optional[list[dict]] = None,
    fail_policy: Optional[dict] = None,
    experiment_spec: Optional[dict[str, Any]] = None,
) -> dict:
    if experiments is None:
        experiments = [
            {"name": "baseline_alpha158_lightgbm", "config": "baseline_lightgbm.yaml"},
            {"name": "treatment_alpha158_deformation_lightgbm", "config": "treatment_lightgbm.yaml"},
        ]
    if fail_policy is None:
        fail_policy = {
            "on_qlib_error": "mark_benchmark_failed",
            "on_missing_metrics": "mark_inconclusive",
        }

    benchmark_dir = BENCHMARKS_ROOT / benchmark_id

    spec = {
        "job_id": f"qlib_job_{benchmark_id}",
        "benchmark_id": benchmark_id,
        "input_dir": str(benchmark_dir / "sandbox_input"),
        "workspace_dir": str(benchmark_dir / "qlib_workspace"),
        "output_dir": str(benchmark_dir / "qlib_output"),
        "experiments": experiments,
        "read_only_input": True,
        "fail_policy": fail_policy,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if experiment_spec is not None:
        protocol_errors = validate_spec(experiment_spec)
        if protocol_errors:
            raise ValueError("Invalid Experiment Spec: " + "; ".join(protocol_errors))
        adapter_name = experiment_spec["engine"]["adapter"]
        adapter = load_registry().get("adapters", {}).get(adapter_name)
        if not isinstance(adapter, dict) or adapter.get("status") != "active":
            raise ValueError(f"Experiment adapter is not active in the registry: {adapter_name}")
        if adapter.get("judgment_write_allowed") is not False:
            raise ValueError(f"Experiment adapter cannot write Judgment: {adapter_name}")
        spec["experiment_spec"] = experiment_spec
    return spec


def validate_job_spec_paths(spec: dict) -> list[str]:
    """Ensure all paths in the job spec are sandboxed. Returns error messages."""
    errors = []
    path_keys = ["input_dir", "workspace_dir", "output_dir"]

    for key in path_keys:
        value = spec.get(key, "")
        if not value:
            errors.append(f"Missing required path: {key}")
            continue
        for forbidden in FORBIDDEN_IN_JOB_SPEC:
            if forbidden in value:
                errors.append(
                    f"Job spec {key}={value!r} contains forbidden pattern {forbidden!r}"
                )

    # output_dir must be under qlib_output
    output_dir = spec.get("output_dir", "")
    if output_dir and "/qlib_output" not in output_dir:
        errors.append(f"output_dir must contain /qlib_output: {output_dir}")

    # input_dir must be under sandbox_input
    input_dir = spec.get("input_dir", "")
    if input_dir and "/sandbox_input" not in input_dir:
        errors.append(f"input_dir must contain /sandbox_input: {input_dir}")

    if "experiment_spec" in spec:
        protocol_errors = validate_spec(spec["experiment_spec"])
        errors.extend(f"experiment_spec: {error}" for error in protocol_errors)

    return errors


def write_job_spec(spec: dict, target_path: Optional[Path] = None) -> Path:
    benchmark_id = spec["benchmark_id"]
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_path or (benchmark_dir / "qlib_job_spec.json")
    out_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def load_job_spec(benchmark_id: str) -> dict[str, Any]:
    path = BENCHMARKS_ROOT / benchmark_id / "qlib_job_spec.json"
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
