"""Run baseline Qlib experiment (Alpha158 + LightGBM, no deformation features)."""

from __future__ import annotations

import json
from pathlib import Path


def run_baseline(name: str, input_dir: Path, workspace_dir: Path, output_dir: Path) -> dict:
    exp_output = output_dir / name
    exp_output.mkdir(parents=True, exist_ok=True)

    try:
        import qlib
        from qlib.contrib.data.handler import Alpha158

        qlib.init(provider_uri=str(workspace_dir / "qlib_data"))

        # Placeholder: full Qlib training + backtest pipeline
        metrics = {
            "rank_ic": 0.0,
            "rank_icir": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "annual_return": 0.0,
            "information_ratio": 0.0,
        }
    except ImportError:
        metrics = {
            "rank_ic": 0.0,
            "rank_icir": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "annual_return": 0.0,
            "information_ratio": 0.0,
            "_note": "qlib_not_installed",
        }

    metrics_path = exp_output / f"{name}_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics
