#!/usr/bin/env python3
"""Claim Ladder Tracker — policy-driven cross-run claim progression evaluator.

Reads the previous run's feedback_pending.json and the current judgment
card to evaluate whether mechanism hypotheses are progressing, stuck,
or invalidated.  Uses governance/claim_ladder_policy.yaml for tier rules.

Usage:
    python3 scripts/commands/weekly/claim_ladder_tracker.py
    python3 scripts/commands/weekly/claim_ladder_tracker.py --json

Output:
    Output/claim_ladder/progression.json  — per-claim progression status
    Output/claim_ladder/state.json        — persistent state machine state
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import operator
from datetime import date
from pathlib import Path
from typing import Any

from scripts._constants import CASELAB_USABLE_THRESHOLD
from scripts._runtime_io import (
    ROOT,
    ensure_dir,
    load_json,
    load_jsonl,
    load_yaml,
    utc_now,
    write_json,
)

logger = logging.getLogger(__name__)

RUNS_DIR = ROOT / "Output" / "runs"
JUDGMENT_PATH = ROOT / "Output" / "judgment" / "latest.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
HMM_PATH = ROOT / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
OUTPUT_DIR = ROOT / "Output" / "claim_ladder"
POLICY_PATH = ROOT / "governance" / "claim_ladder_policy.yaml"
STATE_PATH = OUTPUT_DIR / "state.json"

# Evidence sources for Tier 3 promotion
REPLAY_EVALUATION_PATH = ROOT / "Output" / "workbench" / "evaluation" / "historical_replay_evaluation.json"
IMPROVEMENT_QUEUE_PATH = ROOT / "Data" / "system_learning" / "ledgers" / "improvement_queue.parquet"
FEEDBACK_SAMPLES_DIR = ROOT / "Output" / "feedback_samples"
DATA_QUALITY_PATH = ROOT / "Output" / "current" / "framework_output.json"


def find_previous_run_dir() -> Path | None:
    """Find the most recent completed run bundle directory."""
    if not RUNS_DIR.exists():
        return None
    run_dirs = sorted(RUNS_DIR.iterdir(), reverse=True)
    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
        # Must have manifest.json and be completed
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = load_json(manifest_path)
                if manifest and manifest.get("status") in ("success", "partial_failure"):
                    return run_dir
            except Exception:
                logger.debug("Failed to read manifest at %s", manifest_path, exc_info=True)
                continue
    return None


def find_previous_claim_run_dir() -> Path | None:
    """Find the most recent completed run with structured claim metadata."""
    if not RUNS_DIR.exists():
        return None
    run_dirs = sorted(RUNS_DIR.iterdir(), reverse=True)
    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = load_json(manifest_path)
        except Exception:
            logger.debug("Failed to read manifest for claim run at %s", manifest_path, exc_info=True)
            continue
        if not manifest or manifest.get("status") not in ("success", "partial_failure", "PARTIAL"):
            continue
        pending = load_previous_pending(run_dir)
        if _extract_claim_items(pending):
            return run_dir
    return None


def load_previous_pending(run_dir: Path) -> list[dict[str, Any]]:
    """Load feedback_pending.json from a previous run."""
    pending_path = run_dir / "feedback_pending.json"
    if not pending_path.exists():
        return []
    return load_json(pending_path) or []


def _extract_claim_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract claim ladder items with metadata from feedback_pending."""
    claim_items = []
    for item in items:
        if item.get("source") == "claim_ladder" and item.get("metadata"):
            claim_items.append(item)
    return claim_items


