from __future__ import annotations

import unittest

from src.core.pipeline_stages import PipelineRunPolicy
from src.data.gateway import EvidenceRouter, create_data_hub


class EvidenceRouterTests(unittest.TestCase):
    def test_routes_by_structural_semantics_not_provider_name(self) -> None:
        router = EvidenceRouter()

        route = router.route(
            {
                "channel": "D",
                "measurement_block": "funding_access",
                "evidence_role": "proxy",
            }
        )

        self.assertEqual([preset.name for preset in route.presets], ["dof_funding_access_us"])
        self.assertEqual(route.providers[0], "fed_h41")

    def test_proxy_series_routes_expand_to_channel_presets(self) -> None:
        router = EvidenceRouter()

        routes = router.route_proxy_series(["M_PROXY", "X_PROXY"])

        self.assertIn("M_PROXY", routes)
        self.assertIn("X_PROXY", routes)
        self.assertTrue(any(preset.channel == "M" for preset in routes["M_PROXY"].presets))
        self.assertTrue(any(preset.channel == "X" for preset in routes["X_PROXY"].presets))

    def test_datahub_exposes_router_and_capabilities(self) -> None:
        hub = create_data_hub({"project_name": "test"}, use_mock=True)

        route = hub.route_evidence({"channel": "K", "evidence_role": "proxy"})
        capabilities = hub.provider_capabilities()

        self.assertIn("curvature_jump_instability_us", route["preset_names"])
        self.assertTrue(any(item["provider"] == "fred" for item in capabilities))

    def test_pipeline_policy_can_disable_extensions(self) -> None:
        policy = PipelineRunPolicy.from_config(
            {
                "pipeline": {
                    "run_extensions": False,
                    "run_belief_extension": True,
                    "run_ml_extensions": True,
                    "run_narrative_extension": True,
                }
            }
        )

        self.assertFalse(policy.run_extensions)
        self.assertFalse(policy.run_belief_extension)
        self.assertFalse(policy.run_ml_extensions)
        self.assertFalse(policy.run_narrative_extension)

    def test_pipeline_policy_defaults_to_paper_clean(self) -> None:
        policy = PipelineRunPolicy.from_config({})

        self.assertFalse(policy.run_extensions)
        self.assertFalse(policy.run_belief_extension)
        self.assertFalse(policy.run_ml_extensions)
        self.assertFalse(policy.run_narrative_extension)
        self.assertFalse(policy.persist_extension_outputs)


if __name__ == "__main__":
    unittest.main()
