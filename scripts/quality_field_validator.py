#!/usr/bin/env python3
"""Quality Field Validator — enforce consistency across daily output.

Checks that quality fields in framework_output.json are internally consistent
and that K/X/CaseLab/HMM gates are properly enforced.

Usage:
    python3 scripts/quality_field_validator.py
    python3 scripts/quality_field_validator.py --json
    python3 scripts/quality_field_validator.py --fix  # write corrections

Output:
    Output/current/quality_validation.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _constants import CASELAB_USABLE_THRESHOLD
from _runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json

FW_PATH = ROOT / "Output" / "current" / "framework_output.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
HMM_PATH = ROOT / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
OUTPUT_PATH = ROOT / "Output" / "current" / "quality_validation.json"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def check_quality_fields(fw: dict[str, Any]) -> list[dict[str, Any]]:
    """Check that quality fields are internally consistent."""
    issues = []

    basic = fw.get("basic", {})
    advanced = fw.get("advanced", {})
    channel_conf = advanced.get("channel_confidence", {})

    quality_status = basic.get("quality_status", "UNKNOWN")
    measurement_quality = basic.get("measurement_quality", "UNKNOWN")
    measurement_eligibility = basic.get("measurement_eligibility", "UNKNOWN")
    overall = basic.get("overall", "UNKNOWN")

    # Rule 1: ACTIVE_FULL cannot equal high confidence
    if overall == "ACTIVE_FULL" and "HIGH_CONFIDENCE" in str(quality_status).upper():
        issues.append({
            "rule": "ACTIVE_FULL_NOT_HIGH_CONFIDENCE",
            "severity": "ERROR",
            "message": "ACTIVE_FULL cannot have HIGH_CONFIDENCE quality_status",
            "fields": {"overall": overall, "quality_status": quality_status},
        })

    # Rule 2: K must be diagnostic_rebuild
    k_role = channel_conf.get("K", {}).get("readout_role", "")
    if k_role and k_role != "diagnostic_rebuild":
        issues.append({
            "rule": "K_DIAGNOSTIC_ONLY",
            "severity": "ERROR",
            "message": f"K readout_role must be diagnostic_rebuild, got {k_role}",
            "fields": {"K_readout_role": k_role},
        })

    # Rule 3: X_agg must be background_only
    x_role = channel_conf.get("X_agg", {}).get("readout_role", "")
    if x_role and x_role != "background_only":
        issues.append({
            "rule": "X_BACKGROUND_ONLY",
            "severity": "ERROR",
            "message": f"X_agg readout_role must be background_only, got {x_role}",
            "fields": {"X_agg_readout_role": x_role},
        })

    # Rule 4: semantic_warning presence check
    semantic_warning = basic.get("semantic_warning")
    if semantic_warning and "STRONG" in str(semantic_warning).upper():
        issues.append({
            "rule": "SEMANTIC_WARNING_STRONG",
            "severity": "WARNING",
            "message": f"Semantic warning indicates strong claim: {semantic_warning}",
            "fields": {"semantic_warning": semantic_warning},
        })

    return issues


def check_caselab_gate(date_str: str) -> list[dict[str, Any]]:
    """Check CaseLab match quality gate."""
    issues = []

    caselab_path = CASELAB_DIR / f"{date_str}.json"
    caselab = load_json(caselab_path)
    if not caselab:
        return [{"rule": "CASELAB_MISSING", "severity": "INFO", "message": "No CaseLab output for today"}]

    match_quality = caselab.get("match_quality", {})
    top_score = _as_float(match_quality.get("top_score", 0))
    label = match_quality.get("label", "unknown")

    # Rule: top_score < CASELAB_USABLE_THRESHOLD must be weak analogy
    if top_score < CASELAB_USABLE_THRESHOLD and label != "weak":
        issues.append({
            "rule": "CASELAB_WEAK_MISLABEL",
            "severity": "ERROR",
            "message": f"CaseLab top_score={top_score:.3f} < {CASELAB_USABLE_THRESHOLD} but label={label}, should be weak",
            "fields": {"top_score": top_score, "label": label},
        })

    # Rule: weak matches must not be presented as strong analogies
    if label == "weak":
        matches = caselab.get("matches", [])
        for m in matches:
            narrative = m.get("narrative", "")
            if "像" in narrative or "similar to" in narrative.lower():
                issues.append({
                    "rule": "CASELAB_WEAK_NO_NARRATIVE",
                    "severity": "WARNING",
                    "message": f"CaseLab weak match has narrative analogy: {narrative[:80]}",
                    "fields": {"case_name": m.get("case_name"), "score": m.get("score")},
                })

    return issues


def check_hmm_gate() -> list[dict[str, Any]]:
    """Check HMM output gates."""
    issues = []

    hmm = load_json(HMM_PATH)
    if not hmm:
        return [{"rule": "HMM_MISSING", "severity": "INFO", "message": "No HMM output found"}]

    regime = hmm.get("regime", {})
    current_prob = _as_float(regime.get("current_probability", 0))

    # Rule: probability=1.0 must not be displayed as certainty
    if current_prob >= 0.99:
        issues.append({
            "rule": "HMM_OVERCONFIDENT",
            "severity": "WARNING",
            "message": f"HMM probability={current_prob:.3f} appears overconfident",
            "fields": {"current_probability": current_prob},
        })

    # Rule: HMM must not output "truth"
    regime_label = regime.get("current", "")
    if "truth" in str(regime_label).lower():
        issues.append({
            "rule": "HMM_NO_TRUTH",
            "severity": "ERROR",
            "message": f"HMM regime label contains 'truth': {regime_label}",
            "fields": {"regime_label": regime_label},
        })

    return issues


def build_validation_report(fw: dict[str, Any] | None, date_str: str) -> dict[str, Any]:
    """Build complete validation report."""
    all_issues = []

    if fw:
        all_issues.extend(check_quality_fields(fw))
        all_issues.extend(check_caselab_gate(date_str))
    else:
        all_issues.append({"rule": "FRAMEWORK_MISSING", "severity": "ERROR", "message": "framework_output.json not found"})

    all_issues.extend(check_hmm_gate())

    errors = [i for i in all_issues if i["severity"] == "ERROR"]
    warnings = [i for i in all_issues if i["severity"] == "WARNING"]

    return {
        "schema_version": "system.quality_validation.v1",
        "generated_at": utc_now().isoformat(),
        "as_of": date_str,
        "status": "PASS" if not errors else "FAIL",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": all_issues,
        "gate_summary": {
            "K_gate": "PASS" if not any(i["rule"] == "K_DIAGNOSTIC_ONLY" for i in errors) else "FAIL",
            "X_gate": "PASS" if not any(i["rule"] == "X_BACKGROUND_ONLY" for i in errors) else "FAIL",
            "caselab_gate": "PASS" if not any(i["rule"].startswith("CASELAB") for i in errors) else "FAIL",
            "hmm_gate": "PASS" if not any(i["rule"].startswith("HMM") for i in errors) else "FAIL",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate quality fields in daily output.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date for lookup.")
    args = parser.parse_args()

    fw = load_json(FW_PATH)
    date_str = args.date or utc_now().strftime("%Y-%m-%d")
    if fw:
        as_of = str(fw.get("as_of", ""))[:10]
        if as_of:
            date_str = as_of

    report = build_validation_report(fw, date_str)

    ensure_dir(OUTPUT_PATH.parent)
    write_json(OUTPUT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Quality validation: {report['status']}")
        print(f"Errors: {report['error_count']}, Warnings: {report['warning_count']}")
        for issue in report["issues"]:
            icon = "❌" if issue["severity"] == "ERROR" else "⚠️" if issue["severity"] == "WARNING" else "ℹ️"
            print(f"  {icon} [{issue['rule']}] {issue['message']}")


if __name__ == "__main__":
    main()
