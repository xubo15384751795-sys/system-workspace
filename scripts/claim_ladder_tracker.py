#!/usr/bin/env python3
"""Claim Ladder Tracker — cross-run claim progression evaluator.

Reads the previous run's feedback_pending.json and the current judgment
card to evaluate whether mechanism hypotheses are progressing, stuck,
or invalidated.

Usage:
    python3 scripts/claim_ladder_tracker.py
    python3 scripts/claim_ladder_tracker.py --json

Output:
    Output/claim_ladder/progression.json  — per-claim progression status
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from _runtime_io import ensure_dir, load_json, utc_now, write_json

RUNS_DIR = ROOT / "Output" / "runs"
JUDGMENT_PATH = ROOT / "Output" / "judgment" / "latest.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
HMM_PATH = ROOT / "Output" / "ml_signals" / "latest" / "regime_hmm.json"
OUTPUT_DIR = ROOT / "Output" / "claim_ladder"


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
                continue
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
    import datetime as _dt
    today = _dt.date.today().isoformat()
    caselab_path = CASELAB_DIR / f"{today}.json"
    current_gap = prev_gap  # default: no change
    if caselab_path.exists():
        try:
            caselab = load_json(caselab_path) or {}
            mq = caselab.get("match_quality", {})
            top_score = mq.get("top_score", 0)
            usable_th = mq.get("thresholds", {}).get("usable", 0.55)
            current_gap = round(max(0, usable_th - top_score), 3)
        except Exception:
            pass

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

    regime = hmm.get("regime", "unknown")
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
    """Build the full claim ladder progression report."""
    now = utc_now()

    # Find previous run
    prev_run_dir = find_previous_run_dir()
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

    # Evaluate progression
    claims = evaluate_progression(prev_items, current_judgment)

    return {
        "schema_version": "claim_ladder_progression.v1",
        "generated_at": now.isoformat(),
        "previous_run": prev_run_dir.name,
        "current_judgment_date": current_judgment.get("as_of", ""),
        "status": "evaluated",
        "claims": claims,
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
        for claim in report.get("claims", []):
            prev = claim["previous_run_claim"]
            print(f"  Tier {prev['claim_tier']}: {claim['overall_status']}")


if __name__ == "__main__":
    main()
