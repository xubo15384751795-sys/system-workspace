from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PATTERN_COLORS: dict[str, str] = {
    "SHADOW_DOMINANT": "#d18a00",
    "PRE_SINGULAR": "#dd6b20",
    "REFLEXIVITY_LOOP": "#c53030",
    "ANCHOR_DRIFT": "#d69e2e",
    "STABLE_LOCAL": "#2f855a",
    "UNKNOWN": "#718096",
}

PATTERN_SUMMARIES: dict[str, str] = {
    "SHADOW_DOMINANT": "Hidden pressure is accumulating while visible liquidity/curvature channels are not yet fully stressed.",
    "PRE_SINGULAR": "Effective freedom and transition geometry are both deteriorating; this is the closest non-crisis warning state.",
    "REFLEXIVITY_LOOP": "Model-mediated or policy-mediated feedback appears active across multiple channels.",
    "ANCHOR_DRIFT": "Anchor mismatch is the dominant symptom while path freedom and curvature remain less stressed.",
    "STABLE_LOCAL": "The system remains in a locally stable explanatory regime under the current proxy readings.",
    "UNKNOWN": "The system does not have enough interpretable signal to classify the current state.",
}


@dataclass(frozen=True)
class MarketStateInterpretation:
    pattern: str
    leading_channel: str
    severity: str
    summary: str
    channel_notes: dict[str, str]
    recommended_actions: list[str]


def leading_channel(directions: Mapping[str, str] | Any) -> str:
    for key, val in dict(directions or {}).items():
        if val == "WORSENING":
            return str(key)
    return "NONE"


def classify_pattern(directions: Mapping[str, str], reflexivity_flags: Mapping[str, bool] | None = None) -> str:
    flags = dict(reflexivity_flags or {})
    if flags and any(flags.values()):
        return "REFLEXIVITY_LOOP"

    values = dict(directions or {})
    d_bad = values.get("D") == "WORSENING"
    k_bad = values.get("K") == "WORSENING"
    x_bad = values.get("X") == "WORSENING"
    m_bad = values.get("M") == "WORSENING"

    if x_bad and not d_bad and not k_bad:
        return "SHADOW_DOMINANT"
    if d_bad and k_bad and not x_bad:
        return "PRE_SINGULAR"
    if m_bad and not d_bad and not k_bad:
        return "ANCHOR_DRIFT"
    return "STABLE_LOCAL"


def interpret_snapshot(snapshot: Any) -> MarketStateInterpretation:
    directions = dict(snapshot.proxy.directions)
    reflexivity_flags = dict(snapshot.state.reflexivity_flags)
    pattern = snapshot.state.pattern or classify_pattern(directions, reflexivity_flags)
    channel = snapshot.state.leading_channel or leading_channel(directions)
    severity = severity_label(pattern=pattern, singular_flag=bool(snapshot.state.singular_flag), escalation=bool(snapshot.escalation))
    return MarketStateInterpretation(
        pattern=pattern,
        leading_channel=channel,
        severity=severity,
        summary=PATTERN_SUMMARIES.get(pattern, PATTERN_SUMMARIES["UNKNOWN"]),
        channel_notes=channel_notes(snapshot.proxy),
        recommended_actions=recommended_actions(snapshot),
    )


def severity_label(pattern: str, singular_flag: bool, escalation: bool) -> str:
    if escalation or singular_flag:
        return "HUMAN_REVIEW"
    if pattern in {"PRE_SINGULAR", "REFLEXIVITY_LOOP"}:
        return "ELEVATED"
    if pattern in {"SHADOW_DOMINANT", "ANCHOR_DRIFT"}:
        return "WATCH"
    return "BASELINE"


def channel_notes(proxy: Any) -> dict[str, str]:
    notes: dict[str, str] = {}
    for channel in ["M", "D", "K", "X"]:
        direction = str(proxy.directions.get(channel, "UNKNOWN"))
        value = getattr(proxy, channel, None)
        notes[channel] = channel_note(channel, direction, value)
    return notes


def channel_note(channel: str, direction: str, value: float | None) -> str:
    value_text = "unavailable" if value is None else f"{value:.3f}"
    if channel == "D":
        meaning = "effective freedom / feasible paths"
        worsening = "path freedom is contracting"
    elif channel == "K":
        meaning = "transition-map deformation"
        worsening = "local linear transport is becoming less reliable"
    elif channel == "X":
        meaning = "hidden or deferred pressure"
        worsening = "shadow load is accumulating or releasing"
    else:
        meaning = "anchor mismatch"
        worsening = "price, funding, verification, or liquidation anchors are drifting"

    if direction == "WORSENING":
        return f"{channel} ({meaning}) is worsening: {worsening}; latest value {value_text}."
    if direction == "IMPROVING":
        return f"{channel} ({meaning}) is improving; latest value {value_text}."
    if direction == "UNKNOWN":
        return f"{channel} ({meaning}) is unavailable and should not drive interpretation."
    return f"{channel} ({meaning}) is locally stable; latest value {value_text}."


def recommended_actions(snapshot: Any) -> list[str]:
    actions: list[str] = []
    pattern = snapshot.state.pattern or "UNKNOWN"
    directions = dict(snapshot.proxy.directions)

    if snapshot.escalation:
        actions.append("Escalate to human review and pause automated diagnosis.")
    if bool(snapshot.state.singular_flag):
        actions.append("Run a focused singular-regime check on the latest run window.")
    if pattern == "PRE_SINGULAR":
        actions.append("Prioritize stress testing on D and K channels over the next weekly cycle.")
    if pattern == "SHADOW_DOMINANT":
        actions.append("Inspect shadow-load components and compare Xproxy against BIS/SRISK-style benchmarks.")
    if pattern == "ANCHOR_DRIFT":
        actions.append("Review price-funding, price-verifiability, and liquidation anchor gaps.")
    if directions.get("D") == "WORSENING":
        actions.append("Log a policy/liquidity scenario event and track T+30 / T+60 reflexivity.")
    if not actions:
        actions.append("Continue standard weekly monitoring and archive this snapshot as baseline.")
    return actions
