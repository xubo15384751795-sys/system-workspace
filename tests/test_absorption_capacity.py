from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.absorption_capacity import build_absorption_capacity, case_baseline_check


def test_absorption_capacity_accepts_channel_aliases_and_optional_buffers() -> None:
    index = pd.date_range("2020-01-01", periods=260, freq="B")
    channels = pd.DataFrame(
        {
            "channel_M": np.sin(np.linspace(0, 4, 260)),
            "channel_D_contraction": np.linspace(1.0, 0.0, 260),
            "channel_K": np.cos(np.linspace(0, 4, 260)),
            "channel_X_agg": np.linspace(0.0, 1.0, 260),
        },
        index=index,
    )
    panel = pd.DataFrame(
        {
            "FRED:WRESBAL": np.linspace(100, 200, 260),
            "bank_assets_proxy": np.linspace(1_000, 1_100, 260),
            "FRED:RRPONTSYD": np.linspace(50, 150, 260),
            "bank_equity_over_assets": np.linspace(0.08, 0.12, 260),
        },
        index=index,
    )
    result = build_absorption_capacity(channels, panel, min_periods=50)
    assert list(result.columns) == ["absorption_A", "absorption_A_deterioration"]
    assert result["absorption_A"].dropna().notna().any()
    assert result["absorption_A_deterioration"].dropna().notna().any()


def test_absorption_capacity_uses_x_stock_when_channel_x_missing() -> None:
    index = pd.RangeIndex(220)
    channels = pd.DataFrame(
        {
            "M": np.linspace(0.0, 1.0, 220),
            "D": np.linspace(1.0, 0.0, 220),
            "K": np.linspace(0.2, 0.8, 220),
        },
        index=index,
    )
    panel = pd.DataFrame({"TOTRESNS": np.linspace(10, 20, 220), "RRPONTSYD": np.linspace(5, 10, 220)}, index=index)
    x_stock = pd.Series(np.linspace(0.0, 2.0, 220), index=index)
    result = build_absorption_capacity(channels, panel, x_stock=x_stock, min_periods=40)
    assert result["absorption_A"].notna().sum() > 50
    assert result["absorption_A"].dropna().between(-1.0, 1.0).all()


def test_case_baseline_check_flags_below_prior_mean() -> None:
    index = pd.date_range("2020-01-01", periods=160, freq="B")
    series = pd.Series(1.0, index=index)
    series.iloc[-1] = 0.0
    checks = case_baseline_check(series, [index[-1]], lookback_days=126)
    item = checks[str(index[-1].date())]
    assert item["below_prior_mean"] is True
    assert item["lookback_observations"] == 126
