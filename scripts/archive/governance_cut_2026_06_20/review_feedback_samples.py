"""Review Feedback Samples.

Human review helper: displays samples needing review with context,
accepts review labels and notes, and writes them back to the replay outputs.

This script is interactive — it presents each case and asks for a label.
It is the 20% human-in-the-loop step after the 80% automated evaluation.

Usage:
    python3 scripts/review_feedback_samples.py
    python3 scripts/review_feedback_samples.py --top 20
    python3 scripts/review_feedback_samples.py --type misleading
    python3 scripts/review_feedback_samples.py --batch review_notes.jsonl
"""
from __future__ import annotations

import argparse
from pathlib import Path

from _workspace_imports import add_scripts
add_scripts()
from _runtime_io import ROOT, ensure_dir, load_json, load_jsonl, utc_now, write_json  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPLAY_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs"
REVIEW_QUEUE_PATH = ROOT / "Output" / "feedback_samples" / "review_queue.jsonl"

# Valid review labels
VALID_LABELS = [
    "useful",
    "misleading",
    "too_early",
    "false_positive",
    "missed_stress",
    "correct_but_low_value",
    "needs_review",
    "not_evaluable",
]


def _print_sample(sample: dict, index: int, total: int) -> None:
    """Print a sample for human review."""
    j = sample.get("system_judgment", {})
    fo = sample.get("forward_outcome", {})
    spy = fo.get("spy", {})
    vix = fo.get("vix", {})
    state = sample.get("system_state", {})
    cond = sample.get("conditions", {})

    print(f"\n{'='*70}")
    print(f"  REVIEW [{index+1}/{total}]  {sample.get('sample_id', 'unknown')}")
    print(f"{'='*70}")
    print(f"  Date:         {sample.get('as_of_date')}")
    print(f"  Type:         {sample.get('sample_type')}")
    print(f"  Why selected: {sample.get('why_selected', 'N/A')}")
    print(f"  Auto label:   {sample.get('review_label')} — {sample.get('auto_label_reason', 'N/A')}")
    print()
    print(f"  --- System State ---")
    print(f"  M={state.get('m_value')}  D={state.get('d_value')}  K={state.get('k_value')}  X={state.get('x_value')}")
    print()
    print(f"  --- System Judgment ---")
    print(f"  Decision:     {j.get('decision')}")
    print(f"  Confidence:   {j.get('confidence')}")
    print(f"  Claim tier:   {j.get('claim_tier')} ({j.get('claim_label', '')})")
    print(f"  Mechanism:    {j.get('mechanism_hypothesis', 'N/A')}")
    print(f"  Evidence:     {j.get('evidence_grade', 'N/A')}")
    print()
    print(f"  --- Forward Outcome ---")
    print(f"  SPY  1d={spy.get('pct_1d')}  1w={spy.get('pct_1w')}  1m={spy.get('pct_1m')}  3m={spy.get('pct_3m')}")
    print(f"  VIX  at={vix.get('level_at')}  1w={vix.get('change_1w')}  1m={vix.get('change_1m')}")
    print(f"  Max DD 1m:    {fo.get('max_drawdown_1m')}")
    print(f"  Stress event: {fo.get('stress_event_happened')}")
    print()
    if cond.get("watch_conditions"):
        print(f"  --- Watch Conditions ---")
        for wc in cond["watch_conditions"][:3]:
            print(f"    • {wc}")
    if cond.get("invalidation_conditions"):
        print(f"  --- Invalidation Conditions ---")
        for ic in cond["invalidation_conditions"][:3]:
            print(f"    • {ic}")
    print()