def check_md_persistence(
    prev_claim: dict[str, Any],
    current_judgment: dict[str, Any],
) -> dict[str, Any]:
    """Check if M/D direction persisted from previous to current run."""
    prev_hypothesis = prev_claim.get("metadata", {}).get("mechanism_hypothesis", "")
    current_meaning = current_judgment.get("meaning", [])

    # Extract direction from previous hypothesis
    prev_dir = "unknown"
    if "relief" in prev_hypothesis.lower() or "negative" in prev_hypothesis.lower():
        prev_dir = "stress_relief"
    elif "stress" in prev_hypothesis.lower() or "elevated" in prev_hypothesis.lower():
        prev_dir = "stress_building"

    # Extract direction from current meaning
    curr_dir = "unknown"
    for line in current_meaning:
        if "relief" in line.lower() or "negative" in line.lower():
            curr_dir = "stress_relief"
            break
        elif "stress" in line.lower() or "elevated" in line.lower():
            curr_dir = "stress_building"
            break

    persisted = prev_dir == curr_dir and prev_dir != "unknown"
    return {
        "check": "md_persistence",
        "previous_direction": prev_dir,
        "current_direction": curr_dir,
        "persisted": persisted,
        "status": "confirmed" if persisted else "reversed",
    }


def check_caselab_improvement(
    prev_claim: dict[str, Any],
) -> dict[str, Any]:
    """Check if CaseLab score gap has narrowed."""
    prev_gap = prev_claim.get("metadata", {}).get("caselab_score_gap", 0)

    # Read current CaseLab
    today = date.today().isoformat()
    caselab_path = CASELAB_DIR / f"{today}.json"
    current_gap = prev_gap  # default: no change
    if caselab_path.exists():
        try:
            caselab = load_json(caselab_path) or {}
            mq = caselab.get("match_quality", {})
            top_score = mq.get("top_score", 0)
            usable_th = mq.get("thresholds", {}).get("usable", CASELAB_USABLE_THRESHOLD)
            current_gap = round(max(0, usable_th - top_score), 3)
        except Exception:
            logger.debug("Failed to read CaseLab match quality", exc_info=True)

    improved = current_gap < prev_gap
    return {
        "check": "caselab_improvement",
        "previous_gap": prev_gap,
        "current_gap": current_gap,
        "improved": improved,
        "status": "improved" if improved else ("stable" if current_gap == prev_gap else "worsened"),
    }


def check_hmm_conflict(
    prev_claim: dict[str, Any],
) -> dict[str, Any]:
    """Check if HMM regime conflicts with the mechanism hypothesis."""
    prev_hypothesis = prev_claim.get("metadata", {}).get("mechanism_hypothesis", "")

    hmm = load_json(HMM_PATH)
    if not hmm:
        return {"check": "hmm_conflict", "status": "no_data", "conflict": False}

    regime = _hmm_regime_label(hmm)
    # stress_relief hypothesis conflicts with volatile/stress regime
    # stress_building hypothesis conflicts with calm/relief regime
    conflict = False
    if "relief" in prev_hypothesis.lower() and regime.lower() in ("volatile", "stress"):
        conflict = True
    elif "stress" in prev_hypothesis.lower() and regime.lower() in ("calm", "relief"):
        conflict = True

    return {
        "check": "hmm_conflict",
        "current_regime": regime,
        "hypothesis": prev_hypothesis[:100],
        "conflict": conflict,
        "status": "conflict" if conflict else "aligned",
    }


def _hmm_regime_label(hmm: dict[str, Any]) -> str:
    """Return the current HMM regime across old and new artifact shapes."""
    regime = hmm.get("regime", "unknown")
    if isinstance(regime, dict):
        return str(regime.get("current") or regime.get("label") or regime.get("state") or "unknown")
    return str(regime or "unknown")


def check_invalidation(
    prev_claim: dict[str, Any],
    current_judgment: dict[str, Any],
) -> dict[str, Any]:
    """Check if any invalidation conditions from previous claim are triggered."""
    prev_inv_conditions = prev_claim.get("metadata", {}).get("invalidation_conditions", [])
    if not prev_inv_conditions:
        return {"check": "invalidation", "status": "no_conditions", "triggered": []}

    # Check current gate status for invalidation signals
    gate_status = current_judgment.get("gate_status", {})
    triggered = []

    for condition in prev_inv_conditions:
        cond_lower = condition.lower()
        # Check HMM stability
        if "hmm" in cond_lower and gate_status.get("hmm_stability") == "WEAK":
            triggered.append(condition)
        # Check K gate
        elif "k" in cond_lower and "curvature" in cond_lower and gate_status.get("k_gate") == "FAIL":
            triggered.append(condition)
        # Check M reversal
        elif "m reverses" in cond_lower or "m sign" in cond_lower:
            meaning = current_judgment.get("meaning", [])
            has_stress = any("stress" in m.lower() for m in meaning)
            has_relief = any("relief" in m.lower() for m in meaning)
            if "relief" in cond_lower and has_stress:
                triggered.append(condition)
            elif "stress" in cond_lower and has_relief:
                triggered.append(condition)

    return {
        "check": "invalidation",
        "conditions_checked": len(prev_inv_conditions),
        "triggered": triggered,
        "status": "triggered" if triggered else "not_triggered",
    }


