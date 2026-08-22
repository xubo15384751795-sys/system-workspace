from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.validate_data_contract_replay import replay_data_contract


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-20"]),
            "symbol": ["SPY"],
            "open": [99.0],
            "high": [101.0],
            "low": [98.0],
            "close": [100.0],
            "volume": [1_000.0],
        }
    )


def _write_targets(root: Path, frame: pd.DataFrame) -> tuple[Path, Path]:
    mirror = root / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    release = (
        root
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "data"
        / "cross_asset_daily_panel.parquet"
    )
    mirror.parent.mkdir(parents=True)
    release.parent.mkdir(parents=True)
    frame.to_parquet(mirror, index=False)
    frame.to_parquet(release, index=False)
    return mirror, release


def test_replay_reads_both_real_data_surfaces_without_writing(tmp_path: Path) -> None:
    mirror, release = _write_targets(tmp_path, _frame())
    before = (mirror.read_bytes(), release.read_bytes())

    report = replay_data_contract(tmp_path, expected_symbols=["SPY"])

    assert report["status"] == "PASS"
    assert {item["name"] for item in report["reports"]} == {
        "workspace_mirror",
        "latest_release",
    }
    assert (mirror.read_bytes(), release.read_bytes()) == before


def test_replay_blocks_invalid_surface_and_preserves_bytes(tmp_path: Path) -> None:
    frame = _frame().drop(columns=["volume"])
    mirror, release = _write_targets(tmp_path, frame)
    before = (mirror.read_bytes(), release.read_bytes())

    report = replay_data_contract(tmp_path, expected_symbols=["SPY"])

    assert report["status"] == "BLOCK"
    assert all(item["violations"] for item in report["reports"])
    assert (mirror.read_bytes(), release.read_bytes()) == before
