"""Daily CaseLab signal — match current System state to historical cases.

Reads the latest M/D/K/X proxy readings and structural state,
converts to S-A-L-V-P-tau, runs EnhancedSimilarityEngine,
and outputs a structured case-match report.

Usage:
    python3 scripts/caselab_daily_signal.py
    python3 scripts/caselab_daily_signal.py --json   # JSON output only
    python3 scripts/caselab_daily_signal.py --top 5   # top N cases

Output:
    Output/state/caselab/YYYY-MM-DD.json     (structured)
    Output/state/caselab/YYYY-MM-DD.md       (readable)
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

from verity.runtime._constants import (
    CASELAB_STRONG_THRESHOLD,
    CASELAB_USABLE_THRESHOLD,
    CASELAB_WEAK_THRESHOLD,
    D_DETERIORATION_THRESHOLD,
    D_IMPROVEMENT_THRESHOLD,
    DEFAULT_SIGMA_T,
    K_CURVATURE_COMPRESSED,
    K_CURVATURE_ELEVATED,
    K_CURVATURE_MODERATE,
    K_CURVATURE_STRONG_COMPRESS,
    M_MACRO_RELIEF,
    M_MACRO_SIGNIFICANT,
    M_MACRO_STRESS,
    SIGMA_COMPRESSION_LOW,
    SIGMA_ELEVATED,
    STRESS_DIRECTION_DEPRESSED,
    STRESS_DIRECTION_ELEVATED,
    STRESS_DIRECTION_MILD_BUILD,
    STRESS_DIRECTION_MILD_RELIEF,
    STRESS_DIRECTION_STRONG_BUILD,
    STRESS_DIRECTION_STRONG_RELIEF,
    X_CROSS_MARKET_DECLINE,
    X_CROSS_MARKET_ELEVATED,
    X_CROSS_MARKET_UNWIND,
)
from verity.runtime.runtime_io import (
    ROOT,
    ensure_dir,
    load_json,
    surface_dir,
    utc_now,
    write_json,
)

OUTPUT_DIR = ROOT / "Output" / "state" / "caselab"


def _operational_direction(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Operational direction is main_pressure, never the frozen (M+K+X)/3 label."""
    from workbench.judgment.neutral_state import reading_from_snapshot

    if snapshot is None:
        snapshot = load_json(surface_dir("current") / "neutral_pressure_snapshot.json")
    reading = reading_from_snapshot(snapshot)
    direction = reading.get("direction")
    return {
        "direction": direction,
        "source": "neutral_pressure_snapshot.basic.main_pressure",
        "M": reading.get("M"),
        "D": reading.get("D"),
        "operational": "authoritative" if direction else "unavailable",
    }


FROZEN_V1_STAMP = {
    "theory_authority": False,
    "falsified_claim_set": "deformation_v1_four_channel_universal_predictor",
    "direction_formula": "archived_v1_mdkx_mean",
    "operational_use": "diagnostic_only",
}

# Scoring policy thresholds — canonical values in _constants.py
STRONG_THRESHOLD = CASELAB_STRONG_THRESHOLD
USABLE_THRESHOLD = CASELAB_USABLE_THRESHOLD
WEAK_THRESHOLD = CASELAB_WEAK_THRESHOLD


def get_latest_state() -> dict:
    """Read the compatibility copy of M/D/K/X from framework_output.json.

    This is not a live Deformation snapshot and is not recomputed here.
    Downstream direction still uses the frozen v1 (M+K+X)/3 composite, which
    has no theory authority. proxy_readings.parquet remains a stale fallback.
    """
    framework_path = surface_dir("current") / "framework_output.json"
    proxy_path = ROOT / "Data" / "structural_lab" / "processed" / "proxies" / "proxy_readings.parquet"
    state_path = ROOT / "Data" / "structural_lab" / "processed" / "state" / "structural_state.parquet"

    state = {
        "date": None,
        "M": None, "K": None, "D": None, "X": None,
        "sigma_t": None,
        "pattern": None,
        "leading_channel": None,
        "direction": None,
        "z_vector": None,
        "active_operators": [],
        "escalation": False,
    }

    # Primary source: framework_output.json (always fresh after daily run)
    if framework_path.exists():
        try:
            fw = load_json(framework_path) or {}
            sv = fw.get("advanced", {}).get("sigma_vector", {})
            state["date"] = str(fw.get("as_of", ""))[:10]
            state["M"] = float(sv.get("M", 0)) if sv.get("M") is not None else None
            state["K"] = float(sv.get("K", 0)) if sv.get("K") is not None else None
            state["D"] = float(sv.get("D", 0)) if sv.get("D") is not None else None
            state["X"] = float(sv.get("X_agg", 0)) if sv.get("X_agg") is not None else None
            state["leading_channel"] = str(sv.get("dominant_channel", ""))
            # Direction from basic status
            basic = fw.get("basic", {})
            state["direction"] = str(basic.get("main_pressure", ""))
            state["pattern"] = str(basic.get("primary_market_space", ""))
        except Exception:
            logger.debug("Failed to read framework_output for state", exc_info=True)

    # Fallback: proxy_readings.parquet
    if state["M"] is None and proxy_path.exists():
        df = pd.read_parquet(proxy_path)
        latest_date = df["run_date"].max()
        latest = df[df["run_date"] == latest_date]
        state["date"] = str(latest_date)

        for _, row in latest.iterrows():
            name = row["proxy_name"]
            if name in ("M", "K", "D", "X"):
                state[name] = float(row["value"]) if pd.notna(row["value"]) else None
            if name == "M":  # direction from M proxy
                state["direction"] = str(row.get("direction", ""))

    # Structural state
    if state_path.exists():
        df2 = pd.read_parquet(state_path)
        # Find last non-NaN row
        for i in range(len(df2) - 1, -1, -1):
            row = df2.iloc[i]
            if pd.notna(row.get("sigma_t")):
                state["sigma_t"] = float(row["sigma_t"])
                state["pattern"] = str(row.get("pattern", ""))
                state["leading_channel"] = str(row.get("leading_channel", ""))
                state["escalation"] = bool(row.get("escalation", False))

                # z_vector
                zv = row.get("z_vector")
                if zv is not None:
                    try:
                        state["z_vector"] = [float(x) for x in zv]
                    except (TypeError, ValueError):
                        logger.warning("Unable to normalize CaseLab z_vector", exc_info=True)

                # Extract active operators from diagnostics
                diag = row.get("operator_diagnostics")
                if isinstance(diag, str):
                    try:
                        diag = json.loads(diag)
                    except json.JSONDecodeError:
                        diag = {}
                if isinstance(diag, dict):
                    state["active_operators"] = [
                        app.get("operator", "")
                        for app in diag.get("applications", [])
                        if app.get("operator")
                    ]
                break

    return state