# ---------------------------------------------------------------------------
# Evidence loaders for Tier 3 promotion
# ---------------------------------------------------------------------------

def _load_replay_evidence() -> dict[str, Any]:
    """Load replay evaluation metrics from historical replay evaluation.

    Returns dict with replay_evaluation_count, replay_useful_rate,
    replay_false_positive_rate, and mechanism_misleading_rate.
    """
    defaults = {
        "replay_evaluation_count": 0,
        "replay_useful_rate": 0.0,
        "replay_false_positive_rate": 1.0,
        "mechanism_misleading_rate": 1.0,
    }
    if not REPLAY_EVALUATION_PATH.exists():
        return defaults

    try:
        data = load_json(REPLAY_EVALUATION_PATH) or {}
        summary = data.get("summary", [])
        if not summary:
            return defaults

        # Aggregate across all indicators
        total_cases = 0
        weighted_hit = 0.0
        weighted_fp = 0.0
        n_valid = 0
        for indicator in summary:
            cases = indicator.get("cases", 0)
            hit_rate = indicator.get("hit_rate", 0)
            fp_rate = indicator.get("avg_false_positive_rate", 0)
            # Skip NaN / invalid entries
            if math.isnan(hit_rate) or math.isnan(fp_rate):
                continue
            total_cases += cases
            weighted_hit += hit_rate * cases
            weighted_fp += fp_rate * cases
            n_valid += 1

        if total_cases == 0:
            return defaults

        useful_rate = weighted_hit / total_cases
        fp_rate = weighted_fp / total_cases

        # Mechanism misleading rate: indicators with hit_rate < 0.5
        misleading_indicators = sum(
            1 for ind in summary
            if not math.isnan(ind.get("hit_rate", 0)) and ind.get("hit_rate", 0) < 0.5
        )
        misleading_rate = misleading_indicators / max(n_valid, 1)

        return {
            "replay_evaluation_count": total_cases,
            "replay_useful_rate": round(useful_rate, 3),
            "replay_false_positive_rate": round(fp_rate, 3),
            "mechanism_misleading_rate": round(misleading_rate, 3),
        }
    except Exception:
        logger.debug("Failed to load replay evidence from %s", REPLAY_EVALUATION_PATH, exc_info=True)
        return defaults


def _load_learning_hub_severity() -> int:
    """Count unresolved high/critical improvement items from Learning Hub."""
    if not IMPROVEMENT_QUEUE_PATH.exists():
        return 0

    try:
        import pandas as pd
        df = pd.read_parquet(IMPROVEMENT_QUEUE_PATH)
        # Unresolved = closed_at is empty or NaN
        mask = (
            df["severity"].isin(["high", "critical"])
            & (df["closed_at"].isna() | (df["closed_at"] == ""))
        )
        return int(mask.sum())
    except Exception:
        logger.debug("Failed to load Learning Hub improvement queue from %s", IMPROVEMENT_QUEUE_PATH, exc_info=True)
        return 0


def _load_data_quality_grade() -> str:
    """Derive data quality grade from framework output freshness and completeness."""
    if not DATA_QUALITY_PATH.exists():
        return "D"

    try:
        fw = load_json(DATA_QUALITY_PATH) or {}
        sigma = fw.get("sigma_vector", {})
        # Check which channels have valid (non-null) values
        channels = ["M", "D", "K", "X_agg"]
        valid = sum(1 for ch in channels if sigma.get(ch) is not None)
        if valid >= 4:
            return "A"
        elif valid >= 3:
            return "B"
        elif valid >= 2:
            return "C"
        else:
            return "D"
    except Exception:
        logger.debug("Failed to load data quality grade", exc_info=True)
        return "D"


