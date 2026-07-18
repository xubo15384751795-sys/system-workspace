"""Qlib Feature Exporter — prepare M/D/K/X velocity features for Qlib.

Generates deformation_features.parquet with market-level structural
features that can be broadcast to all instruments in the Qlib pipeline.

Features exported:
  - Raw channels: deform_M, deform_D, deform_K, deform_X
  - Velocity (5d/10d/20d change): deform_M_vel5, deform_M_vel10, deform_M_vel20, etc.
  - Cofire count: deform_cofire_5d, deform_cofire_10d, deform_cofire_20d
  - Velocity gate signal: deform_velocity_gate (0 or 1)
  - Stress level: deform_stress_level (continuous 0-1)

Usage:
    python scripts/strategy_lab/qlib_features.py
    python scripts/strategy_lab/qlib_features.py --output /path/to/sandbox_input/
"""
from __future__ import annotations

import argparse
import sys
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


def build_features(
    start: str = "2000-01-01",
    end: str | None = None,
) -> pd.DataFrame:
    """Build M/D/K/X velocity features for Qlib.

    Returns DataFrame indexed by date with deform_* columns.
    """
    signals = load_signals(start=start, end=end)

    features = pd.DataFrame(index=signals.index)

    # ── Raw channels ─────────────────────────────────────────────────
    for ch in ["M", "D", "K", "X"]:
        features[f"deform_{ch}"] = signals[ch]

    # ── Velocity features (change over window) ───────────────────────
    for window in [5, 10, 20]:
        velocity = signals.diff(window)
        for ch in ["M", "D", "K", "X"]:
            features[f"deform_{ch}_vel{window}"] = velocity[ch]

    # ── Cofire count (channels deteriorating together) ───────────────
    for window in [5, 10, 20]:
        velocity = signals.diff(window)
        cofire = pd.Series(0, index=signals.index)
        for ch in ["M", "D", "K", "X"]:
            cofire += (velocity[ch] > DEFAULT_COFIRE_V).astype(int)
        features[f"deform_cofire_{window}d"] = cofire

    # ── Velocity gate signal (binary) ────────────────────────────────
    gate = compute_velocity_gate(signals)
    features["deform_velocity_gate"] = gate

    # ── Stress level (continuous 0-1, based on max velocity) ─────────
    velocity_20d = signals.diff(20)
    max_vel = pd.Series(0.0, index=signals.index)
    for ch in ["M", "D", "K", "X"]:
        max_vel = np.maximum(max_vel, velocity_20d[ch].fillna(0))
    # Normalize: velocity > threshold = stress, scale to 0-1
    stress = np.clip((max_vel - DEFAULT_VELOCITY_THRESHOLD) / 2.0, 0, 1)
    features["deform_stress_level"] = stress

    # ── Channel-specific stress flags ────────────────────────────────
    for ch in ["M", "D", "K", "X"]:
        vel = velocity_20d[ch].fillna(0)
        features[f"deform_{ch}_stress_flag"] = (vel > 0.3).astype(float)

    # ── Rolling volatility of channels (signal noise measure) ────────
    for ch in ["M", "D", "K", "X"]:
        features[f"deform_{ch}_vol20d"] = signals[ch].rolling(20).std()

    return features


def main() -> None:
    parser = argparse.ArgumentParser(description="Export M/D/K/X velocity features for Qlib")
    parser.add_argument("--start", type=str, default="2000-01-01")
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--output", type=str, default=None, help="Output directory")
    args = parser.parse_args()

    features = build_features(start=args.start, end=args.end)

    out_dir = Path(args.output) if args.output else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / "deformation_features.parquet"
    features.to_parquet(out_path)

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