def mdx_to_salvptau(state: dict) -> dict[str, float]:
    """Convert M/D/K/X proxy values to S-A-L-V-P-tau vector.

    CRITICAL: M/D/K/X are signed values.
      Positive M/K = stress building
      Negative M/K = stress relieving
      D = -K (always opposite sign)
      Positive X = cross-market stress building

    The conversion must respect signs. Negative M/K means LOW stress,
    not high stress.
    """
    M = state.get("M") or 0.0
    K = state.get("K") or 0.0
    D = state.get("D") or 0.0
    X = state.get("X") or 0.0
    sigma = state.get("sigma_t") or DEFAULT_SIGMA_T

    # Directional indicators
    # stress_level: how much stress is present (use max of M,K,X, clamped to [0,1])
    max(0.0, min(1.0, (abs(M) + abs(K) + abs(X)) / 3.0))
    # stress_direction: positive = building, negative = relieving
    stress_direction = (M + K + X) / 3.0  # positive = stress building

    # Base mapping — uses signed values
    # When M/K are negative (relief), S should be LOW
    vec = {
        # S: stress level, scaled by sign. Negative M/K = low S
        "S": max(0.0, min(1.0, 0.4 * max(0, K) + 0.3 * max(0, M) + 0.2 * sigma)),
        # A: asymmetry from D magnitude and X. D negative = improving visibility
        "A": max(0.0, min(1.0, 0.3 * abs(D) + 0.2 * abs(X) + 0.2 * sigma)),
        # L: leverage from X and K. Negative K/X = deleveraging
        "L": max(0.0, min(1.0, 0.3 * max(0, X) + 0.3 * max(0, K) + 0.2 * sigma)),
        # V: volatility from sigma and K. Compression when K negative
        "V": max(0.0, min(1.0, 0.4 * sigma + 0.3 * max(0, K))),
        # P: positioning from M. Negative M = risk-off
        "P": max(0.0, min(1.0, 0.3 * max(0, M) + 0.2 * max(0, K))),
        # tau: time pressure from D direction and sigma
        "tau": max(0.0, min(1.0, 0.3 * abs(D) + 0.2 * sigma)),
    }

    # Directional adjustment: if overall stress is DECREASING, reduce all vectors
    if stress_direction < STRESS_DIRECTION_DEPRESSED:
        reduction = min(0.4, abs(stress_direction) * 0.3)
        for k in vec:
            vec[k] = max(0.0, vec[k] - reduction)

    # Operator-based adjustments (only if stress is building)
    if stress_direction > 0:
        operators = " ".join(state.get("active_operators", [])).upper()
        if "FUNDING_LIQUIDITY_SPIRAL" in operators:
            vec["S"] += 0.08
            vec["tau"] += 0.06
        if "COLLATERAL_LEVERAGE_CYCLE" in operators:
            vec["L"] += 0.08
            vec["A"] += 0.05
        if "NETWORK_CONCENTRATION" in operators:
            vec["P"] += 0.08
            vec["A"] += 0.04
        if "POLICY_DELAY" in operators:
            vec["tau"] += 0.08
        if "MARKET_LIQUIDITY_GAP" in operators:
            vec["S"] += 0.06
            vec["V"] += 0.05

    # Escalation boost
    if state.get("escalation"):
        vec["S"] += 0.10
        vec["tau"] += 0.10

    return {k: max(0.0, min(1.0, round(v, 3))) for k, v in vec.items()}


