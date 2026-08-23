from __future__ import annotations

import pandas as pd
import pytest

from harvester.quality.data_contract import (
    DATA_CONTRACT_VIOLATION,
    DataContractViolation,
    ETF_PRE_LISTING_EXCEPTION,
    validate_cross_asset_panel_contract,
)


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-18", "2026-08-19"]),
            "symbol": ["SPY", "SPY"],
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 101.0],
            "volume": [1.0, 1.0],
        }
    )


def test_cross_asset_contract_reports_coverage_without_failing_degraded_release() -> None:
    report = validate_cross_asset_panel_contract(
        _panel(), expected_symbols=["SPY", "QQQ"], require_nonempty=True
    )

    assert report["status"] == "WARN"
    assert report["coverage"]["missing_symbols"] == ["QQQ"]
    assert report["error_code"] is None


def test_cross_asset_contract_raises_typed_duplicate_violation() -> None:
    frame = pd.concat([_panel(), _panel().iloc[[0]]], ignore_index=True)

    with pytest.raises(DataContractViolation) as exc_info:
        validate_cross_asset_panel_contract(frame, raise_on_error=True)

    assert exc_info.value.code == DATA_CONTRACT_VIOLATION
    assert any(
        item.startswith("duplicate_symbol_date_rows")
        for item in exc_info.value.report["violations"]
    )


def test_cross_asset_contract_allows_only_declared_pre_listing_gap() -> None:
    frame = _panel().iloc[[0]].copy()
    report = validate_cross_asset_panel_contract(
        frame,
        expected_symbols=["SPY", "QQQ"],
        listing_dates={"SPY": "1993-01-29", "QQQ": "2027-01-01"},
        declared_exceptions=[ETF_PRE_LISTING_EXCEPTION],
        require_nonempty=True,
    )

    assert report["status"] == "PASS"
    assert report["coverage"]["missing_symbols"] == []
    assert report["coverage"]["pre_listing_symbols"] == ["QQQ"]


def test_cross_asset_contract_rejects_unlisted_exception() -> None:
    report = validate_cross_asset_panel_contract(
        _panel(),
        declared_exceptions=["任意放宽"],
    )

    assert report["status"] == "BLOCK"
    assert any(
        item.startswith("unsupported_declared_exceptions:")
        for item in report["violations"]
    )


def test_cross_asset_contract_keeps_structured_pandera_diagnostics() -> None:
    frame = _panel().copy()
    frame["close"] = frame["close"].astype(object)
    frame.loc[0, "close"] = "not-a-number"

    report = validate_cross_asset_panel_contract(frame)

    assert report["status"] == "BLOCK"
    assert report["pandera"] == "failed"
    assert report["pandera_report"]["failure_count"] >= 1
    assert report["pandera_report"]["failure_cases"]


def test_cross_asset_contract_rejects_close_as_volume_pollution() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-21"]),
            "symbol": ["HYG"],
            "open": [79.61],
            "high": [79.61],
            "low": [79.61],
            "close": [79.61],
            "volume": [79.61],
        }
    )

    report = validate_cross_asset_panel_contract(frame, require_nonempty=True)

    assert report["status"] == "BLOCK"
    assert report["violations"] == ["volume_equals_close_rows:1"]
