"""Tests for training provenance emitted by the DL anomaly detector."""

from pathlib import Path

from src.data.dual_write_snapshot_store import DualWriteSnapshotStore
from src.data.harvester_snapshot_store import HarvesterSnapshotStore
from src.ml.dl_anomaly_detector import _snapshot_store_provenance


def test_harvester_training_provenance_matches_selected_store(tmp_path: Path) -> None:
    store = HarvesterSnapshotStore(path=str(tmp_path / "snapshots"), data_root=str(tmp_path))

    provenance = _snapshot_store_provenance(store)

    assert provenance == {
        "training_data_source": "snapshot_store_interface",
        "training_data_backend": "harvester_parquet",
        "training_data_store_class": "HarvesterSnapshotStore",
        "training_data_paths": [str(tmp_path / "snapshots")],
    }


def test_dual_write_training_provenance_records_both_store_paths(tmp_path: Path) -> None:
    primary = HarvesterSnapshotStore(path=str(tmp_path / "snapshots"), data_root=str(tmp_path))
    secondary = type("LegacyStore", (), {"path": tmp_path / "legacy.duckdb"})()
    store = DualWriteSnapshotStore(primary=primary, secondary=secondary)  # type: ignore[arg-type]

    provenance = _snapshot_store_provenance(store)

    assert provenance["training_data_backend"] == "dual_write_harvester_primary"
    assert provenance["training_data_store_class"] == "DualWriteSnapshotStore"
    assert provenance["training_data_paths"] == [
        str(tmp_path / "snapshots"),
        str(tmp_path / "legacy.duckdb"),
    ]