def derive_tags(state: dict) -> list[str]:
    """Derive tags from active operators AND M/D/K/X regime state.

    Tags must reflect the ACTUAL regime, not just operator names.
    When M/D/K/X are negative (relief), stress tags should NOT be added.
    """
    tags: list[str] = []

    M = state.get("M") or 0.0
    K = state.get("K") or 0.0
    state.get("D") or 0.0
    X = state.get("X") or 0.0
    stress_direction = (M + K + X) / 3.0

    # Regime-aware tags based on M/D/K/X signs
    if stress_direction > STRESS_DIRECTION_ELEVATED:
        # Stress building — add stress tags from operators
        operators = " ".join(state.get("active_operators", [])).upper()
        op_tag_map = {
            "FUNDING_LIQUIDITY_SPIRAL": ["liquidity", "spiral", "funding"],
            "COLLATERAL_LEVERAGE_CYCLE": ["leverage", "collateral"],
            "MARKET_LIQUIDITY_GAP": ["liquidity", "market_microstructure"],
            "NETWORK_CONCENTRATION": ["concentration", "systemic"],
            "POLICY_DELAY": ["policy", "regulation"],
            "PROCyclical_LEVERAGE": ["leverage", "procyclical"],
            "COMPRESSION_ERROR": ["volatility", "compression"],
            "INTERMEDIARY_CAPACITY": ["intermediary", "credit"],
            "CAPITAL_CONSTRAINT": ["capital", "constraint"],
            "TRANCHING_COMPLEXITY": ["structured", "tranching"],
            "COLLATERAL_ANCHOR_GAP": ["collateral", "valuation"],
            "TRANCHE_VERIFIABILITY_GAP": ["visibility", "structured"],
        }
        for op_name, op_tags in op_tag_map.items():
            if op_name in operators:
                tags.extend(op_tags)
        tags.append("stress_building")
    elif stress_direction < STRESS_DIRECTION_DEPRESSED:
        # Stress relieving — add relief tags
        tags.extend(["stress_relief", "deleveraging", "volatility_compression"])
        if K < K_CURVATURE_STRONG_COMPRESS:
            tags.append("structural_improvement")
        if M < -1.0:
            tags.append("macro_easing")
    else:
        # Neutral
        tags.append("neutral")

    # Mechanism-derived tags — bridge to case library patterns.
    # These add structural keywords that overlap with case tags,
    # improving tag Jaccard from 0.0 to nonzero for relief states.
    mechanism_tag_map = {
        "anchor_drift": ["valuation", "mispricing", "fundamental"],
        "funding_path_stress": ["liquidity", "funding", "repo"],
        "liquidity_compression": ["volatility", "compression"],
        "leverage_unwind": ["leverage", "forced_selling", "margin"],
        "volatility_regime_mismatch": ["divergence", "regime"],
        "relief_decompression": ["recovery", "stabilization"],
        "cross_market_contagion": ["contagion", "spillover", "correlation"],
        "policy_delay_stress": ["policy", "regulation"],
    }
    # Detect mechanism types from current state
    _mechs = detect_mechanism_types(state)
    for mech_name in _mechs.get("mechanism_types", []):
        mech_tags = mechanism_tag_map.get(mech_name, [])
        tags.extend(mech_tags)

    # Pattern-based tags
    pattern = (state.get("pattern") or "").upper()
    if "STABLE" in pattern:
        tags.append("stable")
    if "CRISIS" in pattern:
        tags.append("crisis")
    if "TRANSITION" in pattern:
        tags.append("transition")

    return list(dict.fromkeys(tags))  # dedupe


def derive_event_text(state: dict) -> str:
    """Build a natural language description of current state for text matching.

    CRITICAL: The text must match the ACTUAL regime.
    When M/D/K/X are negative (relief), use relief/stability keywords.
    When positive (stress building), use stress/crisis keywords.
    Using the wrong keywords will match wrong cases.
    """
    parts: list[str] = []

    M = state.get("M") or 0
    K = state.get("K") or 0
    D = state.get("D") or 0
    X = state.get("X") or 0
    pattern = state.get("pattern", "")
    stress_direction = (M + K + X) / 3.0

    if stress_direction > STRESS_DIRECTION_ELEVATED:
        # STRESS BUILDING — use stress keywords
        if K > K_CURVATURE_ELEVATED:
            parts.append("High structural stress in the system.")
        elif K > K_CURVATURE_MODERATE:
            parts.append("Moderate structural stress with elevated vigilance.")
        if D < D_DETERIORATION_THRESHOLD:
            parts.append("Deteriorating conditions with negative D signal.")
        if M > M_MACRO_STRESS:
            parts.append("Macro stress elevated with policy pressure.")
        if X > X_CROSS_MARKET_ELEVATED:
            parts.append("Cross-market stress and shadow leverage building.")
        parts.append(f"Pattern: {pattern}. Leading channel: {state.get('leading_channel', 'N/A')}.")

        # Stress operators
        operators = state.get("active_operators", [])
        op_map = {
            "FUNDING_LIQUIDITY_SPIRAL": "funding liquidity spiral active",
            "COLLATERAL_LEVERAGE_CYCLE": "collateral leverage cycle",
            "MARKET_LIQUIDITY_GAP": "market liquidity gap",
            "NETWORK_CONCENTRATION": "network concentration risk",
            "POLICY_DELAY": "policy delay creating time pressure",
        }
        for op in operators:
            for key, desc in op_map.items():
                if key in op.upper():
                    parts.append(desc)

    elif stress_direction < STRESS_DIRECTION_DEPRESSED:
        # STRESS RELIEVING — use relief keywords for mechanism matching
        parts.append("M/D/K/X composite direction is negative, indicating pressure relief and deleveraging.")
        parts.append("Volatility compression with stabilizing conditions.")
        if M < M_MACRO_RELIEF:
            parts.append("M anchor relief — macro easing environment.")
        if D < D_IMPROVEMENT_THRESHOLD:
            parts.append("D path improvement — structural recovery.")
        if K < K_CURVATURE_STRONG_COMPRESS:
            parts.append("K curvature compressed — low structural stress.")
        if X < X_CROSS_MARKET_DECLINE:
            parts.append("X shadow-load unwinding — cross-market normalization.")
        parts.append(f"Pattern: {pattern}. Leading channel: {state.get('leading_channel', 'N/A')}.")

    else:
        # NEUTRAL
        parts.append("Neutral conditions. No clear directional stress.")
        parts.append(f"Pattern: {pattern}. Leading channel: {state.get('leading_channel', 'N/A')}.")

    if state.get("escalation"):
        parts.append("ESCALATION flagged — conditions worsening.")

    return " ".join(parts)


