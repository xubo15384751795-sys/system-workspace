"""Release quality gate and promotion policy.

Determines which releases can become latest, which are archived,
and which can serve Deformation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harvester.registry import RegistrySeries, SeriesRegistry


# ---------------------------------------------------------------------------
# Promotion states
# ---------------------------------------------------------------------------


class PromotionState:
    CREATED = "created"
    VALIDATED = "validated"
    PROMOTED = "promoted"
    REJECTED = "rejected"


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

    @property
    def promotion_allowed(self) -> bool:
        return self.state == PromotionState.PROMOTED


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
) -> GateResult:
    checks: list[GateCheck] = []
    blockers: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

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
    "PromotionState",
    "generate_gate_report",
    "run_promotion_gate",
    "write_gate_report",
]
