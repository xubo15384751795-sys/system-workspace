"""Boundary tests for ResearchNote assembly (no core / derivation / operators on fresh import)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from src.dynamic.criticality import CriticalityState
from src.dynamic.mismatch import MismatchMap, MismatchProfile
from src.dynamic.models import EventPhase, TemporalFrame
from src.dynamic.provider_integrity import ProviderCheck, ProviderIntegrityPanel
from src.dynamic.research_note import ResearchNote
from src.dynamic.signal_card import EvidenceItem, SignalCard

_REPO_ROOT = Path(__file__).resolve().parents[1]


class ResearchNoteSchemaTests(unittest.TestCase):
    def _note(self) -> ResearchNote:
        temporal = TemporalFrame(
            case_id="ldi_2022",
            phases=(
                EventPhase("pre_shock", "2022-09-01", "2022-09-22", "m1", None),
                EventPhase("shock", "2022-09-23", "2022-09-27", "m2", None),
            ),
            event_speed="acute",
            required_resolution="daily",
            observation_lag_tolerance_days=3,
        )
        mismatch = MismatchMap(
            case_id="ldi_2022",
            profiles=[
                MismatchProfile(
                    pair=("A", "L"),
                    mismatch_type="anchor_path_mismatch",
                    status="warning",
                    magnitude=None,
                    direction=None,
                    persistence=None,
                    evidence=["synthetic"],
                    implication="Anchor legibility diverges from feasible liquidation paths.",
                )
            ],
            summary="Synthetic mismatch view for schema test.",
            source="unit",
        )
        criticality = CriticalityState(
            case_id="ldi_2022",
            status="near_threshold",
            nearest_threshold="sigma_composite",
            distance_to_threshold=0.1,
            crossed_conditions=[],
            transition_candidate=True,
            level_risk=0.9,
            transition_risk=0.3,
            evidence=["synthetic"],
            interpretation="Elevated pressure band for schema validation.",
        )
        pip = ProviderIntegrityPanel(
            case_id="ldi_2022",
            overall_status="medium",
            checks=[
                ProviderCheck(
                    series="UK_LONG_YIELD",
                    provider="VendorA",
                    status="pass",
                    issue=None,
                    frequency="daily",
                    staleness_days=1,
                    provider_disagreement=0.02,
                )
            ],
            affected_signal_cards=["ldi_2022_term_structure_deformation"],
            interpretation="Synthetic integrity panel.",
        )
        card = SignalCard(
            signal_id="ldi_2022_term_structure_deformation",
            title="Schema card",
            status="watch",
            severity="medium",
            confidence="high",
            time_window="2022-09-23 to 2022-09-27",
            phase="shock",
            main_trigger=["t1"],
            affected_dimensions=["A", "L"],
            path_interpretation="Non-boilerplate path read for validation.",
            evidence=[
                EvidenceItem(
                    source="synthetic",
                    metric="m",
                    value=1.0,
                    timestamp=None,
                    reliability="medium",
                )
            ],
            user_action=["act"],
        )
        return ResearchNote(
            note_id="note_ldi_schema",
            title="LDI schema note",
            generated_at="2026-05-08T12:00:00Z",
            executive_summary="Synthetic executive summary for JSON round-trip confidence.",
            signal_cards=[card],
            temporal_frame=temporal,
            mismatch_map=mismatch,
            criticality=criticality,
            provider_integrity=pip,
            scenario_paths=["policy_backstop_then_repricing"],
            limitations=["No live market feed attached"],
            disclaimer="diagnostic-only; not connected to final scoring",
        )

    def test_valid_construction(self) -> None:
        note = self._note()
        self.assertEqual(note.note_id, "note_ldi_schema")

    def test_invalid_signal_card_confidence_raises(self) -> None:
        with self.assertRaises(ValueError):
            SignalCard(
                signal_id="x",
                title="t",
                status="inactive",
                severity="low",
                confidence="bad",  # type: ignore[arg-type]
                time_window="w",
                phase=None,
                main_trigger=[],
                affected_dimensions=[],
                path_interpretation="p",
                evidence=[],
                user_action=[],
            )

    def test_to_serializable_dict_json_dumps(self) -> None:
        json.dumps(self._note().to_serializable_dict())

    def test_fresh_import_avoids_forbidden_packages(self) -> None:
        code = """
import importlib
import sys
importlib.import_module("src.dynamic.research_note")
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