def detect_mechanism_types(state: dict) -> dict[str, Any]:
    """Detect which mechanism archetypes the current state resembles.

    Returns a context packet with mechanism types, descriptions, and
    what kind of historical cases to look for.
    """
    M = state.get("M") or 0.0
    K = state.get("K") or 0.0
    D = state.get("D") or 0.0
    X = state.get("X") or 0.0
    sigma = state.get("sigma_t") or DEFAULT_SIGMA_T
    stress_direction = (M + K + X) / 3.0
    operators = " ".join(state.get("active_operators", [])).upper()

    mechanism_types: list[str] = []
    missing_case_types: list[str] = []

    # Anchor drift: M is significant and moving
    if abs(M) > M_MACRO_SIGNIFICANT:
        mechanism_types.append("anchor_drift")

    # Funding path stress: funding-related operators active or high L
    if "FUNDING" in operators or "LIQUIDITY" in operators or (abs(K) > K_CURVATURE_MODERATE and abs(X) > X_CROSS_MARKET_DECLINE):
        mechanism_types.append("funding_path_stress")

    # Liquidity compression: low vol, low stress, compression-like
    if stress_direction < STRESS_DIRECTION_MILD_RELIEF and sigma < SIGMA_COMPRESSION_LOW:
        mechanism_types.append("liquidity_compression")

    # Leverage unwind: X declining, K declining, deleveraging
    if stress_direction < STRESS_DIRECTION_DEPRESSED and X < X_CROSS_MARKET_UNWIND:
        mechanism_types.append("leverage_unwind")

    # Volatility regime mismatch: HMM and M/D/K/X might diverge
    # (we detect this but let reconcile_regime confirm)
    if abs(stress_direction) < STRESS_DIRECTION_ELEVATED and sigma > SIGMA_ELEVATED:
        mechanism_types.append("volatility_regime_mismatch")

    # Relief decompression: overall stress declining
    if stress_direction < STRESS_DIRECTION_DEPRESSED:
        mechanism_types.append("relief_decompression")

    # Cross-market contagion: X elevated
    if abs(X) > X_CROSS_MARKET_ELEVATED:
        mechanism_types.append("cross_market_contagion")

    # Policy delay: policy operators active
    if "POLICY" in operators or "DELAY" in operators:
        mechanism_types.append("policy_delay_stress")

    # If no mechanisms detected, note what we're missing
    if not mechanism_types:
        if stress_direction < STRESS_DIRECTION_MILD_RELIEF:
            missing_case_types.append("relief_decompression")
            missing_case_types.append("leverage_unwind")
        else:
            missing_case_types.append("neutral_transition")

    return {
        "mechanism_types": mechanism_types,
        "missing_case_types": missing_case_types,
        "context_description": _describe_mechanism_context(
            mechanism_types, M, K, D, X, stress_direction
        ),
        "stress_direction": round(stress_direction, 3),
        "what_to_look_for": _what_to_look_for(mechanism_types),
    }


def _describe_mechanism_context(
    types: list[str], M: float, K: float, D: float, X: float, sd: float
) -> str:
    """Generate a human-readable description of the mechanism context."""
    if not types:
        return "No specific mechanism archetype detected."
    descs = []
    if "anchor_drift" in types:
        descs.append(f"anchor drift (M={M:.2f})")
    if "funding_path_stress" in types:
        descs.append("funding/lubricity path stress")
    if "liquidity_compression" in types:
        descs.append("liquidity compression (low vol, low stress)")
    if "leverage_unwind" in types:
        descs.append(f"leverage unwind (X={X:.2f})")
    if "volatility_regime_mismatch" in types:
        descs.append("volatility regime mismatch")
    if "relief_decompression" in types:
        descs.append(f"relief decompression (stress_dir={sd:.2f})")
    if "cross_market_contagion" in types:
        descs.append(f"cross-market contagion (X={X:.2f})")
    if "policy_delay_stress" in types:
        descs.append("policy delay stress")
    return "Detected: " + ", ".join(descs) + "."


def _what_to_look_for(types: list[str]) -> list[str]:
    """Describe what kind of historical cases would be useful."""
    mapping = {
        "anchor_drift": "historical episodes of anchor valuation mispricing",
        "funding_path_stress": "funding liquidity spirals and repo market stress",
        "liquidity_compression": "volatility compression periods before stress emergence",
        "leverage_unwind": "forced deleveraging and margin call cascades",
        "volatility_regime_mismatch": "periods where HMM and structural signals diverged",
        "relief_decompression": "post-crisis relief and normalization episodes",
        "cross_market_contagion": "cross-market contagion and spillover events",
        "policy_delay_stress": "policy response delay creating market stress",
    }
    return [mapping[t] for t in types if t in mapping]


def build_context_packet(state: dict, vec: dict, reconciliation: dict) -> dict[str, Any]:
    """Build a rich context packet for CaseLab matching.

    This goes into the output alongside the match results, helping
    downstream consumers understand WHY the system is looking for
    certain types of cases.
    """
    M = state.get("M") or 0.0
    K = state.get("K") or 0.0
    D = state.get("D") or 0.0
    X = state.get("X") or 0.0
    stress_direction = (M + K + X) / 3.0

    # Direction and strength
    if abs(stress_direction) < STRESS_DIRECTION_MILD_BUILD:
        direction_label = "neutral"
        strength = "weak"
    elif abs(stress_direction) < STRESS_DIRECTION_STRONG_BUILD:
        direction_label = "stress_relief" if stress_direction < 0 else "stress_building"
        strength = "moderate"
    else:
        direction_label = "stress_relief" if stress_direction < 0 else "stress_building"
        strength = "strong"

    # K/X degradation reasons
    kx_notes = []
    if K < K_CURVATURE_COMPRESSED:
        kx_notes.append(f"K={K:.2f}: curvature proxy compressed — low structural stress signal")
    if X < X_CROSS_MARKET_UNWIND:
        kx_notes.append(f"X={X:.2f}: shadow-load declining — cross-market stress easing")
    if abs(K) < K_CURVATURE_MODERATE and abs(X) < X_CROSS_MARKET_DECLINE:
        kx_notes.append("K and X near neutral — no strong directional signal")

    return {
        "structural_state": {
            "M": round(M, 3),
            "D": round(D, 3),
            "K": round(K, 3),
            "X": round(X, 3),
            "stress_direction": round(stress_direction, 3),
            "direction_label": direction_label,
            "strength": strength,
        },
        "vector": vec,
        "kx_degradation_notes": kx_notes,
        "hmm_vs_structural": {
            "hmm_regime": reconciliation.get("hmm_regime", "unknown"),
            "mdx_regime": reconciliation.get("mdx_regime", "unknown"),
            "divergence": reconciliation.get("divergence", False),
            "unified_regime": reconciliation.get("unified_regime", "unknown"),
        },
        "claim_ceiling": "diagnostic_watch_only",
        "direction_label_source": "archived_v1_mdkx_mean",
        "direction_label_note": (
            "direction_label comes from the frozen v1 (M+K+X)/3 composite "
            "and has no theory authority."
        ),
        "operational_direction": _operational_direction(),
        "needs_mechanism_type": _what_to_look_for(
            detect_mechanism_types(state).get("mechanism_types", [])
        ),
    }


