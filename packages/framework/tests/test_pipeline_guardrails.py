from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.core.models import NarrativeReading, ProxyReading
from src.core.pipeline import ResearchPipeline
from src.data.quality.manifest import (
    QUALITY_MOCK,
    ChannelEvidenceRecord,
    DataEvidenceManifest,
    SeriesEvidenceRecord,
)
from src.stubs.stubs import InMemorySnapshotStore, StubAnomalyDetector, StubReflexivityDetector


def _raw_frame() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=8, freq="D")
    return pd.DataFrame(
        {
            "M_PROXY": np.linspace(0.1, 0.8, len(idx)),
            "D_PROXY": np.linspace(-0.1, -0.8, len(idx)),
            "K_PROXY": np.linspace(0.2, 0.9, len(idx)),
            "X_PROXY": np.linspace(0.3, 1.0, len(idx)),
        },
        index=idx,
    )


def _proxy(
    *,
    m: float | None = 0.4,
    d: float | None = -0.4,
    k: float | None = 0.4,
    x: float | None = 0.4,
) -> ProxyReading:
    values = {"M": m, "D": d, "K": k, "X": x}
    return ProxyReading(
        run_date="2026-01-08",
        M=m,
        D=d,
        K=k,
        X=x,
        directions={key: "WORSENING" if value is not None else "UNKNOWN" for key, value in values.items()},
        available={key: value is not None for key, value in values.items()},
        components=values,
    )


