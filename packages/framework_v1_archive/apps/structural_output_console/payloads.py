"""Load `outputs/dynamic/json` payloads into dynamic-layer dataclasses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from src.dynamic.criticality import CriticalityState
from src.dynamic.mismatch import MismatchMap, MismatchProfile
from src.dynamic.models import EventPhase, TemporalFrame
from src.dynamic.provider_integrity import ProviderCheck, ProviderIntegrityPanel
from src.dynamic.signal_card import EvidenceItem, SignalCard


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def json_prefix_for_case(case_id: str) -> str:
    """Map registry case_id to the LDI MVP filename stem."""
    if case_id == "ldi_2022":
        return "ldi"
    return case_id


def load_signal_bundle(json_dir: Path, case_id: str) -> tuple[TemporalFrame | None, list[SignalCard]]:
    stem = json_prefix_for_case(case_id)
    path = json_dir / f"{stem}_signal_cards.json"
    if not path.is_file():
        return None, []
    data = _read_json(path)
    temporal: TemporalFrame | None = None
    raw_tf = data.get("temporal_frame")
    if isinstance(raw_tf, dict):
        phases_raw = raw_tf.get("phases", [])
        if isinstance(phases_raw, list):
            phases = tuple(
                EventPhase(
                    name=str(p["name"]),
                    start=str(p["start"]),
                    end=str(p["end"]),
                    dominant_mechanism=p.get("dominant_mechanism"),
                    expected_resolution=p.get("expected_resolution"),
                )
                for p in phases_raw
                if isinstance(p, dict)
            )
            temporal = TemporalFrame(
                case_id=str(raw_tf["case_id"]),
                phases=phases,
                event_speed=str(raw_tf["event_speed"]),
                required_resolution=str(raw_tf["required_resolution"]),
                observation_lag_tolerance_days=int(raw_tf["observation_lag_tolerance_days"]),
            )

    cards_raw = data.get("signal_cards", [])
    cards: list[SignalCard] = []
    if isinstance(cards_raw, list):
        for c in cards_raw:
            if not isinstance(c, dict):
                continue
            ev_raw = c.get("evidence", [])
            evidence: list[EvidenceItem] = []
            if isinstance(ev_raw, list):
                for e in ev_raw:
                    if not isinstance(e, dict):
                        continue
                    evidence.append(
                        EvidenceItem(
                            source=str(e["source"]),
                            metric=str(e["metric"]),
                            value=e["value"],  # float | str in JSON
                            timestamp=e.get("timestamp"),
                            reliability=e["reliability"],  # type: ignore[arg-type]
                        )
                    )
            cards.append(
                SignalCard(
                    signal_id=str(c["signal_id"]),
                    title=str(c["title"]),
                    status=c["status"],  # type: ignore[arg-type]
                    severity=c["severity"],  # type: ignore[arg-type]
                    confidence=c["confidence"],  # type: ignore[arg-type]
                    time_window=str(c["time_window"]),
                    phase=c.get("phase"),
                    main_trigger=list(c.get("main_trigger", [])),
                    affected_dimensions=list(c.get("affected_dimensions", [])),
                    path_interpretation=str(c["path_interpretation"]),
                    evidence=evidence,
                    user_action=list(c.get("user_action", [])),
                )
            )
    return temporal, cards


def load_mismatch_map(json_dir: Path, case_id: str) -> MismatchMap | None:
    stem = json_prefix_for_case(case_id)
    path = json_dir / f"{stem}_mismatch_map.json"
    if not path.is_file():
        return None
    d = _read_json(path)
    profiles_raw = d.get("profiles", [])
    profiles: list[MismatchProfile] = []
    if isinstance(profiles_raw, list):
        for p in profiles_raw:
            if not isinstance(p, dict):
                continue
            pair_raw = p.get("pair", [])
            pair = (str(pair_raw[0]), str(pair_raw[1])) if isinstance(pair_raw, list) and len(pair_raw) == 2 else ("?", "?")
            profiles.append(
                MismatchProfile(
                    pair=pair,
                    mismatch_type=str(p["mismatch_type"]),
                    status=str(p["status"]),
                    magnitude=p.get("magnitude"),
                    direction=p.get("direction"),
                    persistence=p.get("persistence"),
                    evidence=list(p.get("evidence", [])),
                    implication=str(p["implication"]),
                )
            )
    return MismatchMap(
        case_id=d.get("case_id"),
        profiles=profiles,
        summary=str(d.get("summary", "")),
        source=d.get("source"),
    )


def load_criticality(json_dir: Path, case_id: str) -> CriticalityState | None:
    stem = json_prefix_for_case(case_id)
    path = json_dir / f"{stem}_criticality.json"
    if not path.is_file():
        return None
    d = _read_json(path)
    return CriticalityState(
        case_id=d.get("case_id"),
        status=str(d["status"]),
        nearest_threshold=d.get("nearest_threshold"),
        distance_to_threshold=d.get("distance_to_threshold"),
        crossed_conditions=list(d.get("crossed_conditions", [])),
        transition_candidate=bool(d.get("transition_candidate", False)),
        level_risk=d.get("level_risk"),
        transition_risk=d.get("transition_risk"),
        evidence=list(d.get("evidence", [])),
        interpretation=str(d.get("interpretation", "")),
    )


def load_provider_integrity(json_dir: Path, case_id: str) -> ProviderIntegrityPanel | None:
    stem = json_prefix_for_case(case_id)
    path = json_dir / f"{stem}_provider_integrity.json"
    if not path.is_file():
        return None
    d = _read_json(path)
    checks_raw = d.get("checks", [])
    checks: list[ProviderCheck] = []
    if isinstance(checks_raw, list):
        for c in checks_raw:
            if not isinstance(c, dict):
                continue
            checks.append(
                ProviderCheck(
                    series=str(c["series"]),
                    provider=str(c["provider"]),
                    status=c["status"],  # type: ignore[arg-type]
                    issue=c.get("issue"),
                    frequency=c.get("frequency"),
                    staleness_days=c.get("staleness_days"),
                    provider_disagreement=c.get("provider_disagreement"),
                )
            )
    return ProviderIntegrityPanel(
        case_id=d.get("case_id"),
        overall_status=d["overall_status"],  # type: ignore[arg-type]
        checks=checks,
        affected_signal_cards=list(d.get("affected_signal_cards", [])),
        interpretation=str(d.get("interpretation", "")),
    )


def load_markdown_note(markdown_dir: Path, case_id: str) -> str | None:
    stem = json_prefix_for_case(case_id)
    path = markdown_dir / f"{stem}_research_note.md"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
