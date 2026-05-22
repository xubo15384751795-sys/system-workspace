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

    All metric values are null (not zero) so downstream consumers can
    distinguish "benchmark not run" from "benchmark returned zero signal."
    The feedback will be marked as 'inconclusive' by the collector.
    """
    metrics = {
        "experiment": name,
        "config": config_name,
        "executor_status": "placeholder_no_qlib",
        "placeholder": True,
        "feedback_blocked": True,
        "_note": "qlib_not_installed_placeholder",
        "rank_ic": None,
        "rank_icir": None,
        "sharpe": None,
        "max_drawdown": None,
        "annual_return": None,
        "information_ratio": None,
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
    """Run a Qlib experiment with Alpha158 + LightGBM + backtest.

    Only reaches here if qlib is installed. Produces real metrics
    distinguishable from the placeholder null-metric output.
    """
    import qlib
    from qlib.config import REG_CN
    from qlib.contrib.data.handler import Alpha158
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.contrib.strategy import TopkDropoutStrategy
    from qlib.backtest import backtest, executor
    from qlib.contrib.evaluate import risk_analysis
    from qlib.utils import init_instance_by_config

    qlib_data_dir = workspace_dir / "qlib_data"

    # Check for pre-converted Qlib data; if absent, convert from market_panel
    if not (qlib_data_dir / "features").exists():
        _convert_market_panel_to_qlib(input_dir, qlib_data_dir)

    provider_uri = str(qlib_data_dir.resolve())
    qlib.init(provider_uri=provider_uri, region=REG_CN)

    market = "csi300" if (qlib_data_dir / "instruments" / "csi300.txt").exists() else "all"

    # Alpha158 handler — standard 158 factor definitions
    data_handler_config = {
        "class": "Alpha158",
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "start_time": "2010-01-01",
            "end_time": "2025-12-31",
            "fit_start_time": "2010-01-01",
            "fit_end_time": "2020-12-31",
            "instruments": market,
        },
    }
    handler = init_instance_by_config(data_handler_config)

    # Dataset split
    dataset_config = {
        "class": "DatasetH",
        "module_path": "qlib.data.dataset",
        "kwargs": {
            "handler": handler,
            "segments": {
                "train": ("2010-01-01", "2020-12-31"),
                "valid": ("2021-01-01", "2022-12-31"),
                "test": ("2023-01-01", "2025-12-31"),
            },
        },
    }
    dataset = init_instance_by_config(dataset_config)

    # LightGBM model
    model = LGBModel(
        loss="mse",
        num_leaves=64,
        learning_rate=0.05,
        n_estimators=200,
        early_stopping_rounds=20,
    )
    model.fit(dataset)

    # Backtest with TopkDropout strategy
    strategy_config = {
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy",
        "kwargs": {"topk": 50, "n_drop": 10},
    }
    strategy = init_instance_by_config(strategy_config)

    executor_config = {
        "class": "SimulatorExecutor",
        "module_path": "qlib.backtest.executor",
        "kwargs": {
            "time_per_step": "day",
            "generate_portfolio_metrics": True,
        },
    }
    exec_inst = init_instance_by_config(executor_config)

    backtest_config = {
        "start_time": "2023-01-01",
        "end_time": "2025-12-31",
        "account": 100000000,
        "benchmark": "SH000300" if market == "csi300" else None,
        "exchange_kwargs": {
            "freq": "day",
            "limit_threshold": 0.095,
            "deal_price": "close",
            "open_cost": 0.0005,
            "close_cost": 0.0015,
            "min_cost": 5,
        },
    }

    try:
        portfolio_dict, indicator_dict = backtest.backtest(
            strategy=strategy,
            executor=exec_inst,
            pred=model.predict(dataset),
            **backtest_config,
        )

        analysis = risk_analysis(portfolio_dict["portfolio"])
        metrics = {
            "experiment": name,
            "config": config_name,
            "executor_status": "qlib_real",
            "placeholder": False,
            "feedback_blocked": False,
            "rank_ic": float(analysis.get("information_ratio", {}).get("IC", 0.0) or 0.0),
            "rank_icir": float(analysis.get("information_ratio", {}).get("ICIR", 0.0) or 0.0),
            "sharpe": float(analysis.get("excess_return_without_cost", {}).get("annualized_ratio", 0.0) or 0.0),
            "max_drawdown": float(analysis.get("max_drawdown", 0.0) or 0.0),
            "annual_return": float(analysis.get("excess_return_without_cost", {}).get("annualized_return", 0.0) or 0.0),
            "information_ratio": float(analysis.get("information_ratio", {}).get("ICIR", 0.0) or 0.0),
        }
    except Exception:
        import traceback
        metrics = {
            "experiment": name,
            "config": config_name,
            "executor_status": "qlib_error",
            "placeholder": False,
            "feedback_blocked": True,
            "error": traceback.format_exc(),
            "rank_ic": None,
            "rank_icir": None,
            "sharpe": None,
            "max_drawdown": None,
            "annual_return": None,
            "information_ratio": None,
        }

    metrics_path = output_dir / f"{name}_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    return metrics


def _convert_market_panel_to_qlib(input_dir: Path, qlib_data_dir: Path, *, freq: str = "day") -> None:
    """Convert sandbox market_panel.parquet into the canonical Qlib binary layout.

    Output structure (Qlib v0.9+ format):
      qlib_data_dir/
        calendars/{freq}.txt          one ISO date per line
        instruments/all.txt           "SYMBOL\\tstart_date\\tend_date" per line
        features/{symbol_lower}/{field}.{freq}.bin
          little-endian float32; first element is the start-date index into
          the calendar, followed by one value per calendar slot.

    The function intentionally does not depend on qlib.scripts.dump_bin
    so the runner stays self-contained.  If market_panel has no
    "instrument" column, the entire panel is dumped under symbol "_ALL"
    which Alpha158 will still index (useful for unit-test fixtures).
    """
    import numpy as np
    import pandas as pd

    market_panel = input_dir / "market_panel.parquet"
    if not market_panel.exists():
        return

    df = pd.read_parquet(market_panel)
    qlib_data_dir.mkdir(parents=True, exist_ok=True)

    if "date" not in df.columns:
        return
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    if "instrument" not in df.columns:
        df["instrument"] = "_ALL"
    df["instrument"] = df["instrument"].astype(str).str.strip()
    df = df[df["instrument"] != ""]

    calendar = sorted(df["date"].unique())
    if not calendar:
        return
    calendar_idx = {ts: i for i, ts in enumerate(calendar)}

    cal_dir = qlib_data_dir / "calendars"
    cal_dir.mkdir(parents=True, exist_ok=True)
    (cal_dir / f"{freq}.txt").write_text(
        "\n".join(pd.Timestamp(d).strftime("%Y-%m-%d") for d in calendar) + "\n",
        encoding="utf-8",
    )

    features_dir = qlib_data_dir / "features"
    features_dir.mkdir(parents=True, exist_ok=True)

    instruments = sorted(df["instrument"].unique())
    instrument_rows: list[tuple[str, str, str]] = []

    field_columns = [c for c in df.columns if c not in ("date", "instrument")]

    for instrument in instruments:
        inst_df = df[df["instrument"] == instrument].sort_values("date")
        if inst_df.empty:
            continue
        first_date = inst_df["date"].iloc[0]
        last_date = inst_df["date"].iloc[-1]
        start_idx = calendar_idx[first_date]
        end_idx = calendar_idx[last_date]
        inst_dir = features_dir / instrument.lower()
        inst_dir.mkdir(parents=True, exist_ok=True)

        inst_df = inst_df.set_index("date")
        # Reindex to contiguous slice of the calendar from start to end so
        # missing rows become NaN (Qlib expects continuous binary data).
        slice_idx = pd.DatetimeIndex(calendar[start_idx : end_idx + 1])
        inst_df = inst_df.reindex(slice_idx)

        for field in field_columns:
            series = pd.to_numeric(inst_df[field], errors="coerce") if field in inst_df.columns else None
            if series is None or series.dropna().empty:
                continue
            values = np.asarray(series.to_numpy(), dtype="<f4")
            payload = np.concatenate([
                np.array([np.float32(start_idx)], dtype="<f4"),
                values,
            ])
            bin_path = inst_dir / f"{field.lower()}.{freq}.bin"
            with bin_path.open("wb") as fh:
                fh.write(payload.tobytes(order="C"))

        instrument_rows.append((
            instrument.upper(),
            pd.Timestamp(first_date).strftime("%Y-%m-%d"),
            pd.Timestamp(last_date).strftime("%Y-%m-%d"),
        ))

    instr_dir = qlib_data_dir / "instruments"
    instr_dir.mkdir(parents=True, exist_ok=True)
    (instr_dir / "all.txt").write_text(
        "\n".join(f"{sym}\t{start}\t{end}" for sym, start, end in instrument_rows) + "\n",
        encoding="utf-8",
    )


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


def validate_benchmark_metrics(metrics: dict, *, require_distinguishable: bool = True) -> None:
    """Reject benchmark results that cannot be distinguished from no-op placeholders.

    Callers in the main system should use this to gate benchmark evidence before
    accepting it as valid comparison data.
    """
    if metrics.get("placeholder") is True or metrics.get("feedback_blocked") is True:
        return  # explicitly marked — caller decides how to handle

    numeric_keys = {"rank_ic", "rank_icir", "sharpe", "max_drawdown", "annual_return", "information_ratio"}
    numeric_values = [metrics.get(k) for k in numeric_keys]

    if all(v is None for v in numeric_values):
        raise ValueError(
            "Benchmark metrics are all null — benchmark was not executed. "
            "Rejecting results to avoid false compliance."
        )

    if require_distinguishable and all(v == 0.0 for v in numeric_values if v is not None):
        raise ValueError(
            "Benchmark metrics are all zero with no placeholder marker. "
            "This is indistinguishable from the no-qlib placeholder. Rejecting."
        )

    if require_distinguishable and not any(v != 0.0 for v in numeric_values if v is not None and isinstance(v, (int, float))):
        raise ValueError(
            "Benchmark metrics contain no non-zero signal. Results are not distinguishable from no-op."
        )


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
