"""Tests for DualWriteSnapshotStore — evidence-window bridge.

Verifies that writes fan out to both backends and reads prefer the primary
(Harvester) store with fallback to the secondary (DuckDB).
"""

from __future__ import annotations

import tempfile
import unittest

import numpy as np

from src.core.models import (
    ChannelBeliefState,
    DistributionState,
    NarrativeReading,
    ProxyReading,
    Snapshot,
    StructuralBeliefState,
    StructuralState,
)
from src.data.dual_write_snapshot_store import DualWriteSnapshotStore
from src.data.harvester_snapshot_store import HarvesterSnapshotStore
from src.data.snapshot_store import DuckDBSnapshotStore


def _build_snapshot(run_date: str) -> Snapshot:
    proxy = ProxyReading(
        run_date=run_date,
        M=0.1,
        D=0.2,
        K=0.3,
        X=0.4,
        directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.1, "D": 0.2, "K": 0.3, "X": 0.4},
    )
    state = StructuralState(
        run_date=run_date,
        z_vector=np.ones(6, dtype=float),
        sigma_t=0.5,
        singular_flag=False,
        leading_channel="NONE",
        pattern="STABLE_LOCAL",
        anomaly_score=-0.1,
        reflexivity_flags={"credit": False},
        provenance={"git_hash": "abc"},
        belief_state=StructuralBeliefState(
            run_date=run_date,
            channels={
                "M": ChannelBeliefState(
                    channel="M",
                    raw_point=0.1,
                    transformed_point=0.095,
                    distribution=DistributionState(
                        family="normal",
                        transform="signed_log1p",
                        mean=0.095,
                        variance=0.04,
                        raw_mean=0.1,
                        raw_variance=0.04,
                        lower_q=-0.1,
                        upper_q=0.3,
                        breach_prob=0.1,
                        singular_mass=0.1,
                    ),
                )
            },
            escalation_metrics={"sigma_breach_prob": 0.2},
        ),
    )
    narrative = NarrativeReading(
        run_date=run_date,
        ai_unicorn="ANCHORED",
        clo_cmbs="ANCHORED",
        policy="ANCHORED",
        drift_scores={"ai_unicorn": 0.0},
    )
    return Snapshot(
        run_date=run_date,
        run_type="WEEKLY",
        proxy=proxy,
        state=state,
        narrative=narrative,
        escalation=False,
        escalation_reason=None,
    )


class DualWriteSnapshotStoreTests(unittest.TestCase):
    def test_write_fans_out_to_both_backends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            secondary = DuckDBSnapshotStore(path=f"{tmpdir}/system.duckdb", data_root=tmpdir)
            store = DualWriteSnapshotStore(primary=primary, secondary=secondary)

            snap = _build_snapshot("2026-04-01")
            store.save(snap)

            # Both backends should have the snapshot.
            self.assertIsNotNone(primary.load("2026-04-01"))
            self.assertIsNotNone(secondary.load("2026-04-01"))

    def test_read_prefers_primary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            secondary = DuckDBSnapshotStore(path=f"{tmpdir}/system.duckdb", data_root=tmpdir)
            store = DualWriteSnapshotStore(primary=primary, secondary=secondary)

            snap = _build_snapshot("2026-04-01")
            store.save(snap)

            loaded = store.load("2026-04-01")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_date, "2026-04-01")

    def test_read_falls_back_to_secondary_when_primary_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            secondary = DuckDBSnapshotStore(path=f"{tmpdir}/system.duckdb", data_root=tmpdir)
            store = DualWriteSnapshotStore(primary=primary, secondary=secondary)

            # Write only to secondary (simulating pre-migration data).
            snap = _build_snapshot("2026-04-01")
            secondary.save(snap)

            # Read should fall back to secondary.
            loaded = store.load("2026-04-01")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_date, "2026-04-01")

    def test_load_range_merges_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            secondary = DuckDBSnapshotStore(path=f"{tmpdir}/system.duckdb", data_root=tmpdir)
            store = DualWriteSnapshotStore(primary=primary, secondary=secondary)

            # Primary has 2026-04-01, secondary has 2026-04-01 (dup) + 2026-04-08.
            store.save(_build_snapshot("2026-04-01"))  # writes to both
            secondary.save(_build_snapshot("2026-04-08"))  # secondary only

            subset = store.load_range("2026-04-01", "2026-04-30")
            dates = sorted(snap.run_date for snap in subset)
            self.assertEqual(dates, ["2026-04-01", "2026-04-08"])

    def test_load_latest_before_falls_back_to_secondary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            primary = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            secondary = DuckDBSnapshotStore(path=f"{tmpdir}/system.duckdb", data_root=tmpdir)
            store = DualWriteSnapshotStore(primary=primary, secondary=secondary)

            secondary.save(_build_snapshot("2026-04-01"))

            latest = store.load_latest_before("2026-04-10")
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.run_date, "2026-04-01")


if __name__ == "__main__":
    unittest.main()
