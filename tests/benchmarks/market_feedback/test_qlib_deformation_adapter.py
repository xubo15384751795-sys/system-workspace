"""Tests for the isolated Qlib deformation-feature adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RUNNER_ROOT = Path(__file__).resolve().parents[3] / "ExternalTools" / "qlib_benchmark_runner"
sys.path.insert(0, str(RUNNER_ROOT))

from run_qlib_benchmark import (  # noqa: E402
    _convert_market_panel_to_qlib,
    _deformation_feature_status,
    _read_deformation_features,
)


def _market_panel(dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for instrument in ("AAA", "BBB"):
        for index, date in enumerate(dates):
            rows.append(
                {
                    "instrument": instrument,
                    "date": date,
                    "open": 100.0 + index,
                    "high": 101.0 + index,
                    "low": 99.0 + index,
                    "close": 100.5 + index,
                    "volume": 1000.0 + index,
                }
            )
    return pd.DataFrame(rows)


def test_deformation_index_is_normalized_and_written_for_each_instrument(tmp_path: Path) -> None:
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    sandbox = tmp_path / "sandbox_input"
    sandbox.mkdir()
    _market_panel(dates).to_parquet(sandbox / "market_panel.parquet", index=False)
    pd.DataFrame(
        {
            "deform_M": np.linspace(0.1, 0.5, len(dates)),
            "deform_stress_level": np.linspace(1.0, 2.0, len(dates)),
        },
        index=pd.DatetimeIndex(dates),
    ).to_parquet(sandbox / "deformation_features.parquet")

    frame, fields, error = _read_deformation_features(sandbox)
    assert error is None
    assert frame is not None
    assert fields == ["deform_M", "deform_stress_level"]
    assert frame["date"].iloc[0] == dates[0]

    qlib_data = tmp_path / "qlib_data"
    _convert_market_panel_to_qlib(sandbox, qlib_data)

    for instrument in ("aaa", "bbb"):
        assert (qlib_data / "features" / instrument / "deform_m.day.bin").exists()
        assert (qlib_data / "features" / instrument / "deform_stress_level.day.bin").exists()
        payload = np.frombuffer(
            (qlib_data / "features" / instrument / "deform_m.day.bin").read_bytes(),
            dtype="<f4",
        )
        assert len(payload) == len(dates) + 1

    manifest = json.loads((qlib_data / "deformation_features_manifest.json").read_text())
    assert manifest["matched_market_dates"] == len(dates)
    assert _deformation_feature_status("treatment_alpha158", sandbox, qlib_data) == (
        "integrated",
        True,
        str(sandbox / "deformation_features.parquet"),
    )


def test_deformation_dates_without_market_overlap_fail_closed(tmp_path: Path) -> None:
    dates = pd.date_range("2024-01-02", periods=2, freq="B")
    sandbox = tmp_path / "sandbox_input"
    sandbox.mkdir()
    _market_panel(dates).to_parquet(sandbox / "market_panel.parquet", index=False)
    pd.DataFrame(
        {"deform_M": [1.0, 2.0]},
        index=pd.date_range("2025-01-02", periods=2, freq="B"),
    ).to_parquet(sandbox / "deformation_features.parquet")

    with pytest.raises(ValueError, match="do not overlap"):
        _convert_market_panel_to_qlib(sandbox, tmp_path / "qlib_data")
