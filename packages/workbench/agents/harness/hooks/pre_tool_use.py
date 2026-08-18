"""pre_tool_use — primary pre-execution hook for the Tool Registry.

Evaluates every tool invocation before execution.  Consults:
  1. permissions.yaml   — mode-based risk category permissions
  2. boundary_rules.yaml — hard-deny boundary crossing rules
  3. feature_flags.yaml  — runtime feature output gating (status-based)
  4. specialized gates   — pre_edit, pre_finalize_release, pre_publish_snapshot

Returns a PolicyDecision with:
  - decision:  allow | ask | deny | require_manual_review
  - reason:    human-readable explanation
  - rule_id:   which rule triggered the decision
  - by_hook:   which hook made the decision

Priority chain (highest wins):
  boundary_rules (deny) > feature_flags (deny) > permissions (deny) > require_manual_review > ask > allow
  Hook "allow" can never override a global deny.
  Feature flags block exploratory/engineering_required features from paper output.

Also provides specialized sub-hooks:
  - pre_edit()            — code edit gate
  - pre_finalize_release() — release finalization gate
  - pre_publish_snapshot() — snapshot publish gate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml
from hooks.risk_classifier import RiskClassification, classify

logger = logging.getLogger(__name__)

HARNESS_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = HARNESS_ROOT / "policies"

# Decision priority for conflict resolution (higher = wins)
_DECISION_PRIORITY = {
    "deny": 4,
    "require_manual_review": 3,
    "ask": 2,
    "allow": 1,
}


@dataclass
class PolicyDecision:
    """Result of a policy evaluation."""
    decision: str       # allow | ask | deny | require_manual_review
    reason: str
    rule_id: str
    by_hook: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_denied(self) -> bool:
        return self.decision == "deny"

    @property
    def requires_manual_review(self) -> bool:
        return self.decision == "require_manual_review"


# ── static cache ────────────────────────────────────────────────────────

def _load_yaml(filename: str) -> dict:
    path = POLICIES_DIR / filename
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return cast(dict, yaml.safe_load(f) or {})


def _load_boundary_rules() -> dict:
    return _load_yaml("boundary_rules.yaml")


def _load_permissions() -> dict:
    return _load_yaml("permissions.yaml")


def _load_feature_flags() -> dict:
    raw = _load_yaml("feature_flags.yaml")
    return cast(dict, raw.get("flags", raw))  # v0.2 nests flags under "flags" key; v0.1 has them flat


# ── core evaluation ─────────────────────────────────────────────────────

def evaluate(tool_spec: Any, input: dict, mode: str, *, dry_run: bool = False) -> PolicyDecision:
    """Evaluate whether a tool invocation should be allowed.

    Args:
        tool_spec: The ToolSpec for the tool being invoked.
        input:     Arguments passed to the tool handler.
        mode:      Current agent mode (explore, verify, implement, release, run, edit, fetch).
        dry_run:   If True, this is a dry-run request (always allow).

    Returns:
        PolicyDecision with the highest-priority decision found.
    """
    # dry-run is always allowed
    if dry_run:
        return PolicyDecision(
            decision="allow",
            reason="Dry-run invocations are always permitted",
            rule_id="dry_run.allow",
            by_hook="pre_tool_use",
        )

    # feature flags
    flags = _load_feature_flags()
    if not flags.get("policy_enforcement_enabled", {}).get("default", True):
        return PolicyDecision(
            decision="allow",
            reason="Policy enforcement is globally disabled via feature_flags.policy_enforcement_enabled",
            rule_id="feature_flag.policy_disabled",
            by_hook="pre_tool_use",
        )

    # classify risk
    classification = classify(tool_spec, input, mode)
    tool_id = getattr(tool_spec, "id", "") if hasattr(tool_spec, "id") else ""
    subsystem = getattr(tool_spec, "subsystem", "") if hasattr(tool_spec, "subsystem") else ""

    decisions: list[PolicyDecision] = []

    # ── Layer 1: mode-based permissions ───────────────────────────────
    perm_decision = _check_mode_permissions(flags, classification, mode, tool_id)
    if perm_decision:
        decisions.append(perm_decision)

    # ── Layer 2: boundary rules (hard deny) ───────────────────────────
    boundary_decision = _check_boundary_rules(flags, tool_spec, input, classification, mode)
    if boundary_decision:
        decisions.append(boundary_decision)

    # ── Layer 2.5: feature flag output gating ────────────────────────
    feature_decision = _check_feature_gates(classification, input, mode, tool_id, subsystem)
    if feature_decision:
        decisions.append(feature_decision)

    # ── Layer 3: specialized sub-hook gates ───────────────────────────
    sub_gate = _check_specialized_gates(flags, tool_spec, input, classification, tool_id, subsystem)
    if sub_gate:
        decisions.append(sub_gate)

    # ── Resolve: highest-priority decision wins ───────────────────────
    # Tiebreaker: boundary rules win over mode permissions for equal priority
    if not decisions:
        return PolicyDecision(
            decision="allow",
            reason="All policy checks passed; no restrictions apply",
            rule_id="default.allow",
            by_hook="pre_tool_use",
        )

    def _decision_sort_key(d: PolicyDecision) -> tuple:
        """Sort by priority desc, then boundary/feature flags first for tiebreaking."""
        pri = _DECISION_PRIORITY.get(d.decision, 0)
        is_boundary = 1 if d.by_hook in ("pre_tool_use.boundary", "feature_flags") else 0
        return (pri, is_boundary)

    decisions.sort(key=_decision_sort_key, reverse=True)
    return decisions[0]


# ── layer 1: mode permissions ───────────────────────────────────────────

def _check_mode_permissions(
    flags: dict, classification: RiskClassification, mode: str, tool_id: str
) -> PolicyDecision | None:
    permissions = _load_permissions()
    mode_config = permissions.get("modes", {}).get(mode)

    if not mode_config:
        return PolicyDecision(
            decision="deny",
            reason=f"Unknown agent mode: {mode}",
            rule_id="permissions.unknown_mode",
            by_hook="pre_tool_use",
        )

    perm_map = mode_config.get("permissions", {})
    primary_cat = classification.primary_category
    decision = perm_map.get(primary_cat, permissions.get("default", "deny"))

    # Also check secondary categories — if any secondary cat has a stricter
    # decision, use that.
    for cat in classification.secondary_categories:
        cat_decision = perm_map.get(cat, "allow")
        if _DECISION_PRIORITY.get(cat_decision, 0) > _DECISION_PRIORITY.get(decision, 0):
            decision = cat_decision
            primary_cat = cat

    if decision == "allow" or decision == "ask":
        return None  # not restrictive enough to return yet — let boundary rules weigh in

    return PolicyDecision(
        decision=decision,
        reason=f"Mode '{mode}' does not permit '{primary_cat}' activity for tool '{tool_id}'",
        rule_id=f"permissions.mode_restriction.{mode}.{primary_cat}",
        by_hook="pre_tool_use",
        metadata={"mode": mode, "risk_category": primary_cat, "permission_mode_config": mode_config},
    )


# ── layer 2: boundary rules ─────────────────────────────────────────────

def _check_boundary_rules(
    flags: dict, tool_spec: Any, input: dict, classification: RiskClassification, mode: str
) -> PolicyDecision | None:
    boundary = _load_boundary_rules()
    rules = boundary.get("rules", [])

    tool_id = getattr(tool_spec, "id", "") if hasattr(tool_spec, "id") else ""
    subsystem = getattr(tool_spec, "subsystem", "") if hasattr(tool_spec, "subsystem") else ""

    for rule in rules:
        scope = rule.get("scope", {})
        conditions = rule.get("conditions", [])
        rule_priority = rule.get("priority", "deny")

        # check scope match
        caller = scope.get("caller_subsystem", "any")
        if caller != "any" and caller != subsystem:
            continue

        # check conditions
        all_matched = True
        for cond in conditions:
            if isinstance(cond, dict):
                if not _match_condition(cond, tool_spec, input, classification, tool_id, subsystem):
                    all_matched = False
                    break

        if all_matched:
            return PolicyDecision(
                decision=rule_priority,
                reason=rule.get("reason", "Blocked by boundary rule"),
                rule_id=rule["id"],
                by_hook="pre_tool_use.boundary",
                metadata={"rule": rule},
            )

    return None


def _match_condition(
    cond: dict, tool_spec: Any, input: dict, classification: RiskClassification,
    tool_id: str, subsystem: str
) -> bool:
    """Evaluate a single condition dict from a boundary rule."""
    # target_contains: any of these strings appear in input target fields
    if "target_contains" in cond:
        patterns = cond["target_contains"]
        # search through relevant input keys
        searchable = [
            input.get("target", ""),
            input.get("output", ""),
            input.get("path", ""),
            input.get("input_path", ""),
            input.get("target_path", ""),
            input.get("release_dir", ""),
        ]
        searchable = [str(s).lower() for s in searchable if s]
        if not any(any(p.lower() in s for p in patterns) for s in searchable):
            return False

    # risk_category_in: primary category must be in this list
    if "risk_category_in" in cond:
        allowed_cats = cond["risk_category_in"]
        if classification.primary_category not in allowed_cats:
            return False

    # target_subsystem_in: target must be in this list
    if "target_subsystem_in" in cond:
        if not any(ts in classification.target_subsystems for ts in cond["target_subsystem_in"]):
            return False

    # input_key_equals: specific input keys must match values
    if "input_key_equals" in cond:
        for key, expected in cond["input_key_equals"].items():
            actual = input.get(key)
            if actual != expected:
                return False

    # action_is: input.action must be in this list
    if "action_is" in cond:
        action = input.get("action", "")
        if action not in cond["action_is"]:
            return False

    # tool_id_in: tool id must be in this list
    if "tool_id_in" in cond:
        if tool_id not in cond["tool_id_in"]:
            return False

    # output_target_contains: check output target for patterns
    if "output_target_contains" in cond:
        patterns = cond["output_target_contains"]
        searchable = [
            input.get("output", ""),
            input.get("output_target", ""),
            input.get("target", ""),
        ]
        searchable = [str(s).lower() for s in searchable if s]
        if not any(any(p.lower() in s for p in patterns) for s in searchable):
            return False

    return True


# ── layer 2.5: feature flag output gating ─────────────────────────────

def _check_feature_gates(
    classification: RiskClassification, input: dict, mode: str,
    tool_id: str, subsystem: str
) -> PolicyDecision | None:
    """Evaluate feature flag output gates based on runtime feature status.

    Checks:
      1. Does the input declare a feature_name?
      2. Does the input declare a target_output?
      3. Is the feature's status compatible with the target output?
      4. Is the feature disabled or denied_for_release?
    """
    feature_name = classification.flags.get("feature_name", "") or input.get("feature_name", "")
    target_output = classification.flags.get("target_output", "") or input.get("target_output", "")

    if not feature_name:
        return None  # no feature declared — not gated

    if not target_output:
        # No explicit target_output: still gate if feature is disabled or denied_for_release
        try:
            from policies.feature_flags import get_feature
            feat = get_feature(feature_name)
            if feat is None:
                return None
            if feat.is_disabled:
                return PolicyDecision(
                    decision="deny",
                    reason=f"Feature '{feature_name}' is disabled — cannot execute",
                    rule_id=f"feature_flag.{feature_name}.disabled",
                    by_hook="feature_flags",
                )
            if feat.is_denied_for_release and mode in ("release", "publish", "finalize"):
                return PolicyDecision(
                    decision="deny",
                    reason=f"Feature '{feature_name}' is denied_for_release — cannot execute in {mode} mode",
                    rule_id=f"feature_flag.{feature_name}.denied_for_release",
                    by_hook="feature_flags",
                )
        except ImportError:
            logger.debug("Output gate dependency unavailable", exc_info=True)
        return None

    # Full gate evaluation
    try:
        from policies.feature_flags import (
            evaluate_output_gate,
        )
        from policies.feature_flags import (
            get_feature as ff_get_feature,
        )

        feat = ff_get_feature(feature_name)
        if feat is None:
            return None
        if feat.is_disabled:
            return PolicyDecision(
                decision="deny",
                reason=f"Feature '{feature_name}' is disabled — cannot execute",
                rule_id=f"feature_flag.{feature_name}.disabled",
                by_hook="feature_flags",
            )

        context = {"mode": mode, "release_context": mode in ("release", "publish", "finalize")}
        decision = evaluate_output_gate(feature_name, target_output, context)
        if decision.decision != "allow":
            return cast(PolicyDecision, decision)
    except ImportError:
        logger.debug("Optional output gate unavailable", exc_info=True)

    return None


# ── layer 3: specialized sub-hook gates ─────────────────────────────────

def _check_specialized_gates(
    flags: dict, tool_spec: Any, input: dict, classification: RiskClassification,
    tool_id: str, subsystem: str
) -> PolicyDecision | None:
    """Run specialized sub-hooks for specific risk categories."""
    primary = classification.primary_category

    if primary == "code_edit":
        return pre_edit(tool_spec, input, classification)

    if primary == "release_finalization":
        return pre_finalize_release(tool_spec, input, classification)

    if primary == "snapshot_publish":
        return pre_publish_snapshot(tool_spec, input, classification)

    return None


# ── specialized sub-hooks ───────────────────────────────────────────────

def pre_edit(
    tool_spec: Any, input: dict, classification: RiskClassification
) -> PolicyDecision | None:
    """Pre-edit gate: check if code edit crosses peer subsystem boundaries."""
    flags = _load_feature_flags()
    if not flags.get("block_cross_boundary_reads", {}).get("default", True):
        return None

    # If learning hub is editing peer source, deny
    subsystem = getattr(tool_spec, "subsystem", "") if hasattr(tool_spec, "id") else ""
    if subsystem == "learning_hub" and classification.is_boundary_crossing:
        return PolicyDecision(
            decision="deny",
            reason="Learning Hub must not modify peer subsystem source code",
            rule_id="pre_edit.deny.learninghub_peer_edit",
            by_hook="pre_edit",
        )

    return None


def pre_finalize_release(
    tool_spec: Any, input: dict, classification: RiskClassification
) -> PolicyDecision | None:
    """Pre-finalize-release gate: always require manual review for releases."""
    flags = _load_feature_flags()
    if not flags.get("require_manual_review_for_finalize", {}).get("default", True):
        return None

    # Check if release is already finalized
    release_status = input.get("release_status", "")
    if release_status == "final":
        # Already finalized — cannot rewrite
        return PolicyDecision(
            decision="deny",
            reason="Finalized releases are immutable — cannot overwrite or re-finalize",
            rule_id="boundary.deny.finalized-release-immutable",
            by_hook="pre_finalize_release",
        )

    # New finalization — requires manual review
    return PolicyDecision(
        decision="require_manual_review",
        reason="Release finalization requires manual human review and approval",
        rule_id="pre_finalize_release.require_manual_review",
        by_hook="pre_finalize_release",
        metadata={"release_status": release_status, "input": input},
    )


def pre_publish_snapshot(
    tool_spec: Any, input: dict, classification: RiskClassification
) -> PolicyDecision | None:
    """Pre-publish-snapshot gate: require manual review + boundary checks."""
    flags = _load_feature_flags()

    # benchmark gate
    if classification.flags.get("is_benchmark") and flags.get("block_benchmark_to_proxy", {}).get("default", True):
        return PolicyDecision(
            decision="deny",
            reason="Benchmark/control runs must not silently enter proxy Sigma_t",
            rule_id="boundary.deny.benchmark-silent-proxy-entry",
            by_hook="pre_publish_snapshot",
        )

    # simulated fallback gate
    if classification.flags.get("is_simulated_fallback"):
        try:
            from events.system_event_writer import write_simulated_fallback_blocked
            tool_id = getattr(tool_spec, "id", "") if hasattr(tool_spec, "id") else ""
            subsystem = getattr(tool_spec, "subsystem", "") if hasattr(tool_spec, "subsystem") else ""
            write_simulated_fallback_blocked(
                tool_id=tool_id, subsystem=subsystem, mode="publish",
                rule_id="boundary.deny.simulated-fallback-silent-production",
                reason="Simulated fallback runs must not enter production publication flows",
            )
        except Exception:
            logger.warning("Boundary simulation gate failed closed", exc_info=True)
        return PolicyDecision(
            decision="deny",
            reason="Simulated fallback runs must not enter production publication flows",
            rule_id="boundary.deny.simulated-fallback-silent-production",
            by_hook="pre_publish_snapshot",
        )

    # exploratory gate
    if classification.flags.get("is_exploratory") and flags.get("block_exploratory_to_paper", {}).get("default", True):
        output_target = input.get("output_target", "")
        output = input.get("output", "")
        combined = f"{output_target}{output}".lower()
        if any(hint in combined for hint in ("paper/main_output", "paper/final", "main_output")):
            return PolicyDecision(
                decision="deny",
                reason="Exploratory runs must not write into paper main output",
                rule_id="boundary.deny.exploratory-not-paper-output",
                by_hook="pre_publish_snapshot",
            )

    if flags.get("require_manual_review_for_finalize", {}).get("default", True):
        return PolicyDecision(
            decision="require_manual_review",
            reason="Snapshot publishing requires manual human review and approval",
            rule_id="pre_publish_snapshot.require_manual_review",
            by_hook="pre_publish_snapshot",
        )

    return None
