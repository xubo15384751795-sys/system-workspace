#!/usr/bin/env python3
"""Build CaseLab context review queue from feedback log.

Reads caselab_context/feedback_log.jsonl and classifies each entry by
review readiness. Outputs a human-readable queue and structured samples.

Auto-accept criteria (field completeness):
  - actor, verb, object, regime all present
  - deeper_structure non-empty
  - risk_transfer has from and to
  - non_transferable_conditions non-empty
  - failure_modes non-empty
  - next_checks non-empty

Usage:
    python3 scripts/build_context_review_queue.py
    python3 scripts/build_context_review_queue.py --auto-accept
    python3 scripts/build_context_review_queue.py --json

Output:
    Output/caselab_runtime/context_review_queue.md
    Data/caselab_runtime/accepted_context_samples.jsonl
    Data/caselab_runtime/golden_context_samples.jsonl
    Data/caselab_runtime/rejected_context_samples.jsonl
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from _runtime_io import ensure_dir, load_jsonl, utc_now

FEEDBACK_LOG = ROOT / "caselab_context" / "feedback_log.jsonl"
OUTPUT_DIR = ROOT / "Output" / "caselab_runtime"
DATA_DIR = ROOT / "Data" / "caselab_runtime"

# Review status flow:
#   needs_review → accepted → golden_candidate → golden → resolver_rule
#   needs_review → rejected
#   needs_review → revise
#   accepted → needs_review (if new evidence contradicts)


def _check_field_completeness(entry: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check if an entry has all required fields for auto-accept.

    Returns: (is_complete, missing_fields)
    """
    missing: list[str] = []

    inp = entry.get("input", {})
    if not inp.get("actor"):
        missing.append("actor")
    if not inp.get("verb"):
        missing.append("verb")
    if not inp.get("object"):
        missing.append("object")
    regime = inp.get("regime", {})
    if not regime or not any(regime.values()):
        missing.append("regime")

    meaning = entry.get("contextual_meaning", {})
    if not meaning.get("deeper_structure"):
        missing.append("deeper_structure")

    risk = meaning.get("risk_transfer", {})
    if not risk.get("from"):
        missing.append("risk_transfer.from")
    if not risk.get("to"):
        missing.append("risk_transfer.to")

    if not meaning.get("non_transferable_conditions"):
        missing.append("non_transferable_conditions")
    if not meaning.get("failure_modes"):
        missing.append("failure_modes")
    if not meaning.get("next_checks"):
        missing.append("next_checks")

    return len(missing) == 0, missing


def _check_golden_criteria(entry: dict[str, Any], all_entries: list[dict]) -> tuple[bool, list[str]]:
    """Check if an entry meets golden_candidate criteria.

    Requires: accepted + repeated pattern + resolvable + non-misleading.
    """
    reasons: list[str] = []

    # Must be accepted first
    if entry.get("review_status") != "accepted":
        return False, ["not_accepted"]

    # Check for repeated pattern (same actor+verb+object appearing 2+ times)
    inp = entry.get("input", {})
    actor = inp.get("actor", "")
    verb = inp.get("verb", "")
    obj = inp.get("object", "")
    similar_count = sum(
        1 for e in all_entries
        if e.get("input", {}).get("actor") == actor
        and e.get("input", {}).get("verb") == verb
        and e.get("input", {}).get("object") == obj
    )
    if similar_count < 2:
        reasons.append(f"only {similar_count} similar sample(s), need >= 2")

    # Check if resolver rules matched (meaning it's machine-resolvable)
    if not entry.get("matched_rules"):
        reasons.append("no resolver rules matched")

    # Check confidence
    meaning = entry.get("contextual_meaning", {})
    if meaning.get("confidence") == "low":
        reasons.append("low confidence")

    return len(reasons) == 0, reasons


def classify_entries(
    entries: list[dict[str, Any]],
    auto_accept: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Classify entries by review status.

    Returns dict with keys: needs_review, accepted, golden_candidate, rejected, revise
    """
    classified: dict[str, list[dict[str, Any]]] = {
        "needs_review": [],
        "accepted": [],
        "golden_candidate": [],
        "golden": [],
        "rejected": [],
        "revise": [],
    }

    for entry in entries:
        current_status = entry.get("review_status", "needs_review")

        # If already in a terminal state, keep it
        if current_status in ("golden", "rejected"):
            classified[current_status].append(entry)
            continue

        # Auto-accept if fields are complete and currently needs_review
        if current_status == "needs_review" and auto_accept:
            is_complete, missing = _check_field_completeness(entry)
            if is_complete:
                entry["review_status"] = "accepted"
                entry["auto_accepted"] = True
                entry["accept_reason"] = "All required fields present"
                current_status = "accepted"

        # Check golden criteria for accepted entries
        if current_status == "accepted":
            is_golden, reasons = _check_golden_criteria(entry, entries)
            if is_golden:
                entry["review_status"] = "golden_candidate"
                current_status = "golden_candidate"
            elif reasons:
                entry["golden_blockers"] = reasons

        classified[current_status].append(entry)

    return classified


def write_outputs(classified: dict[str, list[dict[str, Any]]]) -> dict[str, Path]:
    """Write review queue and structured samples."""
    ensure_dir(OUTPUT_DIR)
    ensure_dir(DATA_DIR)

    # Write markdown queue
    md_path = OUTPUT_DIR / "context_review_queue.md"
    lines = [
        "# CaseLab Context Review Queue",
        "",
        f"**Generated:** {utc_now().isoformat()}",
        "",
    ]

    for status, entries in classified.items():
        if not entries:
            continue
        lines.append(f"## {status.replace('_', ' ').title()} ({len(entries)})")
        lines.append("")
        for entry in entries:
            inp = entry.get("input", {})
            meaning = entry.get("contextual_meaning", {})
            fid = entry.get("feedback_id", "unknown")
            lines.append(f"### {fid}")
            lines.append(f"- **Actor:** {inp.get('actor', '?')}")
            lines.append(f"- **Action:** {inp.get('verb', '?')} / {inp.get('object', '?')}")
            lines.append(f"- **Surface:** {meaning.get('surface_action', '?')}")
            lines.append(f"- **Confidence:** {meaning.get('confidence', '?')}")
            if entry.get("auto_accepted"):
                lines.append(f"- **Auto-accepted:** {entry.get('accept_reason', '')}")
            if entry.get("golden_blockers"):
                lines.append(f"- **Golden blockers:** {', '.join(entry['golden_blockers'])}")
            lines.append("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Write JSONL samples
    for status in ("accepted", "golden_candidate", "rejected"):
        entries = classified.get(status, [])
        if entries:
            jsonl_path = DATA_DIR / f"{status}_context_samples.jsonl"
            with jsonl_path.open("w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto-accept", action="store_true", help="Auto-accept entries with complete fields.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary to stdout.")
    args = parser.parse_args()

    entries = load_jsonl(FEEDBACK_LOG)
    if not entries:
        print(f"No entries found in {FEEDBACK_LOG}")
        return

    classified = classify_entries(entries, auto_accept=args.auto_accept)
    paths = write_outputs(classified)

    summary = {k: len(v) for k, v in classified.items()}
    total = sum(summary.values())

    if args.json:
        print(json.dumps({"total": total, "by_status": summary}, indent=2))
    else:
        print(f"Context review queue: {paths['markdown']}")
        print(f"Total entries: {total}")
        for status, count in summary.items():
            if count:
                print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
