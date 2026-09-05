"""feature_flags — runtime feature gate engine.

Feature lifecycle statuses govern where output may flow:

    paper_aligned        → any output, including paper/main_output
    engineering_required → sandbox, experiment, benchmark_report (NOT paper)
    exploratory          → sandbox, experiment only
    experimental         → sandbox only
    disabled             → cannot run at all
    denied_for_release   → can run but denied in release/publish context
    archived_denied      → archived evidence only; cannot execute as a live host

The engine is NOT just a dictionary lookup — it enforces the output hierarchy
so that the agent cannot accidentally route exploratory results to paper.

Public API:
    is_enabled(feature_name, context)          → bool
    can_promote(feature_name, target_output)   → GateResult
    explain_gate(feature_name, target_output)  → str
    evaluate_output_gate(feature_name, target_output, context) → PolicyDecision
    list_features(subsystem=None)              → list[FeatureSpec]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

HARNESS_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = HARNESS_ROOT / "policies"
CONFIG_PATH = POLICIES_DIR / "feature_flags.yaml"

# ── data structures ─────────────────────────────────────────────────────

STATUS_RANK = {
    "paper_aligned": 5,
    "engineering_required": 4,
    "exploratory": 3,
    "experimental": 2,
    "disabled": 1,
    "denied_for_release": 0,
    "archived_denied": -1,
}

OUTPUT_RANK = {
    "paper/main_output": 5,
    "paper/supplementary": 4,
    "benchmark_report": 3,
    "experiment": 2,
    "sandbox": 1,
    "none": 0,
}

RELEASE_CONTEXT_MODES = {"release", "publish", "finalize"}


@dataclass
class FeatureSpec:
    """Specification for a single runtime feature flag."""
    name: str
    subsystem: str
    status: str
    owner: str
    description: str
    allowed_outputs: list[str]
    promotion_requires: list[str]
    default_enabled: bool

    @property
    def is_disabled(self) -> bool:
        return self.status == "disabled"

    @property
    def is_archived_denied(self) -> bool:
        return self.status == "archived_denied"

    @property
    def is_denied_for_release(self) -> bool:
        return self.status == "denied_for_release"

    @property
    def is_paper_aligned(self) -> bool:
        return self.status == "paper_aligned"

    @property
    def is_exploratory_or_below(self) -> bool:
        return self.status in ("exploratory", "experimental")


@dataclass
class GateResult:
    """Result of an output gate evaluation."""
    allowed: bool
    feature_name: str
    feature_status: str
    target_output: str
    reason: str
    promotion_requires: list[str] = field(default_factory=list)

    def to_policy_decision(self) -> Any:
        """Convert to a PolicyDecision compatible with pre_tool_use."""
        # deferred import to avoid circular dependency
        from hooks.pre_tool_use import PolicyDecision

        if self.allowed:
            return PolicyDecision(
                decision="allow",
                reason=self.reason,
                rule_id=f"feature_flag.{self.feature_name}.allow",
                by_hook="feature_flags",
                metadata={"gate_result": self},
            )
        else:
            return PolicyDecision(
                decision="deny",
                reason=self.reason,
                rule_id=f"feature_flag.{self.feature_name}.deny",
                by_hook="feature_flags",
                metadata={"gate_result": self},
            )


# ── loading ─────────────────────────────────────────────────────────────

_features_cache: dict[str, FeatureSpec] | None = None
_output_hierarchy_cache: dict[str, int] | None = None
_default_status_cache: str | None = None


def _load_raw() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return cast(dict, yaml.safe_load(f) or {})


def _ensure_loaded():
    global _features_cache, _output_hierarchy_cache, _default_status_cache
    if _features_cache is not None:
        return
    raw = _load_raw()
    _features_cache = {}
    for name, data in raw.get("features", {}).items():
        parts = name.split(".", 1)
        subsystem = parts[0] if len(parts) > 1 else "unknown"
        _features_cache[name] = FeatureSpec(
            name=name,
            subsystem=subsystem,
            status=data.get("status", "engineering_required"),
            owner=data.get("owner", "unknown"),
            description=data.get("description", ""),
            allowed_outputs=data.get("allowed_outputs", []),
            promotion_requires=data.get("promotion_requires", []),
            default_enabled=data.get("default_enabled", True),
        )
    _output_hierarchy_cache = {
        k: v for k, v in (raw.get("output_hierarchy") or OUTPUT_RANK).items()
    }
    _default_status_cache = raw.get("default_feature_status", "engineering_required")


def _get_feature(name: str) -> FeatureSpec | None:
    _ensure_loaded()
    assert _features_cache is not None
    return _features_cache.get(name)


# ── public API ──────────────────────────────────────────────────────────

def is_enabled(feature_name: str) -> bool:
    """Check if a feature is enabled at all (disabled status → False)."""
    feat = _get_feature(feature_name)
    if feat is None:
        return False
    if feat.is_archived_denied:
        return False
    return not feat.is_disabled and feat.default_enabled


def can_promote(feature_name: str, target_output: str) -> GateResult:
    """Check whether a feature's output can flow to target_output.

    Args:
        feature_name:  e.g. "deformation.gnn_benchmark"
        target_output: e.g. "paper/main_output", "experiment", "sandbox"

    Returns:
        GateResult with allowed=True/False and human-readable reason.
    """
    feat = _get_feature(feature_name)
    if feat is None:
        return GateResult(
            allowed=False,
            feature_name=feature_name,
            feature_status="unknown",
            target_output=target_output,
            reason=f"Feature '{feature_name}' is not registered in feature_flags.yaml",
        )

    if feat.is_archived_denied:
        return GateResult(
            allowed=False,
            feature_name=feature_name,
            feature_status=feat.status,
            target_output=target_output,
            reason=(
                f"Feature '{feature_name}' is archived_denied — "
                "ARCHIVED_FALSIFIED evidence only, not a live host"
            ),
            promotion_requires=feat.promotion_requires,
        )

    # disabled: cannot run at all
    if feat.is_disabled:
        return GateResult(
            allowed=False,
            feature_name=feature_name,
            feature_status=feat.status,
            target_output=target_output,
            reason=f"Feature '{feature_name}' is disabled — cannot execute",
            promotion_requires=feat.promotion_requires,
        )

    # if target_output is not in the feature's allowed list, compute the gap
    if target_output not in feat.allowed_outputs:
        return GateResult(
            allowed=False,
            feature_name=feature_name,
            feature_status=feat.status,
            target_output=target_output,
            reason=(
                f"Feature '{feature_name}' (status={feat.status}) cannot output to "
                f"'{target_output}'. Allowed targets: {feat.allowed_outputs}"
            ),
            promotion_requires=feat.promotion_requires,
        )

    return GateResult(
        allowed=True,
        feature_name=feature_name,
        feature_status=feat.status,
        target_output=target_output,
        reason=f"Feature '{feature_name}' (status={feat.status}) is permitted to output to '{target_output}'",
        promotion_requires=feat.promotion_requires,
    )


def _compute_max_output(status: str) -> str:
    """Compute the maximum output bucket a feature status permits."""
    status_to_max = {
        "paper_aligned": "paper/main_output",
        "engineering_required": "benchmark_report",
        "exploratory": "experiment",
        "experimental": "sandbox",
        "disabled": "none",
        "denied_for_release": "experiment",
        "archived_denied": "none",
    }
    return status_to_max.get(status, "sandbox")


def explain_gate(feature_name: str, target_output: str) -> str:
    """Provide a human-readable explanation of why a gate triggered.

    The explanation includes:
    - Feature status
    - Target output
    - Why the gap exists
    - What's needed to promote
    """
    result = can_promote(feature_name, target_output)

    if result.allowed:
        return f"[ALLOWED] {result.reason}"

    feat = _get_feature(feature_name)
    if feat is None:
        return result.reason

    max_output = _compute_max_output(feat.status)
    output_rank = OUTPUT_RANK.get(target_output, 0)
    max_rank = OUTPUT_RANK.get(max_output, 0)

    lines = [
        f"GATE BLOCKED: {feature_name} → {target_output}",
        f"  Feature status:  {feat.status}",
        f"  Max allowed output: {max_output}",
        f"  Requested output:   {target_output} (rank {output_rank} vs max {max_rank})",
        f"  Reason: {result.reason}",
    ]
    if feat.promotion_requires:
        lines.append(f"  Promotion requires:")
        for req in feat.promotion_requires:
            lines.append(f"    - {req}")
    lines.append(f"  Owner: {feat.owner}")

    return "\n".join(lines)


def evaluate_output_gate(
    feature_name: str,
    target_output: str,
    context: dict | None = None,
) -> Any:
    """Evaluate the output gate and return a PolicyDecision.

    This is the primary integration point with pre_tool_use's evaluate().

    Args:
        feature_name:  e.g. "deformation.narrative_detector"
        target_output: e.g. "paper/main_output"
        context:       Optional dict with keys: mode, release_context, dry_run

    Returns:
        PolicyDecision with decision=allow|deny.
    """
    from hooks.pre_tool_use import PolicyDecision

    ctx = context or {}

    # special case: denied_for_release in a release context → deny
    feat = _get_feature(feature_name)
    if feat is None:
        return PolicyDecision(
            decision="allow",
            reason=f"Feature '{feature_name}' not registered — no gate applied",
            rule_id="feature_flag.unknown",
            by_hook="feature_flags",
        )

    mode = ctx.get("mode", "")
    release_context = ctx.get("release_context", False) or mode in RELEASE_CONTEXT_MODES

    if feat.is_archived_denied:
        return PolicyDecision(
            decision="deny",
            reason=(
                f"Feature '{feature_name}' is archived_denied. "
                "ARCHIVED_FALSIFIED — inspect evidence only, never execute as a live host."
            ),
            rule_id=f"feature_flag.{feature_name}.archived_denied",
            by_hook="feature_flags",
            metadata={
                "feature_name": feature_name,
                "feature_status": feat.status,
                "mode": mode,
            },
        )

    # denied_for_release: deny in any release-like context
    if feat.is_denied_for_release and release_context:
        return PolicyDecision(
            decision="deny",
            reason=(
                f"Feature '{feature_name}' is denied_for_release. "
                f"Cannot execute in mode '{mode}' (release context)."
            ),
            rule_id=f"feature_flag.{feature_name}.denied_for_release",
            by_hook="feature_flags",
            metadata={
                "feature_name": feature_name,
                "feature_status": feat.status,
                "mode": mode,
                "release_context": release_context,
            },
        )

    # disabled: deny always
    if feat.is_disabled:
        return PolicyDecision(
            decision="deny",
            reason=f"Feature '{feature_name}' is disabled — cannot execute",
            rule_id=f"feature_flag.{feature_name}.disabled",
            by_hook="feature_flags",
        )

    # output gate check
    result = can_promote(feature_name, target_output)
    if not result.allowed:
        return result.to_policy_decision()

    # auto_approval check (special case)
    if feature_name == "learning_hub.auto_approval" and feat.is_disabled:
        return PolicyDecision(
            decision="deny",
            reason=f"Feature '{feature_name}' is disabled — cannot use auto-approval",
            rule_id=f"feature_flag.{feature_name}.disabled",
            by_hook="feature_flags",
        )

    return result.to_policy_decision()


def list_features(subsystem: str | None = None) -> list[FeatureSpec]:
    """List all registered features, optionally filtered by subsystem."""
    _ensure_loaded()
    assert _features_cache is not None
    result = list(_features_cache.values())
    if subsystem:
        result = [f for f in result if f.subsystem == subsystem]
    return sorted(result, key=lambda f: f.name)


def get_feature(name: str) -> FeatureSpec | None:
    """Get a single feature by name."""
    return _get_feature(name)