def _load_invalidation_sample_evidence() -> dict[str, Any]:
    """Check if invalidation conditions have been tested in replay samples.

    Returns dict with invalidation_triggered_and_recorded and
    invalidation_never_triggered_in_sample.
    """
    defaults = {
        "invalidation_triggered_and_recorded": 0,
        "invalidation_never_triggered_in_sample": True,
    }
    # Check feedback samples for invalidation evidence
    review_queue = FEEDBACK_SAMPLES_DIR / "review_queue.jsonl"
    if not review_queue.exists():
        return defaults

    try:
        entries = load_jsonl(review_queue)
    except Exception:
        logger.debug("Failed to load invalidation samples from %s", review_queue, exc_info=True)
        return defaults

    if not entries:
        return defaults

    triggered_count = 0
    for entry in entries:
        if entry.get("invalidation_triggered", False):
            triggered_count += 1

    return {
        "invalidation_triggered_and_recorded": triggered_count,
        "invalidation_never_triggered_in_sample": triggered_count == 0,
    }


# ---------------------------------------------------------------------------
# Policy-driven state machine
# ---------------------------------------------------------------------------

def load_policy() -> dict[str, Any]:
    """Load claim ladder policy from governance YAML."""
    policy = load_yaml(POLICY_PATH)
    if not policy:
        raise FileNotFoundError(f"Claim ladder policy not found: {POLICY_PATH}")
    return policy


def load_state() -> dict[str, Any]:
    """Load persistent claim ladder state, or return empty initial state."""
    state = load_json(STATE_PATH)
    if state and state.get("schema_version") == "claim_ladder_state.v1":
        return state
    return {
        "schema_version": "claim_ladder_state.v1",
        "generated_at": utc_now().isoformat(),
        "claims": [],
    }


def save_state(state: dict[str, Any]) -> Path:
    """Persist claim ladder state to disk."""
    ensure_dir(OUTPUT_DIR)
    state["generated_at"] = utc_now().isoformat()
    write_json(STATE_PATH, state)
    return STATE_PATH


