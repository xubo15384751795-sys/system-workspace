#!/usr/bin/env python3
"""Claim Evaluator — verify past claims against current market data.

Reads trade ledger entries and evaluates whether claims were validated
by subsequent M/D/K/X movements. Updates forward_outcome in ledger
entries and produces an aggregate claim evaluation report.

Usage:
    python3 scripts/commands/weekly/claim_evaluator.py
    python3 scripts/commands/weekly/claim_evaluator.py --json

Output:
    Output/system_learning/latest/claim_evaluation.json
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts._runtime_io import (
    ROOT,
    dedupe_entries,
    ensure_dir,
    load_json,
    load_jsonl,
    surface_dir,
    utc_now,
)
from scripts._runtime_io import (
    entry_key as _entry_key,
)
from system_runtime.events import JsonlEventStore

logger = logging.getLogger(__name__)

TRADE_LEDGER_PATH = surface_dir("trade_ledger") / "decisions.jsonl"
FRAMEWORK_PATH = surface_dir("current") / "framework_output.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
OUTPUT_DIR = surface_dir("system_learning") / "latest"
FEEDBACK_PENDING_PATH = surface_dir("system_learning") / "latest" / "claim_failures_pending.json"



def save_jsonl(path: Path, entries: list[dict]) -> None:
    """Write entries back to JSONL file."""
    if path == TRADE_LEDGER_PATH:
        JsonlEventStore(path).replace_payloads(
            entries,
            event_type="trade_decision_recorded",
            payload_schema="trade_ledger_entry.v2",
            producer="claim_evaluator",
        )
        return
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_current_state() -> dict[str, Any]:
    """Read current M/D/K/X from framework_output.json."""
    fw = load_json(FRAMEWORK_PATH)
    if not fw:
        return {}
    sv = fw.get("advanced", {}).get("sigma_vector", {})
    return {
        "M": sv.get("M"),
        "D": sv.get("D"),
        "K": sv.get("K"),
        "X_agg": sv.get("X_agg"),
        "as_of": fw.get("as_of"),
    }


def get_current_caselab_score() -> float | None:
    """Read current CaseLab top score."""
    today = utc_now().strftime("%Y-%m-%d")
    caselab_path = CASELAB_DIR / f"{today}.json"
    caselab = load_json(caselab_path)
    if caselab:
        return caselab.get("match_quality", {}).get("top_score")
    return None


def _sign(value: float | None) -> int:
    """Return sign of value: -1, 0, or 1."""
    if value is None:
        return 0
    return -1 if value < 0 else (1 if value > 0 else 0)


def check_md_continuity(
    entry: dict, current_M: float | None, current_D: float | None
) -> dict[str, Any]:
    """Check if M/D direction persisted since the entry."""
    thesis = entry.get("trade_thesis", {})
    ladder = thesis.get("claim_ladder", {})
    values = thesis.get("md_values") or ladder.get("md_values") or {}
    entry_M = values.get("M") if isinstance(values, dict) else None
    entry_D = values.get("D") if isinstance(values, dict) else None
    try:
        entry_M = float(entry_M) if entry_M is not None else None
        entry_D = float(entry_D) if entry_D is not None else None
    except (TypeError, ValueError):
        entry_M = entry_D = None

    if entry_M is None or current_M is None:
        return {"M_persisted": None, "D_persisted": None, "direction_same": None}

    M_same_sign = _sign(entry_M) == _sign(current_M)
    D_same_sign = _sign(entry_D) == _sign(current_D) if entry_D is not None else None

    return {
        "entry_M": round(entry_M, 3),
        "entry_D": round(entry_D, 3) if entry_D is not None else None,
        "current_M": round(current_M, 3),
        "current_D": round(current_D, 3) if current_D is not None else None,
        "M_persisted": M_same_sign,
        "D_persisted": D_same_sign,
        "direction_same": M_same_sign and (D_same_sign if D_same_sign is not None else True),
    }


def check_invalidation(
    entry: dict, current_state: dict[str, Any]
) -> dict[str, Any]:
    """Check if any invalidation condition has been triggered."""
    thesis = entry.get("trade_thesis", {})
    conditions = thesis.get("invalidation_conditions", [])
    current_M = current_state.get("M")
    current_K = current_state.get("K")

    results = {}
    for cond in conditions:
        cond_lower = cond.lower()
        triggered = False
        reason = ""

        # M sign reversal
        if "m reverses sign" in cond_lower or "m reversal" in cond_lower:
            if current_M is not None:
                # Check if M has reversed from negative to positive or vice versa
                # For now, check if M is near zero (reversal zone)
                if abs(current_M) < 0.1:
                    triggered = True
                    reason = f"M near zero ({current_M:.3f})"

        # K curvature above 0.5
        if "k curvature" in cond_lower and "0.5" in cond_lower:
            if current_K is not None and current_K > 0.5:
                triggered = True
                reason = f"K={current_K:.3f} > 0.5"

        # Funding spreads normalize
        if "funding spreads normalize" in cond_lower:
            # TODO: wire to real funding spread data when available
            triggered = False
            reason = "no_funding_spread_data_available"

        # Volatility re-emerges
        if "volatility re-emerges" in cond_lower:
            # TODO: wire to real volatility regime data when available
            triggered = False
            reason = "no_volatility_regime_data_available"

        results[cond[:80]] = {"triggered": triggered, "reason": reason}

    all_clear = not any(r["triggered"] for r in results.values())
    return {"conditions": results, "all_clear": all_clear}


def evaluate_single_entry(
    entry: dict,
    current_state: dict[str, Any],
    current_caselab_score: float | None,
    days_since: int,
) -> dict[str, Any]:
    """Evaluate a single trade ledger entry."""
    current_M = current_state.get("M")
    current_D = current_state.get("D")

    # M/D continuity
    md_continuity = check_md_continuity(entry, current_M, current_D)

    # Invalidation status
    invalidation = check_invalidation(entry, current_state)

    # Watch progress
    thesis = entry.get("trade_thesis", {})
    claim = thesis.get("claim_ladder", {})
    entry_caselab = None
    claim_stmt = claim.get("claim_statement", "")
    if "CaseLab score:" in claim_stmt:
        try:
            score_part = claim_stmt.split("CaseLab score:")[1].split(")")[0]
            entry_caselab = float(score_part.strip())
        except (ValueError, IndexError):
            logger.debug("Unable to parse historical CaseLab score", exc_info=True)

    caselab_delta = None
    if entry_caselab is not None and current_caselab_score is not None:
        caselab_delta = round(current_caselab_score - entry_caselab, 4)

    # M/D persistence count (how many consecutive runs in same direction)
    md_persistence = 0
    if md_continuity.get("M_persisted") and md_continuity.get("D_persisted"):
        md_persistence = 1  # At least 1 (this entry)

    # Forward outcome — use entry values from md_continuity
    entry_M = md_continuity.get("entry_M")
    entry_D = md_continuity.get("entry_D")
    outcome = {
        "M_delta": round(current_M - entry_M, 3) if current_M is not None and entry_M is not None else None,
        "D_delta": round(current_D - entry_D, 3) if current_D is not None and entry_D is not None else None,
        "direction_correct": md_continuity.get("direction_same"),
    }

    # Overall status
    if not invalidation["all_clear"]:
        status = "invalidated"
    elif md_continuity.get("direction_same") is True:
        status = "confirmed"
    elif md_continuity.get("direction_same") is False:
        status = "contradicted"
    else:
        status = "tracking"

    return {
        "entry_date": entry.get("date"),
        "days_since": days_since,
        "claim_tier": claim.get("tier"),
        "claim_label": claim.get("label"),
        "md_continuity": md_continuity,
        "invalidation_status": invalidation,
        "watch_progress": {
            "caselab_delta": caselab_delta,
            "md_persistence_runs": md_persistence,
        },
        "outcome": outcome,
        "status": status,
    }


def score_mechanisms(evaluations: list[dict]) -> dict[str, dict]:
    """Aggregate mechanism-level scoring from evaluations."""
    # This is a placeholder — real mechanism scoring needs historical data
    # For now, return empty since we only have 1-2 days of data
    return {}


def score_modules(ledger_entries: list[dict]) -> dict[str, dict]:
    """Score module contributions based on frequency in trade ledger."""
    module_stats = {
        "hmm": {"times_adopted": 0, "times_limiting": 0, "times_rejected": 0},
        "caselab": {"times_adopted": 0, "times_weak": 0, "times_rejected": 0},
        "k_gate": {"times_pass": 0, "times_fail": 0},
        "x_gate": {"times_pass": 0, "times_fail": 0},
        "quality_validation": {"times_pass": 0, "times_fail": 0},
    }

    for entry in ledger_entries:
        for source in entry.get("system_sources", []):
            src_type = source.get("source_type", "")
            status = source.get("status", "")

            if src_type in ("hmm", "audit"):
                if status in ("ADEQUATE", "PASS"):
                    module_stats["hmm"]["times_adopted"] += 1
                elif status in ("WEAK", "BLOCKED"):
                    module_stats["hmm"]["times_limiting"] += 1
                else:
                    module_stats["hmm"]["times_rejected"] += 1

            elif src_type == "analogy":
                if status in ("strong", "usable"):
                    module_stats["caselab"]["times_adopted"] += 1
                elif status in ("weak", "no_reliable_analogy"):
                    module_stats["caselab"]["times_weak"] += 1
                else:
                    module_stats["caselab"]["times_rejected"] += 1

            elif src_type == "gate":
                # K and X gates
                if status == "PASS":
                    module_stats["k_gate"]["times_pass"] += 1
                elif status == "FAIL":
                    module_stats["k_gate"]["times_fail"] += 1

    # Calculate usefulness scores
    result = {}
    for module, stats in module_stats.items():
        total = sum(v for v in stats.values() if isinstance(v, int))
        if total == 0:
            result[module] = {**stats, "usefulness": "no_data"}
        elif module == "hmm":
            if stats["times_adopted"] > stats["times_limiting"]:
                result[module] = {**stats, "usefulness": "supportive"}
            elif stats["times_limiting"] > 0:
                result[module] = {**stats, "usefulness": "limiting"}
            else:
                result[module] = {**stats, "usefulness": "neutral"}
        elif module == "caselab":
            if stats["times_adopted"] > 0:
                result[module] = {**stats, "usefulness": "supportive"}
            elif stats["times_weak"] > 0:
                result[module] = {**stats, "usefulness": "weak"}
            else:
                result[module] = {**stats, "usefulness": "neutral"}
        else:
            result[module] = {**stats, "usefulness": "diagnostic"}

    return result


def evaluate_claims(
    ledger_entries: list[dict],
    current_state: dict[str, Any],
    current_caselab_score: float | None,
) -> dict[str, Any]:
    """Evaluate all claims in the trade ledger."""
    evaluations = []
    today = utc_now().date()

    for entry in ledger_entries:
        entry_date = entry.get("date")
        if not entry_date:
            continue

        try:
            ed = datetime.strptime(entry_date, "%Y-%m-%d").date()
            days_since = (today - ed).days
        except ValueError:
            days_since = 0

        eval_result = evaluate_single_entry(
            entry, current_state, current_caselab_score, days_since
        )
        eval_result["entry_key"] = _entry_key(entry)
        evaluations.append(eval_result)

    # Aggregate mechanism scores
    mechanism_scores = score_mechanisms(evaluations)

    # Module contributions
    module_contributions = score_modules(ledger_entries)

    # Summary stats
    total = len(evaluations)
    confirmed = sum(1 for e in evaluations if e["status"] == "confirmed")
    contradicted = sum(1 for e in evaluations if e["status"] == "contradicted")
    invalidated = sum(1 for e in evaluations if e["status"] == "invalidated")
    tracking = sum(1 for e in evaluations if e["status"] == "tracking")

    return {
        "schema_version": "claim_evaluation.v1",
        "generated_at": utc_now().isoformat(),
        "summary": {
            "total_evaluations": total,
            "confirmed": confirmed,
            "contradicted": contradicted,
            "invalidated": invalidated,
            "tracking": tracking,
        },
        "evaluations": evaluations,
        "mechanism_scores": mechanism_scores,
        "module_contributions": module_contributions,
    }


def update_forward_outcomes(
    ledger_entries: list[dict], evaluations: list[dict]
) -> list[dict]:
    """Update forward_outcome in ledger entries based on evaluations."""
    eval_by_key = {
        ev.get("entry_key"): ev
        for ev in evaluations
        if ev.get("entry_key") is not None
    }

    updated = []
    for entry in ledger_entries:
        key = _entry_key(entry)
        if key in eval_by_key:
            ev = eval_by_key[key]
            entry["forward_outcome"] = {
                "evaluated_at": utc_now().isoformat(),
                "days_since": ev["days_since"],
                "status": ev["status"],
                "md_continuity": ev["md_continuity"],
                "invalidation_status": ev["invalidation_status"],
                "outcome": ev["outcome"],
            }
        updated.append(entry)

    return updated


def write_failures_to_feedback_pending(
    evaluations: list[dict], module_contributions: dict[str, dict]
) -> list[dict]:
    """Write contradicted/invalidated claims as feedback pending items.

    These items are consumed by threshold_review_bridge.py to generate
    review candidates with gate/threshold attribution.
    """
    failures = []
    for ev in evaluations:
        status = ev.get("status", "")
        if status not in ("contradicted", "invalidated"):
            continue

        # Determine which gate/module was the binding constraint
        blocking_gates = []
        if status == "invalidated":
            for cond_name, cond_data in ev.get("invalidation_status", {}).get("conditions", {}).items():
                if cond_data.get("triggered"):
                    blocking_gates.append(f"invalidation:{cond_name[:60]}")

        # Check module contributions for gate failures
        for mod, stats in module_contributions.items():
            usefulness = stats.get("usefulness", "")
            if usefulness in ("limiting", "weak"):
                blocking_gates.append(f"module:{mod}")

        failures.append({
            "item": f"Claim {status}: {ev.get('claim_label', 'unknown')} on {ev.get('entry_date', '?')}",
            "source": "claim_evaluator",
            "validation_type": "claim_failure",
            "priority": "high" if status == "invalidated" else "medium",
            "added_at": utc_now().isoformat(),
            "metadata": {
                "entry_date": ev.get("entry_date"),
                "days_since": ev.get("days_since"),
                "claim_tier": ev.get("claim_tier"),
                "claim_label": ev.get("claim_label"),
                "failure_status": status,
                "md_continuity": ev.get("md_continuity"),
                "invalidation_status": ev.get("invalidation_status"),
                "outcome": ev.get("outcome"),
                "blocking_gates": blocking_gates,
                "module_contributions": {
                    mod: stats.get("usefulness") for mod, stats in module_contributions.items()
                },
            },
        })

    # Write to file
    if failures:
        ensure_dir(FEEDBACK_PENDING_PATH.parent)
        FEEDBACK_PENDING_PATH.write_text(
            json.dumps(failures, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote %d claim failure items to %s", len(failures), FEEDBACK_PENDING_PATH)

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate past claims")
    parser.add_argument("--json", action="store_true", help="JSON output only")
    args = parser.parse_args()

    # Load data
    ledger_entries = load_jsonl(TRADE_LEDGER_PATH)
    evaluation_entries = dedupe_entries(ledger_entries)
    current_state = get_current_state()
    current_caselab_score = get_current_caselab_score()

    if not evaluation_entries:
        logger.warning("No trade ledger entries to evaluate")
        return

    # Evaluate claims
    result = evaluate_claims(evaluation_entries, current_state, current_caselab_score)

    # Update forward_outcomes in ledger
    updated_entries = update_forward_outcomes(ledger_entries, result["evaluations"])
    save_jsonl(TRADE_LEDGER_PATH, updated_entries)

    # Write output
    ensure_dir(OUTPUT_DIR)
    output_path = OUTPUT_DIR / "claim_evaluation.json"
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Bridge: write failures to feedback_pending for threshold_review_bridge
    write_failures_to_feedback_pending(
        result["evaluations"], result.get("module_contributions", {})
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Claim evaluation: {output_path}")
        s = result["summary"]
        print(f"  Total: {s['total_evaluations']}")
        print(f"  Confirmed: {s['confirmed']}")
        print(f"  Contradicted: {s['contradicted']}")
        print(f"  Invalidated: {s['invalidated']}")
        print(f"  Tracking: {s['tracking']}")

        mc = result.get("module_contributions", {})
        if mc:
            print("\nModule contributions:")
            for mod, stats in mc.items():
                print(f"  {mod}: {stats.get('usefulness', 'unknown')}")


if __name__ == "__main__":
    main()
