from __future__ import annotations

import unittest
from unittest.mock import Mock

from src.ui.components.regime_badge import render_reflexivity_flags
from src.ui.components.snapshot_readout import format_sigma, reflexivity_summary
from src.ui.components.state_cards import format_proxy_value, qualitative_label
from src.ui.helpers.ui_runtime import ensure_seed_snapshot


class CurrentStateUITests(unittest.TestCase):
    def test_proxy_value_formatting_is_short(self) -> None:
        self.assertEqual(format_proxy_value(1.234567, True), "1.23")
        self.assertEqual(format_proxy_value(None, False), "unavailable")

    def test_qualitative_labels_use_research_terms(self) -> None:
        self.assertEqual(qualitative_label("D", "WORSENING", True), "Path contraction")
        self.assertEqual(qualitative_label("M", "STABLE", True), "Contained")
        self.assertEqual(qualitative_label("X", "UNKNOWN", False), "Missing")

    def test_reflexivity_renderer_is_importable(self) -> None:
        self.assertTrue(callable(render_reflexivity_flags))

    def test_snapshot_readout_formats_metadata_quietly(self) -> None:
        self.assertEqual(format_sigma(1.234567), "1.23")
        self.assertEqual(format_sigma(None), "-")
        self.assertEqual(reflexivity_summary({"credit": False, "policy": False}), "Quiet")
        self.assertEqual(reflexivity_summary({"credit": True, "policy": False}), "Credit Active")

    def test_seed_snapshot_is_lazy_by_default(self) -> None:
        ctx = Mock()
        ctx.config = {"default_run_date": "2026-04-14", "default_run_type": "WEEKLY", "ui": {}}

        ensure_seed_snapshot(ctx)

        ctx.pipeline.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
