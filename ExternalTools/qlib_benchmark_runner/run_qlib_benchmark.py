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
import math
import os
import sys
from pathlib import Path

FORBIDDEN_PATTERNS = [
    "/Data/",
    "/src/",
    "/Output/deformation_runs/",
    "/Output/system_learning/",
    "/configs/",
    "/protocols/",
    "/packages/framework/",
    "/packages/framework_v1_archive/",
    "/packages/harvester/",
    "/packages/learning_hub/",
    "/packages/orchestration/",
    "/packages/workbench/",
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
        instruments_target = qlib_data_dir / "instruments.json"
        # The sandbox input is intentionally read-only.  Do not preserve that
        # mode on the mutable workspace copy, otherwise a rerun cannot replace
        # the previous workspace file.
        if instruments_target.exists():
            instruments_target.chmod(0o644)
        shutil.copyfile(instruments_file, instruments_target)
        instruments_target.chmod(0o644)

    # Rebuild the mutable Qlib snapshot on every invocation so a rerun with a
    # new sandbox release cannot silently reuse stale custom features.
    _convert_market_panel_to_qlib(input_dir, qlib_data_dir)


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
        _configure_mlflow_tracking(workspace_dir)
        __import__("qlib")
    except ImportError:
        return _run_placeholder_experiment(name, config_name, input_dir, experiment_output)
    return _run_real_qlib_experiment(
        name,
        config_name,
        input_dir,
        workspace_dir,
        experiment_output,
        spec,
    )


def _configure_mlflow_tracking(workspace_dir: Path) -> str:
    """Keep Qlib's recorder inside the benchmark sandbox.

    Qlib 0.9.7 delegates ``R.start`` to MLflow.  New MLflow releases reject
    the legacy ``./mlruns`` file store, so use a per-benchmark SQLite file
    instead of relying on a global working-directory default or a service.
    The artifact root is explicit as well: MLflow's direct client API falls
    back to ``Path.cwd()/mlruns`` when creating an experiment, which would
    leak runner state into the repository root.
    """
    tracking_db = (workspace_dir / "mlflow.db").resolve()
    tracking_uri = f"sqlite:///{tracking_db}"
    artifact_root = (workspace_dir / "mlflow_artifacts").resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    os.environ["MLFLOW_TRACKING_URI"] = tracking_uri
    # MLflow's SQLAlchemy store uses this server-side override when it creates
    # the built-in Default experiment.  Keep that metadata inside the same
    # sandbox too; the runner must not even register a repository-root path.
    os.environ["_MLFLOW_SERVER_ARTIFACT_ROOT"] = artifact_root.as_uri()
    os.environ["MLFLOW_DEFAULT_ARTIFACT_ROOT"] = artifact_root.as_uri()
    return tracking_uri


def _ensure_mlflow_experiment(
    tracking_uri: str,
    experiment_name: str,
    artifact_root: Path,
) -> None:
    """Create the Qlib experiment with a sandbox-local artifact location.

    Qlib's ``MLflowExpManager.create_exp`` does not pass an artifact location
    to MLflow.  Create the experiment first through the MLflow client so that
    Qlib reuses it without falling back to a process-working-directory path.
    An existing experiment pointing elsewhere is rejected instead of being
    silently reused.
    """
    import mlflow

    artifact_uri = artifact_root.resolve().as_uri()
    client = mlflow.tracking.MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        client.create_experiment(experiment_name, artifact_location=artifact_uri)
        return
    if experiment.artifact_location.rstrip("/") != artifact_uri.rstrip("/"):
        raise RuntimeError(
            f"MLflow experiment {experiment_name!r} points outside the sandbox: "
            f"{experiment.artifact_location}; expected {artifact_uri}"
        )


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


PRESSURE_FEATURE_FILES = ("pressure_features.parquet", "structural_features.parquet")


def _pressure_feature_path(input_dir: Path):
    for name in PRESSURE_FEATURE_FILES:
        candidate = input_dir / name
        if candidate.exists():
            return candidate
    return input_dir / PRESSURE_FEATURE_FILES[0]


def _read_pressure_features(input_dir: Path):
    """Load the market-level pressure-feature snapshot from the sandbox.

    inherited_theory_authority is false: these are measurement overlays,
    not Deformation v1 host theory.
    """
    import pandas as pd

    feature_path = _pressure_feature_path(input_dir)
    if not feature_path.exists():
        return None, [], "missing_input"
    try:
        frame = pd.read_parquet(feature_path)
    except Exception as exc:
        return None, [], f"read_error:{type(exc).__name__}"

    if "date" not in frame.columns:
        if not isinstance(frame.index, pd.DatetimeIndex):
            return None, [], "missing_date"
        frame = frame.reset_index()
        index_column = frame.columns[0]
        frame = frame.rename(columns={index_column: "date"})

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"])
    fields = [
        str(column)
        for column in frame.columns
        if column not in {"date", "timestamp", "instrument"}
        and pd.api.types.is_numeric_dtype(frame[column])
    ]
    if not fields:
        return None, [], "missing_numeric_fields"
    return frame[["date", *fields]], fields, None


def _has_pressure_fields(qlib_data_dir: Path, fields: list[str]) -> bool:
    """Check that every requested custom field was written to Qlib storage."""
    if not fields:
        return False
    features_root = qlib_data_dir / "features"
    if not features_root.exists():
        return False
    feature_dirs = [path for path in features_root.iterdir() if path.is_dir()]
    if not feature_dirs:
        return False
    return all(any((directory / f"{field.lower()}.day.bin").exists() for directory in feature_dirs) for field in fields)


def _pressure_feature_status(
    name: str,
    input_dir: Path,
    qlib_data_dir: Path | None = None,
) -> tuple[str, bool, str | None]:
    """Describe whether the treatment handler consumed pressure features."""
    if "treatment" not in name.lower():
        return "not_applicable", False, None
    feature_path = _pressure_feature_path(input_dir)
    _frame, fields, source_error = _read_pressure_features(input_dir)
    if source_error:
        return source_error, False, str(feature_path)
    if qlib_data_dir is None or not _has_pressure_fields(qlib_data_dir, fields):
        return "not_integrated", False, str(feature_path)
    return "integrated", True, str(feature_path)


# Compatibility aliases for older tests.
_read_deformation_features = _read_pressure_features
_deformation_feature_status = _pressure_feature_status
_has_deformation_fields = _has_pressure_fields


def _run_real_qlib_experiment(
    name: str,
    config_name: str,
    input_dir: Path,
    workspace_dir: Path,
    output_dir: Path,
    spec: dict,
) -> dict:
    """Run a Qlib experiment via workflow APIs when available.

    Prefers ``qlib.workflow`` / ``qrun``-style task configs over a hand-rolled
    Alpha158+LGB mini-pipeline. Falls back to a compact init_instance_by_config
    workflow if the high-level helper is unavailable.
    """
    import traceback

    import qlib
    from qlib.config import REG_CN
    from qlib.utils import init_instance_by_config

    qlib_data_dir = workspace_dir / "qlib_data"
    has_treatment = "treatment" in name.lower()
    has_treatment_in_spec = any(
        "treatment" in str(experiment.get("name", "")).lower()
        for experiment in spec.get("experiments", [])
    )
    _frame, deformation_fields, source_error = _read_deformation_features(input_dir)
    if not (qlib_data_dir / "features").exists() or (
        has_treatment_in_spec and not _has_deformation_fields(qlib_data_dir, deformation_fields)
    ):
        _convert_market_panel_to_qlib(input_dir, qlib_data_dir)

    feature_status = "not_applicable"
    feature_used = False
    feature_path = None
    if has_treatment:
        feature_path = str(_pressure_feature_path(input_dir))
        if source_error:
            feature_status = source_error
        elif not _has_deformation_fields(qlib_data_dir, deformation_fields):
            feature_status = "not_integrated"
        else:
            feature_status = "integrated"
            feature_used = True

    provider_uri = str(qlib_data_dir.resolve())
    qlib.init(provider_uri=provider_uri, region=REG_CN)
    tracking_uri = _configure_mlflow_tracking(workspace_dir)
    market = "csi300" if (qlib_data_dir / "instruments" / "csi300.txt").exists() else "all"
    benchmark = "SH000300" if market == "csi300" else _select_benchmark_instrument(qlib_data_dir)
    backtest_end = _last_backtest_date(qlib_data_dir)

    handler = {
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
    if has_treatment:
        if not feature_used:
            raise RuntimeError(f"Treatment deformation features are not ready: {feature_status}")
        handler = {
            "class": "DeformationAlpha158",
            "module_path": "runner.deformation_handler",
            "kwargs": {
                "start_time": "2010-01-01",
                "end_time": "2025-12-31",
                "fit_start_time": "2010-01-01",
                "fit_end_time": "2020-12-31",
                "instruments": market,
                "deformation_fields": deformation_fields,
            },
        }

    task = {
        "model": {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "num_leaves": 64,
                "learning_rate": 0.05,
                "n_estimators": 200,
                "early_stopping_rounds": 20,
            },
        },
        "dataset": {
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
        },
    }

    try:
        # Prefer workflow recorder API (official Qlib path).
        try:
            from qlib.workflow import R
            from qlib.workflow.task.manage import TaskManager
        except Exception:
            R = None
            TaskManager = None

        model = init_instance_by_config(task["model"])
        dataset = init_instance_by_config(task["dataset"])
        if R is not None:
            experiment_name = f"system_{name}"
            _ensure_mlflow_experiment(
                tracking_uri,
                experiment_name,
                workspace_dir / "mlflow_artifacts",
            )
            with R.start(experiment_name=experiment_name, uri=tracking_uri):
                model.fit(dataset)
                pred = model.predict(dataset)
                R.save_objects(**{f"{name}_pred.pkl": pred})
        else:
            model.fit(dataset)
            pred = model.predict(dataset)

        from qlib.contrib.evaluate import risk_analysis
        from qlib.contrib.strategy import TopkDropoutStrategy
        from qlib.backtest import backtest as qlib_backtest

        strategy = TopkDropoutStrategy(signal=pred, topk=50, n_drop=10)
        portfolio_metric, _ = qlib_backtest(
            executor={
                "class": "SimulatorExecutor",
                "module_path": "qlib.backtest.executor",
                "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
            },
            strategy=strategy,
            start_time="2023-01-01",
            end_time=backtest_end,
            account=100_000_000,
            benchmark=benchmark,
            exchange_kwargs={
                "freq": "day",
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": 0.0005,
                "close_cost": 0.0015,
                "min_cost": 5,
            },
        )
        portfolio_entry = next(iter(portfolio_metric.values()))
        portfolio_frame = portfolio_entry[0]
        risk = risk_analysis(portfolio_frame["return"].dropna())["risk"]
        rank_ic, rank_icir = _calculate_prediction_metrics(dataset, pred)
        metrics = {
            "experiment": name,
            "config": config_name,
            "executor_status": "qlib_workflow",
            "placeholder": False,
            "workflow": "qlib.workflow" if R is not None else "init_instance_by_config",
            "rank_ic": rank_ic,
            "rank_icir": rank_icir,
            "sharpe": float(risk["information_ratio"]),
            "max_drawdown": float(risk["max_drawdown"]),
            "annual_return": float(risk["annualized_return"]),
            "information_ratio": float(risk["information_ratio"]),
        }
        blocked_reasons = []
        if rank_ic is None or rank_icir is None:
            blocked_reasons.append("missing_rank_ic_metrics")
        if feature_status not in {"not_applicable", "integrated"}:
            blocked_reasons.append(f"deformation_features_{feature_status}")
        metrics.update(
            {
            "feedback_blocked": bool(blocked_reasons),
            "feedback_block_reasons": blocked_reasons,
            "deformation_feature_status": feature_status,
                "deformation_features_used": feature_used,
                "deformation_feature_path": feature_path,
            }
        )
        del TaskManager  # imported for workflow surface; unused intentionally
    except Exception:
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
            "deformation_feature_status": feature_status,
            "deformation_features_used": feature_used,
            "deformation_feature_path": feature_path,
            "feedback_block_reasons": (
                [f"deformation_features_{feature_status}"]
                if has_treatment and feature_status != "integrated"
                else ["qlib_error"]
            ),
        }

    metrics_path = output_dir / f"{name}_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return metrics


