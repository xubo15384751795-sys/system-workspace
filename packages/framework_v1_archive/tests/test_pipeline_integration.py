from __future__ import annotations

import unittest

import pandas as pd

from src._legacy.data.data_sources import MockDataSource
from src.derivation.belief_builder import DefaultBeliefBuilder
from src.dynamics.ode_engine import ScipyODEEngine
from src.derivation.proxy_builder import DefaultProxyBuilder
from src.derivation.singular_detector import ThresholdSingularDetector
from src.operators import build_default_operator_registry
from src.stubs.stubs import (
    InMemorySnapshotStore,
    StubAnomalyDetector,
    StubNarrativeDetector,
    StubReflexivityDetector,
)
from src.core.pipeline import ResearchPipeline
from src.core.execution import RunContext


class PipelineIntegrationTests(unittest.TestCase):
    def _base_config(self) -> dict:
        return {
            "series_ids": ["M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"],
            "history_start": "2026-01-01",
            "ode_params": {"horizon": 4, "dt": 1.0, "alpha": 0.1, "beta": 0.05},
            "pipeline": {
                "run_extensions": True,
                "run_belief_extension": True,
                "run_ml_extensions": True,
                "run_narrative_extension": True,
                "persist_extension_outputs": True,
            },
        }

    def test_end_to_end_with_mock_data_source(self) -> None:
        pipeline = ResearchPipeline(
            data_source=MockDataSource(seed=42),
            proxy_builder=DefaultProxyBuilder(),
            ode_engine=ScipyODEEngine(),
            singular_detector=ThresholdSingularDetector(sigma_threshold=10.0),
            anomaly_detector=StubAnomalyDetector(),
            narrative_detector=StubNarrativeDetector(),
            reflexivity_detector=StubReflexivityDetector(),
            snapshot_store=InMemorySnapshotStore(),
            config=self._base_config(),
            belief_builder=DefaultBeliefBuilder(sigma_threshold=10.0),
        )

        snapshot = pipeline.run("2026-04-14", "WEEKLY")
        self.assertFalse(snapshot.escalation)
        self.assertEqual(snapshot.run_date, "2026-04-14")
        self.assertIsNotNone(snapshot.state.z_vector)
        self.assertIsNotNone(snapshot.narrative)
        provenance = dict(snapshot.state.provenance)
        self.assertIn("data_version", provenance)
        self.assertIn("code_version", provenance)
        self.assertIn("config_version", provenance)
        self.assertIn("run_timestamp", provenance)
        self.assertIn("datahub_manifest", provenance)
        manifest = provenance["datahub_manifest"]
        self.assertEqual(manifest["manifest_version"], "1.0")
        self.assertIn("providers_touched", manifest)
        self.assertIn("response_stats", manifest)
        self.assertIn("preset_names", manifest)
        self.assertIn("channels_touched", manifest)
        self.assertIn("blocks_touched", manifest)
        self.assertIn("evidence_roles", manifest)
        self.assertIsNotNone(snapshot.state.belief_state)
        assert snapshot.state.belief_state is not None
        self.assertIn("sigma_breach_prob", snapshot.state.belief_state.escalation_metrics)
        self.assertIsNotNone(snapshot.state.primitive_state)
        self.assertIsNotNone(snapshot.state.shadow_mass_state)
        self.assertIsNotNone(snapshot.state.mean_field_gap)
        self.assertIn("shadow_mass_state", provenance)
        self.assertIn("mean_field_gap", provenance)
        self.assertIn("singular_detector", provenance)
        self.assertIn("structural_singular_time", provenance)

    def test_pipeline_accepts_run_context(self) -> None:
        pipeline = ResearchPipeline(
            data_source=MockDataSource(seed=42),
            proxy_builder=DefaultProxyBuilder(),
            ode_engine=ScipyODEEngine(),
            singular_detector=ThresholdSingularDetector(sigma_threshold=10.0),
            anomaly_detector=StubAnomalyDetector(),
            narrative_detector=StubNarrativeDetector(),
            reflexivity_detector=StubReflexivityDetector(),
            snapshot_store=InMemorySnapshotStore(),
            config=self._base_config(),
            belief_builder=DefaultBeliefBuilder(sigma_threshold=10.0),
        )

        ctx = RunContext(
            run_date="2026-04-14",
            run_type="WEEKLY",
            history_start="2026-01-01",
            series_ids=("M_PROXY", "D_PROXY", "K_PROXY", "X_PROXY"),
            config=self._base_config(),
        )
        snapshot = pipeline.run(ctx)

        self.assertFalse(snapshot.escalation)
        self.assertEqual(snapshot.run_date, "2026-04-14")
        self.assertEqual(snapshot.run_type, "WEEKLY")

    def test_reuses_existing_snapshot_when_enabled(self) -> None:
        source = MockDataSource(seed=42)
        store = InMemorySnapshotStore()
        pipeline = ResearchPipeline(
            data_source=source,
            proxy_builder=DefaultProxyBuilder(),
            ode_engine=ScipyODEEngine(),
            singular_detector=ThresholdSingularDetector(sigma_threshold=10.0),
            anomaly_detector=StubAnomalyDetector(),
            narrative_detector=StubNarrativeDetector(),
            reflexivity_detector=StubReflexivityDetector(),
            snapshot_store=store,
            config={
                **self._base_config(),
                "pipeline": {
                    **self._base_config()["pipeline"],
                    "reuse_existing_snapshot": True,
                },
            },
            belief_builder=DefaultBeliefBuilder(sigma_threshold=10.0),
        )

        first = pipeline.run("2026-04-14", "WEEKLY")
        pipeline.data_source = None  # type: ignore[assignment]
        second = pipeline.run("2026-04-14", "WEEKLY")

        self.assertIs(second, first)

    def test_escalates_when_singular_flag_triggered(self) -> None:
        pipeline = ResearchPipeline(
            data_source=MockDataSource(seed=42),
            proxy_builder=DefaultProxyBuilder(),
            ode_engine=ScipyODEEngine(),
            singular_detector=ThresholdSingularDetector(sigma_threshold=0.01),
            anomaly_detector=StubAnomalyDetector(),
            narrative_detector=StubNarrativeDetector(),
            reflexivity_detector=StubReflexivityDetector(),
            snapshot_store=InMemorySnapshotStore(),
            config=self._base_config(),
            belief_builder=DefaultBeliefBuilder(sigma_threshold=0.01),
        )

        snapshot = pipeline.run("2026-04-14", "WEEKLY")
        self.assertTrue(snapshot.escalation)
        self.assertEqual(snapshot.escalation_reason, "Singular regime flag triggered")

    def test_event_log_is_applied_as_structural_operator_layer(self) -> None:
        event_log = pd.DataFrame(
            [
                {
                    "date": "2026-04-13",
                    "intervention_type": "Funding haircut",
                    "description": "Collateral haircut widened.",
                }
            ]
        )
        pipeline = ResearchPipeline(
            data_source=MockDataSource(seed=42),
            proxy_builder=DefaultProxyBuilder(),
            ode_engine=ScipyODEEngine(),
            singular_detector=ThresholdSingularDetector(sigma_threshold=10.0),
            anomaly_detector=StubAnomalyDetector(),
            narrative_detector=StubNarrativeDetector(),
            reflexivity_detector=StubReflexivityDetector(),
            snapshot_store=InMemorySnapshotStore(),
            config={**self._base_config(), "operators": {"enabled": True}},
            event_loader=lambda: event_log,
            operator_registry=build_default_operator_registry(),
            belief_builder=DefaultBeliefBuilder(sigma_threshold=10.0),
        )

        snapshot = pipeline.run("2026-04-14", "EVENT")
        diagnostics = snapshot.state.operator_diagnostics

        self.assertFalse(snapshot.escalation)
        self.assertIsNotNone(diagnostics)
        self.assertEqual(diagnostics.operator_count, 1)
        self.assertEqual(diagnostics.sequence_signature, "FUNDING_HAIRCUT")


if __name__ == "__main__":
    unittest.main()
