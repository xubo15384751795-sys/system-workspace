"""Claim Ladder — graduated claim tiers for the judgment system.

The claim ladder replaces the binary blocked/pass model with a graduated
system where the system can express increasingly specific claims as
evidence quality improves.

Tiers:
  0. diagnostic_claim       — raw observations (always available)
  1. mechanism_hypothesis   — "this structure resembles X mechanism"
  2. watch_condition        — "watch for Y to confirm/invalidate"
  3. invalidation_condition — "if Z happens, hypothesis is wrong"

Each tier is strictly additive — you can't skip tiers. The system can
only be at one tier at a time. Promotion requires meeting the conditions
of the next tier; demotion happens when current-tier conditions are no
longer met.

Usage:
    from workbench.judgment.claim_ladder import evaluate_claim_tier

    ladder = evaluate_claim_tier(
        judgment=judgment_card,
        caselab=caselab_output,
        hmm=hmm_output,
        mechanism_context=mechanism_ctx,
        run_history=recent_runs,
    )
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Tier definitions ────────────────────────────────────────────────────

CLAIM_LADDER_TIERS: dict[int, dict[str, Any]] = {
    0: {
        "label": "diagnostic_claim",
        "description": "Raw observations: M/D/K/X values, stress direction, pattern.",
        "allowed_language": [
            "measurement", "reading", "observation", "diagnostic",
            "stress direction", "pattern", "value",
        ],
        "forbidden_language": [
            "mechanism", "resembles", "hypothesis", "regime",
            "prediction", "forecast", "signal",
        ],
    },
    1: {
        "label": "mechanism_hypothesis",
        "description": "Structural comparison: the current state resembles a known mechanism.",
        "allowed_language": [
            "measurement", "reading", "observation", "diagnostic",
            "mechanism", "resembles", "structural similarity",
            "historical pattern", "analogy",
        ],
        "forbidden_language": [
            "prediction", "forecast", "signal", "regime call",
            "directional conviction", "position",
        ],
    },
    2: {
        "label": "watch_condition",
        "description": "Specific observable conditions to monitor for confirmation/invalidation.",
        "allowed_language": [
            "measurement", "observation", "mechanism", "resembles",
            "watch", "monitor", "condition", "threshold",
            "if-then", "upgrade path",
        ],
        "forbidden_language": [
            "prediction", "forecast", "signal", "position",
            "directional conviction",
        ],
    },
    3: {
        "label": "invalidation_condition",
        "description": "Explicit falsification criteria for the current hypothesis.",
        "allowed_language": [
            "measurement", "observation", "mechanism", "resembles",
            "watch", "monitor", "condition", "invalidation",
            "falsification", "boundary", "diagnostic claim",
        ],
        "forbidden_language": [
            "prediction", "forecast", "signal", "position",
        ],
    },
}

# Minimum CaseLab score to qualify for Tier 1
_CASELAB_TIER1_THRESHOLD = 0.30
# CaseLab score below which demotion to Tier 0
_CASELAB_DEMOTION_THRESHOLD = 0.20
# Minimum consecutive runs with same M/D direction for Tier 2
_PERSISTENCE_RUNS_FOR_TIER2 = 2


@dataclass
class ClaimTier:
    """Result of claim ladder evaluation."""
    tier: int
    label: str
    claim_statement: str
    watch_conditions: list[str] = field(default_factory=list)
    invalidation_conditions: list[str] = field(default_factory=list)
    promotion_conditions: dict[str, str] = field(default_factory=dict)
    demotion_risk: str = ""
    allowed_language: list[str] = field(default_factory=list)
    forbidden_language: list[str] = field(default_factory=list)
    md_direction: str = ""
    persistence_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "label": self.label,
            "claim_statement": self.claim_statement,
            "watch_conditions": self.watch_conditions,
            "invalidation_conditions": self.invalidation_conditions,
            "promotion_conditions": self.promotion_conditions,
            "demotion_risk": self.demotion_risk,
            "allowed_language": self.allowed_language,
            "forbidden_language": self.forbidden_language,
            "md_direction": self.md_direction,
            "persistence_count": self.persistence_count,
        }


# ── Evaluation logic ────────────────────────────────────────────────────

def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _get_md_direction(judgment: dict) -> tuple[float, float, str]:
    """Extract M, D values and direction label from judgment card."""
    meaning = judgment.get("meaning", [])
    # Try to parse M and D from meaning strings
    m_val, d_val = 0.0, 0.0
    for line in meaning:
        if "M=" in line and "D=" in line:
            import re
            m_match = re.search(r"M=(-?[\d.]+)", line)
            d_match = re.search(r"D=(-?[\d.]+)", line)
            if m_match:
                m_val = float(m_match.group(1))
            if d_match:
                d_val = float(d_match.group(1))
            break

    stress_dir = (m_val + d_val) / 2.0
    if stress_dir > 0.3:
        direction = "stress_building"
    elif stress_dir < -0.3:
        direction = "stress_relief"
    else:
        direction = "neutral"
    return m_val, d_val, direction


def _check_caselab_for_tier1(caselab: dict | None) -> tuple[bool, float, str]:
    """Check if CaseLab qualifies for Tier 1."""
    if not caselab:
        return False, 0.0, "no CaseLab output"
    mq = caselab.get("match_quality", {})
    top_score = _as_float(mq.get("top_score", 0))
    label = mq.get("label", "unknown")
    if top_score >= _CASELAB_TIER1_THRESHOLD:
        return True, top_score, f"CaseLab score {top_score:.3f} >= {_CASELAB_TIER1_THRESHOLD}"
    return False, top_score, f"CaseLab score {top_score:.3f} < {_CASELAB_TIER1_THRESHOLD}"


def _check_mechanism_context(caselab: dict | None) -> tuple[bool, list[str]]:
    """Check if mechanism types were detected in CaseLab output."""
    if not caselab:
        return False, []
    mc = caselab.get("mechanism_context", {})
    types = mc.get("mechanism_types", [])
    return len(types) > 0, types


def _check_persistence(
    run_history: list[dict] | None,
    current_direction: str,
) -> tuple[bool, int]:
    """Check how many consecutive runs share the same M/D direction.

    Counts the current run plus matching prior runs (newest first).
    Returns (meets_threshold, consecutive_count).
    """
    if current_direction in ("", "unknown", "neutral"):
        return False, 0

    count = 1  # current run
    if not run_history:
        return count >= _PERSISTENCE_RUNS_FOR_TIER2, count

    for run in run_history:
        run_dir = run.get("md_direction", "")
        if run_dir == current_direction:
            count += 1
        else:
            break

    return count >= _PERSISTENCE_RUNS_FOR_TIER2, count


def _derive_invalidation_conditions(
    m_val: float, d_val: float, direction: str, mechanism_types: list[str],
) -> list[str]:
    """Derive invalidation conditions from current state."""
    conditions = []

    if direction == "stress_relief":
        # If M reverses sign, relief hypothesis is weakened
        conditions.append(
            f"If M reverses sign (currently {m_val:.2f}), "
            f"the stress-relief hypothesis is invalidated."
        )
        # If K rises significantly
        conditions.append(
            "If K curvature proxy rises above 0.5, "
            "structural stress is re-emerging."
        )
    elif direction == "stress_building":
        conditions.append(
            f"If M falls below 0 (currently {m_val:.2f}), "
            f"the stress-building hypothesis weakens."
        )
        conditions.append(
            "If K curvature proxy drops below -0.3, "
            "structural stress is relieving."
        )
    else:
        conditions.append(
            "If M or D move decisively (>0.5 absolute), "
            "the neutral state is broken."
        )

    # Mechanism-specific invalidation
    if "anchor_drift" in mechanism_types:
        conditions.append(
            "If M anchor re-anchors to a new stable level, "
            "the drift hypothesis is resolved."
        )
    if "funding_path_stress" in mechanism_types:
        conditions.append(
            "If funding spreads normalize (repo stress < 0.2), "
            "the funding path stress is no longer active."
        )
    if "relief_decompression" in mechanism_types:
        conditions.append(
            "If volatility re-emerges (sigma > 0.6), "
            "the decompression phase is ending."
        )

    return conditions


def _generate_claim_statement(
    tier: int, m_val: float, d_val: float, direction: str,
    mechanism_types: list[str], top_score: float,
) -> str:
    """Generate a human-readable claim statement for the current tier."""
    if tier == 0:
        return (
            f"M={m_val:.3f}, D={d_val:.3f}; "
            f"stress direction is {direction}. "
            f"This is a measurement observation, not a structural judgment."
        )

    mech_str = ", ".join(mechanism_types) if mechanism_types else "no specific mechanism"
    base = (
        f"Current structure resembles {mech_str}. "
        f"M={m_val:.3f}, D={d_val:.3f}; direction: {direction}."
    )

    if tier == 1:
        return (
            f"{base} "
            f"This is a mechanism hypothesis (CaseLab score: {top_score:.3f}), "
            f"not a directional forecast."
        )

    if tier == 2:
        return (
            f"{base} "
            f"Watch conditions defined for confirmation/invalidation. "
            f"This supports monitoring, not position sizing."
        )

    if tier == 3:
        return (
            f"{base} "
            f"Invalidation conditions explicitly defined. "
            f"This is a diagnostic claim with clear falsification boundaries."
        )

    return base


def _generate_watch_conditions(
    tier: int, m_val: float, d_val: float, direction: str,
    caselab: dict | None, mechanism_types: list[str],
    persistence_count: int,
) -> list[str]:
    """Generate watch conditions for Tier 1+."""
    if tier < 1:
        return []

    conditions = []

    top_score = _as_float((caselab or {}).get("match_quality", {}).get("top_score", 0))
    gap_to_usable = max(0, 0.55 - top_score)

    if top_score < 0.55:
        conditions.append(
            f"If CaseLab top_score rises above 0.55 (currently {top_score:.3f}, "
            f"gap: {gap_to_usable:.3f}), the mechanism analogy becomes usable."
        )

    if tier < 2:
        if persistence_count < _PERSISTENCE_RUNS_FOR_TIER2:
            remaining = _PERSISTENCE_RUNS_FOR_TIER2 - persistence_count
            conditions.append(
                f"If M/D stress direction ({direction}) persists for "
                f"{remaining} more consecutive run(s), "
                f"upgrade to watch_condition tier."
            )
    else:
        conditions.append(
            f"M/D direction ({direction}) has persisted for "
            f"{persistence_count} consecutive runs."
        )

    if direction == "stress_relief":
        conditions.append(
            "Monitor for M reversal (sign change) — "
            "would indicate relief is ending."
        )
    elif direction == "stress_building":
        conditions.append(
            "Monitor for K/X attenuation — "
            "would indicate stress is plateauing."
        )

    return conditions


def evaluate_claim_tier(
    judgment: dict,
    caselab: dict | None = None,
    hmm: dict | None = None,
    mechanism_context: dict | None = None,
    run_history: list[dict] | None = None,
) -> ClaimTier:
    """Evaluate the current claim ladder tier.

    Parameters
    ----------
    judgment : dict
        The judgment card (Output/judgment/latest.json).
    caselab : dict, optional
        CaseLab daily signal output.
    hmm : dict, optional
        HMM regime detection output.
    mechanism_context : dict, optional
        Mechanism context from caselab_daily_signal.
    run_history : list[dict], optional
        Recent run summaries for persistence checking.
        Each dict should have at least 'md_direction' key.

    Returns
    -------
    ClaimTier
        The current tier with all claim components.
    """
    m_val, d_val, direction = _get_md_direction(judgment)

    # Check Tier 1 eligibility
    caselab_qualifies, top_score, caselab_reason = _check_caselab_for_tier1(caselab)
    mech_qualifies, mechanism_types = _check_mechanism_context(caselab)

    # Also check mechanism_context if provided separately
    if not mech_qualifies and mechanism_context:
        mc_types = mechanism_context.get("mechanism_types", [])
        if mc_types:
            mech_qualifies = True
            mechanism_types = mc_types

    tier1_eligible = caselab_qualifies or mech_qualifies

    # Check Tier 2 eligibility (persistence)
    persistence_ok, persistence_count = _check_persistence(run_history, direction)

    # Check Tier 3 eligibility (invalidation conditions derivable)
    invalidation_conditions = []
    if tier1_eligible:
        invalidation_conditions = _derive_invalidation_conditions(
            m_val, d_val, direction, mechanism_types,
        )
    tier3_eligible = len(invalidation_conditions) > 0 and persistence_ok

    # Determine tier
    if tier3_eligible:
        tier = 3
    elif persistence_ok and tier1_eligible:
        tier = 2
    elif tier1_eligible:
        tier = 1
    else:
        tier = 0

    # Generate components
    claim_statement = _generate_claim_statement(
        tier, m_val, d_val, direction, mechanism_types, top_score,
    )

    watch_conditions = _generate_watch_conditions(
        tier, m_val, d_val, direction, caselab, mechanism_types, persistence_count,
    )

    if tier < 3:
        # Generate potential invalidation conditions for display
        invalidation_conditions = _derive_invalidation_conditions(
            m_val, d_val, direction, mechanism_types,
        )

    # Promotion conditions
    promotion = {}
    if tier < 1:
        promotion["to_tier_1"] = (
            f"CaseLab top_score >= {_CASELAB_TIER1_THRESHOLD} "
            f"(currently {top_score:.3f}) OR mechanism types detected"
        )
    if tier < 2:
        promotion["to_tier_2"] = (
            f"M/D direction persisted >= {_PERSISTENCE_RUNS_FOR_TIER2} runs "
            f"(currently {persistence_count})"
        )
    if tier < 3:
        promotion["to_tier_3"] = "At least 1 invalidation condition explicitly tracked"

    # Demotion risk
    demotion_risks = []
    if top_score < _CASELAB_DEMOTION_THRESHOLD and top_score > 0:
        demotion_risks.append(
            f"CaseLab score {top_score:.3f} near demotion threshold "
            f"({_CASELAB_DEMOTION_THRESHOLD})"
        )
    if direction in ("stress_relief", "stress_building"):
        demotion_risks.append(
            f"M/D direction reversal would demote to Tier 0"
        )
    if not demotion_risks:
        demotion_risks.append("No immediate demotion risk")

    tier_def = CLAIM_LADDER_TIERS[tier]

    return ClaimTier(
        tier=tier,
        label=tier_def["label"],
        claim_statement=claim_statement,
        watch_conditions=watch_conditions,
        invalidation_conditions=invalidation_conditions,
        promotion_conditions=promotion,
        demotion_risk="; ".join(demotion_risks),
        allowed_language=tier_def["allowed_language"],
        forbidden_language=tier_def["forbidden_language"],
        md_direction=direction,
        persistence_count=persistence_count,
    )
