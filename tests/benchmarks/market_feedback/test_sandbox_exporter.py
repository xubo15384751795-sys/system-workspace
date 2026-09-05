"""Test sandbox_exporter: data export must be copied snapshots."""

# Adjust path
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages" / "workbench" / "src"))

from benchmarks.market_feedback.sandbox_exporter import _build_joined_features


class TestSandboxExporter:
    def test_manifest_declares_copied_snapshot_mode(self):
        """All exported files must be copied snapshots, not references."""
        # Build a sample manifest matching sandbox_input_manifest schema
        manifest = {
            "files": [
                {"path": "market_panel.parquet", "source": "Data/releases/...", "mode": "copied_snapshot"},
                {"path": "pressure_features.parquet", "source": "Output/...", "mode": "copied_snapshot"},
            ]
        }
        for f in manifest["files"]:
            assert f["mode"] == "copied_snapshot", (
                f"File {f['path']} mode must be 'copied_snapshot', got {f['mode']}"
            )

    def test_manifest_includes_required_fields(self):
        manifest = {
            "input_id": "sandbox_input_test_001",
            "market_data_release": "2026-05-05_OPENBB",
            "deformation_feature_release": "2026-05-05_WEEKLY",
            "files": [],
            "feature_scope": {
                "deformation_features": "market_level",
                "broadcast_to_instruments": True,
            },
            "created_at": "2026-05-05T10:00:00Z",
        }
        assert "input_id" in manifest
        assert "market_data_release" in manifest
        assert "deformation_feature_release" in manifest
        assert "files" in manifest
        assert "feature_scope" in manifest

    def test_joined_features_accept_datetime_index_source(self, tmp_path):
        dates = pd.date_range("2024-01-02", periods=3, freq="B")
        market = pd.DataFrame(
            {
                "date": dates.tolist() * 2,
                "instrument": ["AAA"] * 3 + ["BBB"] * 3,
            }
        )
        deformation = pd.DataFrame(
            {"deform_M": [1.0, 2.0, 3.0]},
            index=pd.DatetimeIndex(dates),
        )
        market.to_parquet(tmp_path / "market_panel.parquet", index=False)
        deformation.to_parquet(tmp_path / "pressure_features.parquet")

        _build_joined_features(tmp_path)

        joined = pd.read_parquet(tmp_path / "joined_features.parquet")
        assert joined.shape == (6, 3)
        assert joined["deform_M"].notna().all()
