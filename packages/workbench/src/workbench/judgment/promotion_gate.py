"""Judgment Promotion Gate — enforce claim strength boundaries.

This module is the FINAL gate before any output reaches the user.
It reads judgment card + all supporting evidence and decides:
- What language is allowed
- What language is blocked
- What the claim ceiling is

Usage:
    from workbench.judgment.promotion_gate import run_promotion_gate

    report = run_promotion_gate(date_str)
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
JUDGMENT_PATH = ROOT / "Output" / "judgment" / "latest.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
HMM_PATH = ROOT / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
HMM_AUDIT_PATH = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
OUTPUT_DIR = ROOT / "Output" / "judgment"


def load_json(path: Path) -> dict[str, Any] | None:
    """Load a JSON file, returning None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def check_confidence(judgment: dict[str, Any]) -> dict[str, Any]:
    """Check confidence gate with layered confidence support.

    Uses mechanism_confidence when available to allow mechanism claims
    even when trade_confidence is low.
    """
    conf = judgment.get("confidence") or {}
    confidence = conf.get("level", "unknown")
    layered = conf.get("layered", {})
    claim_ceiling = judgment.get("claim_ceiling", "unknown")

    if confidence == "low":
        # Check if mechanism confidence is sufficient for mechanism claims
        mech_conf = layered.get("mechanism_confidence", confidence)
        diag_conf = layered.get("diagnostic_confidence", confidence)

        if mech_conf in ("medium_low", "medium", "medium_high", "high"):
            return {
                "status": "WATCH",
                "reason": (
                    f"Trade confidence is low, but mechanism_confidence={mech_conf} — "
                    f"mechanism hypothesis allowed, trade blocked"
                ),
                "blocked_terms": ["signal", "regime call", "prediction", "forecast", "position"],
            }
        return {
            "status": "BLOCKED",
            "reason": f"Confidence is low, claim_ceiling={claim_ceiling}",
            "blocked_terms": ["signal", "regime call", "prediction", "forecast"],
        }
    return {"status": "PASS", "blocked_terms": []}


def check_claim_ceiling(judgment: dict[str, Any]) -> dict[str, Any]:
    """Check claim ceiling gate.

    Supports graduated ceilings:
    - diagnostic_watch_only: BLOCKED (legacy behavior)
    - mechanism_hypothesis: WATCH (allows mechanism language, blocks operational)
    - structural_diagnostic_with_caveats: WATCH
    - structural_diagnostic: PASS
    """
    claim_ceiling = judgment.get("claim_ceiling", "unknown")

    if claim_ceiling == "mechanism_hypothesis":
        return {
            "status": "WATCH",
            "reason": "Claim ceiling is mechanism_hypothesis — mechanism language allowed, operational blocked",
            "blocked_terms": ["signal", "regime call", "prediction", "forecast", "position", "strong claim"],
        }

    if claim_ceiling == "diagnostic_watch_only":
        return {
            "status": "BLOCKED",
            "reason": "Claim ceiling is diagnostic_watch_only",
            "blocked_terms": ["signal", "regime call", "prediction", "forecast", "strong claim"],
        }

    if claim_ceiling == "structural_diagnostic_with_caveats":
        return {
            "status": "WATCH",
            "reason": "Claim ceiling has caveats",
            "blocked_terms": ["prediction", "forecast"],
        }

    return {"status": "PASS", "blocked_terms": []}


def check_caselab(date_str: str) -> dict[str, Any]:
    caselab_path = CASELAB_DIR / f"{date_str}.json"
    caselab = load_json(caselab_path)
    if not caselab:
        return {"status": "BLOCKED", "reason": "No CaseLab output", "blocked_terms": ["historical analogy"]}
    match_quality = caselab.get("match_quality", {})
    label = match_quality.get("label", "unknown")
    top_score = _as_float(match_quality.get("top_score", 0))
    if label == "no_reliable_analogy":
        return {
            "status": "BLOCKED",
            "reason": f"CaseLab match quality: {label} (score={top_score:.3f})",
            "blocked_terms": ["historical analogy", "similar to", "like"],
        }
    if label == "weak":
        # Weak analogy: allow mechanism hypothesis language (Claim Ladder Tier 1),
        # but block strong analogy claims. Not a gate blocker.
        return {
            "status": "WATCH",
            "reason": f"CaseLab match quality: {label} (score={top_score:.3f}) — mechanism hypothesis only",
            "blocked_terms": ["strong analogy", "historical precedent"],
        }
    return {"status": "PASS", "blocked_terms": []}