def reconcile_regime(state: dict) -> dict[str, Any]:
    """Compare HMM regime with M/D/K/X and produce unified signal.

    The HMM classifies based on raw market data (volatility, correlations).
    M/D/K/X are structural proxies. They can diverge:
    - HMM says "crisis" (high vol still present) but M/D/K/X say "relief" (stress declining)
    - HMM says "compression" (low vol) but M/D/K/X say "stress building" (K rising)

    When they diverge, M/D/K/X should take precedence for structural analysis,
    because they measure the RATE OF CHANGE, not the LEVEL.
    """
    M = state.get("M") or 0.0
    K = state.get("K") or 0.0
    state.get("D") or 0.0
    X = state.get("X") or 0.0
    stress_direction = (M + K + X) / 3.0

    # M/D/K/X regime
    if stress_direction > STRESS_DIRECTION_STRONG_BUILD:
        mdx_regime = "stress_building"
    elif stress_direction > STRESS_DIRECTION_MILD_BUILD:
        mdx_regime = "elevated"
    elif stress_direction > STRESS_DIRECTION_MILD_RELIEF:
        mdx_regime = "neutral"
    elif stress_direction > STRESS_DIRECTION_STRONG_RELIEF:
        mdx_regime = "relieving"
    else:
        mdx_regime = "stress_relief"

    # HMM regime
    hmm_regime = "unknown"
    hmm_path = Path(str(ROOT / "Output" / "state" / "ml_signals" / "latest" / "regime_hmm.json"))
    state_date = str(state.get("date") or "")
    dated_path = None
    if state_date:
        dated_path = ROOT / "Output" / "state" / "ml_signals" / f"harvester_{state_date}" / "regime_hmm.json"
    if dated_path and dated_path.exists():
        hmm_path = dated_path
    if hmm_path.exists():
        try:
            with open(hmm_path) as f:
                hmm = json.load(f)
            hmm_regime = hmm.get("regime", {}).get("current", "unknown")
        except Exception:
            logger.debug("Failed to read HMM regime from %s", hmm_path, exc_info=True)

    # Reconciliation
    divergence = False
    unified_regime = mdx_regime  # default: trust M/D/K/X

    if hmm_regime == "crisis" and mdx_regime in ("relieving", "stress_relief"):
        divergence = True
        unified_regime = "post_crisis_relief"
        note = "HMM still sees crisis patterns in raw data, but M/D/K/X show stress is declining. Trust M/D/K/X: system is in post-crisis relief phase."
    elif hmm_regime == "compression" and mdx_regime in ("stress_building", "elevated"):
        divergence = True
        unified_regime = "pre_stress_buildup"
        note = "HMM sees calm (low vol), but M/D/K/X show stress building underneath. Trust M/D/K/X: pre-stress buildup phase."
    elif hmm_regime == "crisis" and mdx_regime in ("stress_building", "elevated"):
        unified_regime = "active_stress"
        note = "Both HMM and M/D/K/X agree: stress is active and building."
        divergence = False
    else:
        note = f"HMM={hmm_regime}, M/D/K/X={mdx_regime}. Aligned."

    return {
        "hmm_regime": hmm_regime,
        "mdx_regime": mdx_regime,
        "unified_regime": unified_regime,
        "divergence": divergence,
        "stress_direction": round(stress_direction, 3),
        "hmm_signal_path": str(hmm_path),
        "hmm_signal_found": hmm_path.exists(),
        "note": note,
    }


def _load_claim_ladder_mechanisms() -> list[str]:
    """Load mechanism types from the current judgment's claim_ladder."""
    judgment_path = surface_dir("judgment") / "latest.json"
    if not judgment_path.exists():
        return []
    try:
        judgment = load_json(judgment_path) or {}
        ladder = judgment.get("claim_ladder", {})
        claim = ladder.get("claim_statement", "")
        # Extract mechanism names from claim statement
        # e.g. "Current structure resembles anchor_drift, funding_path_stress, ..."
        mechanisms = []
        if "resembles" in claim:
            after_resembles = claim.split("resembles")[1].split(".")[0]
            for part in after_resembles.split(","):
                m = part.strip().rstrip(".")
                if m and "_" in m:  # mechanism names have underscores
                    mechanisms.append(m)
        return mechanisms
    except Exception:
        logger.debug("Failed to parse mechanisms from resembles text", exc_info=True)
        return []


