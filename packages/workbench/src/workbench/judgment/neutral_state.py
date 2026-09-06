"""Neutral-measurement direction and persistence.

This is the operational M/D state for claim-ladder tier 2 and overall
progression. It is not a Deformation v1 patch: direction is
``neutral_pressure_snapshot.basic.main_pressure``, persistence is consecutive
runs of that state, and a numeric dead band keeps small |ΔM|, |ΔD| as
confirmed even when the label changes.
"""
from __future__ import annotations

from typing import Any, Mapping

DEAD_BAND = 0.10
HISTORY_SCHEMA = "neutral_state.history.v1"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def md_values(snapshot: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    """Read live M/D gauges from a neutral-pressure snapshot."""
    if not isinstance(snapshot, Mapping):
        return None, None
    advanced = snapshot.get("advanced") if isinstance(snapshot.get("advanced"), Mapping) else {}
    readout = advanced.get("primary_readout") if isinstance(advanced.get("primary_readout"), Mapping) else {}
    m_block = readout.get("M_anchor_geometry") if isinstance(readout.get("M_anchor_geometry"), Mapping) else {}
    d_block = readout.get("D_path_geometry") if isinstance(readout.get("D_path_geometry"), Mapping) else {}
    m_val = _as_float(m_block.get("value"))
    d_val = _as_float(d_block.get("value"))
    if m_val is not None or d_val is not None:
        return m_val, d_val
    chain = snapshot.get("canonical_chain") if isinstance(snapshot.get("canonical_chain"), Mapping) else {}
    for key in ("measurement", "observation"):
        block = chain.get(key) if isinstance(chain.get(key), Mapping) else {}
        value = block.get("value") if isinstance(block.get("value"), Mapping) else {}
        m_val = _as_float(value.get("M"))
        d_val = _as_float(value.get("D"))
        if m_val is not None or d_val is not None:
            return m_val, d_val
    return None, None


def reading_from_snapshot(
    snapshot: Mapping[str, Any] | None,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Project a snapshot into a comparable reading."""
    basic = snapshot.get("basic") if isinstance(snapshot, Mapping) else None
    direction = None
    if isinstance(basic, Mapping):
        raw = basic.get("main_pressure")
        if raw is not None and str(raw).strip():
            direction = str(raw).strip()
    m_val, d_val = md_values(snapshot)
    if run_id is None and isinstance(snapshot, Mapping):
        raw_run = snapshot.get("run_id")
        run_id = str(raw_run) if raw_run else None
    return {
        "run_id": run_id,
        "direction": direction,
        "M": m_val,
        "D": d_val,
    }


def within_dead_band(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    *,
    dead_band: float = DEAD_BAND,
) -> bool:
    """True when both |ΔM| and |ΔD| are defined and below the dead band."""
    if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
        return False
    prev_m, prev_d = _as_float(previous.get("M")), _as_float(previous.get("D"))
    curr_m, curr_d = _as_float(current.get("M")), _as_float(current.get("D"))
    if None in (prev_m, prev_d, curr_m, curr_d):
        return False
    return abs(curr_m - prev_m) < dead_band and abs(curr_d - prev_d) < dead_band


def compare_readings(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
    *,
    history: list[Mapping[str, Any]] | None = None,
    dead_band: float = DEAD_BAND,
) -> dict[str, Any]:
    """Compare two readings and count consecutive persistent runs.

    ``status``:
      - ``unknown`` if the current (or previous, for a pair) reading is missing
      - ``confirmed`` if ``main_pressure`` is unchanged or the dead band holds
      - ``reversed`` if the label changed and the move is outside the dead band
    """
    history = list(history or [])
    current_reading = dict(current) if isinstance(current, Mapping) else {}
    direction = current_reading.get("direction")
    if not direction:
        return {
            "check": "neutral_state",
            "source": "neutral_pressure_snapshot.basic.main_pressure",
            "theory": "neutral_measurements_requalified",
            "operational": "authoritative",
            "direction": None,
            "previous_direction": (previous or {}).get("direction") if isinstance(previous, Mapping) else None,
            "M": current_reading.get("M"),
            "D": current_reading.get("D"),
            "delta_M": None,
            "delta_D": None,
            "dead_band": dead_band,
            "dead_band_hold": False,
            "persisted": False,
            "status": "unknown",
            "consecutive_runs": 0,
        }

    previous_direction = (previous or {}).get("direction") if isinstance(previous, Mapping) else None
    prev_m = _as_float((previous or {}).get("M")) if isinstance(previous, Mapping) else None
    prev_d = _as_float((previous or {}).get("D")) if isinstance(previous, Mapping) else None
    curr_m = _as_float(current_reading.get("M"))
    curr_d = _as_float(current_reading.get("D"))
    delta_m = (curr_m - prev_m) if prev_m is not None and curr_m is not None else None
    delta_d = (curr_d - prev_d) if prev_d is not None and curr_d is not None else None
    dead_band_hold = within_dead_band(previous, current_reading, dead_band=dead_band)

    if previous is None or not previous_direction:
        status = "unknown"
        persisted = False
        consecutive = 1
    elif previous_direction == direction or dead_band_hold:
        status = "confirmed"
        persisted = True
        consecutive = _trailing_persistent_count(history, current_reading, dead_band=dead_band) + 1
    elif None in (prev_m, prev_d, curr_m, curr_d):
        status = "unknown"
        persisted = False
        consecutive = 1
    else:
        status = "reversed"
        persisted = False
        consecutive = 0

    return {
        "check": "neutral_state",
        "source": "neutral_pressure_snapshot.basic.main_pressure",
        "theory": "neutral_measurements_requalified",
        "operational": "authoritative",
        "direction": direction,
        "previous_direction": previous_direction,
        "M": curr_m,
        "D": curr_d,
        "delta_M": round(delta_m, 6) if delta_m is not None else None,
        "delta_D": round(delta_d, 6) if delta_d is not None else None,
        "dead_band": dead_band,
        "dead_band_hold": dead_band_hold,
        "persisted": persisted,
        "status": status,
        "consecutive_runs": consecutive,
    }


def _trailing_persistent_count(
    history: list[Mapping[str, Any]],
    current: Mapping[str, Any],
    *,
    dead_band: float,
) -> int:
    count = 0
    cursor = current
    for rec in reversed(history):
        if not isinstance(rec, Mapping):
            break
        if rec.get("direction") == cursor.get("direction") or within_dead_band(
            rec, cursor, dead_band=dead_band
        ):
            count += 1
            cursor = rec
            continue
        break
    return count


def empty_history() -> dict[str, Any]:
    return {"schema_version": HISTORY_SCHEMA, "runs": []}


def parse_history(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return []
    return [dict(item) for item in runs if isinstance(item, Mapping)]