def check_hmm() -> dict[str, Any]:
    """Check HMM gate with claim-type-aware blocking.

    HMM blocks REGIME claims when model_health is FAIL or calibration
    is INSUFFICIENT_HISTORY. But it does NOT block mechanism hypothesis,
    M/D structural readout, or watch conditions.
    """
    hmm = load_json(HMM_PATH)
    hmm_audit = load_json(HMM_AUDIT_PATH)
    if not hmm:
        return {
            "status": "BLOCKED",
            "reason": "No HMM output",
            "blocked_terms": ["regime", "crisis", "compression"],
            "supportable_claims": [],
        }

    if hmm_audit:
        # Use new split dimensions if available
        model_health = hmm_audit.get("model_health", {}).get("grade", "UNKNOWN")
        cal_status = hmm_audit.get("calibration_status", {}).get("status", "UNKNOWN")
        grade = hmm_audit.get("stability_grade", "UNKNOWN")
        supportable = hmm_audit.get("hmm_supportable_claims", [])
        blocked_claims = hmm_audit.get("hmm_blocked_claims", [])

        if model_health == "FAIL":
            return {
                "status": "BLOCKED",
                "reason": f"HMM model health: {model_health}",
                "blocked_terms": ["regime", "crisis", "compression", "mechanism"],
                "supportable_claims": [],
            }

        if cal_status == "INSUFFICIENT_HISTORY":
            return {
                "status": "BLOCKED",
                "reason": f"HMM calibration: {cal_status} — regime claims blocked, mechanism hypothesis allowed",
                "blocked_terms": blocked_claims or ["regime", "crisis", "compression"],
                "supportable_claims": supportable,
            }

        if grade == "WEAK":
            return {
                "status": "BLOCKED",
                "reason": f"HMM stability: {grade}",
                "blocked_terms": ["regime", "crisis", "compression"],
                "supportable_claims": supportable,
            }

    regime = hmm.get("regime", {})

    # Use calibrated confidence when available; fall back to raw probability
    calibrated = regime.get("calibrated_confidence")
    raw_prob = _as_float(regime.get("raw_probability", regime.get("current_probability", 0)))

    if calibrated:
        calibration_passed = regime.get("calibration_passed", False)
        cal_info = hmm.get("calibration", {})
        if not calibration_passed:
            return {
                "status": "WATCH",
                "reason": (
                    f"HMM calibration not passed: "
                    f"raw_prob={raw_prob:.4f}, calibrated={calibrated}, "
                    f"cap={cal_info.get('cap_applied', 'unknown')} — "
                    f"regime claims blocked, mechanism hypothesis allowed"
                ),
                "blocked_terms": ["regime", "crisis", "compression", "certain"],
                "supportable_claims": hmm_audit.get("hmm_supportable_claims", []) if hmm_audit else [],
            }
    else:
        if raw_prob >= 0.99:
            return {
                "status": "BLOCKED",
                "reason": f"HMM overconfident: probability={raw_prob:.3f}",
                "blocked_terms": ["certain", "definitely", "truth"],
                "supportable_claims": [],
            }

    current = regime.get("current", "unknown")
    if current == "crisis":
        return {
            "status": "WATCH",
            "reason": "HMM indicates crisis — verify with M/D/K/X",
            "blocked_terms": [],
            "supportable_claims": hmm_audit.get("hmm_supportable_claims", []) if hmm_audit else [],
        }
    return {
        "status": "PASS",
        "blocked_terms": [],
        "supportable_claims": hmm_audit.get("hmm_supportable_claims", []) if hmm_audit else [],
    }


def check_k_gate() -> dict[str, Any]:
    k_gate = load_json(K_GATE_PATH)
    if not k_gate:
        return {"status": "NOT_AVAILABLE", "reason": "K gate not run", "blocked_terms": []}
    verdict = k_gate.get("gate_verdict", "UNKNOWN")
    if verdict != "PASS":
        return {
            "status": "BLOCKED",
            "reason": f"K gate: {verdict}",
            "blocked_terms": ["K primary", "K signal", "curvature signal"],
        }
    return {"status": "PASS", "blocked_terms": []}


def check_x_gate() -> dict[str, Any]:
    x_gate = load_json(X_GATE_PATH)
    if not x_gate:
        return {"status": "NOT_AVAILABLE", "reason": "X gate not run", "blocked_terms": []}
    verdict = x_gate.get("gate_verdict", "UNKNOWN")
    if verdict != "PASS":
        return {
            "status": "BLOCKED",
            "reason": f"X_agg gate: {verdict}",
            "blocked_terms": ["X primary", "X signal", "leverage signal"],
        }
    return {"status": "PASS", "blocked_terms": []}


