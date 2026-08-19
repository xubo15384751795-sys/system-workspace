"""Policy-backed claim ladder evaluation for the judgment system.

The governance policy is the only authority for tier labels, language, and
promotion/demotion requirements. This module evaluates typed measurement and
evidence context; rendered ``meaning`` strings are never parsed back into
machine values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[5]
POLICY_PATH = ROOT / "governance" / "claim_ladder_policy.yaml"


def _load_policy() -> dict[str, Any]:
    try:
        payload = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"claim ladder policy unavailable: {POLICY_PATH}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("tiers"), dict):
        raise RuntimeError(f"claim ladder policy has no tiers: {POLICY_PATH}")
    return payload


CLAIM_LADDER_POLICY = _load_policy()
CLAIM_LADDER_POLICY_VERSION = str(
    CLAIM_LADDER_POLICY.get("schema_version", "claim_ladder_policy.v1")
)

# Compatibility export for consumers that used the old module constant. The
# values are projected from policy at import time; they are not a second rule
# source.
CLAIM_LADDER_TIERS: dict[int, dict[str, Any]] = {
    int(key): dict(value)
    for key, value in CLAIM_LADDER_POLICY["tiers"].items()
    if isinstance(value, dict)
}


def _policy_rule(tier: int, *, section: str, rule_id: str) -> str | None:
    for item in CLAIM_LADDER_TIERS.get(tier, {}).get(section, []) or []:
        if isinstance(item, dict) and item.get("id") == rule_id:
            raw = item.get("rule")
            return str(raw) if raw is not None else None
    return None


def _rule_threshold(tier: int, *, section: str, rule_id: str) -> float:
    rule = _policy_rule(tier, section=section, rule_id=rule_id)
    if not rule:
        raise RuntimeError(
            f"claim ladder policy rule is missing: tier={tier} section={section} id={rule_id}"
        )
    tokens = rule.replace(")", " ").replace("(", " ").split()
    for index, token in enumerate(tokens):
        if token in {">=", "<=", ">", "<", "==", "!="} and index + 1 < len(tokens):
            try:
                return float(tokens[index + 1])
            except ValueError:
                continue
    raise RuntimeError(f"claim ladder policy rule is not numeric: {rule_id}={rule}")


# These are projections of the single governance policy for compatibility
# with old callers and tests.
_CASELAB_TIER1_THRESHOLD = _rule_threshold(
    1, section="promotion_requirements", rule_id="caselab_score_above_threshold"
)
_CASELAB_DEMOTION_THRESHOLD = _rule_threshold(
    1, section="demotion_triggers", rule_id="caselab_score_below_threshold"
)
_PERSISTENCE_RUNS_FOR_TIER2 = int(
    _rule_threshold(2, section="promotion_requirements", rule_id="md_direction_persistence")
)


@dataclass
class ClaimTier:
    """Result of policy evaluation for one current canonical claim set."""

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
    md_values: dict[str, float] = field(default_factory=dict)
    persistence_count: int = 0
    policy_version: str = CLAIM_LADDER_POLICY_VERSION
    evidence: dict[str, Any] = field(default_factory=dict)
    promotion_blockers: list[dict[str, Any]] = field(default_factory=list)

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
            "md_values": self.md_values,
            "persistence_count": self.persistence_count,
            "policy_version": self.policy_version,
            "evidence": self.evidence,
            "promotion_blockers": self.promotion_blockers,
        }


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _get_md_direction(judgment: dict[str, Any]) -> tuple[float, float, str]:
    """Read M/D from typed fields only.

    ``meaning`` is a rendered view and intentionally has no parsing fallback.
    """

    values = (
        judgment.get("md_values")
        or judgment.get("measurement_values")
        or judgment.get("measurements")
        or {}
    )
    if not isinstance(values, dict):
        values = {}
    m_val = _as_float(values.get("M", values.get("m")), 0.0)
    d_val = _as_float(values.get("D", values.get("d")), 0.0)
    stress_dir = (m_val + d_val) / 2.0
    if stress_dir > 0.3:
        direction = "stress_building"
    elif stress_dir < -0.3:
        direction = "stress_relief"
    else:
        direction = "neutral"
    return m_val, d_val, direction


def _check_caselab_for_tier1(caselab: dict | None) -> tuple[bool, float, str]:
    """Check the policy-derived Tier 1 CaseLab threshold."""

    if not caselab:
        return False, 0.0, "no CaseLab output"
    mq = caselab.get("match_quality", {})
    top_score = _as_float(mq.get("top_score", 0))
    if top_score >= _CASELAB_TIER1_THRESHOLD:
        return True, top_score, f"CaseLab score {top_score:.3f} >= {_CASELAB_TIER1_THRESHOLD}"
    return False, top_score, f"CaseLab score {top_score:.3f} < {_CASELAB_TIER1_THRESHOLD}"


def _check_mechanism_context(caselab: dict | None) -> tuple[bool, list[str]]:
    if not caselab:
        return False, []
    mc = caselab.get("mechanism_context", {})
    types = mc.get("mechanism_types", []) if isinstance(mc, dict) else []
    return bool(types), [str(item) for item in types]


def _check_persistence(
    run_history: list[dict] | None,
    current_direction: str,
) -> tuple[bool, int]:
    """Count consecutive typed direction values, including the current run."""

    if current_direction in ("", "unknown", "neutral"):
        return False, 0
    count = 1
    for run in run_history or []:
        if run.get("md_direction", "") == current_direction:
            count += 1
        else:
            break
    return count >= _PERSISTENCE_RUNS_FOR_TIER2, count


def _derive_invalidation_conditions(
    m_val: float, d_val: float, direction: str, mechanism_types: list[str],
) -> list[str]:
    """Render invalidation specs from operational M/D and named mechanisms.

    K/X are deliberately absent. Research-only measurements may request
    review, but cannot create invalidation authority for a canonical claim.
    """

    conditions: list[str] = []
    if direction == "stress_relief":
        conditions.append(
            f"If M reverses sign (currently {m_val:.2f}), the stress-relief hypothesis is invalidated."
        )
    elif direction == "stress_building":
        conditions.append(
            f"If M falls below 0 (currently {m_val:.2f}), the stress-building hypothesis weakens."
        )
    else:
        conditions.append("If M or D move decisively (>0.5 absolute), the neutral state is broken.")

    if "anchor_drift" in mechanism_types:
        conditions.append("If M anchor re-anchors to a new stable level, the drift hypothesis is resolved.")
    if "funding_path_stress" in mechanism_types:
        conditions.append("If funding spreads normalize (repo stress < 0.2), the funding path stress is no longer active.")
    if "relief_decompression" in mechanism_types:
        conditions.append("If volatility re-emerges (sigma > 0.6), the decompression phase is ending.")
    return conditions


def _generate_claim_statement(
    tier: int, m_val: float, d_val: float, direction: str,
    mechanism_types: list[str], top_score: float,
) -> str:
    label = str(CLAIM_LADDER_TIERS.get(tier, {}).get("label", ""))
    if not label:
        raise RuntimeError(f"claim ladder policy has no label for tier {tier}")
    if tier == 0:
        return (
            f"M={m_val:.3f}, D={d_val:.3f}; stress direction is {direction}. "
            "This is a measurement observation, not a structural judgment."
        )
    mech_str = ", ".join(mechanism_types) if mechanism_types else "no specific mechanism"
    base = f"Current structure resembles {mech_str}. M={m_val:.3f}, D={d_val:.3f}; direction: {direction}."
    if label == "mechanism_hypothesis":
        return f"{base} This is a mechanism hypothesis (CaseLab score: {top_score:.3f}), not a directional forecast."
    if label == "watch_condition":
        return f"{base} Watch conditions are defined for confirmation/invalidation. This supports monitoring, not position sizing."
    return f"{base} Policy requirements for {label} are satisfied only when their replay and review evidence is present."


def _generate_watch_conditions(
    tier: int, direction: str, caselab: dict | None, persistence_count: int,
) -> list[str]:
    if tier < 1:
        return []
    conditions: list[str] = []
    top_score = _as_float((caselab or {}).get("match_quality", {}).get("top_score", 0))
    if top_score < _CASELAB_TIER1_THRESHOLD:
        conditions.append(
            f"If CaseLab top_score improves from {top_score:.3f}, review whether the mechanism analogy remains useful."
        )
    if tier < 2 and persistence_count < _PERSISTENCE_RUNS_FOR_TIER2:
        remaining = _PERSISTENCE_RUNS_FOR_TIER2 - persistence_count
        conditions.append(
            f"If M/D stress direction ({direction}) persists for {remaining} more consecutive run(s), upgrade to watch_condition tier."
        )
    elif tier >= 2:
        conditions.append(f"M/D direction ({direction}) has persisted for {persistence_count} consecutive runs.")
    if direction == "stress_relief":
        conditions.append("Monitor for M reversal (sign change), which would indicate relief is ending.")
    elif direction == "stress_building":
        conditions.append("Monitor for M/D attenuation, which would indicate stress is plateauing.")
    return conditions


def _quality_grade(value: Any) -> str:
    text = str(value or "C").strip().upper()
    if text in {"A", "B", "C", "D", "F"}:
        return text
    if "HIGH" in text or "FULL" in text:
        return "B"
    if "LOW" in text or "REDUCED" in text or "PARTIAL" in text:
        return "C"
    return "C"


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if actual is None:
        return False
    if isinstance(expected, str) and expected.upper() in {"A", "B", "C", "D", "F"}:
        ranks = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
        actual_rank = ranks.get(_quality_grade(actual), 0)
        expected_rank = ranks[expected.upper()]
        return {
            ">=": actual_rank >= expected_rank,
            "<=": actual_rank <= expected_rank,
            ">": actual_rank > expected_rank,
            "<": actual_rank < expected_rank,
            "==": actual_rank == expected_rank,
            "!=": actual_rank != expected_rank,
        }[operator]
    try:
        if isinstance(expected, bool):
            actual_value: Any = actual if isinstance(actual, bool) else str(actual).lower() == "true"
        elif isinstance(expected, float):
            actual_value = float(actual)
        else:
            actual_value = int(actual)
    except (TypeError, ValueError):
        actual_value = str(actual)
    return {
        ">=": actual_value >= expected,
        "<=": actual_value <= expected,
        ">": actual_value > expected,
        "<": actual_value < expected,
        "==": actual_value == expected,
        "!=": actual_value != expected,
    }[operator]


def _check_rule(rule: str, evidence: dict[str, Any]) -> bool:
    """Evaluate the small declarative rule language used by policy YAML."""

    text = str(rule).strip()
    lowered = text.lower()
    if lowered == "any tier 2 demotion trigger":
        return bool(evidence.get("tier2_demotion_triggered", False))
    if " OR " in text:
        return any(_check_rule(part, evidence) for part in text.split(" OR "))
    if " AND " in text:
        return all(_check_rule(part, evidence) for part in text.split(" AND "))
    for operator in (">=", "<=", "!=", "==", ">", "<"):
        if operator not in text:
            continue
        variable, raw_expected = text.split(operator, 1)
        variable = variable.strip()
        raw_expected = raw_expected.strip()
        if raw_expected.lower() in {"true", "false"}:
            expected: Any = raw_expected.lower() == "true"
        else:
            try:
                expected = float(raw_expected) if "." in raw_expected else int(raw_expected)
            except ValueError:
                expected = raw_expected
        return _compare(evidence.get(variable), operator, expected)
    return bool(evidence.get(text, False))


def _requirements_for_tier(tier: int, evidence: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    requirements = CLAIM_LADDER_TIERS.get(tier, {}).get("promotion_requirements", []) or []
    blockers: list[dict[str, Any]] = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        rule = str(requirement.get("rule", ""))
        if not _check_rule(rule, evidence):
            blockers.append({
                "id": str(requirement.get("id", "unknown")),
                "rule": rule,
                "description": str(requirement.get("description", "")),
                "actual_value": evidence.get(rule.split()[0]),
            })
    return not blockers, blockers


def _active_demotion_triggers(tier: int, evidence: dict[str, Any]) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for trigger in CLAIM_LADDER_TIERS.get(tier, {}).get("demotion_triggers", []) or []:
        if not isinstance(trigger, dict):
            continue
        rule = str(trigger.get("rule", ""))
        if _check_rule(rule, evidence):
            active.append({
                "id": str(trigger.get("id", "unknown")),
                "severity": str(trigger.get("severity", "warning")),
                "description": str(trigger.get("description", "")),
            })
    return active


def evaluate_claim_tier(
    judgment: dict[str, Any],
    caselab: dict | None = None,
    hmm: dict | None = None,
    mechanism_context: dict | None = None,
    run_history: list[dict] | None = None,
    *,
    evidence_context: dict[str, Any] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> ClaimTier:
    """Evaluate the highest policy-satisfied claim tier.

    ``claims`` and ``evidence_context`` are the preferred API. The legacy
    CaseLab/HMM parameters remain as an adapter for existing callers, but the
    evaluator consumes only the structured values derived from them.
    """

    del claims  # compatibility parameter; structured context is the authority
    m_val, d_val, direction = _get_md_direction(judgment)
    _, top_score, _ = _check_caselab_for_tier1(caselab)
    _, mechanism_types = _check_mechanism_context(caselab)
    if not mechanism_types and mechanism_context:
        mc_types = mechanism_context.get("mechanism_types", [])
        if mc_types:
            mechanism_types = [str(item) for item in mc_types]

    _, persistence_count = _check_persistence(run_history, direction)
    invalidation_conditions = _derive_invalidation_conditions(m_val, d_val, direction, mechanism_types)
    assessment = dict(evidence_context or {})
    reconciliation = (caselab or {}).get("regime_reconciliation", {}) if caselab else {}
    hmm_conflict = bool(reconciliation.get("divergence", False))
    if isinstance(hmm, dict):
        hmm_conflict = hmm_conflict or bool(hmm.get("conflict", False))
    assessment.setdefault("caselab_top_score", top_score)
    assessment.setdefault("active_mechanism_count", len(mechanism_types))
    assessment.setdefault("md_direction", direction)
    assessment.setdefault("md_direction_consecutive_runs", persistence_count)
    assessment.setdefault("hmm_conflict", hmm_conflict)
    assessment.setdefault("hmm_conflict_consecutive_runs", 0)
    assessment.setdefault("md_direction_reversed", False)
    assessment.setdefault("invalidation_condition_count", len(invalidation_conditions))
    assessment.setdefault("invalidation_triggered_count", 0)
    assessment.setdefault("invalidation_triggered_and_recorded", 0)
    assessment.setdefault("invalidation_never_triggered_in_sample", False)
    assessment["data_quality_grade"] = _quality_grade(assessment.get("data_quality_grade", "C"))
    assessment.setdefault("replay_evaluation_count", 0)
    assessment.setdefault("replay_useful_rate", 0.0)
    assessment.setdefault("replay_false_positive_rate", 1.0)
    assessment.setdefault("mechanism_misleading_rate", 1.0)
    assessment.setdefault("learning_hub_unresolved_high_severity", 0)
    assessment.setdefault("tier2_duration_runs", 0)
    assessment["tier2_demotion_triggers"] = _active_demotion_triggers(2, assessment)
    assessment["tier2_demotion_triggered"] = bool(assessment["tier2_demotion_triggers"])

    max_tier = max(CLAIM_LADDER_TIERS, default=0)
    tier = 0
    blockers: list[dict[str, Any]] = []
    for candidate in range(1, max_tier + 1):
        eligible, candidate_blockers = _requirements_for_tier(candidate, assessment)
        if not eligible:
            blockers = candidate_blockers
            break
        tier = candidate

    tier_def = CLAIM_LADDER_TIERS.get(tier, {})
    label_value = tier_def.get("label")
    if not isinstance(label_value, str) or not label_value:
        raise RuntimeError(f"claim ladder policy has no label for tier {tier}")
    label = label_value
    claim_statement = _generate_claim_statement(tier, m_val, d_val, direction, mechanism_types, top_score)
    watch_conditions = _generate_watch_conditions(tier, direction, caselab, persistence_count)
    promotion: dict[str, str] = {}
    for candidate in range(tier + 1, max_tier + 1):
        requirements = CLAIM_LADDER_TIERS.get(candidate, {}).get("promotion_requirements", []) or []
        promotion[f"to_tier_{candidate}"] = "; ".join(
            str(item.get("description", item.get("rule", "")))
            for item in requirements if isinstance(item, dict)
        )
    active_triggers = _active_demotion_triggers(tier, assessment)
    demotion_risk = "; ".join(item["description"] for item in active_triggers)
    if not demotion_risk:
        demotion_risk = "No active policy demotion trigger"

    return ClaimTier(
        tier=tier,
        label=label,
        claim_statement=claim_statement,
        watch_conditions=watch_conditions,
        invalidation_conditions=invalidation_conditions,
        promotion_conditions=promotion,
        demotion_risk=demotion_risk,
        allowed_language=list(tier_def.get("allowed_language", [])),
        forbidden_language=list(tier_def.get("forbidden_language", [])),
        md_direction=direction,
        md_values={"M": m_val, "D": d_val},
        persistence_count=persistence_count,
        policy_version=CLAIM_LADDER_POLICY_VERSION,
        evidence=assessment,
        promotion_blockers=blockers,
    )


__all__ = [
    "CLAIM_LADDER_POLICY",
    "CLAIM_LADDER_POLICY_VERSION",
    "CLAIM_LADDER_TIERS",
    "ClaimTier",
    "evaluate_claim_tier",
]
