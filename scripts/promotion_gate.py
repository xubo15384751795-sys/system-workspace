#!/usr/bin/env python3
"""Promotion Gate — enforce claim strength boundaries.

Checks that system outputs are not described beyond their evidence level.
Blocks use of "signal", "regime call", "prediction" when gates fail.

Usage:
    python3 scripts/promotion_gate.py
    python3 scripts/promotion_gate.py --json
    python3 scripts/promotion_gate.py --check-report report.md

Output:
    Output/promotion/promotion_gate.json
    Output/promotion/promotion_gate.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from _runtime_io import ensure_dir, load_json, utc_now, write_json

JUDGMENT_PATH = ROOT / "Output" / "judgment" / "latest.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
HMM_AUDIT_PATH = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
CALIBRATION_PATH = ROOT / "Output" / "judgment" / "calibration_report.json"
OUTPUT_DIR = ROOT / "Output" / "promotion"

# Minimum calibration samples required
MIN_CALIBRATION_SAMPLES = 10


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def check_confidence_gate(judgment: dict[str, Any] | None) -> dict[str, Any]:
    """Check if confidence level blocks promotion."""
    if not judgment:
        return {"status": "BLOCKED", "reason": "No judgment card available"}

    confidence = (judgment.get("confidence") or {}).get("level", "unknown")
    if confidence == "low":
        return {"status": "BLOCKED", "reason": "Confidence is low"}
    return {"status": "PASS"}


def check_caselab_gate(date_str: str) -> dict[str, Any]:
    """Check if CaseLab match quality blocks promotion."""
    caselab_path = CASELAB_DIR / f"{date_str}.json"
    caselab = load_json(caselab_path)

    if not caselab:
        return {"status": "BLOCKED", "reason": "No CaseLab output available"}

    match_quality = caselab.get("match_quality", {})
    label = match_quality.get("label", "unknown")

    if label in ("weak", "no_reliable_analogy"):
        return {"status": "BLOCKED", "reason": f"CaseLab match quality: {label}"}
    return {"status": "PASS"}


def check_k_gate() -> dict[str, Any]:
    """Check if K measurement gate passes."""
    k_gate = load_json(K_GATE_PATH)

    if not k_gate:
        return {"status": "BLOCKED", "reason": "K measurement gate not available"}

    verdict = k_gate.get("gate_verdict", "UNKNOWN")
    if verdict != "PASS":
        return {"status": "BLOCKED", "reason": f"K gate: {verdict}"}
    return {"status": "PASS"}


def check_x_gate() -> dict[str, Any]:
    """Check if X_agg measurement gate passes."""
    x_gate = load_json(X_GATE_PATH)

    if not x_gate:
        return {"status": "BLOCKED", "reason": "X_agg measurement gate not available"}

    verdict = x_gate.get("gate_verdict", "UNKNOWN")
    if verdict != "PASS":
        return {"status": "BLOCKED", "reason": f"X_agg gate: {verdict}"}
    return {"status": "PASS"}


def check_hmm_stability() -> dict[str, Any]:
    """Check if HMM stability is adequate."""
    hmm_audit = load_json(HMM_AUDIT_PATH)

    if not hmm_audit:
        return {"status": "BLOCKED", "reason": "HMM stability audit not available"}

    grade = hmm_audit.get("stability_grade", "UNKNOWN")
    if grade == "WEAK":
        return {"status": "BLOCKED", "reason": f"HMM stability: {grade}"}
    return {"status": "PASS"}


def check_calibration_samples() -> dict[str, Any]:
    """Check if enough calibration samples exist."""
    calibration = load_json(CALIBRATION_PATH)

    if not calibration:
        return {"status": "BLOCKED", "reason": "Calibration report not available"}

    summary = calibration.get("summary", {})
    evaluated = summary.get("evaluated_cards", 0)

    if evaluated < MIN_CALIBRATION_SAMPLES:
        return {"status": "BLOCKED", "reason": f"Calibration samples={evaluated} < {MIN_CALIBRATION_SAMPLES}"}
    return {"status": "PASS"}


def get_blocked_terms() -> list[str]:
    """Get list of terms that are blocked when gates fail."""
    return [
        "signal",
        "regime call",
        "prediction",
        "forecast",
        "trading signal",
        "strong signal",
        "high confidence signal",
    ]


def check_text_for_blocked_terms(text: str, gates: dict[str, Any]) -> list[dict[str, Any]]:
    """Check if text contains blocked terms when gates fail."""
    violations = []
    blocked_terms = get_blocked_terms()

    # Only check if any gate is blocked
    any_blocked = any(g.get("status") == "BLOCKED" for g in gates.values())
    if not any_blocked:
        return violations

    text_lower = text.lower()
    for term in blocked_terms:
        if term in text_lower:
            violations.append({
                "term": term,
                "context": text[max(0, text_lower.index(term) - 50):text_lower.index(term) + len(term) + 50],
            })

    return violations


def run_promotion_gate(date_str: str | None = None) -> dict[str, Any]:
    """Run complete promotion gate check."""
    if not date_str:
        date_str = utc_now().strftime("%Y-%m-%d")

    judgment = load_json(JUDGMENT_PATH)

    # Run all gates
    gates = {
        "confidence": check_confidence_gate(judgment),
        "caselab": check_caselab_gate(date_str),
        "k_gate": check_k_gate(),
        "x_gate": check_x_gate(),
        "hmm_stability": check_hmm_stability(),
        "calibration_samples": check_calibration_samples(),
    }

    # Determine overall status
    blocked_gates = [name for name, gate in gates.items() if gate.get("status") == "BLOCKED"]
    overall_status = "BLOCKED" if blocked_gates else "PASS"

    # Determine allowed language
    if overall_status == "BLOCKED":
        allowed_language = ["diagnostic", "watch", "observation", "monitor"]
        forbidden_language = ["signal", "regime call", "prediction", "forecast"]
    else:
        allowed_language = ["signal", "regime call", "prediction", "forecast", "diagnostic", "watch"]
        forbidden_language = []

    return {
        "schema_version": "system.promotion_gate.v1",
        "generated_at": utc_now().isoformat(),
        "as_of": date_str,
        "overall_status": overall_status,
        "gates": gates,
        "blocked_gates": blocked_gates,
        "allowed_language": allowed_language,
        "forbidden_language": forbidden_language,
        "blocking_reasons": [gates[g]["reason"] for g in blocked_gates],
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Promotion Gate Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Date: {report['as_of']}",
        f"- Overall status: **{report['overall_status']}**",
        "",
        "## Gates",
        "",
        "| Gate | Status | Reason |",
        "|---|---|---|",
    ]

    for gate_name, gate in report["gates"].items():
        reason = gate.get("reason", "")
        lines.append(f"| {gate_name} | {gate['status']} | {reason} |")

    lines += [
        "",
        "## Allowed Language",
        "",
    ]
    for term in report["allowed_language"]:
        lines.append(f"- {term}")

    if report["forbidden_language"]:
        lines += [
            "",
            "## Forbidden Language",
            "",
        ]
        for term in report["forbidden_language"]:
            lines.append(f"- {term}")

    if report["blocking_reasons"]:
        lines += [
            "",
            "## Blocking Reasons",
            "",
        ]
        for reason in report["blocking_reasons"]:
            lines.append(f"- {reason}")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run promotion gate check.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date for lookup.")
    parser.add_argument("--check-report", default=None, help="Check a report file for blocked terms.")
    args = parser.parse_args()

    report = run_promotion_gate(args.date)

    ensure_dir(OUTPUT_DIR)
    json_path = OUTPUT_DIR / "promotion_gate.json"
    md_path = OUTPUT_DIR / "promotion_gate.md"

    write_json(json_path, report)
    md_path.write_text(format_markdown(report), encoding="utf-8")

    # Check report if provided
    if args.check_report:
        report_path = Path(args.check_report)
        if report_path.exists():
            text = report_path.read_text(encoding="utf-8")
            violations = check_text_for_blocked_terms(text, report["gates"])
            if violations:
                print(f"WARNING: Found {len(violations)} blocked terms in {args.check_report}:")
                for v in violations:
                    print(f"  - '{v['term']}' in: ...{v['context']}...")
            else:
                print(f"No blocked terms found in {args.check_report}")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Promotion gate: {report['overall_status']}")
        if report["blocked_gates"]:
            print(f"Blocked by: {', '.join(report['blocked_gates'])}")
        print(f"Allowed: {', '.join(report['allowed_language'])}")
        if report["forbidden_language"]:
            print(f"Forbidden: {', '.join(report['forbidden_language'])}")


if __name__ == "__main__":
    main()
