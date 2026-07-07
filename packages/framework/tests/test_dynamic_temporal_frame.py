"""DYN-1.2 / DYN-1.3: TemporalFrame validation and LDI registry."""

from __future__ import annotations

import unittest

from src.dynamic.models import EventPhase, TemporalFrame
from src.dynamic.registry import get_temporal_frame, list_temporal_frames


def _valid_phases() -> tuple[EventPhase, ...]:
    return (
        EventPhase("a", "2024-01-01", "2024-01-05", "m1", None),
        EventPhase("b", "2024-01-06", "2024-01-10", "m2", None),
    )


class TestTemporalFrameValidation(unittest.TestCase):
    def test_valid_frame_passes(self) -> None:
        frame = TemporalFrame(
            case_id="x",
            phases=_valid_phases(),
            event_speed="normal",
            required_resolution="weekly",
            observation_lag_tolerance_days=7,
        )
        self.assertEqual(frame.case_id, "x")
        self.assertEqual(len(frame.phases), 2)

    def test_invalid_date_order_fails(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            EventPhase("bad", "2024-02-10", "2024-02-01", None, None)
        self.assertIn("on or before", str(ctx.exception))

    def test_duplicate_phase_names_fail(self) -> None:
        phases = (
            EventPhase("same", "2024-01-01", "2024-01-03", None, None),
            EventPhase("same", "2024-01-04", "2024-01-06", None, None),
        )
        with self.assertRaises(ValueError) as ctx:
            TemporalFrame(
                case_id="x",
                phases=phases,
                event_speed="n",
                required_resolution="d",
                observation_lag_tolerance_days=1,
            )
        self.assertIn("unique", str(ctx.exception).lower())

    def test_overlapping_phases_fail(self) -> None:
        phases = (
            EventPhase("p1", "2024-01-01", "2024-01-10", None, None),
            EventPhase("p2", "2024-01-08", "2024-01-15", None, None),
        )
        with self.assertRaises(ValueError) as ctx:
            TemporalFrame(
                case_id="x",
                phases=phases,
                event_speed="n",
                required_resolution="d",
                observation_lag_tolerance_days=1,
            )
        self.assertIn("overlap", str(ctx.exception).lower())

    def test_to_serializable_dict(self) -> None:
        frame = TemporalFrame(
            case_id="z",
            phases=_valid_phases(),
            event_speed="s",
            required_resolution="r",
            observation_lag_tolerance_days=2,
        )
        d = frame.to_serializable_dict()
        self.assertEqual(d["case_id"], "z")
        self.assertEqual(len(d["phases"]), 2)
        self.assertIn("observation_lag_tolerance_days", d)


class TestLDIRegistry(unittest.TestCase):
    def test_ldi_2022_exists(self) -> None:
        self.assertIn("ldi_2022", list_temporal_frames())

    def test_ldi_phase_names(self) -> None:
        frame = get_temporal_frame("ldi_2022")
        names = [p.name for p in frame.phases]
        self.assertEqual(names, ["pre_shock", "shock", "intervention", "post_shock"])

    def test_ldi_phases_non_overlapping_via_construction(self) -> None:
        # Registry entry is built at import time; validation proves non-overlap.
        frame = get_temporal_frame("ldi_2022")
        self.assertEqual(len(frame.phases), 4)

    def test_unknown_case_raises_clear_keyerror(self) -> None:
        with self.assertRaises(KeyError) as ctx:
            get_temporal_frame("no_such_case")
        msg = str(ctx.exception)
        self.assertIn("no_such_case", msg)
        self.assertIn("Known", msg)


if __name__ == "__main__":
    unittest.main()
