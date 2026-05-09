# Qlib Benchmark Runner — external, isolated executor.
#
# This runner lives OUTSIDE the main system. It communicates only through:
#   - A job spec JSON file (read)
#   - Sandbox input directory (read)
#   - Qlib workspace directory (write)
#   - Qlib output directory (write)
#
# It does NOT import main system code. It does NOT know about Data/, src/,
# deformation_runs/, system_learning/, or any canonical ledger.

from __future__ import annotations

import json
import sys
from pathlib import Path

FORBIDDEN_PATTERNS = [
    "/Data/",
    "/src/",
    "/Output/deformation_runs/",
    "/Output/system_learning/",
    "/configs/",
    "/protocols/",
    "/Workbench/",
]


def assert_path_allowed(path: Path, allowed_root: Path) -> None:
    path = path.resolve()
    allowed_root = allowed_root.resolve()
    if not str(path).startswith(str(allowed_root)):
        raise RuntimeError(
            f"Path outside allowed root: {path}\n"
            f"  Allowed root: {allowed_root}"
        )


def assert_no_forbidden(path: Path) -> None:
    path_str = str(path.resolve())
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in path_str:
            raise RuntimeError(
                f"Forbidden path pattern {pattern!r} found in: {path_str}"
            )


def load_job_spec(job_spec_path: str) -> dict:
    """Load and validate the job spec from JSON."""
    spec_path = Path(job_spec_path).resolve()

    if not spec_path.exists():
        print(json.dumps({
            "status": "failed",
            "error": f"Job spec not found: {spec_path}",
            "benchmark_status": "failed",
            "feedback_type": "inconclusive",
        }))
        sys.exit(1)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    return spec


def validate_paths(spec: dict) -> tuple[Path, Path, Path]:
    """Validate and return the three sandbox directories."""
    input_dir = Path(spec["input_dir"]).resolve()
    workspace_dir = Path(spec["workspace_dir"]).resolve()
    output_dir = Path(spec["output_dir"]).resolve()

    benchmark_dir = input_dir.parent

    # All paths must live under the benchmark directory
    assert_path_allowed(input_dir, benchmark_dir)
    assert_path_allowed(workspace_dir, benchmark_dir)
    assert_path_allowed(output_dir, benchmark_dir)

    # Check forbidden patterns
    for d in [input_dir, workspace_dir, output_dir]:
        assert_no_forbidden(d)

    # Create workspace and output dirs
    workspace_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    return input_dir, workspace_dir, output_dir


def prepare_qlib_data(input_dir: Path, workspace_dir: Path) -> None:
    """Convert sandbox input into Qlib-compatible format in workspace."""
    qlib_data_dir = workspace_dir / "qlib_data"
    qlib_data_dir.mkdir(parents=True, exist_ok=True)

    market_panel = input_dir / "market_panel.parquet"
    if not market_panel.exists():
        print(json.dumps({
            "status": "failed",
            "error": f"market_panel.parquet not found in sandbox input: {input_dir}",
            "benchmark_status": "failed",
            "feedback_type": "inconclusive",
        }))
        sys.exit(1)

    # Prepare instruments config
    instruments_file = input_dir / "instruments.json"
    if instruments_file.exists():
        import shutil
        shutil.copy2(instruments_file, qlib_data_dir / "instruments.json")


def run_experiment(
    name: str,
    config_name: str,
    input_dir: Path,
    workspace_dir: Path,
    output_dir: Path,
    spec: dict,
) -> dict:
    """Run a single Qlib experiment. Returns metrics dict.

    This is a skeleton that produces structured output even without Qlib
    installed — so the main system can validate the pipeline contract.
    """
    experiment_output = output_dir / name
    experiment_output.mkdir(parents=True, exist_ok=True)

    try:
        import qlib
        return _run_real_qlib_experiment(name, config_name, input_dir, workspace_dir, experiment_output)
    except ImportError:
        return _run_placeholder_experiment(name, config_name, input_dir, experiment_output)


