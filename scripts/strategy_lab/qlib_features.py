"""Qlib Feature Exporter — prepare pressure-gauge velocity features for Qlib.

Generates pressure_features.parquet from live Neutral Macro Pressure gauges.
M/D names are compatibility keys only. inherited_theory_authority is false.

Features exported:
  - Raw gauges: pressure_M, pressure_D
  - Velocity (5d/10d/20d change)
  - Cofire count, velocity gate, stress level

Usage:
    python scripts/strategy_lab/qlib_features.py
    python scripts/strategy_lab/qlib_features.py --output /path/to/sandbox_input/
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts import _runtime_io as rio
from scripts.strategy_lab.data_loader import load_signals
from scripts.strategy_lab.risk_gate import (
    DEFAULT_COFIRE_V,
    DEFAULT_VELOCITY_THRESHOLD,
    compute_velocity_gate,
)

OUTPUT_DIR = rio.ROOT / "ExternalTools" / "qlib_benchmark_runner" / "sandbox_input"
PRESSURE_FEATURES_FILENAME = "pressure_features.parquet"
PRESSURE_CHANNELS = ("M", "D")


def build_features(
    start: str = "2000-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """Build Neutral Macro Pressure velocity features for Qlib.

    Returns DataFrame indexed by date with pressure_* columns.
    inherited_theory_authority is false: these are measurement gauges.
    """
    signals = load_signals(start=start, end=end)
    channels = [ch for ch in PRESSURE_CHANNELS if ch in signals.columns]
    features = pd.DataFrame(index=signals.index)

    for ch in channels:
        features[f"pressure_{ch}"] = signals[ch]

    for window in [5, 10, 20]:
        velocity = signals.diff(window)
        for ch in channels:
            features[f"pressure_{ch}_vel{window}"] = velocity[ch]

    for window in [5, 10, 20]:
        velocity = signals.diff(window)
        cofire = pd.Series(0, index=signals.index)
        for ch in channels:
            cofire += (velocity[ch] > DEFAULT_COFIRE_V).astype(int)
        features[f"pressure_cofire_{window}d"] = cofire

    gate = compute_velocity_gate(signals)
    features["pressure_velocity_gate"] = gate

    velocity_20d = signals.diff(20)
    max_vel = pd.Series(0.0, index=signals.index)
    for ch in channels:
        max_vel = np.maximum(max_vel, velocity_20d[ch].fillna(0))
    stress = np.clip((max_vel - DEFAULT_VELOCITY_THRESHOLD) / 2.0, 0, 1)
    features["pressure_stress_level"] = stress

    for ch in channels:
        vel = velocity_20d[ch].fillna(0)
        features[f"pressure_{ch}_stress_flag"] = (vel > 0.3).astype(float)
        features[f"pressure_{ch}_vol20d"] = signals[ch].rolling(20).std()

    return features


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Neutral Macro Pressure features for Qlib")
    parser.add_argument("--start", type=str, default="2000-01-01")
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--output", type=str, default=None, help="Output directory")
    args = parser.parse_args()

    features = build_features(start=args.start, end=args.end)

    out_dir = Path(args.output) if args.output else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / PRESSURE_FEATURES_FILENAME
    features.to_parquet(out_path)
    manifest_path = out_dir / "pressure_features_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "pressure_features.v1",
                "source": "neutral_macro_pressure",
                "inherited_theory_authority": False,
                "channels": list(PRESSURE_CHANNELS),
                "rows": int(len(features)),
                "columns": list(features.columns),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Exported {len(features)} rows × {len(features.columns)} features")
    print(f"Date range: {features.index[0].date()} → {features.index[-1].date()}")
    print(f"Output: {out_path}")
    print()
    print("Features:")
    for col in features.columns:
        valid = features[col].notna().sum()
        print(f"  {col}: {valid} valid / {len(features)} total")


if __name__ == "__main__":
    main()
