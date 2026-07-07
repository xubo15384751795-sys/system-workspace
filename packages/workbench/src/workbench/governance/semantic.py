from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


class SemanticRegistry:
    """Load and query the semantic distance registry (semantic_registry.json)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, dict[str, Any]] = json.loads(self.path.read_text(encoding="utf-8"))
        self.validate()

    def get(self, concept: str) -> dict[str, Any]:
        """Return metadata for *concept*. Raises KeyError if not registered."""
        if concept not in self.data:
            raise KeyError(f"Concept not found in semantic registry: {concept}")
        return self.data[concept]

    def require_safe_for_structural_claim(self, concept: str) -> None:
        """Veto check — raise ValueError if *concept* cannot support a strong structural claim.

        Blocks NOT_IMPLEMENTED concepts and those with semantic_distance >= 4.
        Does not grant authority; only confirms the concept is safe to use.
        """
        meta = self.get(concept)
        status = meta.get("implemented_status")
        distance = meta.get("semantic_distance")
        if status == "NOT_IMPLEMENTED":
            raise ValueError(f"{concept} is NOT_IMPLEMENTED and cannot support structural claim.")
        if distance is not None and distance >= 4:
            raise ValueError(
                f"{concept} has semantic_distance={distance}; cannot be used as strong structural concept."
            )

    def attach_metadata(self, proxy_row: dict[str, Any], concept: str) -> dict[str, Any]:
        """Enrich *proxy_row* with semantic metadata from the registry for *concept*."""
        meta = self.get(concept)
        return {
            **proxy_row,
            "target_concept": concept,
            "implemented_status": meta.get("implemented_status"),
            "proxy_status": meta.get("proxy_status"),
            "semantic_distance": meta.get("semantic_distance"),
            "reduction_errors": meta.get("reduction_errors", []),
            "valid_for": meta.get("valid_for", []),
            "not_valid_for": meta.get("not_valid_for", []),
        }

    def validate(self) -> None:
        """Validate all entries in the registry. Raises ValueError on structural violations."""
        for concept, meta in self.data.items():
            validate_semantic_entry(concept, meta)


def validate_semantic_entry(concept: str, meta: dict[str, Any]) -> None:
    """Validate a single semantic registry entry's structural constraints.

    Raises ValueError if required fields are missing, NOT_IMPLEMENTED entries
    have proxy/distance declared, or high-distance entries lack reduction_errors.
    """
    required = {
        "implemented_status",
        "proxy_status",
        "semantic_distance",
        "operational_proxy",
        "reduction_errors",
        "valid_for",
        "not_valid_for",
    }
    missing = sorted(required - set(meta))
    if missing:
        raise ValueError(f"{concept} semantic entry missing required fields: {missing}")
    implemented_status = meta.get("implemented_status")
    proxy_status = meta.get("proxy_status")
    distance = meta.get("semantic_distance")
    if implemented_status == "NOT_IMPLEMENTED":
        if proxy_status != "NO_PROXY":
            raise ValueError(f"{concept} is NOT_IMPLEMENTED but proxy_status is {proxy_status}")
        if distance is not None:
            raise ValueError(f"{concept} is NOT_IMPLEMENTED but semantic_distance is not null")
        if meta.get("operational_proxy") is not None:
            raise ValueError(f"{concept} is NOT_IMPLEMENTED but operational_proxy is declared")
    else:
        if not isinstance(distance, int) or distance < 0:
            raise ValueError(f"{concept} must declare a non-negative integer semantic_distance")
        if not meta.get("operational_proxy"):
            raise ValueError(f"{concept} must declare operational_proxy")
    if proxy_status != "NO_PROXY":
        if not meta.get("reduction_errors"):
            raise ValueError(f"{concept} proxy entry must declare reduction_errors")
        if not meta.get("not_valid_for"):
            raise ValueError(f"{concept} proxy entry must declare not_valid_for")
    if distance is not None and distance >= 3 and not meta.get("not_valid_for"):
        raise ValueError(f"{concept} semantic_distance >= 3 must declare not_valid_for")


def validate_proxy_row_semantics(proxy_row: dict[str, Any]) -> None:
    """Validate that a proxy row carries required semantic metadata.

    Raises ValueError if target_concept, proxy_status, semantic_distance,
    reduction_errors, or not_valid_for are missing.  High-distance proxies
    (>= 3) must declare reduction_errors and not_valid_for.
    """
    required = {"target_concept", "proxy_status", "semantic_distance", "reduction_errors", "not_valid_for"}
    missing = sorted(required - set(proxy_row))
    if missing:
        raise ValueError(f"Proxy row missing semantic metadata: {missing}")
    distance = proxy_row.get("semantic_distance")
    if distance is not None and distance >= 3:
        if not proxy_row.get("reduction_errors"):
            raise ValueError(f"{proxy_row.get('target_concept')} high-distance proxy missing reduction_errors")
        if not proxy_row.get("not_valid_for"):
            raise ValueError(f"{proxy_row.get('target_concept')} high-distance proxy missing not_valid_for")


# The four canonical primitive channels (Finance-2.tex §4.1). They are
# retained as the framework-space contract: a channel may legitimately have no
# signal (NaN / NOT_IMPLEMENTED), but the joint Sigma reading must NEVER
# silently collapse a missing channel to 0.0 and let the remaining channels
# dominate as though the four-channel state were complete. X_PRE / X_REALIZED
# are retired engineering splits (superseded by X_agg) and are intentionally
# NOT part of this set.
CANONICAL_CHANNELS = ["M", "D", "K", "X_agg"]

PRIMARY_READOUT_CHANNELS = ["M", "D"]

MEASUREMENT_ELIGIBILITY: dict[str, dict[str, Any]] = {
    "M": {
        "framework_role": "canonical_dimension",
        "readout_role": "primary_readout",
        "current_status": "PRIMARY_CORE",
        "reason": "high unique discrimination; captures policy-market anchor gap",
        "primitive_mapping": ["A_t anchor configuration", "tau_t policy-market latency", "S_t actor interpretation"],
    },
    "D": {
        "framework_role": "canonical_dimension",
        "readout_role": "primary_readout",
        "current_status": "PRIMARY_CORE",
        "reason": "high unique discrimination; captures funding/credit path feasibility independent of vol",
        "primitive_mapping": ["L_t liquidation path feasibility", "P_t positional constraint", "tau_t funding/clearing latency"],
    },
    "K": {
        "framework_role": "canonical_dimension",
        "readout_role": "diagnostic_rebuild",
        "current_status": "THEORY_RETAINED_MEASUREMENT_INCOMPLETE",
        "reason": "current proxy is weak and dominated by SKEW/VVIX-style option sentiment",
        "reactivation_condition": "vol surface + realized volatility/jump + cross-asset curvature pass measurement gate",
    },
    "X_agg": {
        "framework_role": "canonical_dimension",
        "readout_role": "background_only",
        "current_status": "BACKGROUND_ONLY_REBUILD_REQUIRED",
        "reason": "daily trigger decommissioned; current OFR_FSI-style proxy overlaps VIX/vol stress",
        "reactivation_condition": "daily/weekly shadow leverage data pass discrimination retest; daily trigger remains disabled meanwhile",
    },
}


def _is_live(value: Any) -> bool:
    """A channel is live only if it has a real numeric score (not None/NaN)."""
    if value is None:
        return False
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def build_primary_readout(scores: dict[str, Any]) -> dict[str, Any]:
    """Build the daily executive readout from current measurement-eligible channels.

    This is intentionally separate from the canonical SigmaVector contract. K
    and X_agg remain canonical framework dimensions, but they do not determine
    the primary daily market-space state until their measurement gates pass.
    """
    m_live = _is_live(scores.get("M"))
    d_live = _is_live(scores.get("D"))
    live = [ch for ch in PRIMARY_READOUT_CHANNELS if _is_live(scores.get(ch))]

    if not (m_live and d_live):
        return {
            "state": "PRIMARY_READOUT_UNAVAILABLE",
            "eligible_channels": PRIMARY_READOUT_CHANNELS,
            "channels_live": live,
            "channels_missing": [ch for ch in PRIMARY_READOUT_CHANNELS if ch not in live],
            "basis": "M/D primary readout requires both anchor and path readings.",
            "blocked_from_primary": ["K", "X_agg"],
        }

    m_val = float(scores["M"])
    d_val = float(scores["D"])
    m_abs = abs(m_val)
    d_abs = abs(d_val)

    anchor_drift = m_abs >= 0.40
    anchor_stress = m_abs >= 0.65
    path_narrowing = d_abs >= 0.40
    path_stress = d_abs >= 0.65

    if anchor_stress and path_stress:
        state = "MIXED_ANCHOR_PATH_STRESS"
    elif anchor_stress and not path_narrowing:
        state = "POLICY_MARKET_GAP"
    elif not anchor_drift and path_stress:
        state = "CREDIT_PATH_STRESS"
    elif not anchor_drift and path_narrowing:
        state = "FUNDING_PATH_NARROWING"
    elif anchor_drift and path_stress:
        state = "ANCHOR_DRIFT_PATH_STRESS"
    elif anchor_drift:
        state = "ANCHOR_DRIFT_PATH_OPEN"
    elif path_stress:
        state = "ANCHOR_STABLE_PATH_STRESS"
    else:
        state = "ANCHOR_STABLE_PATH_OPEN"

    return {
        "state": state,
        "eligible_channels": PRIMARY_READOUT_CHANNELS,
        "channels_live": live,
        "channels_missing": [],
        "M_anchor_geometry": {
            "value": m_val,
            "status": "anchor_drift" if anchor_drift else "anchor_stable",
            "stress": anchor_stress,
        },
        "D_path_geometry": {
            "value": d_val,
            "status": "path_stress" if path_stress else "path_narrowing" if path_narrowing else "path_open",
            "stress": path_stress,
        },
        "basis": "Primary daily state is determined by M_anchor_geometry and D_path_geometry only.",
        "blocked_from_primary": ["K", "X_agg"],
    }


def build_sigma_vector(scores: dict[str, float], semantic_registry: SemanticRegistry) -> dict[str, Any]:
    """Build the canonical Sigma vector from current channel scores.

    Returns a dict with M/D/K/X_agg values, live/missing channel lists,
    dominant channel, cofire count, measurement eligibility, primary readout,
    and semantic warnings.  Missing channels are never silently collapsed to 0.0.
    """
    live = [c for c in CANONICAL_CHANNELS if _is_live(scores.get(c))]
    not_implemented = [c for c in CANONICAL_CHANNELS if c not in live]
    complete = len(live) == len(CANONICAL_CHANNELS)

    # dominant / cofire are computed ONLY over live channels — a missing
    # channel is not a 0.0 vote, it is an absent vote.
    dominant = max(live, key=lambda channel: abs(scores[channel])) if live else None
    cofire_count = sum(1 for channel in live if abs(scores[channel]) >= 0.65)

    warnings: list[str] = []
    for channel in CANONICAL_CHANNELS:
        try:
            meta = semantic_registry.get(channel)
        except KeyError:
            continue
        distance = meta.get("semantic_distance")
        if distance is not None and distance >= 3:
            warnings.append(f"{channel}: {meta.get('proxy_status')} distance={distance}")
    if not complete:
        # Loud, machine-readable flag so no downstream consumer mistakes a
        # degraded reading for a complete four-channel structural state.
        warnings.append(
            f"PARTIAL_CHANNEL_COVERAGE: {len(live)}/{len(CANONICAL_CHANNELS)} canonical "
            f"channels live; NOT_IMPLEMENTED={not_implemented}. The joint Σ reading is "
            f"PARTIAL — dominant_channel/cofire_count are within the live subset only and "
            f"must NOT be interpreted as a complete four-channel structural state."
        )

    primary_readout = build_primary_readout(scores)

    return {
        "M": scores.get("M"),
        "D": scores.get("D"),
        "K": scores.get("K"),
        "X_agg": scores.get("X_agg"),
        "operator_penalty": scores.get("operator_penalty", 0.0),
        "channels_live": live,
        "channels_not_implemented": not_implemented,
        "complete": complete,
        "dominant_channel": dominant,
        "cofire_count": cofire_count,
        "measurement_eligibility": MEASUREMENT_ELIGIBILITY,
        "primary_readout": primary_readout,
        "semantic_warning": warnings,
    }
