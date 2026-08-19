from __future__ import annotations

import pandas as pd
import pytest

from harvester.quality.data_contract import (
    DATA_CONTRACT_VIOLATION,
    DataContractViolation,
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