def _interactive_review(samples: list[dict]) -> list[dict]:
    """Interactive review loop."""
    reviewed = []
    total = len(samples)

    print(f"\nStarting interactive review of {total} samples.")
    print(f"Valid labels: {', '.join(VALID_LABELS)}")
    print(f"Type 's' to skip, 'q' to quit, 'a' to accept auto-label.\n")

    for i, sample in enumerate(samples):
        _print_sample(sample, i, total)

        while True:
            raw = input(f"  Label [{sample.get('review_label', 'needs_review')}]> ").strip().lower()

            if raw == "q":
                print("[INFO] Quitting review")
                return reviewed
            elif raw == "s":
                print("  → Skipped")
                break
            elif raw == "a":
                # Accept auto-label
                label = sample.get("review_label", "needs_review")
                note = input(f"  Notes (optional)> ").strip()
                sample["review_label"] = label
                sample["review_notes"] = note or f"Human accepted auto-label: {label}"
                sample["reviewed_at"] = utc_now().isoformat()
                sample["reviewed_by"] = "human"
                reviewed.append(sample)
                # Write back
                out_path = REPLAY_DIR / f"{sample['sample_id']}.json"
                write_json(out_path, sample)
                print(f"  → Accepted: {label}")
                break
            elif raw in VALID_LABELS:
                note = input(f"  Notes (optional)> ").strip()
                sample["review_label"] = raw
                sample["review_notes"] = note
                sample["reviewed_at"] = utc_now().isoformat()
                sample["reviewed_by"] = "human"
                reviewed.append(sample)
                # Write back
                out_path = REPLAY_DIR / f"{sample['sample_id']}.json"
                write_json(out_path, sample)
                print(f"  → Labeled: {raw}")
                break
            else:
                print(f"  Invalid label. Options: {', '.join(VALID_LABELS)}, a, s, q")

    print(f"\n[DONE] Reviewed {len(reviewed)} samples")
    return reviewed


def _batch_review(batch_path: Path) -> int:
    """Apply review labels from a JSONL batch file.

    Each line: {"sample_id": "...", "review_label": "...", "review_notes": "..."}
    """
    entries = load_jsonl(batch_path)
    if not entries:
        print(f"[ERROR] No entries in {batch_path}")
        return 0

    updated = 0
    for entry in entries:
        sid = entry.get("sample_id")
        label = entry.get("review_label")
        notes = entry.get("review_notes", "")

        if not sid or not label:
            continue
        if label not in VALID_LABELS:
            print(f"  [WARN] Invalid label '{label}' for {sid}, skipping")
            continue

        fpath = REPLAY_DIR / f"{sid}.json"
        sample = load_json(fpath)
        if not sample:
            print(f"  [WARN] Sample {sid} not found, skipping")
            continue

        sample["review_label"] = label
        sample["review_notes"] = notes
        sample["reviewed_at"] = utc_now().isoformat()
        sample["reviewed_by"] = "human_batch"
        write_json(fpath, sample)
        updated += 1

    print(f"[OK] Updated {updated} samples from batch file")
    return updated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Human review of feedback samples"
    )
    parser.add_argument(
        "--top", type=int, default=20,
        help="Number of samples to review (default: 20)"
    )
    parser.add_argument(
        "--type", type=str, default=None,
        choices=["misleading", "missed_stress", "false_positive", "needs_review"],
        help="Filter to specific review label type"
    )
    parser.add_argument(
        "--batch", type=str, default=None,
        help="Path to JSONL batch file with review labels to apply"
    )
    args = parser.parse_args()

    if args.batch:
        _batch_review(Path(args.batch))
        return

    # Load review queue
    if REVIEW_QUEUE_PATH.exists():
        queue = load_jsonl(REVIEW_QUEUE_PATH)
    else:
        # Fallback: scan replay directory
        queue = []
        for fpath in sorted(REPLAY_DIR.glob("*.json")):
            sample = load_json(fpath)
            if sample:
                queue.append(sample)

    if not queue:
        print("[ERROR] No samples to review")
        return

    # Filter by type
    if args.type:
        queue = [s for s in queue if s.get("review_label") == args.type]

    # Limit
    queue = queue[:args.top]

    print(f"[INFO] {len(queue)} samples to review")

    # Load full sample data for review
    full_samples = []
    for entry in queue:
        sid = entry.get("sample_id")
        if sid:
            fpath = REPLAY_DIR / f"{sid}.json"
            sample = load_json(fpath)
            if sample:
                full_samples.append(sample)

    if not full_samples:
        print("[ERROR] Could not load sample data")
        return

    _interactive_review(full_samples)


if __name__ == "__main__":
    main()
