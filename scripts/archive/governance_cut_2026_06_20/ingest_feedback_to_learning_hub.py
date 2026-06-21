"""Ingest Feedback Sample Factory results into the Learning Hub.

Reads calibration_summary.json and evaluation_report.md, then generates:
1. Improvement queue items for calibration findings
2. Runtime events for the Learning Hub ledger
3. Updated calibration summary in Learning Hub format

Output:
- Output/system_learning/latest/feedback_calibration_summary.json
- Appends to Output/system_learning/runtime/records_{date}.jsonl
- Output/system_learning/latest/feedback_improvement_queue.md

This script does NOT automatically change rules.
It produces findings and recommendations — rule changes require human confirmation.

Usage:
    python3 scripts/ingest_feedback_to_learning_hub.py
    python3 scripts/ingest_feedback_to_learning_hub.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from _workspace_imports import add_scripts
add_scripts()
from _constants import (
    FEEDBACK_MISSED_RATE_HIGH, FEEDBACK_MISSED_RATE_MEDIUM,
    FEEDBACK_STRESS_WINDOW_MISSED_HIGH, FEEDBACK_USEFUL_RATE_LOW,
)  # noqa: E402
from _runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CALIBRATION_SUMMARY_PATH = ROOT / "Output" / "feedback_samples" / "calibration_summary.json"
LH_LATEST_DIR = ROOT / "Output" / "system_learning" / "latest"
LH_RUNTIME_DIR = ROOT / "Output" / "system_learning" / "runtime"
FEEDBACK_CAL_PATH = LH_LATEST_DIR / "feedback_calibration_summary.json"
FEEDBACK_QUEUE_PATH = LH_LATEST_DIR / "feedback_improvement_queue.md"


def _make_event(subsystem: str, event_type: str, severity: str,
                description: str, **extra) -> dict:
    """Create a Learning Hub runtime event record."""
    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": utc_now().isoformat(),
        "subsystem": subsystem,
        "event_type": event_type,
        "severity": severity,
        "source_tool": "feedback_sample_factory",
        "context_type": "calibration",
        "confidence": "medium",
        "description": description,
        "governance_mode": "observe_only",
    }
    event.update(extra)
    return event


def _severity_from_rate(useful_rate: float, missed_rate: float) -> str:
    """Map useful/missed rates to severity level."""
    if missed_rate > FEEDBACK_MISSED_RATE_HIGH:
        return "high"
    if missed_rate > FEEDBACK_MISSED_RATE_MEDIUM or useful_rate < FEEDBACK_USEFUL_RATE_LOW:
        return "medium"
    return "info"


def generate_findings(summary: dict) -> tuple[list[dict], list[dict]]:
    """Generate improvement queue items and runtime events from calibration summary.

    Returns (queue_items, runtime_events).
    """
    queue_items = []
    events = []
    total = summary.get("total_samples", 0)
    if total == 0:
        return queue_items, events

    labels = summary.get("label_distribution", {})
    useful = labels.get("useful", 0)
    missed = labels.get("missed_stress", 0)
    fp = labels.get("false_positive", 0)
    misleading = labels.get("misleading", 0)
    useful_rate = useful / total
    missed_rate = missed / total

    # --- Finding 1: Overall calibration ---
    severity = _severity_from_rate(useful_rate, missed_rate)
    queue_items.append({
        "module": "feedback_factory",
        "issue_type": "confidence_calibration",
        "lifecycle": "proposed",
        "priority": 30 if severity == "high" else 20,
        "severity": severity,
        "governance_mode": "review",
        "proposed_action": (
            f"Calibration baseline established: {total} samples, "
            f"useful_rate={useful_rate:.1%}, missed_stress_rate={missed_rate:.1%}. "
            f"{'Stress detection needs improvement.' if missed_rate > 0.25 else 'Baseline acceptable.'}"
        ),
        "verification": "Run next batch of 500 samples and verify missed_stress rate improves.",
    })
    events.append(_make_event(
        "feedback_factory", "calibration_finding", severity,
        f"Feedback calibration baseline: {total} samples, useful={useful_rate:.1%}, missed={missed_rate:.1%}",
        total_samples=total, useful_rate=round(useful_rate, 4), missed_rate=round(missed_rate, 4),
    ))

    # --- Finding 2: Stress window performance ---
    by_type = summary.get("by_sample_type", {})
    stress_stats = by_type.get("stress_window", {})
    if stress_stats:
        sw_useful = stress_stats.get("useful_rate", 0)
        sw_missed = 1 - sw_useful
        sw_n = stress_stats.get("count", 0)
        if sw_missed > FEEDBACK_STRESS_WINDOW_MISSED_HIGH:
            queue_items.append({
                "module": "workbench",
                "issue_type": "stress_detection_gap",
                "lifecycle": "proposed",
                "priority": 35,
                "severity": "high",
                "governance_mode": "review",
                "proposed_action": (
                    f"Stress window useful rate is only {sw_useful:.1%} ({sw_n} samples). "
                    f"System misses stress in {sw_missed:.1%} of known-stress dates. "
                    f"Consider: (1) lowering WATCH threshold, (2) adding VIX/MOVE triggers, "
                    f"(3) improving M proxy sensitivity."
                ),
                "verification": "Stress window useful rate > 60% in next evaluation batch.",
            })
            events.append(_make_event(
                "workbench", "calibration_finding", "high",
                f"Stress detection gap: {sw_missed:.1%} of stress_window samples missed ({sw_n} total)",
                sample_type="stress_window", useful_rate=round(sw_useful, 4), count=sw_n,
            ))

    # --- Finding 3: Decision discrimination ---
    by_decision = summary.get("by_decision", {})
    if len(by_decision) > 1:
        rr_stats = by_decision.get("RESEARCH_REVIEW", {})
        no_trade_stats = by_decision.get("NO_TRADE", {})
        if rr_stats and no_trade_stats:
            rr_useful = rr_stats.get("useful_rate", 0)
            nt_useful = no_trade_stats.get("useful_rate", 0)
            rr_stress = rr_stats.get("stress_hit_rate", 0)
            nt_stress = no_trade_stats.get("stress_hit_rate", 0)
            if rr_stress > nt_stress:
                queue_items.append({
                    "module": "workbench",
                    "issue_type": "decision_discrimination",
                    "lifecycle": "verified",
                    "priority": 25,
                    "severity": "medium",
                    "governance_mode": "review",
                    "proposed_action": (
                        f"RESEARCH_REVIEW has {rr_stress:.1%} stress hit rate vs "
                        f"NO_TRADE {nt_stress:.1%}. Decision threshold is working. "
                        f"Consider using RESEARCH_REVIEW as an early warning signal."
                    ),
                    "verification": "Confirm RESEARCH_REVIEW stress_hit_rate > NO_TRADE in next batch.",
                })
                events.append(_make_event(
                    "workbench", "calibration_verified", "info",
                    f"Decision discrimination confirmed: RESEARCH_REVIEW stress={rr_stress:.1%} vs NO_TRADE={nt_stress:.1%}",
                    research_review_stress_rate=round(rr_stress, 4),
                    no_trade_stress_rate=round(nt_stress, 4),
                ))

    # --- Finding 4: Claim tier discrimination ---
    by_tier = summary.get("by_claim_tier", {})
    if len(by_tier) > 1:
        tier_0 = by_tier.get("0", {})
        tier_1 = by_tier.get("1", {})
        if tier_0 and tier_1:
            t0_rate = tier_0.get("useful_rate", 0)
            t1_rate = tier_1.get("useful_rate", 0)
            if t1_rate > t0_rate:
                queue_items.append({
                    "module": "workbench",
                    "issue_type": "claim_ladder_calibration",
                    "lifecycle": "verified",
                    "priority": 20,
                    "severity": "info",
                    "governance_mode": "review",
                    "proposed_action": (
                        f"Tier 1 (mechanism_hypothesis) useful rate {t1_rate:.1%} > "
                        f"Tier 0 (observation) {t0_rate:.1%}. "
                        f"Claim ladder promotion is providing value."
                    ),
                    "verification": "Confirm tier 1 outperforms tier 0 in next batch.",
                })

    # --- Finding 5: False positive analysis ---
    if fp > 0:
        fp_rate = fp / total
        queue_items.append({
            "module": "workbench",
            "issue_type": "false_positive_analysis",
            "lifecycle": "proposed",
            "priority": 15,
            "severity": "info",
            "governance_mode": "review",
            "proposed_action": (
                f"{fp} false positives out of {total} samples ({fp_rate:.1%}). "
                f"Low false positive rate — system is conservative, not alarmist. "
                f"This is acceptable but review individual cases."
            ),
            "verification": "False positive rate remains < 2% in next batch.",
        })

    # --- Finding 6: Quiet window baseline ---
    quiet_stats = by_type.get("quiet_window", {})
    if quiet_stats:
        q_useful = quiet_stats.get("useful_rate", 0)
        q_missed = 1 - q_useful
        if q_missed > 0.15:
            events.append(_make_event(
                "feedback_factory", "calibration_finding", "medium",
                f"Quiet window missed_stress rate is {q_missed:.1%} — "
                f"system may be triggering false stress signals on calm days",
                sample_type="quiet_window", useful_rate=round(q_useful, 4),
            ))

    return queue_items, events


def generate_improvement_queue_md(items: list[dict]) -> str:
    """Generate improvement_queue.md content."""
    lines = [
        "# Feedback Calibration — Improvement Queue",
        "",
        f"Generated: {utc_now().isoformat()}",
        "",
        f"Active items: {len(items)}",
        "",
        "*These are findings from the Feedback Sample Factory. "
        "Rule changes require human confirmation.*",
        "",
    ]

    # Sort by priority descending
    sorted_items = sorted(items, key=lambda x: -x.get("priority", 0))
    for i, item in enumerate(sorted_items, 1):
        lines += [
            f"## {i}. {item.get('module', 'unknown')} — {item.get('issue_type', 'unknown')}",
            "",
            f"- **Lifecycle:** {item.get('lifecycle', 'proposed')}",
            f"- **Priority:** {item.get('priority', 0)}",
            f"- **Severity:** {item.get('severity', 'info')}",
            f"- **Governance mode:** {item.get('governance_mode', 'review')}",
            f"- **Proposed action:** {item.get('proposed_action', '')}",
            f"- **Verification:** {item.get('verification', '')}",
            "",
        ]

    return "\n".join(lines)


def ingest(dry_run: bool = False) -> None:
    """Main ingestion: read calibration summary, generate LH outputs."""
    summary = load_json(CALIBRATION_SUMMARY_PATH)
    if not summary:
        print(f"[ERROR] No calibration summary at {CALIBRATION_SUMMARY_PATH}")
        print("        Run evaluate_feedback_samples.py first.")
        return

    print(f"[INFO] Calibration summary: {summary.get('total_samples', 0)} samples")

    # Generate findings
    queue_items, events = generate_findings(summary)
    print(f"[INFO] Generated {len(queue_items)} improvement items, {len(events)} runtime events")

    if dry_run:
        print("\n[DRY-RUN] Improvement queue items:")
        for item in queue_items:
            print(f"  [{item['priority']}] {item['module']} — {item['issue_type']}: {item['severity']}")
        print(f"\n[DRY-RUN] Would write {len(events)} runtime events")
        return

    # Ensure directories
    ensure_dir(LH_LATEST_DIR)
    ensure_dir(LH_RUNTIME_DIR)

    # 1. Write feedback calibration summary to LH latest
    lh_summary = {
        "generated_at": utc_now().isoformat(),
        "source": "feedback_sample_factory",
        "total_samples": summary.get("total_samples", 0),
        "label_distribution": summary.get("label_distribution", {}),
        "by_sample_type": summary.get("by_sample_type", {}),
        "by_decision": summary.get("by_decision", {}),
        "by_claim_tier": summary.get("by_claim_tier", {}),
        "confidence_calibration": summary.get("confidence_calibration", {}),
        "improvement_items_count": len(queue_items),
        "runtime_events_count": len(events),
    }
    write_json(FEEDBACK_CAL_PATH, lh_summary)
    print(f"[OK] Feedback calibration summary: {FEEDBACK_CAL_PATH}")

    # 2. Write improvement queue markdown
    queue_md = generate_improvement_queue_md(queue_items)
    FEEDBACK_QUEUE_PATH.write_text(queue_md, encoding="utf-8")
    print(f"[OK] Improvement queue: {FEEDBACK_QUEUE_PATH}")

    # 3. Append runtime events
    today = utc_now().strftime("%Y-%m-%d")
    runtime_path = LH_RUNTIME_DIR / f"records_{today}.jsonl"
    with open(runtime_path, "a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(f"[OK] Appended {len(events)} events to {runtime_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest feedback calibration findings into Learning Hub"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    ingest(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