def _calculate_prediction_metrics(dataset, pred) -> tuple[float | None, float | None]:
    """Calculate cross-sectional Rank IC and Rank ICIR on Qlib's test split."""
    import pandas as pd

    label = dataset.prepare("test", col_set="label")
    if isinstance(label, pd.DataFrame):
        label = label.iloc[:, 0]
    if isinstance(pred, pd.DataFrame):
        pred = pred.iloc[:, 0]
    frame = pd.concat([pred.rename("score"), label.rename("label")], axis=1).dropna()
    if frame.empty or "datetime" not in frame.index.names:
        return None, None

    rank_ic_by_day = frame.groupby(level="datetime", group_keys=False).apply(
        lambda group: group["score"].corr(group["label"], method="spearman")
    ).dropna()
    if rank_ic_by_day.empty:
        return None, None
    rank_ic = float(rank_ic_by_day.mean())
    std = float(rank_ic_by_day.std(ddof=1))
    rank_icir = rank_ic if not math.isfinite(std) or std == 0.0 else rank_ic / std * math.sqrt(238)
    if not math.isfinite(rank_ic) or not math.isfinite(rank_icir):
        return None, None
    return rank_ic, rank_icir


def _select_benchmark_instrument(qlib_data_dir: Path) -> str:
    """Select a real instrument for non-CN universes instead of Qlib's default."""
    instrument_file = qlib_data_dir / "instruments" / "all.txt"
    if instrument_file.exists():
        for line in instrument_file.read_text(encoding="utf-8").splitlines():
            symbol = line.split("\t", 1)[0].strip()
            if symbol:
                return symbol
    raise ValueError(f"No benchmark instrument found in {instrument_file}")


