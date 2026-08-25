from __future__ import annotations

import pandas as pd

from harvester.quality.pandera_adapter import validate_cross_asset_panel_with_pandera


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-18", "2026-08-19"]),
            "symbol": ["SPY", "SPY"],
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 101.0],
            "volume": [1.0, 2.0],
        }
    )


def test_pandera_adapter_passes_a_clean_panel() -> None:
    report = validate_cross_asset_panel_with_pandera(_panel())
    assert report["status"] == "passed"
    assert report["failure_count"] == 0


def test_pandera_adapter_rejects_non_positive_close() -> None:
    frame = _panel()
    frame.loc[0, "close"] = 0.0
    report = validate_cross_asset_panel_with_pandera(frame)
    assert report["status"] == "failed"
    assert report["failure_count"] >= 1


def test_pandera_adapter_rejects_non_monotonic_symbol_dates() -> None:
    frame = _panel()
    frame.loc[0, "date"] = pd.Timestamp("2026-08-20")
    report = validate_cross_asset_panel_with_pandera(frame)
    assert report["status"] == "failed"
    assert report["failure_count"] >= 1


def test_pandera_adapter_mirrors_required_nonempty_contract() -> None:
    report = validate_cross_asset_panel_with_pandera(
        _panel().iloc[0:0],
        require_nonempty=True,
    )

    assert report["status"] == "failed"
    assert report["failure_count"] >= 1
