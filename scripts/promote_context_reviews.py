#!/usr/bin/env python3
"""Promote context reviews — manage CaseLab review state transitions.

Review status flow:
    needs_review → accepted → golden_candidate → golden → resolver_rule
    needs_review → rejected
    needs_review → revise
    accepted → needs_review (if new evidence contradicts)

Usage:
    python3 scripts/promote_context_reviews.py --list needs_review
    python3 scripts/promote_context_reviews.py --list golden_candidate
    python3 scripts/promote_context_reviews.py --accept ctx-20260616-XXXX
    python3 scripts/promote_context_reviews.py --reject ctx-20260616-XXXX --reason "wrong actor"
    python3 scripts/promote_context_reviews.py --confirm-golden ctx-20260616-XXXX
    python3 scripts/promote_context_reviews.py --auto-accept
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _runtime_io import load_jsonl, utc_now

FEEDBACK_LOG = ROOT / "caselab_context" / "feedback_log.jsonl"

VALID_STATUSES = {"needs_review", "accepted", "rejected", "revise", "golden_candidate", "golden"}
TERMINAL_STATUSES = {"golden", "rejected"}


def _load_entries() -> list[dict]:
    """Load all feedback entries."""
    return load_jsonl(FEEDBACK_LOG)


def _save_entries(entries: list[dict]) -> None:
    """Write entries back to feedback log."""
    with FEEDBACK_LOG.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _find_entry(entries: list[dict], feedback_id: str) -> dict | None:
    """Find an entry by feedback_id."""
    for entry in entries:
        if entry.get("feedback_id") == feedback_id:
            return entry
    return None


def list_entries(entries: list[dict], status: str) -> list[dict]:
    """List entries with a given status."""
    return [e for e in entries if e.get("review_status") == status]


def transition_entry(
    entry: dict,
    new_status: str,
    reason: str = "",
    *,
    check_completeness: bool = False,
) -> bool:
    """Transition an entry to a new status. Returns True if successful."""
    current = entry.get("review_status", "needs_review")

    # Don't transition terminal states
    if current in TERMINAL_STATUSES:
        return False

    # Validate transition
    valid_transitions = {
        "needs_review": {"accepted", "rejected", "revise"},
        "accepted": {"golden_candidate", "needs_review"},
        "golden_candidate": {"golden", "accepted"},
        "revise": {"needs_review", "accepted"},
    }
    if new_status not in valid_transitions.get(current, set()):
        return False

    # Optional completeness check for auto-accept
    if check_completeness and new_status == "accepted":
        from build_context_review_queue import _check_field_completeness
        is_complete, missing = _check_field_completeness(entry)
        if not is_complete:
            return False

    entry["review_status"] = new_status
    entry.setdefault("review_history", []).append({
        "timestamp": utc_now().isoformat(),
        "from_status": current,
        "to_status": new_status,
        "reason": reason,
    })
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", metavar="STATUS", help="List entries with given status.")
    parser.add_argument("--accept", metavar="ID", help="Accept a single entry.")
    parser.add_argument("--reject", metavar="ID", help="Reject a single entry.")
    parser.add_argument("--confirm-golden", metavar="ID", help="Confirm golden_candidate as golden.")
    parser.add_argument("--auto-accept", action="store_true", help="Auto-accept all entries with complete fields.")
    parser.add_argument("--reason", default="", help="Reason for the action.")
    parser.add_argument("--json", action="store_true", help="JSON output.")
    args = parser.parse_args()

    entries = _load_entries()

    if args.list:
        found = list_entries(entries, args.list)
        if args.json:
            print(json.dumps(found, indent=2, ensure_ascii=False))
        else:
            print(f"Entries with status '{args.list}': {len(found)}")
            for e in found:
                inp = e.get("input", {})
                fid = e.get("feedback_id", "?")
                print(f"  {fid}: {inp.get('actor', '?')} / {inp.get('verb', '?')} / {inp.get('object', '?')}")
        return

    if args.auto_accept:
        from build_context_review_queue import _check_field_completeness
        count = 0
        for entry in entries:
            if entry.get("review_status") == "needs_review":
                is_complete, _ = _check_field_completeness(entry)
                if is_complete:
                    transition_entry(entry, "accepted", "auto-accepted: all required fields present")
                    count += 1
        _save_entries(entries)
        print(f"Auto-accepted {count} entries.")
        return

    if args.accept:
        entry = _find_entry(entries, args.accept)
        if not entry:
            print(f"Entry not found: {args.accept}", file=sys.stderr)
            sys.exit(1)
        ok = transition_entry(entry, "accepted", args.reason or "manually accepted")
        if ok:
            _save_entries(entries)
            print(f"Accepted: {args.accept}")
        else:
            print(f"Cannot accept '{args.accept}' — current status: {entry.get('review_status')}", file=sys.stderr)
            sys.exit(1)
        return

    if args.reject:
        entry = _find_entry(entries, args.reject)
        if not entry:
            print(f"Entry not found: {args.reject}", file=sys.stderr)
            sys.exit(1)
        ok = transition_entry(entry, "rejected", args.reason or "manually rejected")
        if ok:
            _save_entries(entries)
            print(f"Rejected: {args.reject}")
        else:
            print(f"Cannot reject '{args.reject}' — current status: {entry.get('review_status')}", file=sys.stderr)
            sys.exit(1)
        return

    if args.confirm_golden:
        entry = _find_entry(entries, args.confirm_golden)
        if not entry:
            print(f"Entry not found: {args.confirm_golden}", file=sys.stderr)
            sys.exit(1)
        ok = transition_entry(entry, "golden", args.reason or "manually confirmed as golden")
        if ok:
            _save_entries(entries)
            print(f"Confirmed golden: {args.confirm_golden}")
        else:
            print(f"Cannot confirm golden for '{args.confirm_golden}' — current status: {entry.get('review_status')}", file=sys.stderr)
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
