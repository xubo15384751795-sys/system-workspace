"""Release quality gate and promotion policy.

Determines which releases can become latest, which are archived,
and which can serve Deformation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from harvester.registry import SeriesRegistry


# ---------------------------------------------------------------------------
# Promotion states
# ---------------------------------------------------------------------------


class PromotionState:
    CREATED = "created"
    VALIDATED = "validated"
    PROMOTED = "promoted"
    REJECTED = "rejected"


PROVIDER_FAILURE_CLASSES = frozenset(
    {
        "NONE",
        "NO_DATA",
        "PROVIDER_DOWN",
        "NETWORK",
        "SCHEMA_CHANGED",
        "PARSER",
        "PERMISSION",
        "RATE_LIMIT",
        "UNKNOWN",
    }
)


# ---------------------------------------------------------------------------
# Gate result
# ---------------------------------------------------------------------------


@dataclass
class GateCheck:
    """Single gate check result."""

    name: str
    passed: bool
    detail: str = ""
    severity: str = "error"  # error, warn, info


@dataclass
class GateResult:
    passed: bool
    state: str  # created, validated, promoted, rejected
    checks: list[GateCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    provider_failure_classes: dict[str, list[str]] = field(default_factory=dict)

    @property
    def promotion_allowed(self) -> bool:
        return self.state == PromotionState.PROMOTED


def _provider_status_policy(status: str) -> dict[str, str] | None:
    """Load the workspace-owned status matrix for promotion decisions.

    Harvester remains independently buildable, but promotion is fail-closed
    when the workspace governance policy is not available.  This prevents a
    standalone package fallback from silently becoming a second status
    authority.
    """
    try:
        from system_runtime.provider_status import provider_status_policy

        configured_root = os.environ.get("SYSTEM_ROOT", "").strip()
        root = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else Path(__file__).resolve().parents[4]
        )
        return cast(dict[str, str], provider_status_policy(status, root=root))
    except (ImportError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------


def run_promotion_gate(
    release_dir: Path,
    registry: SeriesRegistry,
    *,
    panel_series_ids: set[str] | None = None,
    manifest_series_ids: set[str] | None = None,
    sha256_verified: bool = True,
    has_future_vintage: bool = False,
    has_lookahead_violation: bool = False,
    empty_panels: list[str] | None = None,
    retired_in_current_input: bool = False,
    cross_asset_row_count: int | None = None,
    cross_asset_symbol_count: int | None = None,
    cross_asset_provider_status: str | None = None,
    benchmark_provider_status: str | None = None,
    provider_failure_classes: Mapping[str, Sequence[str]] | None = None,
) -> GateResult:
    checks: list[GateCheck] = []
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    normalized_failure_classes: dict[str, list[str]] = {}
    invalid_failure_classes: list[str] = []
    for scope, values in (provider_failure_classes or {}).items():
        normalized: set[str] = set()
        for value in values:
            category = str(value).strip().upper()
            if category not in PROVIDER_FAILURE_CLASSES:
                invalid_failure_classes.append(f"{scope}:{category or '<empty>'}")
            else:
                normalized.add(category)
        if normalized:
            normalized_failure_classes[str(scope)] = sorted(normalized)
    if invalid_failure_classes:
        detail = f"unrecognized provider failure classes: {sorted(invalid_failure_classes)}"
        blockers.append(detail)
        checks.append(GateCheck("provider_failure_class_contract", False, detail))
    elif normalized_failure_classes:
        checks.append(
            GateCheck(
                "provider_failure_class_contract",
                True,
                json.dumps(normalized_failure_classes, sort_keys=True),
                severity="info",
            )
        )

    panel_series = panel_series_ids or set()
    manifest_series = manifest_series_ids or set()
    empty = empty_panels or []
    available = panel_series | manifest_series

    # ------------------------------------------------------------------
    # Check 1: Required-for-release series present
    # ------------------------------------------------------------------
    required = registry.required_series()
    missing_required: list[str] = []
    for s in required:
        sid = s.canonical_id
        if sid not in available and s.allow_synthetic_proxy and s.synthetic_proxy_id:
            if s.synthetic_proxy_id not in available:
                missing_required.append(f"{sid} (no proxy either)")
            else:
                notes.append(f"{sid}: using synthetic proxy {s.synthetic_proxy_id}")
        elif sid not in available:
            missing_required.append(sid)

    if missing_required:
        blockers.append(f"required series missing: {missing_required}")
        checks.append(GateCheck("required_series_present", False, str(missing_required)))
    else:
        checks.append(GateCheck("required_series_present", True, "all required series accounted for"))

    # ------------------------------------------------------------------
    # Check 2: Required-for-model-input fresh
    # ------------------------------------------------------------------
    model_inputs = registry.model_input_series()
    missing_model_input: list[str] = []
    for s in model_inputs:
        if s.canonical_id not in available:
            missing_model_input.append(s.canonical_id)
    if missing_model_input:
        warnings.append(f"model-input series missing: {missing_model_input}")
        checks.append(GateCheck("model_input_fresh", False, str(missing_model_input), "warn"))
    else:
        checks.append(GateCheck("model_input_fresh", True))

    # ------------------------------------------------------------------
    # Check 3: SHA256 integrity
    # ------------------------------------------------------------------
    if sha256_verified:
        checks.append(GateCheck("sha256_integrity", True))
    else:
        blockers.append("sha256 verification failed")
        checks.append(GateCheck("sha256_integrity", False, "hash mismatch detected"))

    # ------------------------------------------------------------------
    # Check 4: No future vintage
    # ------------------------------------------------------------------
    if has_future_vintage:
        blockers.append("future vintage date detected")
        checks.append(GateCheck("no_future_vintage", False, "panel contains future vintage_date"))
    else:
        checks.append(GateCheck("no_future_vintage", True))

    # ------------------------------------------------------------------
    # Check 5: No lookahead violation
    # ------------------------------------------------------------------
    if has_lookahead_violation:
        blockers.append("lookahead violation detected")
        checks.append(GateCheck("no_lookahead_violation", False))
    else:
        checks.append(GateCheck("no_lookahead_violation", True))

    # ------------------------------------------------------------------
    # Check 6: Empty required panels
    # ------------------------------------------------------------------
    if empty:
        blockers.append(f"empty required panels: {empty}")
        checks.append(GateCheck("no_empty_required_panels", False, str(empty)))
    else:
        checks.append(GateCheck("no_empty_required_panels", True))

    # Cross-asset history is an input to K/X validation and forward-event
    # scoring. A few fresh rows must not replace a full historical panel.
    if cross_asset_row_count is not None:
        symbol_count = max(1, int(cross_asset_symbol_count or 0))
        minimum_rows = 252 * symbol_count
        if cross_asset_row_count < minimum_rows:
            detail = (
                f"rows={cross_asset_row_count}, symbols={symbol_count}, "
                f"minimum_rows={minimum_rows}"
            )
            blockers.append(f"cross-asset historical coverage regression: {detail}")
            checks.append(GateCheck("cross_asset_history_preserved", False, detail))
        else:
            checks.append(
                GateCheck(
                    "cross_asset_history_preserved",
                    True,
                    f"rows={cross_asset_row_count}, symbols={symbol_count}",
                )
            )

    if cross_asset_provider_status:
        detail = f"provider_status={cross_asset_provider_status}"
        status_policy = _provider_status_policy(cross_asset_provider_status)
        if status_policy is None:
            policy_detail = f"{detail}; status matrix unavailable or invalid"
            blockers.append(f"cross-asset provider status policy unavailable: {policy_detail}")
            checks.append(GateCheck("cross_asset_provider_status_policy", False, policy_detail))
            checks.append(GateCheck("cross_asset_provider_admission", False, detail))
        else:
            policy_detail = (
                f"{detail}; decision={status_policy['decision']}; "
                f"evaluator_verdict={status_policy['evaluator_verdict']}; "
                f"status_policy={json.dumps(status_policy, sort_keys=True)}"
            )
            checks.append(GateCheck("cross_asset_provider_status_policy", True, policy_detail))
            decision = status_policy["decision"]
            evaluator_verdict = status_policy["evaluator_verdict"]
            if decision == "DENY" or evaluator_verdict in {"FAIL", "BLOCKED"}:
                blockers.append(f"cross-asset provider outcome not acceptable: {policy_detail}")
                checks.append(GateCheck("cross_asset_provider_admission", False, policy_detail))
            elif decision == "CONDITIONAL" or evaluator_verdict == "WARN":
                warnings.append(f"cross-asset provider outcome degraded: {policy_detail}")
                checks.append(GateCheck("cross_asset_provider_admission", False, policy_detail, "warn"))
            else:
                checks.append(GateCheck("cross_asset_provider_admission", True, policy_detail))

    # The benchmark panel is decision-facing too.  Carry-forward after a
    # provider outage is valid evidence for diagnostics, but must not become
    # the next authoritative release when the workspace policy says decision
    # use is denied.
    if benchmark_provider_status:
        detail = f"provider_status={benchmark_provider_status}"
        status_policy = _provider_status_policy(benchmark_provider_status)
        if status_policy is None:
            policy_detail = f"{detail}; status matrix unavailable or invalid"
            blockers.append(f"benchmark provider status policy unavailable: {policy_detail}")
            checks.append(GateCheck("benchmark_provider_status_policy", False, policy_detail))
            checks.append(GateCheck("benchmark_provider_admission", False, detail))
        else:
            policy_detail = (
                f"{detail}; decision={status_policy['decision']}; "
                f"evaluator_verdict={status_policy['evaluator_verdict']}; "
                f"status_policy={json.dumps(status_policy, sort_keys=True)}"
            )
            checks.append(GateCheck("benchmark_provider_status_policy", True, policy_detail))
            decision = status_policy["decision"]
            evaluator_verdict = status_policy["evaluator_verdict"]
            if decision == "DENY" or evaluator_verdict in {"FAIL", "BLOCKED"}:
                blockers.append(f"benchmark provider outcome not acceptable: {policy_detail}")
                checks.append(GateCheck("benchmark_provider_admission", False, policy_detail))
            elif decision == "CONDITIONAL" or evaluator_verdict == "WARN":
                warnings.append(f"benchmark provider outcome degraded: {policy_detail}")
                checks.append(GateCheck("benchmark_provider_admission", False, policy_detail, "warn"))
            else:
                checks.append(GateCheck("benchmark_provider_admission", True, policy_detail))

    # ------------------------------------------------------------------
    # Check 7: Retired series not in current input
    # ------------------------------------------------------------------
    if retired_in_current_input:
        blockers.append("retired series present in current model input")
        checks.append(GateCheck("retired_not_in_current_input", False))
    else:
        checks.append(GateCheck("retired_not_in_current_input", True))

    # ------------------------------------------------------------------
    # Check 8: No TEDRATE without replacement warning
    # ------------------------------------------------------------------
    tedrate = registry.get("TEDRATE")
    if tedrate and tedrate.is_retired:
        replacements_found = [
            rid for rid in [tedrate.replacements.get("primary", ""),
                            tedrate.replacements.get("secondary", ""),
                            tedrate.replacements.get("tertiary", "")]
            if rid and rid in available
        ]
        if not replacements_found:
            warnings.append("TEDRATE retired but no replacement present in release")
            checks.append(GateCheck("tedrate_replacements_available", False, "no replacement found", "warn"))
        else:
            checks.append(GateCheck("tedrate_replacements_available", True, f"found: {replacements_found}"))

    # ------------------------------------------------------------------
    # Determine state
    # ------------------------------------------------------------------
    all_checks = checks
    blocker_checks = [c for c in all_checks if c.severity == "error" and not c.passed]

    if blocker_checks:
        state = PromotionState.REJECTED
        passed = False
    elif warnings:
        state = PromotionState.VALIDATED
        passed = True
    else:
        state = PromotionState.PROMOTED
        passed = True

    return GateResult(
        passed=passed,
        state=state,
        checks=all_checks,
        warnings=warnings,
        blockers=blockers,
        notes=notes,
        provider_failure_classes=normalized_failure_classes,
    )


def generate_gate_report(result: GateResult, release_id: str) -> dict[str, Any]:
    """Generate a machine-readable gate report."""
    return {
        "gate_report_version": "1.0",
        "release_id": release_id,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "promotion_state": result.state,
        "promotion_allowed": result.promotion_allowed,
        "passed": result.passed,
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail, "severity": c.severity}
            for c in result.checks
        ],
        "blockers": result.blockers,
        "warnings": result.warnings,
        "notes": result.notes,
        "provider_failure_classes": result.provider_failure_classes,
    }


def write_gate_report(result: GateResult, release_id: str, release_dir: Path) -> Path:
    """Write gate_report.json to release directory."""
    import json as _json
    report = generate_gate_report(result, release_id)
    path = release_dir / "gate_report.json"
    path.write_text(_json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "GateCheck",
    "GateResult",
    "PROVIDER_FAILURE_CLASSES",
    "PromotionState",
    "generate_gate_report",
    "run_promotion_gate",
    "write_gate_report",
]