@dataclass
class FixedDataSource:
    frame: pd.DataFrame
    last_evidence_manifest: DataEvidenceManifest | None = None
    calls: int = 0

    def fetch(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        return self.frame.loc[pd.to_datetime(start) : pd.to_datetime(end)]

    def available_series(self) -> list[str]:
        return list(self.frame.columns)


@dataclass
class FixedProxyBuilder:
    reading: ProxyReading

    def build(self, raw: pd.DataFrame, run_date: str) -> ProxyReading:
        return self.reading


@dataclass
class FixedODEEngine:
    z: Any

    def integrate(self, proxy: ProxyReading, params: dict, **kwargs) -> Any:
        return self.z

    def map_proxy_to_initial_state(self, proxy: ProxyReading) -> np.ndarray:
        return np.zeros(6)


class NonSingularDetector:
    def detect(self, proxy: ProxyReading, z: np.ndarray, **kwargs) -> tuple[float, bool]:
        return 0.1, False


class NullNarrativeDetector:
    def analyze(self, texts: list[dict], run_date: str) -> None:
        return None


class FixedNarrativeDetector:
    def analyze(self, texts: list[dict], run_date: str) -> NarrativeReading:
        return NarrativeReading(
            run_date=run_date,
            ai_unicorn="ANCHORED",
            clo_cmbs="ANCHORED",
            policy="ANCHORED",
            drift_scores={},
        )


class MultiReflexivityDetector:
    def check(self, event_log: pd.DataFrame, proxy_history: pd.DataFrame, run_date: str) -> dict[str, bool]:
        return {"credit": True, "liquidity": True, "policy": False}


class PipelineGuardrailTests(unittest.TestCase):
    def _config(self, *, reuse_existing_snapshot: bool = False) -> dict:
        return {
            "series_ids": ["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"],
            "history_start": "2026-01-01",
            "ode_params": {"horizon": 2, "dt": 1.0},
            "pipeline": {
                "run_extensions": True,
                "run_ml_extensions": True,
                "run_narrative_extension": True,
                "persist_extension_outputs": True,
                "reuse_existing_snapshot": reuse_existing_snapshot,
            },
        }

    def _pipeline(
        self,
        *,
        proxy: ProxyReading | None = None,
        ode_z: Any | None = None,
        data_source: FixedDataSource | None = None,
        reflexivity_detector: Any | None = None,
        narrative_detector: Any | None = None,
        config: dict | None = None,
        store: InMemorySnapshotStore | None = None,
    ) -> ResearchPipeline:
        return ResearchPipeline(
            data_source=data_source or FixedDataSource(_raw_frame()),
            proxy_builder=FixedProxyBuilder(proxy or _proxy()),
            ode_engine=FixedODEEngine(np.ones(6) if ode_z is None else ode_z),
            singular_detector=NonSingularDetector(),
            anomaly_detector=StubAnomalyDetector(),
            narrative_detector=narrative_detector or FixedNarrativeDetector(),
            reflexivity_detector=reflexivity_detector or StubReflexivityDetector(),
            snapshot_store=store or InMemorySnapshotStore(),
            config=config or self._config(),
        )

    def test_proxy_incompleteness_boundary_is_less_than_two_channels(self) -> None:
        pipeline = self._pipeline()

        self.assertTrue(pipeline._proxy_too_incomplete(_proxy(m=None, d=None, k=None, x=None)))
        self.assertTrue(pipeline._proxy_too_incomplete(_proxy(m=1.0, d=None, k=None, x=None)))
        self.assertFalse(pipeline._proxy_too_incomplete(_proxy(m=1.0, d=1.0, k=None, x=None)))

    def test_escalates_when_proxy_data_is_too_incomplete_and_keeps_distribution_state(self) -> None:
        snapshot = self._pipeline(proxy=_proxy(m=0.1, d=None, k=None, x=None)).run("2026-01-08")

        self.assertTrue(snapshot.escalation)
        self.assertEqual(snapshot.escalation_reason, "Proxy data too incomplete to proceed")
        self.assertIn("distribution_state", snapshot.state.provenance)

    def test_proxy_incomplete_takes_priority_over_invalid_ode(self) -> None:
        snapshot = self._pipeline(proxy=_proxy(m=0.1, d=None, k=None, x=None), ode_z=[]).run("2026-01-08")

        self.assertEqual(snapshot.escalation_reason, "Proxy data too incomplete to proceed")

    def test_escalates_and_suppresses_research_when_all_evidence_is_mock(self) -> None:
        records = (
            SeriesEvidenceRecord("M_PROXY", "mock", "M", None, None, None, 8, False, "mock"),
        )
        manifest = DataEvidenceManifest(
            run_date="2026-01-08",
            series_records=records,
            channel_records=(
                ChannelEvidenceRecord("M", ("M_PROXY",), (), (), 0, 1, True, True),
            ),
            any_fallback=True,
            research_quality=QUALITY_MOCK,
            total_series=1,
            real_series=0,
        )
        source = FixedDataSource(_raw_frame(), last_evidence_manifest=manifest)

        snapshot = self._pipeline(data_source=source).run("2026-01-08")

        self.assertTrue(snapshot.escalation)
        self.assertEqual(
            snapshot.escalation_reason,
            "All channel data is mock/fallback — research interpretation suppressed",
        )
        self.assertEqual(snapshot.state.provenance["data_quality"]["research_quality"], QUALITY_MOCK)

    def test_escalates_when_ode_returns_invalid_state(self) -> None:
        snapshot = self._pipeline(ode_z=[]).run("2026-01-08")

        self.assertTrue(snapshot.escalation)
        self.assertEqual(snapshot.escalation_reason, "ODE integration returned invalid state")
        self.assertIn("distribution_state", snapshot.state.provenance)

    def test_escalates_when_ode_returns_non_finite_values(self) -> None:
        snapshot = self._pipeline(ode_z=np.array([0.0, np.nan])).run("2026-01-08")

        self.assertTrue(snapshot.escalation)
        self.assertEqual(snapshot.escalation_reason, "ODE integration produced non-finite values")

    def test_multi_reflexivity_requires_two_true_flags(self) -> None:
        pipeline = self._pipeline()

        self.assertFalse(pipeline._multi_reflexivity({"credit": True, "liquidity": False}))
        self.assertTrue(pipeline._multi_reflexivity({"credit": True, "liquidity": True}))

    def test_escalates_on_multi_channel_reflexivity(self) -> None:
        snapshot = self._pipeline(reflexivity_detector=MultiReflexivityDetector()).run("2026-01-08")

        self.assertTrue(snapshot.escalation)
        self.assertEqual(snapshot.escalation_reason, "Multi-channel reflexivity detected")

    def test_escalates_when_narrative_detector_returns_none(self) -> None:
        snapshot = self._pipeline(narrative_detector=NullNarrativeDetector()).run("2026-01-08")

        self.assertTrue(snapshot.escalation)
        self.assertEqual(snapshot.escalation_reason, "Narrative detector returned no reading")

    def test_reuse_false_does_not_load_existing_snapshot(self) -> None:
        source = FixedDataSource(_raw_frame())
        store = InMemorySnapshotStore()
        pipeline = self._pipeline(data_source=source, store=store, config=self._config(reuse_existing_snapshot=False))

        first = pipeline.run("2026-01-08", "WEEKLY")
        second = pipeline.run("2026-01-08", "WEEKLY")

        self.assertIsNot(first, second)
        self.assertEqual(source.calls, 2)

    def test_snapshot_reuse_rejects_run_type_mismatch(self) -> None:
        source = FixedDataSource(_raw_frame())
        store = InMemorySnapshotStore()
        pipeline = self._pipeline(data_source=source, store=store, config=self._config(reuse_existing_snapshot=True))

        weekly = pipeline.run("2026-01-08", "WEEKLY")
        monthly = pipeline.run("2026-01-08", "MONTHLY")

        self.assertIsNot(monthly, weekly)
        self.assertEqual(source.calls, 2)


if __name__ == "__main__":
    unittest.main()
