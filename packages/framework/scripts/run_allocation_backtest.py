"""Run the comparative asset-allocation backtest.

Strategies:
  buy_and_hold, sixty_forty, risk_parity, vol_target,
  sigma_regime, channel_aware, plus controls per stress index
  (NFCI, KCFSI, STLFSI4) using the SAME allocation rule.

Equity input: SP500 (FRED price index, daily).
Bond input:   BAMLCC0A0CMTRIV (FRED IG total-return index, daily).

Both are FRED-fetchable. Sigma and channels come from the structural signal
built on weekly_frame and forward-filled to daily for backtest alignment.

Outputs:
  output/allocation_backtest/equity_curves.csv
  output/allocation_backtest/metrics.csv
  output/allocation_backtest/head_to_head_vs_sixty_forty.csv
  output/allocation_backtest/head_to_head_vs_nfci.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

import numpy as np
import pandas as pd

from src.benchmarks.benchmark_panel import all_fred_ids
from src.benchmarks.historical_replay import (
    build_structural_signals,
    fetch_default_fred_frame,
    fetch_fred_graph_series,
    weekly_frame,
)
from src.benchmarks.portfolio_baselines import (
    head_to_head,
    run_strategy_panel,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--panel", default=None, help="Merged panel CSV (if absent, fetch live)")
    p.add_argument("--start", default="2008-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--out-dir", default="output/allocation_backtest")
    p.add_argument("--equity-id", default="SP500")
    p.add_argument("--bond-id", default="BAMLCC0A0CMTRIV")
    p.add_argument("--cache-dir", default="data/raw/fred")
    return p.parse_args()


def _load_or_fetch_series(series_id: str, panel: pd.DataFrame | None, cache_dir: str) -> pd.Series:
    if panel is not None and series_id in panel.columns:
        s = pd.to_numeric(panel[series_id], errors="coerce").dropna()
        s.name = series_id
        return s
    return fetch_fred_graph_series(series_id, cache_dir=cache_dir)


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    panel: pd.DataFrame | None = None
    if args.panel:
        panel = pd.read_csv(args.panel, index_col="date", parse_dates=True).sort_index()

    print(f"Loading {args.equity_id} (equity) and {args.bond_id} (bond) ...")
    equity = _load_or_fetch_series(args.equity_id, panel, args.cache_dir)
    bond = _load_or_fetch_series(args.bond_id, panel, args.cache_dir)

    prices = pd.concat({"equity": equity, "bond": bond}, axis=1).dropna(how="all").ffill()
    prices = prices.loc[pd.Timestamp(args.start) :]
    if args.end:
        prices = prices.loc[: pd.Timestamp(args.end)]
    prices = prices.dropna()
    if prices.empty:
        raise RuntimeError("No price overlap; check series IDs and date range")
    print(f"  prices shape: {prices.shape}, range: {prices.index.min().date()} -> {prices.index.max().date()}")

    print("Building structural signals (weekly -> daily forward-fill) ...")
    if panel is None:
        macro_panel = fetch_default_fred_frame()
    else:
        macro_panel = panel
    weekly = weekly_frame(macro_panel, args.start, args.end or prices.index.max().date().isoformat())
    signals = build_structural_signals(weekly)
    sigma = signals["joint_structural"].rename("SIGMA")
    channels = signals[["M", "D", "K", "X"]]

    sigma_daily = sigma.reindex(prices.index, method="ffill")
    channels_daily = channels.reindex(prices.index, method="ffill")

    extra_signals: dict[str, pd.Series] = {}
    for ctrl in ("NFCI", "ANFCI", "STLFSI4", "KCFSI"):
        if ctrl in weekly.columns:
            extra_signals[ctrl.lower()] = weekly[ctrl].reindex(prices.index, method="ffill").rename(ctrl)

    regime = pd.Series(
        np.where(sigma_daily >= sigma_daily.quantile(0.85), "stress", "calm"),
        index=prices.index,
        name="regime",
    )

    print("Running strategies ...")
    comparison = run_strategy_panel(
        prices=prices,
        sigma=sigma_daily,
        channels=channels_daily,
        extra_signals=extra_signals,
        regime=regime,
    )

    metrics = comparison.metrics_frame()
    curves = comparison.equity_curves()

    metrics_path = out_dir / "metrics.csv"
    curves_path = out_dir / "equity_curves.csv"
    h2h_60_40_path = out_dir / "head_to_head_vs_sixty_forty.csv"

    metrics.to_csv(metrics_path)
    curves.to_csv(curves_path, index_label="date")
    head_to_head(comparison, baseline="sixty_forty").to_csv(h2h_60_40_path)

    nfci_baseline = "nfci_regime"
    if nfci_baseline in metrics.index:
        head_to_head(comparison, baseline=nfci_baseline).to_csv(out_dir / "head_to_head_vs_nfci.csv")

    print()
    pd.set_option("display.float_format", lambda x: f"{x:.3f}")
    keep_cols = [c for c in ("annual_return", "annual_vol", "sharpe", "max_drawdown", "calmar") if c in metrics.columns]
    print(metrics[keep_cols].to_string())
    print()
    print(f"Wrote {metrics_path}")
    print(f"Wrote {curves_path}")
    print(f"Wrote {h2h_60_40_path}")


if __name__ == "__main__":
    main()
