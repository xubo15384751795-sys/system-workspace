"""Boundary tests for SignalCard / EvidenceItem schema (no core / derivation / operators)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from src.dynamic.signal_card import EvidenceItem, SignalCard

_REPO_ROOT = Path(__file__).resolve().parents[1]


class SignalCardSchemaTests(unittest.TestCase):
    def _sample_evidence(self) -> EvidenceItem:
        return EvidenceItem(
            source="FRED/DGS30",
            metric="us_30y_yield_change_bp",
            value=-120.0,
            timestamp="2022-09-28",
            reliability="high",
        )

    def _sample_card(self) -> SignalCard:
        return SignalCard(
            signal_id="ldi_2022_term_structure_deformation",
            title="Long-end gilt discontinuity with collateral feedback",
            status="warning",
            severity="high",
            confidence="medium",
            time_window="2022-09-23 to 2022-10-14",
            phase="shock",
            main_trigger=["Liability-driven flow pressure", "Convexity hedging in thin liquidity"],
            affected_dimensions=["A", "L", "τ"],
            path_interpretation=(
                "The shock concentrated in the long end while balance-sheet hedging paths "
                "compressed faster than discretionary liquidity could re-strike, tightening the "
                "feasible liquidation set without restoring anchor coherence."
            ),
            evidence=[self._sample_evidence()],
            user_action=["Re-map hedge paths against admissible collateral calls", "Stress gap risk at the long end"],
        )

    def test_valid_construction(self) -> None:
        card = self._sample_card()
        self.assertEqual(card.signal_id, "ldi_2022_term_structure_deformation")

    def test_invalid_status_raises(self) -> None:
        base = self._sample_card()
        with self.assertRaises(ValueError):
            SignalCard(
                signal_id=base.signal_id,
                title=base.title,
                status="bogus",  # type: ignore[arg-type]
                severity=base.severity,
                confidence=base.confidence,
                time_window=base.time_window,
                phase=base.phase,
                main_trigger=base.main_trigger,
                affected_dimensions=base.affected_dimensions,
                path_interpretation=base.path_interpretation,
                evidence=base.evidence,
                user_action=base.user_action,
            )

    def test_invalid_severity_raises(self) -> None:
        base = self._sample_card()
        with self.assertRaises(ValueError):
            SignalCard(
                signal_id=base.signal_id,
                title=base.title,
                status=base.status,
                severity="extreme",  # type: ignore[arg-type]
                confidence=base.confidence,
                time_window=base.time_window,
                phase=base.phase,
                main_trigger=base.main_trigger,
                affected_dimensions=base.affected_dimensions,
                path_interpretation=base.path_interpretation,
                evidence=base.evidence,
                user_action=base.user_action,
            )

    def test_invalid_confidence_raises(self) -> None:
        base = self._sample_card()
        with self.assertRaises(ValueError):
            SignalCard(
                signal_id=base.signal_id,
                title=base.title,
                status=base.status,
                severity=base.severity,
                confidence="absolute",  # type: ignore[arg-type]
                time_window=base.time_window,
                phase=base.phase,
                main_trigger=base.main_trigger,
                affected_dimensions=base.affected_dimensions,
                path_interpretation=base.path_interpretation,
                evidence=base.evidence,
                user_action=base.user_action,
            )

    def test_to_serializable_dict_json_dumps(self) -> None:
        blob = self._sample_card().to_serializable_dict()
        json.dumps(blob)

    def test_fresh_import_avoids_forbidden_packages(self) -> None:
        code = """
import importlib
import sys
importlib.import_module("src.dynamic.signal_card")
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