def _last_backtest_date(qlib_data_dir: Path) -> str:
    """Use the penultimate calendar date because Qlib needs a next-step date."""
    calendar_file = qlib_data_dir / "calendars" / "day.txt"
    dates = [line.strip() for line in calendar_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(dates) < 2:
        raise ValueError(f"Qlib backtest needs at least two calendar dates: {calendar_file}")
    return dates[-2]


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

    deformation_frame, deformation_fields, deformation_error = _read_deformation_features(input_dir)
    if deformation_error not in {None, "missing_input"}:
        raise ValueError(f"Invalid deformation feature input: {deformation_error}")
    deformation_manifest = None
    if deformation_frame is not None:
        deformation_daily = (
            deformation_frame[["date", *deformation_fields]]
            .groupby("date", as_index=False)
            .mean(numeric_only=True)
        )
        collisions = sorted(set(deformation_fields).intersection(df.columns))
        if collisions:
            raise ValueError(f"Deformation feature names collide with market fields: {collisions}")
        market_dates = df["date"].drop_duplicates()
        matched_dates = market_dates.isin(deformation_daily["date"]).sum()
        if matched_dates == 0:
            raise ValueError("Deformation feature dates do not overlap the market panel")
        df = df.merge(deformation_daily, on="date", how="left", validate="many_to_one")
        deformation_manifest = {
            "source": _pressure_feature_path(input_dir).name,
            "inherited_theory_authority": False,
            "fields": deformation_fields,
            "source_rows": int(len(deformation_frame)),
            "market_dates": int(len(market_dates)),
            "matched_market_dates": int(matched_dates),
            "date_min": deformation_daily["date"].min().strftime("%Y-%m-%d"),
            "date_max": deformation_daily["date"].max().strftime("%Y-%m-%d"),
        }

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
    if deformation_manifest is not None:
        (qlib_data_dir / "pressure_features_manifest.json").write_text(
            json.dumps(deformation_manifest, indent=2, ensure_ascii=False),
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