def _evaluate_policy_rules(
    claim: dict[str, Any],
    evidence: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[bool, list[dict], list[dict]]:
    """Evaluate promotion requirements and demotion triggers for a claim.

    Returns: (promotion_eligible, blockers, active_triggers)
    """
    tier = claim.get("current_tier", 0)
    tier_policy = policy.get("tiers", {}).get(tier, {})
    next_tier_policy = policy.get("tiers", {}).get(tier + 1, {})

    blockers: list[dict[str, Any]] = []
    active_triggers: list[dict[str, Any]] = []

    # Check demotion triggers for current tier
    for trigger in tier_policy.get("demotion_triggers", []):
        triggered = _check_rule(trigger["rule"], evidence)
        if triggered:
            active_triggers.append({
                "id": trigger["id"],
                "severity": trigger.get("severity", "immediate"),
                "description": trigger.get("description", ""),
            })

    # If no next tier, cannot promote further
    if not next_tier_policy:
        return False, [{"id": "max_tier", "rule": "already at max tier", "description": "No higher tier defined"}], active_triggers

    # Check promotion requirements for next tier
    eligible = True
    for req in next_tier_policy.get("promotion_requirements", []):
        met = _check_rule(req["rule"], evidence)
        if not met:
            eligible = False
            blockers.append({
                "id": req["id"],
                "rule": req["rule"],
                "description": req.get("description", ""),
            })

    return eligible, blockers, active_triggers


def _check_rule(rule: str, evidence: dict[str, Any]) -> bool:
    """Evaluate a policy rule string against evidence values.

    Rules are simple comparisons like "caselab_top_score >= 0.30" or
    "hmm_conflict == false".  Supports OR for compound rules.
    """
    ops = {
        ">=": operator.ge,
        "<=": operator.le,
        ">": operator.gt,
        "<": operator.lt,
        "==": operator.eq,
        "!=": operator.ne,
    }

    # Handle special non-comparison rules
    rule_lower = rule.strip().lower()
    if rule_lower == "any tier 2 demotion trigger":
        return False  # Handled separately by caller

    # Handle OR compound rules
    if " OR " in rule:
        parts = rule.split(" OR ")
        return any(_check_rule(part.strip(), evidence) for part in parts)

    # Handle AND compound rules
    if " AND " in rule:
        parts = rule.split(" AND ")
        return all(_check_rule(part.strip(), evidence) for part in parts)

    # Parse: variable op value
    for op_str, op_func in ops.items():
        if op_str in rule:
            parts = rule.split(op_str, 1)
            var_name = parts[0].strip()
            val_str = parts[1].strip()

            actual = evidence.get(var_name)
            if actual is None:
                return False  # Missing data = condition not met

            # Type coercion
            try:
                if val_str.lower() in ("true", "false"):
                    expected = val_str.lower() == "true"
                    actual = bool(actual) if not isinstance(actual, bool) else actual
                elif "." in val_str:
                    expected = float(val_str)
                    actual = float(actual)
                else:
                    expected = int(val_str)
                    actual = int(actual)
            except (ValueError, TypeError):
                expected = val_str
                actual = str(actual)

            return op_func(actual, expected)

    # Handle bare boolean evidence variables (no operator, just variable name)
    if rule.strip() in evidence:
        return bool(evidence[rule.strip()])

    return False  # Unparseable rule = not met


def apply_transitions(
    state: dict[str, Any],
    progression: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Apply state transitions based on policy evaluation.

    Updates state in-place and returns transition summary.
    """
    promotions = 0
    demotions = 0
    now = utc_now().isoformat()

    # Build a lookup of current claims by mechanism_hypothesis
    existing_claims = {c["mechanism_hypothesis"]: c for c in state.get("claims", [])}

    for prog in progression:
        hypothesis = prog["previous_run_claim"]["mechanism_hypothesis"]
        prev_tier = prog["previous_run_claim"]["claim_tier"]
        checks = prog["checks"]
        overall = prog["overall_status"]

        # Build evidence dict from checks
        caselab_gap = checks.get("caselab_improvement", {}).get("current_gap", 1.0)
        md_persisted = checks.get("md_persistence", {}).get("persisted", False)
        hmm_conflict = checks.get("hmm_conflict", {}).get("conflict", False)

        # Accumulate consecutive runs from persistent state
        prev_md_consecutive = existing_claims.get(hypothesis, {}).get("evidence", {}).get("md_direction_consecutive_runs", 0)
        prev_hmm_consecutive = existing_claims.get(hypothesis, {}).get("evidence", {}).get("hmm_conflict_consecutive_runs", 0)

        evidence = {
            "caselab_top_score": max(0, CASELAB_USABLE_THRESHOLD - caselab_gap),
            "md_direction": checks.get("md_persistence", {}).get("current_direction", "unknown"),
            "md_direction_reversed": checks.get("md_persistence", {}).get("status") == "reversed",
            "md_direction_consecutive_runs": (prev_md_consecutive + 1) if md_persisted else 0,
            "hmm_conflict": hmm_conflict,
            "hmm_conflict_consecutive_runs": (prev_hmm_consecutive + 1) if hmm_conflict else 0,
            "invalidation_condition_count": checks.get("invalidation", {}).get("conditions_checked", 0),
            "invalidation_triggered_count": len(checks.get("invalidation", {}).get("triggered", [])),
            "active_mechanism_count": 1 if hypothesis else 0,
            "data_quality_grade": _load_data_quality_grade(),
        }

        # Tier 3 evidence: replay metrics, Learning Hub severity, invalidation samples
        replay_ev = _load_replay_evidence()
        evidence.update(replay_ev)
        evidence["learning_hub_unresolved_high_severity"] = _load_learning_hub_severity()
        evidence.update(_load_invalidation_sample_evidence())

        # tier2_duration_runs: only meaningful for claims at tier 2+
        tier2_runs = existing_claims.get(hypothesis, {}).get("runs_at_current_tier", 0)
        current_claim_tier = existing_claims.get(hypothesis, {}).get("current_tier", 0)
        evidence["tier2_duration_runs"] = tier2_runs if current_claim_tier >= 2 else 0

        # Get or create claim in state
        if hypothesis in existing_claims:
            claim = existing_claims[hypothesis]
            claim["runs_at_current_tier"] = claim.get("runs_at_current_tier", 0) + 1
        else:
            claim = {
                "claim_id": f"claim-{hypothesis[:40].replace(' ', '_').lower()}",
                "current_tier": prev_tier,
                "tier_label": policy.get("tiers", {}).get(prev_tier, {}).get("label", "unknown"),
                "mechanism_hypothesis": hypothesis,
                "status": "active",
                "entered_tier_at": now,
                "runs_at_current_tier": 1,
                "history": [{
                    "timestamp": now,
                    "action": "created",
                    "from_tier": prev_tier,
                    "to_tier": prev_tier,
                    "reasons": ["Initial claim from feedback_pending"],
                }],
            }
            state["claims"].append(claim)
            existing_claims[hypothesis] = claim

        # Handle invalidation (special case — immediate, not policy-driven)
        if overall == "invalidated":
            claim["evidence"] = evidence
            claim["status"] = "invalidated"
            claim["history"].append({
                "timestamp": now,
                "action": "invalidated",
                "from_tier": claim["current_tier"],
                "to_tier": 0,
                "reasons": [f"Invalidation triggered: {t}" for t in checks.get("invalidation", {}).get("triggered", [])],
            })
            claim["current_tier"] = 0
            claim["tier_label"] = "diagnostic_claim"
            demotions += 1
            continue

        # Policy-driven evaluation
        eligible, blockers, triggers = _evaluate_policy_rules(claim, evidence, policy)

        claim["evidence"] = evidence
        claim["promotion_eligible"] = eligible
        claim["promotion_blockers"] = blockers
        claim["demotion_triggers_active"] = triggers

        # Apply demotion if triggers active
        if triggers:
            new_tier = max(0, claim["current_tier"] - 1)
            if new_tier < claim["current_tier"]:
                claim["history"].append({
                    "timestamp": now,
                    "action": "demoted",
                    "from_tier": claim["current_tier"],
                    "to_tier": new_tier,
                    "reasons": [t["description"] for t in triggers],
                })
                claim["current_tier"] = new_tier
                claim["tier_label"] = policy.get("tiers", {}).get(new_tier, {}).get("label", "unknown")
                claim["status"] = "demoted"
                demotions += 1
        elif eligible and not blockers:
            # Apply promotion
            new_tier = min(3, claim["current_tier"] + 1)
            if new_tier > claim["current_tier"]:
                claim["history"].append({
                    "timestamp": now,
                    "action": "promoted",
                    "from_tier": claim["current_tier"],
                    "to_tier": new_tier,
                    "reasons": [r["description"] for r in policy.get("tiers", {}).get(new_tier, {}).get("promotion_requirements", [])],
                })
                claim["current_tier"] = new_tier
                claim["tier_label"] = policy.get("tiers", {}).get(new_tier, {}).get("label", "unknown")
                claim["status"] = "promoted"
                claim["entered_tier_at"] = now
                claim["runs_at_current_tier"] = 0
                promotions += 1
        else:
            claim["status"] = "tracking"

    # Update summary
    active_claims = [c for c in state.get("claims", []) if c.get("status") != "invalidated"]
    state["summary"] = {
        "total_claims": len(state.get("claims", [])),
        "active_claims": len(active_claims),
        "highest_tier": max((c.get("current_tier", 0) for c in state.get("claims", [])), default=0),
        "promotions_this_run": promotions,
        "demotions_this_run": demotions,
    }

    return state


def evaluate_progression(
    prev_items: list[dict[str, Any]],
    current_judgment: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate claim progression for each previous claim ladder item."""
    claim_items = _extract_claim_items(prev_items)
    results = []

    for item in claim_items:
        metadata = item.get("metadata", {})
        checks = {
            "md_persistence": check_md_persistence(item, current_judgment),
            "caselab_improvement": check_caselab_improvement(item),
            "hmm_conflict": check_hmm_conflict(item),
            "invalidation": check_invalidation(item, current_judgment),
        }

        # Determine overall status
        overall = "tracking"
        if checks["invalidation"]["status"] == "triggered":
            overall = "invalidated"
        elif checks["hmm_conflict"]["status"] == "conflict":
            overall = "conflict"
        elif checks["md_persistence"]["status"] == "confirmed" and checks["caselab_improvement"]["status"] == "improved":
            overall = "progressing"
        elif checks["md_persistence"]["status"] == "reversed":
            overall = "reversed"

        results.append({
            "previous_run_claim": {
                "claim_tier": metadata.get("claim_tier", 0),
                "claim_label": metadata.get("claim_label", ""),
                "mechanism_hypothesis": metadata.get("mechanism_hypothesis", ""),
            },
            "checks": checks,
            "overall_status": overall,
        })

    return results


def build_progression() -> dict[str, Any]:
    """Build the full claim ladder progression report with policy-driven state."""
    now = utc_now()

    # Load policy and persistent state
    try:
        policy = load_policy()
    except FileNotFoundError:
        policy = {"tiers": {}}
    state = load_state()

    # Find previous run with a claim ladder item
    prev_run_dir = find_previous_claim_run_dir() or find_previous_run_dir()
    if not prev_run_dir:
        return {
            "schema_version": "claim_ladder_progression.v1",
            "generated_at": now.isoformat(),
            "status": "no_previous_run",
            "claims": [],
        }

    # Load previous pending and current judgment
    prev_items = load_previous_pending(prev_run_dir)
    current_judgment = load_json(JUDGMENT_PATH)

    if not prev_items or not current_judgment:
        return {
            "schema_version": "claim_ladder_progression.v1",
            "generated_at": now.isoformat(),
            "previous_run": prev_run_dir.name,
            "status": "insufficient_data",
            "claims": [],
        }

    # Evaluate progression (existing logic for backward compat)
    claims = evaluate_progression(prev_items, current_judgment)

    # Apply policy-driven state transitions
    updated_state = apply_transitions(state, claims, policy)
    save_state(updated_state)

    return {
        "schema_version": "claim_ladder_progression.v1",
        "generated_at": now.isoformat(),
        "previous_run": prev_run_dir.name,
        "current_judgment_date": current_judgment.get("as_of", ""),
        "status": "evaluated",
        "claims": claims,
        "state_summary": updated_state.get("summary", {}),
    }


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    """Write progression report."""
    ensure_dir(OUTPUT_DIR)

    json_path = OUTPUT_DIR / "progression.json"
    md_path = OUTPUT_DIR / "progression.md"

    write_json(json_path, report)

    # Generate markdown
    lines = [
        "# Claim Ladder Progression",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Previous run:** {report.get('previous_run', 'N/A')}",
        f"**Status:** {report['status']}",
        "",
    ]
    for claim in report.get("claims", []):
        prev = claim["previous_run_claim"]
        lines.append(f"## Tier {prev['claim_tier']} — {prev['claim_label']}")
        lines.append("")
        lines.append(f"**Hypothesis:** {prev['mechanism_hypothesis'][:120]}")
        lines.append(f"**Overall:** {claim['overall_status']}")
        lines.append("")
        for check_name, check in claim["checks"].items():
            lines.append(f"- **{check_name}:** {check['status']}")
        lines.append("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Track claim ladder progression across runs.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = build_progression()
    paths = write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Claim ladder progression: {paths['markdown']}")
        print(f"Status: {report['status']}")
        summary = report.get("state_summary", {})
        if summary:
            print(f"  Active claims: {summary.get('active_claims', 0)}")
            print(f"  Highest tier: {summary.get('highest_tier', 0)}")
            print(f"  Promotions: {summary.get('promotions_this_run', 0)}")
            print(f"  Demotions: {summary.get('demotions_this_run', 0)}")
        for claim in report.get("claims", []):
            prev = claim["previous_run_claim"]
            print(f"  Tier {prev['claim_tier']}: {claim['overall_status']}")


if __name__ == "__main__":
    main()
