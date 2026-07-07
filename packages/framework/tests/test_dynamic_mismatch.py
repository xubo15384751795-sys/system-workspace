from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.dynamic.mismatch import (
    MismatchMap,
    MismatchProfile,
    build_mismatch_profile_by_type,
    map_morphology_to_mismatch,
)


class MismatchDiagnosticTests(unittest.TestCase):
    def test_valid_mismatch_profile_passes(self) -> None:
        profile = MismatchProfile(
            pair=("A", "L"),
            mismatch_type="anchor_path_mismatch",
            status="warning",
            magnitude=None,
            direction=None,
            persistence=None,
            evidence=["e1"],
            implication="test implication",
        )
        self.assertEqual(profile.pair, ("A", "L"))

    def test_invalid_pair_fails(self) -> None:
        with self.assertRaises(ValueError):
            MismatchProfile(
                pair=("A",),
                mismatch_type="t",
                status="warning",
                magnitude=None,
                direction=None,
                persistence=None,
                evidence=[],
                implication="x",
            )
        with self.assertRaises(ValueError):
            MismatchProfile(
                pair=(" ", "B"),
                mismatch_type="t",
                status="warning",
                magnitude=None,
                direction=None,
                persistence=None,
                evidence=[],
                implication="x",
            )

    def test_invalid_status_fails(self) -> None:
        with self.assertRaises(ValueError):
            MismatchProfile(
                pair=("A", "B"),
                mismatch_type="t",
                status="alert",
                magnitude=None,
                direction=None,
                persistence=None,
                evidence=[],
                implication="x",
            )

    def test_invalid_magnitude_fails(self) -> None:
        with self.assertRaises(ValueError):
            MismatchProfile(
                pair=("A", "B"),
                mismatch_type="t",
                status="normal",
                magnitude=-0.1,
                direction=None,
                persistence=None,
                evidence=[],
                implication="x",
            )

    def test_invalid_persistence_fails(self) -> None:
        with self.assertRaises(ValueError):
            MismatchProfile(
                pair=("A", "B"),
                mismatch_type="t",
                status="normal",
                magnitude=None,
                direction=None,
                persistence=1.1,
                evidence=[],
                implication="x",
            )

    def test_mismatch_map_serializes(self) -> None:
        mmap = MismatchMap(
            case_id="c1",
            profiles=[
                MismatchProfile(
                    pair=("X", "Y"),
                    mismatch_type="t",
                    status="unknown",
                    magnitude=0.0,
                    direction="up",
                    persistence=0.5,
                    evidence=[],
                    implication="imp",
                )
            ],
            summary="s",
            source="unit",
        )
        blob = mmap.to_serializable_dict()
        json.dumps(blob)

    def test_known_morphology_mappings(self) -> None:
        m1 = map_morphology_to_mismatch("anchor_mismatch_plus_path_contraction", case_id="c")
        self.assertEqual(len(m1.profiles), 1)
        self.assertEqual(m1.profiles[0].pair, ("A", "L"))
        self.assertEqual(m1.profiles[0].mismatch_type, "anchor_path_mismatch")

        m2 = map_morphology_to_mismatch("transition_deformation_with_path_collapse")
        self.assertEqual(m2.profiles[0].pair, ("K", "D"))
        self.assertEqual(m2.profiles[0].mismatch_type, "transition_path_mismatch")

        m3 = map_morphology_to_mismatch("shadow_stock_with_transition_deformation")
        self.assertEqual(m3.profiles[0].pair, ("X", "K"))
        self.assertEqual(m3.profiles[0].mismatch_type, "shadow_transition_mismatch")

    def test_unknown_morphology_returns_empty_map(self) -> None:
        m = map_morphology_to_mismatch("mixed_or_low_structural_signal")
        self.assertEqual(m.profiles, [])
        self.assertIn("No mismatch mapping", m.summary)

    def test_build_mismatch_profile_by_type(self) -> None:
        p = build_mismatch_profile_by_type("accounting_market")
        self.assertEqual(p.mismatch_type, "accounting_market")
        self.assertEqual(p.pair, ("A", "V"))
        with self.assertRaises(ValueError):
            build_mismatch_profile_by_type("not_a_type")

    def test_mapper_serializable(self) -> None:
        blob = map_morphology_to_mismatch("anchor_mismatch_plus_path_contraction").to_serializable_dict()
        json.dumps(blob)

    def test_mapper_does_not_import_scoring_stack(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "src" / "dynamic" / "mismatch.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("morphology_classifier", source)
        self.assertNotIn("pipeline", source)
        self.assertNotIn("Snapshot", source)


if __name__ == "__main__":
    unittest.main()
