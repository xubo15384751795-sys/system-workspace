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


def test_duckdb_writer_is_default_and_can_be_explicitly_enabled(
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


def test_duckdb_writer_is_default_when_rollback_flag_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SYSTEM_DUCKDB_CANONICAL_PANEL", raising=False)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY"],
    )

    mirror = sync_panel_to_workspace(_panel(), tmp_path)

    assert mirror.exists()
    assert (tmp_path / "Data" / "canonical" / "panels.duckdb").is_file()


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
    assert duckdb_canonical_panel_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_canonical_writer_escape_hatch_disables_flag(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYSTEM_DUCKDB_CANONICAL_PANEL", value)
    assert duckdb_canonical_panel_enabled() is False


@pytest.mark.parametrize("value", ["maybe", ""])
def test_canonical_writer_unknown_values_stay_enabled(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYSTEM_DUCKDB_CANONICAL_PANEL", value)
    assert duckdb_canonical_panel_enabled() is True


def test_duckdb_export_matches_legacy_mirror_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = _panel()
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY"],
    )

    monkeypatch.setenv("SYSTEM_DUCKDB_CANONICAL_PANEL", "0")
    legacy = sync_panel_to_workspace(frame, tmp_path / "legacy")

    monkeypatch.delenv("SYSTEM_DUCKDB_CANONICAL_PANEL", raising=False)
    modern = sync_panel_to_workspace(frame, tmp_path / "modern")

    legacy_frame = pd.read_parquet(legacy)
    modern_frame = pd.read_parquet(modern)

    assert set(modern_frame.columns) == set(legacy_frame.columns)
    assert len(modern_frame) == len(legacy_frame)

    keys = ["symbol", "date"]
    assert (
        modern_frame[keys].sort_values(keys).reset_index(drop=True)
        .equals(legacy_frame[keys].sort_values(keys).reset_index(drop=True))
    )
    assert modern_frame["close"].tolist() == pytest.approx(legacy_frame["close"].tolist())
    for column in modern_frame.columns:
        if column in ("symbol", "date"):
            continue
        if modern_frame[column].notna().any():
            assert pd.api.types.is_float_dtype(modern_frame[column])
