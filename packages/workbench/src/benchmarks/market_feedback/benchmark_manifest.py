"""Generate benchmark_manifest.json for a market-feedback benchmark run.

The manifest is the isolation contract — it declares what this benchmark is,
where it reads, where it writes, and what it must not touch.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional


BENCHMARKS_ROOT = _workspace_root() / "Output" / "benchmarks" / "market_feedback"

FORBIDDEN_PATHS = [
    "Data/",
    "Workbench/src",
    "Output/deformation_runs",
    "Output/system_learning",
    "Output/benchmarks/market_feedback/latest",
]


def create_benchmark_manifest(
    benchmark_id: str,
    market_data_release: str,
    deformation_feature_release: str,
    universe: str = "sp100_sample_50",
    frequency: str = "daily",
    experiments: Optional[list[dict]] = None,
    created_by: str = "market_feedback_benchmark",
) -> dict:
    if experiments is None:
        experiments = [
            {"name": "baseline_alpha158_lightgbm", "config": "baseline_lightgbm.yaml"},
            {"name": "treatment_alpha158_deformation_lightgbm", "config": "treatment_lightgbm.yaml"},
        ]

    benchmark_dir = BENCHMARKS_ROOT / benchmark_id

    manifest = {
        "benchmark_id": benchmark_id,
        "benchmark_type": "market_feedback",
        "executor": "qlib",
        "isolation_mode": "file_interface_subprocess",
        "data_source": "openbb",
        "market_data_release": market_data_release,
        "deformation_feature_release": deformation_feature_release,
        "universe": universe,
        "frequency": frequency,
        "experiments": experiments,
        "allowed_read_paths": [
            str(benchmark_dir / "sandbox_input"),
        ],
        "allowed_write_paths": [
            str(benchmark_dir / "qlib_workspace"),
            str(benchmark_dir / "qlib_output"),
        ],
        "forbidden_paths": FORBIDDEN_PATHS,
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "initialized",
    }
    return manifest


def validate_manifest_paths(manifest: dict) -> list[str]:
    """Check that no allowed path overlaps with forbidden patterns. Returns errors."""
    errors = []
    for path_list_key in ("allowed_read_paths", "allowed_write_paths"):
        for p in manifest.get(path_list_key, []):
            for f in manifest.get("forbidden_paths", []):
                if f in p:
                    errors.append(
                        f"Path {p} ({path_list_key}) overlaps forbidden pattern {f}"
                    )
    return errors


def write_benchmark_manifest(manifest: dict, target_path: Optional[Path] = None) -> Path:
    benchmark_id = manifest["benchmark_id"]
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_path or (benchmark_dir / "benchmark_manifest.json")
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def load_benchmark_manifest(benchmark_id: str) -> dict:
    path = BENCHMARKS_ROOT / benchmark_id / "benchmark_manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))