def determine_allowed_language(
    gates: dict[str, dict],
    claim_ladder: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    all_blocked = set()
    any_blocked = False
    for gate_name, gate in gates.items():
        if gate.get("status") == "BLOCKED":
            any_blocked = True
            all_blocked.update(gate.get("blocked_terms", []))
    if any_blocked:
        allowed = ["diagnostic", "watch", "observation", "monitor", "research note"]
        forbidden = sorted(all_blocked)
    else:
        allowed = ["signal", "regime call", "prediction", "forecast", "diagnostic", "watch"]
        forbidden = []

    # Merge claim ladder language (ladder can ADD allowed terms at higher tiers)
    if claim_ladder:
        ladder_allowed = claim_ladder.get("allowed_language", [])
        ladder_forbidden = claim_ladder.get("forbidden_language", [])
        # Add ladder-allowed terms that aren't already forbidden by gates
        forbidden_set = set(forbidden)
        for term in ladder_allowed:
            if term not in forbidden_set and term not in allowed:
                allowed.append(term)
        # Add ladder-forbidden terms
        for term in ladder_forbidden:
            if term not in forbidden:
                forbidden.append(term)
        forbidden = sorted(set(forbidden))
        # Remove any term from allowed that ended up forbidden
        forbidden_set = set(forbidden)
        allowed = [t for t in allowed if t not in forbidden_set]

    return {"allowed": allowed, "forbidden": forbidden}


def determine_claim_ceiling(gates: dict[str, dict]) -> str:
    priority_gates = ["confidence", "claim_ceiling", "caselab", "hmm", "k_gate", "x_gate"]
    for gate_name in priority_gates:
        gate = gates.get(gate_name, {})
        if gate.get("status") == "BLOCKED":
            return "diagnostic_watch_only"
    for gate_name in priority_gates:
        gate = gates.get(gate_name, {})
        if gate.get("status") == "WATCH":
            return "structural_diagnostic_with_caveats"
    return "structural_diagnostic"


def run_promotion_gate(date_str: str | None = None) -> dict[str, Any]:
    if not date_str:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    judgment = load_json(JUDGMENT_PATH)
    if not judgment:
        return {
            "schema_version": "system.judgment_promotion_gate.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "as_of": date_str,
            "overall_status": "BLOCKED",
            "reason": "No judgment card available",
            "gates": {},
            "allowed_language": ["diagnostic", "watch"],
            "forbidden_language": ["signal", "regime call", "prediction", "forecast"],
            "claim_ceiling": "diagnostic_watch_only",
        }
    gates = {
        "confidence": check_confidence(judgment),
        "claim_ceiling": check_claim_ceiling(judgment),
        "caselab": check_caselab(date_str),
        "hmm": check_hmm(),
        "k_gate": check_k_gate(),
        "x_gate": check_x_gate(),
    }
    blocked_gates = [name for name, gate in gates.items() if gate.get("status") == "BLOCKED"]
    watch_gates = [name for name, gate in gates.items() if gate.get("status") == "WATCH"]
    if blocked_gates:
        overall_status = "BLOCKED"
    elif watch_gates:
        overall_status = "WATCH"
    else:
        overall_status = "PASS"
    language = determine_allowed_language(gates)
    claim_ceiling = determine_claim_ceiling(gates)

    # Include claim ladder from judgment card if available
    claim_ladder = judgment.get("claim_ladder")

    # Re-evaluate language with ladder context
    if claim_ladder:
        language = determine_allowed_language(gates, claim_ladder)
    blocking_reasons = [gates[g]["reason"] for g in blocked_gates]
    watch_reasons = [gates[g]["reason"] for g in watch_gates]
    return {
        "schema_version": "system.judgment_promotion_gate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": date_str,
        "overall_status": overall_status,
        "judgment_decision": judgment.get("decision"),
        "judgment_confidence": (judgment.get("confidence") or {}).get("level"),
        "claim_ladder": claim_ladder,
        "gates": gates,
        "blocked_gates": blocked_gates,
        "watch_gates": watch_gates,
        "blocking_reasons": blocking_reasons,
        "watch_reasons": watch_reasons,
        "allowed_language": language["allowed"],
        "forbidden_language": language["forbidden"],
        "claim_ceiling": claim_ceiling,
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Judgment Promotion Gate — {report['as_of']}",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Overall status:** {report['overall_status']}",
        f"**Judgment decision:** {report.get('judgment_decision', 'N/A')}",
        f"**Judgment confidence:** {report.get('judgment_confidence', 'N/A')}",
        f"**Claim ceiling:** {report['claim_ceiling']}",
        "",
        "---",
        "",
        "## Gates",
        "",
        "| Gate | Status | Reason |",
        "|---|---|---|",
    ]
    for gate_name, gate in report["gates"].items():
        reason = gate.get("reason", "")
        lines.append(f"| {gate_name} | {gate['status']} | {reason} |")
    if report["blocking_reasons"]:
        lines += ["", "## Blocking Reasons", ""]
        for reason in report["blocking_reasons"]:
            lines.append(f"- {reason}")
    if report["watch_reasons"]:
        lines += ["", "## Watch Reasons", ""]
        for reason in report["watch_reasons"]:
            lines.append(f"- {reason}")
    lines += ["", "## Allowed Language", ""]
    for term in report["allowed_language"]:
        lines.append(f"- ✅ {term}")
    if report["forbidden_language"]:
        lines += ["", "## Forbidden Language", ""]
        for term in report["forbidden_language"]:
            lines.append(f"- ❌ {term}")
    lines += [
        "",
        "---",
        "",
        "*This gate enforces: do not describe system outputs beyond their evidence level.*",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "promotion_gate.json"
    md_path = OUTPUT_DIR / "promotion_gate.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
