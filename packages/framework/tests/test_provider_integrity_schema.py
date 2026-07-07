"""Boundary tests for provider integrity schema (no core / derivation / operators)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from src.dynamic.provider_integrity import ProviderCheck, ProviderIntegrityPanel

_REPO_ROOT = Path(__file__).resolve().parents[1]


class ProviderIntegritySchemaTests(unittest.TestCase):
    def _sample_check(self) -> ProviderCheck:
        return ProviderCheck(
            series="UK30Y_GILT_YIELD",
            provider="Haver",
            status="warn",
            issue="End-of-day batch lagged vs exchange prints during shock window",
            frequency="daily",
            staleness_days=2,
            provider_disagreement=0.08,
        )

    def _sample_panel(self) -> ProviderIntegrityPanel:
        return ProviderIntegrityPanel(
            case_id="ldi_2022",
            overall_status="medium",
            checks=[self._sample_check()],
            affected_signal_cards=["ldi_2022_term_structure_deformation"],
            interpretation=(
                "Cross-checks show the long-end series is usable but lagging; treat same-day "
                "path diagnostics as directional until live prints reconcile."
            ),
        )

    def test_valid_construction(self) -> None:
        panel = self._sample_panel()
        self.assertEqual(panel.overall_status, "medium")

    def test_invalid_check_status_raises(self) -> None:
        with self.assertRaises(ValueError):
            ProviderCheck(
                series="X",
                provider="Y",
                status="maybe",  # type: ignore[arg-type]
                issue=None,
                frequency=None,
                staleness_days=None,
                provider_disagreement=None,
            )

    def test_invalid_overall_status_raises(self) -> None:
        with self.assertRaises(ValueError):
            ProviderIntegrityPanel(
                case_id=None,
                overall_status="ok",  # type: ignore[arg-type]
                checks=[],
                affected_signal_cards=[],
                interpretation="x",
            )

    def test_to_serializable_dict_json_dumps(self) -> None:
        json.dumps(self._sample_panel().to_serializable_dict())

    def test_fresh_import_avoids_forbidden_packages(self) -> None:
        code = """
import importlib
import sys
importlib.import_module("src.dynamic.provider_integrity")
forbidden = ("src.core", "src.derivation", "src.operators")
bad = [m for m in forbidden if m in sys.modules]
assert not bad, bad
"""
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=_REPO_ROOT,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
