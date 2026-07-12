#!/usr/bin/env python3
"""WP-T2 absorption-capacity research candidate.

Shadow-only: writes validation artifacts and does not alter current-state or
promotion paths.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from professional_methods import causal_pit, folded_pit
except ModuleNotFoundError:
    from scripts.professional_methods import causal_pit, folded_pit


def _folded_pit(series: pd.Series, *, min_periods: int = 126) -> pd.Series:
    return folded_pit(series, min_periods=min_periods)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANNELS = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
DEFAULT_OUTPUT = ROOT / "Output" / "validation" / "absorption_capacity"


def _default_panel_path() -> Path:
    try:
        from _data_paths import resolve_benchmark_panel_path
    except ModuleNotFoundError:
        from scripts._data_paths import resolve_benchmark_panel_path
    return resolve_benchmark_panel_path()

CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "M": ("channel_M", "M"),
    "D": ("channel_D_contraction", "D", "D_contraction"),
    "K": ("channel_K", "K"),
    "X": ("channel_X_agg", "X_agg", "X", "x_stock", "x_stock_agg"),
}
PANEL_ALIASES: dict[str, tuple[str, ...]] = {
    "WRESBAL": ("FRED:WRESBAL", "WRESBAL"),
    "TOTRESNS": ("FRED:TOTRESNS", "TOTRESNS"),
    "RRPONTSYD": ("FRED:RRPONTSYD", "RRPONTSYD"),
    "bank_assets_proxy": (
        "bank_assets_proxy",
        "BANK_ASSETS_PROXY",
        "FRED:TLAACBW027SBOG",
        "TLAACBW027SBOG",
    ),
    "bank_equity_over_assets": (
        "bank_equity_over_assets",
        "BANK_EQUITY_OVER_ASSETS",
        "equity_over_assets",
    ),
}


def build_absorption_capacity(
    channels: pd.DataFrame,
    panel: pd.DataFrame | None,
    x_stock: pd.Series | None = None,
    *,
    min_periods: int = 126,
) -> pd.DataFrame:
    """Build WP-T2 absorption capacity and 5-day deterioration candidate."""
    channels = _normalize_channels(channels)
    index = channels.index
    if panel is not None:
        panel = _normalize_panel(panel)
        index = index.union(panel.index).sort_values()
    if x_stock is not None:
        x_stock = pd.to_numeric(x_stock, errors="coerce")
        index = index.union(x_stock.index).sort_values()

    channels = channels.reindex(index)
    panel = panel.reindex(index) if panel is not None else pd.DataFrame(index=index)

    release_inputs: dict[str, pd.Series] = {}
    for name in ("M", "K"):
        if name in channels:
            release_inputs[name] = _folded_pit(channels[name], min_periods=min_periods)
    if "X" in channels:
        release_inputs["X"] = _folded_pit(channels["X"], min_periods=min_periods)
    elif x_stock is not None:
        release_inputs["X"] = _folded_pit(x_stock.reindex(index), min_periods=min_periods)
    release_side = pd.DataFrame(release_inputs, index=index).mean(axis=1, skipna=True)

    absorb_inputs: dict[str, pd.Series] = {}
    if "D" in channels:
        absorb_inputs["freedom"] = 1.0 - causal_pit(channels["D"], min_periods=min_periods)

    reserves = _first_series(panel, PANEL_ALIASES["WRESBAL"])
    if reserves is None:
        reserves = _first_series(panel, PANEL_ALIASES["TOTRESNS"])
    assets = _first_series(panel, PANEL_ALIASES["bank_assets_proxy"])
    if reserves is not None and assets is not None:
        reserve_signal = reserves / assets.replace(0.0, np.nan)
    else:
        reserve_signal = reserves
    if reserve_signal is not None:
        absorb_inputs["reserve_buffer"] = causal_pit(reserve_signal, min_periods=min_periods)

    rrp = _first_series(panel, PANEL_ALIASES["RRPONTSYD"])
    if rrp is not None:
        absorb_inputs["rrp_buffer"] = causal_pit(rrp, min_periods=min_periods)

    equity = _first_series(panel, PANEL_ALIASES["bank_equity_over_assets"])
    if equity is not None:
        absorb_inputs["bank_equity_over_assets"] = causal_pit(equity, min_periods=min_periods)

    absorb_side = pd.DataFrame(absorb_inputs, index=index).mean(axis=1, skipna=True)
    absorption = (absorb_side - release_side).rename("absorption_A")
    return pd.DataFrame(
        {
            "absorption_A": absorption,
            "absorption_A_deterioration": (-absorption.diff(5)).rename("absorption_A_deterioration"),
        },
        index=index,
    )


def case_baseline_check(
    A: pd.Series,
    case_dates: list[Any],
    lookback_days: int = 126,
) -> dict[str, dict[str, Any]]:
    """Check whether A at each case date is below its prior lookback mean."""
    series = pd.to_numeric(A, errors="coerce").sort_index()
    result: dict[str, dict[str, Any]] = {}
    for raw_date in case_dates:
        date = pd.Timestamp(raw_date)
        history = series.loc[:date].dropna()
        if history.empty:
            value = np.nan
            observed_at = None
        else:
            value = float(history.iloc[-1])
            observed_at = str(pd.Timestamp(history.index[-1]).date())
        prior = series.loc[:date].iloc[:-1].dropna().tail(lookback_days)
        prior_mean = float(prior.mean()) if len(prior) else np.nan
        result[str(date.date())] = {
            "observed_at": observed_at,
            "absorption_A": _finite_or_none(value),
            "prior_mean": _finite_or_none(prior_mean),
            "lookback_observations": int(len(prior)),
            "below_prior_mean": bool(np.isfinite(value) and np.isfinite(prior_mean) and value < prior_mean),
        }
    return result


def load_benchmark_panel(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    if {"date", "series_id", "value"}.issubset(raw.columns):
        raw = raw.copy()
        raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
        raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
        return pd.concat(
            {str(k): g.groupby("date", sort=True)["value"].last() for k, g in raw.dropna(subset=["date"]).groupby("series_id")},
            axis=1,
        ).sort_index()
    return _normalize_panel(raw)


def load_series(path: Path) -> pd.Series:
    frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    if isinstance(frame, pd.Series):
        return frame
    date_col = "date" if "date" in frame.columns else frame.columns[0]
    value_cols = [column for column in frame.columns if column != date_col]
    if not value_cols:
        raise ValueError(f"No value column found in {path}")
    return pd.Series(
        pd.to_numeric(frame[value_cols[0]], errors="coerce").to_numpy(),
        index=pd.to_datetime(frame[date_col], errors="coerce"),
        name=value_cols[0],
    ).sort_index()


def run(args: argparse.Namespace) -> dict[str, Any]:
    channels = pd.read_parquet(args.channels)
    panel = load_benchmark_panel(args.panel) if args.panel else None
    x_stock = load_series(args.x_stock) if args.x_stock else None
    output = build_absorption_capacity(channels, panel, x_stock=x_stock, min_periods=args.min_periods)
    checks = case_baseline_check(output["absorption_A"], args.case_dates, lookback_days=args.lookback_days)
    args.output.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output / "absorption_capacity.csv", index_label="date")
    report = {
        "schema_version": "system.absorption_capacity.wp_t2.v1",
        "mode": "research_shadow",
        "inputs": {"channels": str(args.channels), "panel": str(args.panel) if args.panel else None},
        "rows": int(len(output)),
        "latest": {
            key: _finite_or_none(value)
            for key, value in (output.dropna(how="all").iloc[-1].to_dict() if not output.dropna(how="all").empty else {}).items()
        },
        "case_baseline_check": checks,
        "notes": {
            "release_side": "mean(folded PIT of M, K, X_agg or x_stock)",
            "absorb_side": "equal-weight available freedom, reserves, RRP, optional bank equity/assets",
        },
    }
    (args.output / "report.json").write_text(json.dumps(_json_safe(report), indent=2, allow_nan=False), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", type=Path, default=DEFAULT_CHANNELS)
    parser.add_argument("--panel", type=Path, default=None)
    parser.add_argument("--x-stock", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-periods", type=int, default=126)
    parser.add_argument("--lookback-days", type=int, default=126)
    parser.add_argument("--case-dates", nargs="*", default=["2008-09-15", "2020-03-16", "2023-03-10"])
    args = parser.parse_args()
    if args.panel is None:
        try:
            args.panel = _default_panel_path()
        except Exception:
            args.panel = None
    return args


def _normalize_channels(channels: pd.DataFrame) -> pd.DataFrame:
    frame = _normalize_panel(channels)
    out: dict[str, pd.Series] = {}
    for canonical, aliases in CHANNEL_ALIASES.items():
        series = _first_series(frame, aliases)
        if series is not None:
            out[canonical] = series
    if not out:
        raise ValueError("No recognized channel columns found")
    return pd.DataFrame(out, index=frame.index)


def _normalize_panel(frame: pd.DataFrame) -> pd.DataFrame:
    panel = frame.copy()
    if "date" in panel.columns:
        panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
        panel = panel.set_index("date")
    elif _looks_date_like(panel.index):
        try:
            panel.index = pd.to_datetime(panel.index)
        except Exception:
            pass
    panel = panel.sort_index()
    if not panel.index.is_unique:
        panel = panel.groupby(level=0).last()
    return panel


def _looks_date_like(index: pd.Index) -> bool:
    if isinstance(index, pd.DatetimeIndex):
        return False
    if index.dtype.kind in {"M", "O", "U", "S"}:
        sample = index.dropna()[:5]
        return len(sample) > 0 and any("-" in str(value) or "/" in str(value) for value in sample)
    return False


def _first_series(frame: pd.DataFrame, aliases: tuple[str, ...]) -> pd.Series | None:
    lower = {str(column).lower(): column for column in frame.columns}
    for alias in aliases:
        if alias in frame.columns:
            return pd.to_numeric(frame[alias], errors="coerce")
        column = lower.get(alias.lower())
        if column is not None:
            return pd.to_numeric(frame[column], errors="coerce")
    return None


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, bool)) or value is None:
        return value
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    return _finite_or_none(value)


if __name__ == "__main__":
    cli_args = parse_args()
    cli_report = run(cli_args)
    print(json.dumps({"status": "ok", "output": str(cli_args.output), "rows": cli_report["rows"]}))
