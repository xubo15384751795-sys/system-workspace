from __future__ import annotations

from workbench.judgment.neutral_state import (
    DEAD_BAND,
    compare_readings,
    reading_from_snapshot,
)


def _snapshot(*, direction: str, m: float, d: float) -> dict:
    return {
        "basic": {"main_pressure": direction},
        "advanced": {
            "primary_readout": {
                "M_anchor_geometry": {"value": m},
                "D_path_geometry": {"value": d},
            }
        },
    }


def test_reading_uses_main_pressure_and_md_gauges() -> None:
    reading = reading_from_snapshot(_snapshot(direction="PRESSURE_EASING", m=-0.20, d=-0.18))
    assert reading["direction"] == "PRESSURE_EASING"
    assert reading["M"] == -0.20
    assert reading["D"] == -0.18


def test_same_direction_small_delta_is_confirmed() -> None:
    previous = reading_from_snapshot(_snapshot(direction="PRESSURE_EASING", m=-0.20, d=-0.20))
    current = reading_from_snapshot(_snapshot(direction="PRESSURE_EASING", m=-0.18, d=-0.18))
    result = compare_readings(previous, current)
    assert result["status"] == "confirmed"
    assert result["persisted"] is True
    assert result["dead_band_hold"] is True
    assert result["consecutive_runs"] == 1
    assert result["dead_band"] == DEAD_BAND


def test_label_change_outside_dead_band_is_reversed() -> None:
    previous = reading_from_snapshot(_snapshot(direction="PRESSURE_EASING", m=-0.20, d=-0.20))
    current = reading_from_snapshot(_snapshot(direction="PRESSURE_BUILDING", m=0.15, d=0.15))
    result = compare_readings(previous, current)
    assert result["status"] == "reversed"
    assert result["persisted"] is False
    assert result["consecutive_runs"] == 0


def test_missing_gauge_is_unknown_not_reversed() -> None:
    previous = reading_from_snapshot(_snapshot(direction="PRESSURE_EASING", m=-0.20, d=-0.20))
    current = {
        "direction": "PRESSURE_READOUT_UNAVAILABLE",
        "M": None,
        "D": -0.12,
    }
    result = compare_readings(previous, current)
    assert result["status"] == "unknown"
    assert result["persisted"] is False


def test_dead_band_keeps_label_change_confirmed() -> None:
    previous = reading_from_snapshot(_snapshot(direction="PRESSURE_EASING", m=-0.04, d=-0.04))
    current = reading_from_snapshot(_snapshot(direction="PRESSURE_BUILDING", m=0.04, d=0.04))
    result = compare_readings(previous, current)
    assert abs(current["M"] - previous["M"]) < DEAD_BAND
    assert abs(current["D"] - previous["D"]) < DEAD_BAND
    assert result["status"] == "confirmed"
    assert result["dead_band_hold"] is True
    assert result["persisted"] is True