def _analyze_gap(results: list, mechanism_ctx: dict, top_score: float, usable_th: float) -> dict:
    """Analyze why the score didn't reach the usable threshold."""
    gap = round(max(0, usable_th - top_score), 4)
    if gap == 0:
        return {"status": "met", "gap": 0}

    # Check which component is weakest
    if not results:
        return {"status": "no_matches", "gap": gap, "reason": "No historical cases found"}

    top = results[0]
    components = {
        "var_score": top.var_score,
        "tag_score": top.tag_score,
        "text_score": top.text_score,
        "mechanism_score": top.mechanism_score,
    }
    weakest = min(components, key=components.get)

    # Check mechanism coverage
    query_mechs = set(mechanism_ctx.get("mechanism_types", []))
    matched_mechs = set(top.matched_mechanisms or [])
    missing_mechs = query_mechs - matched_mechs

    reason_parts = []
    if weakest == "mechanism_score":
        reason_parts.append(f"mechanism matching weak ({top.mechanism_score:.3f})")
        if missing_mechs:
            reason_parts.append(f"missing: {', '.join(missing_mechs)}")
    elif weakest == "text_score":
        reason_parts.append(f"text/keyword similarity weak ({top.text_score:.3f})")
    elif weakest == "var_score":
        reason_parts.append(f"structural vector distance large ({top.var_score:.3f})")
    elif weakest == "tag_score":
        reason_parts.append(f"tag overlap low ({top.tag_score:.3f})")

    return {
        "status": "below_threshold",
        "gap": gap,
        "weakest_component": weakest,
        "weakest_value": components[weakest],
        "reason": "; ".join(reason_parts) if reason_parts else "multiple components weak",
        "missing_mechanisms": list(missing_mechs) if missing_mechs else [],
    }


def _classify_review_priority(result, match_quality: str) -> str:
    """Classify a match for human review priority."""
    if match_quality == "strong":
        return "high"
    if match_quality == "usable" and result.mechanism_score > CASELAB_USABLE_THRESHOLD:
        return "high"
    if match_quality == "usable":
        return "medium"
    if result.mechanism_score > CASELAB_USABLE_THRESHOLD and result.score > CASELAB_WEAK_THRESHOLD:
        return "medium"
    return "low"


def _build_why_not_usable(
    result,
    query_mechanisms: set[str],
    usable_threshold: float,
) -> str:
    """Explain per-case why the score didn't reach usable threshold.

    Returns a human-readable string explaining the specific reasons.
    """
    if result.score >= usable_threshold:
        return ""

    parts = []
    gap = round(usable_threshold - result.score, 4)

    # Check mechanism coverage
    matched = set(result.matched_mechanisms or [])
    missing = query_mechanisms - matched
    if missing:
        parts.append(f"missing mechanisms: {', '.join(sorted(missing))}")
    if not matched and query_mechanisms:
        parts.append("no mechanism overlap at all")

    # Identify weakest scoring component
    components = {
        "mechanism": result.mechanism_score,
        "keyword": result.text_score,
        "vector": result.var_score,
        "tag": result.tag_score,
    }
    weakest_name = min(components, key=components.get)
    weakest_val = components[weakest_name]
    if weakest_val < 0.2:
        parts.append(f"{weakest_name} score very low ({weakest_val:.3f})")

    parts.append(f"gap to usable: {gap:.3f}")
    return "; ".join(parts)


def _build_review_candidates(
    matches_output: list[dict],
    query_mechanisms: set[str],
) -> list[dict]:
    """Build the review candidates list from match output.

    Selects cases that are close to usable or have high mechanism overlap
    but low overall score — the most informative cases for human review.
    """
    candidates = []
    for m in matches_output:
        score = m.get("score", 0)
        mech_score = m.get("mechanism_score", 0)
        matched = set(m.get("matched_mechanisms", []))
        review_priority = m.get("review_priority", "low")

        # Include if: review priority is high/medium, OR mechanism overlap
        # is good but overall score is low (informative mismatch)
        is_worth_review = (
            review_priority in ("high", "medium")
            or (mech_score > 0.4 and score < USABLE_THRESHOLD)
            or (len(matched) >= 2 and score < USABLE_THRESHOLD)
        )
        if not is_worth_review:
            continue

        missing = query_mechanisms - matched
        candidates.append({
            "case_id": m.get("case_id"),
            "case_name": m.get("case_name"),
            "score": score,
            "mechanism_score": mech_score,
            "matched_mechanisms": sorted(matched),
            "missing_mechanisms": sorted(missing),
            "why_not_usable": m.get("why_not_usable", ""),
            "review_priority": review_priority,
            "review_reason": _review_reason(m, query_mechanisms),
        })

    # Sort by review_priority then by score
    priority_order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: (priority_order.get(c["review_priority"], 9), -c["score"]))
    return candidates


def _review_reason(m: dict, query_mechanisms: set[str]) -> str:
    """Generate a short reason why this case is a review candidate."""
    matched = set(m.get("matched_mechanisms", []))
    score = m.get("score", 0)
    mech_score = m.get("mechanism_score", 0)

    if score >= USABLE_THRESHOLD:
        return "meets usable threshold"
    if mech_score > CASELAB_USABLE_THRESHOLD:
        return f"strong mechanism match ({mech_score:.3f}) but overall score low"
    if len(matched) >= 2:
        return f"multiple mechanisms matched ({len(matched)}) but score still below threshold"
    if score > USABLE_THRESHOLD - 0.1:
        return f"close to usable threshold (gap={USABLE_THRESHOLD - score:.3f})"
    return "has partial mechanism overlap"


