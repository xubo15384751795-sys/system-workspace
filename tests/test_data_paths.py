"""Tests for canonical data path resolution."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from _data_paths import (
    resolve_benchmark_panel_path,
    resolve_cross_asset_panel_path,
)


def _write_panel(path: Path, date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime([date]),
            "symbol": ["SPY"],
            "close": [1.0],
        }
    ).to_parquet(path, index=False)


def test_resolve_benchmark_panel_path() -> None:
    path = resolve_benchmark_panel_path()
    assert path.name == "benchmark_panel.parquet"
    assert "harvester" in path.parts


def test_resolve_cross_asset_panel_prefers_fresher_harvester(tmp_path: Path, monkeypatch) -> None:
    import _data_paths as dp
    import _runtime_io as rio

    harvester = tmp_path / "Data" / "harvester" / "exports" / "latest" / "data"
    mirror = tmp_path / "Data" / "panels"
    h_file = harvester / "cross_asset_daily_panel.parquet"
    m_file = mirror / "cross_asset_daily_panel.parquet"
    _write_panel(h_file, "2026-07-10")
    _write_panel(m_file, "2026-06-04")

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "HARVESTER_LATEST", tmp_path / "Data" / "harvester" / "exports" / "latest")
    monkeypatch.setattr(dp, "HARVESTER_DATA", harvester)

    assert resolve_cross_asset_panel_path() == h_file


def test_resolve_cross_asset_panel_prefers_fresher_mirror(tmp_path: Path, monkeypatch) -> None:
    import _data_paths as dp
    import _runtime_io as rio

    harvester = tmp_path / "Data" / "harvester" / "exports" / "latest" / "data"
    mirror = tmp_path / "Data" / "panels"
    h_file = harvester / "cross_asset_daily_panel.parquet"
    m_file = mirror / "cross_asset_daily_panel.parquet"
    _write_panel(h_file, "2026-06-04")
    _write_panel(m_file, "2026-07-10")

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "HARVESTER_LATEST", tmp_path / "Data" / "harvester" / "exports" / "latest")
    monkeypatch.setattr(dp, "HARVESTER_DATA", harvester)

    assert resolve_cross_asset_panel_path() == m_file


def test_resolve_cross_asset_panel_falls_back_to_mirror(tmp_path: Path, monkeypatch) -> None:
    import _data_paths as dp
    import _runtime_io as rio

    mirror = tmp_path / "Data" / "panels"
    m_file = mirror / "cross_asset_daily_panel.parquet"
    _write_panel(m_file, "2026-07-10")

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "HARVESTER_LATEST", tmp_path / "Data" / "harvester" / "exports" / "latest")
    monkeypatch.setattr(dp, "HARVESTER_DATA", tmp_path / "Data" / "harvester" / "exports" / "latest" / "data")

    assert resolve_cross_asset_panel_path() == m_file
