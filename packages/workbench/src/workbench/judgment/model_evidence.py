"""Generic measurement evidence reader for the judgment consumer.

The preferred path reads ``decision_evidence``.  The legacy projection is
kept here, at the compatibility boundary, so the judgment implementation
does not know any plugin-private field names.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class MeasurementEvidenceView:
    state: str | None
    values: tuple[float | None, ...]
    confidence: float | None
    diagnostics: Mapping[str, Any]
    model_id: str | None
    protocol_version: str | None
    source: str

    def pair(self) -> tuple[float, float]:
        values = list(self.values[:2])
        values.extend([None] * (2 - len(values)))
        return (
            float(values[0]) if values[0] is not None else 0.0,
            float(values[1]) if values[1] is not None else 0.0,
        )


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _generic(document: Mapping[str, Any]) -> MeasurementEvidenceView | None:
    raw = document.get("decision_evidence")
    if not isinstance(raw, Mapping):
        return None
    scores = raw.get("scores")
    if not isinstance(scores, Mapping):
        return None
    ordered = sorted(scores.items(), key=lambda item: str(item[0]))
    return MeasurementEvidenceView(
        state=str(raw.get("state")) if raw.get("state") is not None else None,
        values=tuple(_number(value) for _, value in ordered),
        confidence=_number(raw.get("confidence")),
        diagnostics=(raw.get("diagnostics") if isinstance(raw.get("diagnostics"), Mapping) else {}),
        model_id=str(raw.get("model_id")) if raw.get("model_id") else None,
        protocol_version=(
            str(raw.get("protocol_version")) if raw.get("protocol_version") else None
        ),
        source="decision_evidence",
    )


def _legacy(document: Mapping[str, Any]) -> MeasurementEvidenceView:
    advanced = document.get("advanced") if isinstance(document.get("advanced"), Mapping) else {}
    primary = advanced.get("primary_readout") if isinstance(advanced.get("primary_readout"), Mapping) else {}
    # This is intentionally isolated in the compatibility reader.  No
    # judgment code should reach through these fields directly.
    m_block = primary.get("M_anchor_geometry") if isinstance(primary.get("M_anchor_geometry"), Mapping) else {}
    d_block = primary.get("D_path_geometry") if isinstance(primary.get("D_path_geometry"), Mapping) else {}
    basic = document.get("basic") if isinstance(document.get("basic"), Mapping) else {}
    state = primary.get("state") or basic.get("main_pressure") or basic.get("primary_market_space")
    return MeasurementEvidenceView(
        state=str(state) if state else None,
        values=(_number(m_block.get("value")), _number(d_block.get("value"))),
        confidence=None,
        diagnostics={"compatibility": "legacy_neutral_pressure_snapshot"},
        model_id=None,
        protocol_version=None,
        source="legacy_compatibility",
    )


def measurement_evidence(document: Mapping[str, Any] | None) -> MeasurementEvidenceView:
    if isinstance(document, Mapping):
        generic = _generic(document)
        if generic is not None:
            return generic
        return _legacy(document)
    return MeasurementEvidenceView(
        state=None,
        values=(None, None),
        confidence=None,
        diagnostics={},
        model_id=None,
        protocol_version=None,
        source="missing",
    )


__all__ = ["MeasurementEvidenceView", "measurement_evidence"]