def _run_placeholder_experiment(
    name: str,
    config_name: str,
    input_dir: Path,
    output_dir: Path,
) -> dict:
    """Placeholder metrics when Qlib is not installed.

    This allows the pipeline to function and be tested without Qlib.
    The feedback will be marked as 'inconclusive' by the collector.
    """
    metrics = {
        "experiment": name,
        "config": config_name,
        "executor_status": "placeholder_no_qlib",
        "rank_ic": 0.0,
        "rank_icir": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "annual_return": 0.0,
        "information_ratio": 0.0,
    }

    metrics_path = output_dir / f"{name}_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    return metrics


def _run_real_qlib_experiment(
    name: str,
    config_name: str,
    input_dir: Path,
    workspace_dir: Path,
    output_dir: Path,
) -> dict:
    """Run an actual Qlib experiment. Only reaches here if qlib is installed."""
    import qlib
    from qlib.contrib.data.handler import Alpha158

    # Initialize Qlib with workspace
    qlib.init(provider_uri=str(workspace_dir / "qlib_data"))

    # TODO: Full Qlib experiment pipeline — model training, prediction, backtest
    # This requires market data in Qlib format, which is prepared by
    # prepare_qlib_data().

    metrics = {
        "experiment": name,
        "config": config_name,
        "executor_status": "qlib_initialized_placeholder",
        "rank_ic": 0.0,
        "rank_icir": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "annual_return": 0.0,
        "information_ratio": 0.0,
    }

    metrics_path = output_dir / f"{name}_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    return metrics


def export_metrics(output_dir: Path, results: list[dict]) -> Path:
    """Aggregate experiment results into raw_metrics.json."""
    raw_metrics = {
        "baseline": {},
        "treatment": {},
    }

    for r in results:
        name = r.get("experiment", "")
        metrics = {k: v for k, v in r.items() if k not in ("experiment", "config", "executor_status")}
        if "baseline" in name.lower():
            raw_metrics["baseline"] = metrics
        elif "treatment" in name.lower():
            raw_metrics["treatment"] = metrics

    # If experiments aren't named baseline/treatment, assign by order
    if not raw_metrics["baseline"] and len(results) >= 1:
        r0 = results[0]
        raw_metrics["baseline"] = {k: v for k, v in r0.items() if k not in ("experiment", "config", "executor_status")}
    if not raw_metrics["treatment"] and len(results) >= 2:
        r1 = results[1]
        raw_metrics["treatment"] = {k: v for k, v in r1.items() if k not in ("experiment", "config", "executor_status")}

    raw_path = output_dir / "raw_metrics.json"
    raw_path.write_text(json.dumps(raw_metrics, indent=2, ensure_ascii=False), encoding="utf-8")

    return raw_path


def write_run_manifest(spec: dict, output_dir: Path, status: str) -> None:
    manifest = {
        "job_id": spec.get("job_id"),
        "benchmark_id": spec.get("benchmark_id"),
        "run_status": status,
        "experiments_run": [e["name"] for e in spec.get("experiments", [])],
        "executor": "qlib_benchmark_runner",
        "isolation": "file_interface_subprocess",
    }
    manifest_path = output_dir / "qlib_run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Qlib Benchmark Runner (isolated)")
    parser.add_argument("--job-spec", required=True, help="Path to qlib_job_spec.json")
    args = parser.parse_args()

    try:
        spec = load_job_spec(args.job_spec)
        input_dir, workspace_dir, output_dir = validate_paths(spec)

        prepare_qlib_data(input_dir, workspace_dir)

        results = []
        for exp in spec.get("experiments", []):
            result = run_experiment(
                name=exp["name"],
                config_name=exp["config"],
                input_dir=input_dir,
                workspace_dir=workspace_dir,
                output_dir=output_dir,
                spec=spec,
            )
            results.append(result)

        export_metrics(output_dir, results)
        write_run_manifest(spec, output_dir, "completed")

    except Exception as e:
        output_dir = Path(spec.get("output_dir", ".")) if 'spec' in dir() else Path(".")
        write_run_manifest(
            spec if 'spec' in dir() else {"job_id": "unknown", "benchmark_id": "unknown"},
            output_dir,
            "failed",
        )
        print(json.dumps({
            "status": "failed",
            "error": str(e),
            "benchmark_status": "failed",
            "feedback_type": "inconclusive",
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
