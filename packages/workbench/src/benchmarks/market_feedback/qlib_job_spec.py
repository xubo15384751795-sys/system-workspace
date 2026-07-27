"""Generate and validate qlib_job_spec.json.

The job spec is the ONLY document the external Qlib runner reads. It must
contain only sandbox paths — never paths to main system internals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

BENCHMARKS_ROOT = _workspace_root() / "Output" / "benchmarks" / "market_feedback"

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
        "input_dir": (benchmark_dir / "sandbox_input").as_posix(),
        "workspace_dir": (benchmark_dir / "qlib_workspace").as_posix(),
        "output_dir": (benchmark_dir / "qlib_output").as_posix(),
        "experiments": experiments,
        "read_only_input": True,
        "fail_policy": fail_policy,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
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

    return errors


def write_job_spec(spec: dict, target_path: Optional[Path] = None) -> Path:
    benchmark_id = spec["benchmark_id"]
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_path or (benchmark_dir / "qlib_job_spec.json")
    out_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def load_job_spec(benchmark_id: str) -> dict:
    path = BENCHMARKS_ROOT / benchmark_id / "qlib_job_spec.json"
    return json.loads(path.read_text(encoding="utf-8"))
