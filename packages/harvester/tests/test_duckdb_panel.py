from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from harvester.cross_asset_panel import sync_panel_to_workspace
from harvester.duckdb_panel import duckdb_canonical_panel_enabled, write_canonical_panel


def _panel(close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-18", "2026-08-19"]),
            "symbol": ["SPY", "SPY"],
            "open": [99.0, 100.0],
            "high": [101.0, 102.0],
            "low": [98.0, 99.0],
            "close": [close, close + 1.0],
            "volume": [1000.0, 1100.0],
            "return_1d": [None, 0.01],
            "return_5d": [None, None],
            "return_20d": [None, None],
            "return_60d": [None, None],
            "volatility_20d": [None, None],
            "drawdown_60d": [None, None],
        }
    )


def test_duckdb_writer_enforces_primary_key_and_exports_compatibility_parquet(
    tmp_path: Path,
) -> None:
    result = write_canonical_panel(
        _panel(),
        workspace=tmp_path,
        expected_symbols=["SPY"],
    )

    assert result["row_count"] == 2
    assert result["data_contract"]["status"] == "PASS"
    assert result["exported_data_contract"] is None

    import duckdb

    with duckdb.connect(result["database_path"]) as connection:
        rows = connection.execute(
            "SELECT symbol, date, close FROM cross_asset_daily_panel "
            "ORDER BY date"
        ).fetchall()
        assert len(rows) == 2
        with pytest.raises(duckdb.ConstraintException):
            connection.execute(
                "INSERT INTO cross_asset_daily_panel "
                "(date, symbol, open, high, low, close, volume) "
                "VALUES ('2026-08-18', 'SPY', 99, 101, 98, 100, 1000)"
            )


def test_duckdb_writer_validates_export_and_preserves_existing_parquet_on_block(
    tmp_path: Path,
) -> None:
    parquet_path = tmp_path / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    first = write_canonical_panel(
        _panel(),
        workspace=tmp_path,
        parquet_path=parquet_path,
        expected_symbols=["SPY"],
    )
    before = parquet_path.read_bytes()
    assert first["exported_data_contract"]["status"] == "PASS"

    invalid = _panel()
    invalid.loc[1, "close"] = 0.0
    with pytest.raises(ValueError, match="DATA_CONTRACT_VIOLATION"):
        write_canonical_panel(
            invalid,
            workspace=tmp_path,
            parquet_path=parquet_path,
            expected_symbols=["SPY"],
        )

    assert parquet_path.read_bytes() == before


def test_duckdb_writer_is_only_used_by_explicit_opt_in_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYSTEM_DUCKDB_CANONICAL_PANEL", "1")
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY"],
    )

    mirror = sync_panel_to_workspace(_panel(), tmp_path)

    assert mirror.exists()
    assert (tmp_path / "Data" / "canonical" / "panels.duckdb").exists()
    assert len(pd.read_parquet(mirror)) == 2


def test_offline_parity_drill_does_not_touch_workspace_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SYSTEM_DUCKDB_CANONICAL_PANEL", raising=False)
    from harvester.duckdb_panel import run_offline_parity_drill

    result = run_offline_parity_drill(
        _panel(),
        scratch=tmp_path / "drill",
        expected_symbols=["SPY"],
    )
    assert result["duplicate_rejected"] is True
    assert result["blocked_without_clobber"] is True
    assert result["canonical_flag_consulted"] is False
    assert not (tmp_path / "Data" / "canonical").exists()
    assert duckdb_canonical_panel_enabled() is False