def run_signal(top_k: int = 5, json_only: bool = False) -> dict:
    """Run the daily CaseLab signal and return results."""
    from nlp.caselab.enhanced_similarity import EnhancedSimilarityEngine

    # 1. Get current state
    state = get_latest_state()

    # 2. Convert to S-A-L-V-P-tau
    vec = mdx_to_salvptau(state)

    # 3. Derive tags and text
    tags = derive_tags(state)
    event_text = derive_event_text(state)

    # 3.5. Reconcile HMM vs M/D/K/X
    reconciliation = reconcile_regime(state)

    # 3.6. Detect mechanism types and build context packet
    mechanism_ctx = detect_mechanism_types(state)
    context_packet = build_context_packet(state, vec, reconciliation)

    # 3.7. Enrich with claim_ladder mechanisms from judgment
    claim_ladder_mechanisms = _load_claim_ladder_mechanisms()
    if claim_ladder_mechanisms:
        existing = set(mechanism_ctx.get("mechanism_types", []))
        for m in claim_ladder_mechanisms:
            if m not in existing:
                mechanism_ctx.setdefault("mechanism_types", []).append(m)
        mechanism_ctx["claim_ladder_enriched"] = True

    # 4. Run similarity (with mechanism context)
    engine = EnhancedSimilarityEngine(ROOT)
    results = engine.find_similar(
        variable_vector=vec,
        tags=tags,
        event_text=event_text,
        mechanism_context=mechanism_ctx,
        top_k=top_k,
    )
    top_score = float(results[0].score) if results else 0.0

    # New scoring policy
    if top_score >= STRONG_THRESHOLD:
        match_quality = "strong"
        interpretation = "CaseLab match is strong analogy only, not forecast."
    elif top_score >= USABLE_THRESHOLD:
        match_quality = "usable"
        interpretation = "CaseLab match is usable as analogy only, not as forecast."
    elif top_score >= WEAK_THRESHOLD:
        match_quality = "weak"
        interpretation = "CaseLab match is weak analogy only; do not treat as historical forecast."
    else:
        match_quality = "no_reliable_analogy"
        interpretation = "No reliable historical analogy today. Top matches are debug/reference only."

    # 5. Build output
    output = {
        **FROZEN_V1_STAMP,
        "timestamp": utc_now().isoformat(),
        "operational_direction": _operational_direction(),
        "system_state": {
            "date": state.get("date"),
            "M": state.get("M"),
            "K": state.get("K"),
            "D": state.get("D"),
            "X": state.get("X"),
            "sigma_t": state.get("sigma_t"),
            "pattern": state.get("pattern"),
            "leading_channel": state.get("leading_channel"),
            "direction": state.get("direction"),
            "escalation": state.get("escalation"),
            "active_operators": state.get("active_operators", []),
        },
        "context_packet": context_packet,
        "mechanism_context": mechanism_ctx,
        "derived_vector": vec,
        "derived_tags": tags,
        "event_text": event_text[:500],
        "regime_reconciliation": reconciliation,
        "match_quality": {
            "label": match_quality,
            "top_score": round(top_score, 4),
            "thresholds": {
                "strong": STRONG_THRESHOLD,
                "usable": USABLE_THRESHOLD,
                "weak": WEAK_THRESHOLD,
            },
            "gap_to_usable": round(max(0, USABLE_THRESHOLD - top_score), 4),
            "interpretation": interpretation,
            "score_breakdown": {
                "var_weight": 0.25,
                "tag_weight": 0.05,
                "keyword_weight": 0.15,
                "mechanism_weight": 0.55,
            },
            "gap_analysis": _analyze_gap(results, mechanism_ctx, top_score, USABLE_THRESHOLD),
        },
        "matches": [],
    }

    # Build per-match entries with mechanism analysis
    query_mechs = set(mechanism_ctx.get("mechanism_types", []))
    matches_raw = []
    for i, r in enumerate(results):
        matched_mechs = set(r.matched_mechanisms or [])
        missing_mechs = query_mechs - matched_mechs
        review_priority = _classify_review_priority(r, match_quality)

        entry = {
            "rank": i + 1,
            "case_id": r.case_id,
            "case_name": r.case_name,
            "score": r.score,
            "var_score": r.var_score,
            "tag_score": r.tag_score,
            "text_score": r.text_score,
            "mechanism_score": r.mechanism_score,
            "matched_mechanisms": sorted(matched_mechs),
            "missing_mechanisms": sorted(missing_mechs),
            "why_not_usable": _build_why_not_usable(r, query_mechs, USABLE_THRESHOLD),
            "shared_tags": r.shared_tags,
            "shared_concepts": [{"concept": c, "freq": s} for c, s in r.shared_concepts],
            "review_priority": review_priority,
            # Suppress narratives for weak/no-reliable matches
            "narrative": (
                r.narrative_summary[:200]
                if match_quality in ("strong", "usable")
                else "[suppressed: weak/no reliable analogy]"
            ),
        }
        output["matches"].append(entry)
        matches_raw.append(entry)

    # Review candidates — cases worth human review
    output["review_candidates"] = _build_review_candidates(matches_raw, query_mechs)

    # 6. Write output
    ensure_dir(OUTPUT_DIR)
    today = utc_now().strftime("%Y-%m-%d")

    json_path = OUTPUT_DIR / f"{today}.json"
    write_json(json_path, output)

    if not json_only:
        md_path = OUTPUT_DIR / f"{today}.md"
        md_path.write_text(_format_markdown(output), encoding="utf-8")
        print(f"Output: {md_path}")

    return output


