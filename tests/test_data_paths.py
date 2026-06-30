"""Tests for canonical data path resolution."""
from __future__ import annotations

from pathlib import Path

from _data_paths import (
    resolve_benchmark_panel_path,
    resolve_cross_asset_panel_path,
)


def test_resolve_benchmark_panel_path() -> None:
    path = resolve_benchmark_panel_path()
    assert path.name == "benchmark_panel.parquet"
    assert "harvester" in path.parts


def test_resolve_cross_asset_panel_prefers_harvester(tmp_path: Path, monkeypatch) -> None:
    import _data_paths as dp
    import _runtime_io as rio

    harvester = tmp_path / "Data" / "harvester" / "exports" / "latest" / "data"
    harvester.mkdir(parents=True)
    mirror = tmp_path / "Data" / "panels"
    mirror.mkdir(parents=True)
    h_file = harvester / "cross_asset_daily_panel.parquet"
    m_file = mirror / "cross_asset_daily_panel.parquet"
    h_file.write_bytes(b"h")
    m_file.write_bytes(b"m")

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "HARVESTER_LATEST", tmp_path / "Data" / "harvester" / "exports" / "latest")
    monkeypatch.setattr(dp, "HARVESTER_DATA", harvester)

    assert resolve_cross_asset_panel_path() == h_file


def test_resolve_cross_asset_panel_falls_back_to_mirror(tmp_path: Path, monkeypatch) -> None:
    import _data_paths as dp
    import _runtime_io as rio

    mirror = tmp_path / "Data" / "panels"
    mirror.mkdir(parents=True)
    m_file = mirror / "cross_asset_daily_panel.parquet"
    m_file.write_bytes(b"m")

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "HARVESTER_LATEST", tmp_path / "Data" / "harvester" / "exports" / "latest")
    monkeypatch.setattr(dp, "HARVESTER_DATA", tmp_path / "Data" / "harvester" / "exports" / "latest" / "data")

    assert resolve_cross_asset_panel_path() == m_file
