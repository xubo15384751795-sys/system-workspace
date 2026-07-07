"""Calibrate sigma and joint-hitting thresholds from a training window.

Reads the snapshots parquet, filters to the training window (default 2007–2016),
computes percentile-based thresholds for sigma_t, D (DoF collapse), K (curvature
spike), and X (forced realization), then writes the calibrated values back to
config.yaml under thresholds.sigma and thresholds.joint_hitting.

Usage:
    python3 scripts/calibrate_thresholds.py [--train-end 2016-12-31]

The script does NOT commit the config change — review the diff before committing.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import yaml


SNAPSHOTS_DEFAULT = Path("/Users/a1/System/Data/structural_lab/processed/snapshots/snapshots.parquet")
CONFIG_PATH = ROOT / "config.yaml"

SIGMA_PCT = 90          # sigma_t value at this percentile → threshold
DOF_PCT = 10            # D value at this percentile → dof_collapse (low end)
CURVATURE_PCT = 90      # K value at this percentile → curvature_spike
REALIZATION_PCT = 90    # X value at this percentile → forced_realization


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--snapshots", default=str(SNAPSHOTS_DEFAULT))
    p.add_argument("--train-start", default="2007-01-01")
    p.add_argument("--train-end", default="2016-12-31")
    p.add_argument("--sigma-pct", type=float, default=SIGMA_PCT)
    p.add_argument("--dof-pct", type=float, default=DOF_PCT)
    p.add_argument("--curvature-pct", type=float, default=CURVATURE_PCT)
    p.add_argument("--realization-pct", type=float, default=REALIZATION_PCT)
    p.add_argument("--dry-run", action="store_true", help="Print calibrated values without writing config")
    return p.parse_args()


def load_snapshots(path: str, train_start: str, train_end: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df = df.set_index("date")
    df.index = pd.to_datetime(df.index)
    mask = (df.index >= pd.Timestamp(train_start)) & (df.index <= pd.Timestamp(train_end))
    train = df.loc[mask]
    print(f"Training window: {train_start} to {train_end} — {len(train)} observations")
    return train


def compute_thresholds(df: pd.DataFrame, args: argparse.Namespace) -> dict[str, float]:
    def pct(series_name: str, q: float) -> float | None:
        if series_name not in df.columns:
            return None
        col = pd.to_numeric(df[series_name], errors="coerce").dropna()
        if col.empty:
            return None
        return float(np.percentile(col, q))

    sigma_thresh = pct("sigma_t", args.sigma_pct)
    dof_thresh = pct("D", args.dof_pct)
    curv_thresh = pct("K", args.curvature_pct)
    real_thresh = pct("X", args.realization_pct)

    print(f"  sigma_t P{args.sigma_pct:.0f}  = {sigma_thresh}")
    print(f"  D       P{args.dof_pct:.0f}   = {dof_thresh}")
    print(f"  K       P{args.curvature_pct:.0f}  = {curv_thresh}")
    print(f"  X       P{args.realization_pct:.0f}  = {real_thresh}")

    return {
        "sigma": sigma_thresh,
        "dof_collapse": dof_thresh,
        "curvature_spike": curv_thresh,
        "forced_realization": real_thresh,
    }


def patch_config(thresholds: dict[str, float | None], dry_run: bool) -> None:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    changed: list[str] = []
    if thresholds.get("sigma") is not None:
        old = cfg.get("thresholds", {}).get("sigma")
        cfg.setdefault("thresholds", {})["sigma"] = round(float(thresholds["sigma"]), 4)
        changed.append(f"thresholds.sigma: {old} → {cfg['thresholds']['sigma']}")

    jh = cfg.setdefault("thresholds", {}).setdefault("joint_hitting", {})
    for key in ("dof_collapse", "curvature_spike", "forced_realization"):
        if thresholds.get(key) is not None:
            old = jh.get(key)
            jh[key] = round(float(thresholds[key]), 4)
            changed.append(f"thresholds.joint_hitting.{key}: {old} → {jh[key]}")

    proto = cfg.setdefault("thresholds", {}).setdefault("protocol", {})
    proto["calibration_mode"] = "percentile_from_training_window"
    proto["frozen"] = True
    changed.append("thresholds.protocol.frozen: → True (freeze after calibration)")

    if dry_run:
        print("\n[DRY RUN] Would write to config.yaml:")
        for c in changed:
            print(f"  {c}")
        return

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"\nWrote calibrated thresholds to {CONFIG_PATH}:")
    for c in changed:
        print(f"  {c}")


def main() -> None:
    args = parse_args()
    if not Path(args.snapshots).exists():
        print(f"Snapshots not found at {args.snapshots}")
        print("Run the full pipeline first to generate snapshots, then re-run calibration.")
        sys.exit(1)

    df = load_snapshots(args.snapshots, args.train_start, args.train_end)
    thresholds = compute_thresholds(df, args)
    patch_config(thresholds, args.dry_run)


if __name__ == "__main__":
    main()