def _format_markdown(output: dict) -> str:
    """Format output as readable markdown."""
    s = output["system_state"]
    vec = output["derived_vector"]
    def _fv(v):
        return f"{v:.3f}" if v is not None else "N/A"
    mq = output["match_quality"]
    lines = [
        f"# CaseLab Daily Signal — {output['timestamp'][:10]}",
        "",
        f"- **Theory authority:** {output.get('theory_authority', False)}",
        f"- **Direction formula:** {output.get('direction_formula', 'archived_v1_mdkx_mean')} (diagnostic only)",
        "",
        "## System State",
        f"- **Date:** {s['date']}",
        f"- **M/D/K/X:** {_fv(s['M'])} / {_fv(s['D'])} / {_fv(s['K'])} / {_fv(s['X'])}",
        f"- **σ(t):** {s['sigma_t']:.3f}" if s.get("sigma_t") else "- **σ(t):** N/A",
        f"- **Pattern:** {s['pattern']}",
        f"- **Leading channel:** {s['leading_channel']}",
        f"- **Direction:** {s['direction']}",
        f"- **Escalation:** {'YES' if s.get('escalation') else 'No'}",
        "",
        "## Derived S-A-L-V-P-tau",
        "```",
        f"S={vec['S']:.3f}  A={vec['A']:.3f}  L={vec['L']:.3f}  V={vec['V']:.3f}  P={vec['P']:.3f}  τ={vec['tau']:.3f}",
        "```",
        "",
        "## Tags",
        f"`{'` `'.join(output['derived_tags'])}`",
        "",
        "## Event Description",
        f"> {output['event_text'][:300]}",
        "",
        "## Match Quality",
        f"- **Label:** {mq['label']}",
        f"- **Top score:** {mq['top_score']:.3f}",
        f"- **Gap to usable:** {mq.get('gap_to_usable', 0):.3f}",
        f"- **Thresholds:** strong ≥ {mq['thresholds']['strong']:.2f}, usable ≥ {mq['thresholds']['usable']:.2f}, weak ≥ {mq['thresholds']['weak']:.2f}",
        f"- **Interpretation:** {mq['interpretation']}",
        "",
        "## Top Matches",
        "",
    ]

    # Gap analysis
    gap = output["match_quality"].get("gap_analysis", {})
    if gap.get("status") == "below_threshold":
        lines += [
            "## Gap Analysis",
            f"- **Gap to usable:** {gap['gap']:.3f}",
            f"- **Weakest component:** {gap.get('weakest_component', 'unknown')} ({gap.get('weakest_value', 0):.3f})",
            f"- **Reason:** {gap.get('reason', 'unknown')}",
        ]
        if gap.get("missing_mechanisms"):
            lines.append(f"- **Missing mechanisms:** {', '.join(gap['missing_mechanisms'])}")
        lines.append("")

    # Mechanism enrichment
    mc = output.get("mechanism_context", {})
    if mc.get("claim_ladder_enriched"):
        lines += [
            "## Mechanism Context (enriched from claim_ladder)",
            f"- **Types:** {', '.join(mc.get('mechanism_types', []))}",
            "",
        ]

    for m in output["matches"]:
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(m.get("review_priority", "low"), "⚪")
        lines.append(f"### {priority_icon} {m['rank']}. {m['case_name']} (score={m['score']:.3f}, review={m.get('review_priority', 'low')})")
        lines.append(f"- var={m['var_score']:.3f}  tag={m['tag_score']:.3f}  text={m['text_score']:.3f}  mech={m['mechanism_score']:.3f}")
        if m.get("matched_mechanisms"):
            lines.append(f"- **matched_mechanisms:** {', '.join(m['matched_mechanisms'])}")
        if m.get("missing_mechanisms"):
            lines.append(f"- **missing_mechanisms:** {', '.join(m['missing_mechanisms'])}")
        if m.get("why_not_usable"):
            lines.append(f"- **why_not_usable:** {m['why_not_usable']}")
        if m["shared_tags"]:
            lines.append(f"- tags: {', '.join(m['shared_tags'])}")
        if m["shared_concepts"]:
            concepts = ", ".join(f"{c['concept']}({c['freq']:.0f})" for c in m["shared_concepts"][:5])
            lines.append(f"- concepts: {concepts}")
        if m["narrative"] and not m["narrative"].startswith("[suppressed"):
            lines.append(f"- narrative: {m['narrative'][:150]}")
        lines.append("")

    # Review candidates section
    review = output.get("review_candidates", [])
    if review:
        lines += [
            "---",
            "",
            "## Review Candidates",
            "",
            f"Cases worth human review: **{len(review)}**",
            "",
        ]
        for rc in review:
            lines.append(
                f"- `{rc['case_id']}` — {rc['case_name']} "
                f"(score={rc['score']:.3f}, mech={rc['mechanism_score']:.3f}, "
                f"priority={rc['review_priority']})"
            )
            if rc.get("matched_mechanisms"):
                lines.append(f"  - matched: {', '.join(rc['matched_mechanisms'])}")
            if rc.get("missing_mechanisms"):
                lines.append(f"  - missing: {', '.join(rc['missing_mechanisms'])}")
            if rc.get("why_not_usable"):
                lines.append(f"  - why: {rc['why_not_usable']}")
            if rc.get("review_reason"):
                lines.append(f"  - reason: {rc['review_reason']}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Daily CaseLab signal")
    parser.add_argument("--json", action="store_true", help="JSON output only")
    parser.add_argument("--top", type=int, default=5, help="Top N matches")
    args = parser.parse_args()

    output = run_signal(top_k=args.top, json_only=args.json)

    # Print summary
    s = output["system_state"]
    print(f"\n=== CaseLab Daily Signal — {s['date']} ===")

    def _fv(v: float | None) -> str:
        return f"{v:.3f}" if v is not None else "N/A"

    print(f"M/D/K/X: {_fv(s['M'])} / {_fv(s['D'])} / {_fv(s['K'])} / {_fv(s['X'])}")
    print(f"Pattern: {s['pattern']}  Leading: {s['leading_channel']}  Direction: {s['direction']}")
    print()

    vec = output["derived_vector"]
    print(f"S-A-L-V-P-tau: S={vec['S']:.3f} A={vec['A']:.3f} L={vec['L']:.3f} V={vec['V']:.3f} P={vec['P']:.3f} τ={vec['tau']:.3f}")
    print(f"Tags: {output['derived_tags']}")
    print()

    for m in output["matches"]:
        c = ", ".join(f"{c['concept']}" for c in m["shared_concepts"][:3])
        print(f"  {m['rank']}. {m['case_name'][:50]:<50} {m['score']:.3f}  [{c}]")


if __name__ == "__main__":
    main()
