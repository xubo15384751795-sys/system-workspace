"""Contract tests for HarvesterSnapshotStore — mirror test_snapshot_store.py.

Validates the same 7-method contract surface as DuckDBSnapshotStore, but
against the Parquet-backed HarvesterSnapshotStore. The payload_json round-trip
fidelity (including StructuralBeliefState/DistributionState nesting) is the
key invariant.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.core.models import (
    ChannelBeliefState,
    CrossValidation,
    DistributionState,
    FastSignal,
    NarrativeReading,
    ProxyReading,
    Snapshot,
    StructuralBeliefState,
    StructuralState,
)
from src.data.harvester_snapshot_store import HarvesterSnapshotStore


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


class HarvesterSnapshotStoreTests(unittest.TestCase):
    def test_snapshot_store_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            snap = _build_snapshot("2026-04-01")
            store.save(snap)

            loaded = store.load("2026-04-01")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_date, "2026-04-01")
            self.assertEqual(loaded.state.sigma_t, 0.5)
            self.assertIsNotNone(loaded.state.belief_state)
            assert loaded.state.belief_state is not None
            self.assertIn("M", loaded.state.belief_state.channels)

    def test_snapshot_store_load_range_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            store.save(_build_snapshot("2026-04-01"))
            store.save(_build_snapshot("2026-04-08"))
            store.save(_build_snapshot("2026-04-15"))

            subset = store.load_range("2026-04-02", "2026-04-15")
            self.assertEqual([snap.run_date for snap in subset], ["2026-04-08", "2026-04-15"])

    def test_snapshot_store_iterates_range_in_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            for day in ["2026-04-01", "2026-04-08", "2026-04-15"]:
                store.save(_build_snapshot(day))

            subset = list(store.iter_range("2026-04-01", "2026-04-30", batch_size=2))
            self.assertEqual([snap.run_date for snap in subset], ["2026-04-01", "2026-04-08", "2026-04-15"])

    def test_snapshot_store_loads_latest_before_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            store.save(_build_snapshot("2026-04-01"))
            store.save(_build_snapshot("2026-04-08"))

            latest = store.load_latest_before("2026-04-10")
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.run_date, "2026-04-08")
            self.assertIsNone(store.load_latest_before("2026-04-01"))

    def test_snapshot_store_save_is_idempotent_for_same_run_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            snap = _build_snapshot("2026-04-01")
            store.save(snap)
            store.save(snap)

            # UPSERT semantics: one row per run_date (verified via the store API,
            # not raw SQL — the Parquet backend has no SQL engine).
            df = store._read_parquet("snapshots")
            matches = df[df["run_date"] == "2026-04-01"]
            self.assertEqual(len(matches), 1)

    def test_snapshot_store_writes_parquet_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            store.save(_build_snapshot("2026-04-01"))

            # HarvesterSnapshotStore writes normalized tables as Parquet in the
            # snapshots root (not the processed/ mirror tree).
            proxies = Path(tmpdir) / "snapshots" / "proxy_readings.parquet"
            state = Path(tmpdir) / "snapshots" / "structural_state.parquet"
            snaps = Path(tmpdir) / "snapshots" / "snapshots.parquet"
            self.assertTrue(proxies.exists())
            self.assertTrue(state.exists())
            self.assertTrue(snaps.exists())

    def test_snapshot_store_saves_fast_signal_and_cross_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HarvesterSnapshotStore(path=f"{tmpdir}/snapshots", data_root=tmpdir)
            signal = FastSignal(
                date="2026-04-01",
                M_zscore=1.1,
                D_zscore=0.2,
                K_zscore=-0.1,
                X_zscore=1.4,
                composite=0.65,
                alert_level="WATCH",
                threshold_hits=("M", "X"),
                directions={"M": "WORSENING", "D": "STABLE", "K": "STABLE", "X": "WORSENING"},
            )
            store.save_fast_signal(signal)

            loaded = store.load_fast_signal("2026-04-01")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.alert_level, "WATCH")
            self.assertEqual(loaded.threshold_hits, ("M", "X"))

            validation = CrossValidation(
                date="2026-04-01",
                canonical_date="2026-03-30",
                fast_date="2026-04-01",
                verdict="LEADING",
                confidence_multiplier=0.5,
                agreement_per_channel={"M": True, "D": False, "K": False, "X": True},
                canonical_directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
                fast_directions={"M": "WORSENING", "D": "STABLE", "K": "STABLE", "X": "WORSENING"},
                alert_level="WATCH",
            )
            store.save_cross_validation(validation)

            loaded_validation = store.load_cross_validation("2026-04-01")
            self.assertIsNotNone(loaded_validation)
            assert loaded_validation is not None
            self.assertEqual(loaded_validation.verdict, "LEADING")


if __name__ == "__main__":
    unittest.main()
