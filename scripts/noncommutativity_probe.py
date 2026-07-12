#!/usr/bin/env python3
"""WP-T4 research-only noncommutativity probe.

Computes a threshold-VAR impulse order-distance Delta^NC. This script is a
diagnostic stub only; it does not feed promotion or current-state outputs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
DEFAULT_OUTPUT = ROOT / "Output" / "validation" / "noncommutativity_probe"


def threshold_var_order_distance(
    panel: pd.DataFrame,
    first: str,
    second: str,
    *,
    threshold_quantile: float = 0.75,
    horizon: int = 20,
) -> pd.Series:
    """Distance between first-then-second and second-then-first impulse paths."""
    data = panel[[first, second]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(data) < 80:
        return pd.Series(np.nan, index=panel.index, name="delta_nc")
    threshold = data.expanding(60).quantile(threshold_quantile).shift(1)
    shocks = data.diff()
    out = pd.Series(np.nan, index=data.index, name="delta_nc")
    for i in range(60, len(data) - horizon):
        hit_first = shocks[first].iloc[i] > threshold[first].iloc[i]
        hit_second = shocks[second].iloc[i] > threshold[second].iloc[i]
        if not (hit_first or hit_second):
            continue
        path_a = data[first].iloc[i + 1:i + horizon + 1].to_numpy() - data[first].iloc[i]
        path_b = data[second].iloc[i + 1:i + horizon + 1].to_numpy() - data[second].iloc[i]
        if np.isfinite(path_a).all() and np.isfinite(path_b).all():
            out.iloc[i] = float(np.linalg.norm(path_a - path_b) / np.sqrt(horizon))
    return out.reindex(panel.index)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--first", default="channel_M")
    parser.add_argument("--second", default="channel_K")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    frame = pd.read_parquet(args.panel).sort_index()
    result = threshold_var_order_distance(frame, args.first, args.second)
    args.output.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output / "delta_nc.csv", index_label="date")
    print({"status": "ok", "output": str(args.output)})
