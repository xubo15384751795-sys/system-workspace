from __future__ import annotations

from pathlib import Path

import pandas as pd

from harvester.operators.verify_duckdb_default_path import verify_default_path


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-18", "2026-08-19"]),
            "symbol": ["SPY", "SPY"],
            "open": [99.0, 100.0],
            "high": [101.0, 102.0],
            "low": [98.0, 99.0],
            "close": [100.0, 101.0],
            "volume": [1000.0, 1100.0],
            "return_1d": [None, 0.01],
            "return_5d": [None, None],
            "return_20d": [None, None],
            "return_60d": [None, None],
            "volatility_20d": [None, None],
            "drawdown_60d": [None, None],
        }
    )


def test_default_writer_consumer_evidence_is_isolated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SYSTEM_DUCKDB_CANONICAL_PANEL", raising=False)
    input_panel = tmp_path / "input.parquet"
    _panel().to_parquet(input_panel, index=False)

    report = verify_default_path(
        input_panel=input_panel,
        workspace_root=tmp_path / "scratch",
        expected_symbols=["SPY"],
    )

    assert report["status"] == "MATCH"
    assert report["default_writer_enabled"] is True
    assert report["consumer_shape_match"] is True
    assert report["consumer_digest"] == report["source_digest"]
    assert report["database"]["primary_key_unique"] is True
    assert report["database"]["close_check_satisfied"] is True
    assert report["blocked_without_clobber"] is True
    assert report["workspace_current_touched"] is False


def test_default_path_evidence_fails_closed_when_rollback_is_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SYSTEM_DUCKDB_CANONICAL_PANEL", "0")
    input_panel = tmp_path / "input.parquet"
    _panel().to_parquet(input_panel, index=False)

    report = verify_default_path(
        input_panel=input_panel,
        workspace_root=tmp_path / "scratch",
        expected_symbols=["SPY"],
    )

    assert report["status"] == "BLOCKED"
    assert not (tmp_path / "scratch" / "Data" / "canonical" / "panels.duckdb").exists()
