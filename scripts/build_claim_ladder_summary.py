#!/usr/bin/env python3
"""Build Claim Ladder Summary — long-term mechanism hypothesis tracking.

Reads all run bundles' feedback_pending.json files and the current
claim_ladder progression to produce a Learning Hub summary:
- Which mechanism hypotheses have persisted
- Which have been invalidated
- Which are stuck at weak (tier 0/1 with no progression)

Usage:
    python3 scripts/build_claim_ladder_summary.py
    python3 scripts/build_claim_ladder_summary.py --json

Output:
    Output/system_learning/latest/claim_ladder_summary.json
    Output/system_learning/latest/claim_ladder_summary.md
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "Output" / "runs"
PROGRESSION_PATH = ROOT / "Output" / "claim_ladder" / "progression.json"
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def scan_all_run_claims() -> list[dict[str, Any]]:
    """Scan all run bundles for claim ladder items in feedback_pending."""
    if not RUNS_DIR.exists():
        return []

    all_claims = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        pending_path = run_dir / "feedback_pending.json"
        if not pending_path.exists():
            continue
        try:
            items = json.loads(pending_path.read_text(encoding="utf-8"))
            for item in items:
                if item.get("source") == "claim_ladder" and item.get("metadata"):
                    all_claims.append({
                        "run_id": run_dir.name,
                        "added_at": item.get("added_at", ""),
                        **item["metadata"],
                    })
        except Exception:
            continue

    return all_claims


def classify_claims(
    all_claims: list[dict[str, Any]],
    progression: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Classify claims into persisted, invalidated, and stuck."""
    persisted = []
    invalidated = []
    stuck = []
    tracking = []

    # Build progression lookup
    prog_claims = {}
    if progression and progression.get("claims"):
        for pc in progression["claims"]:
            key = pc["previous_run_claim"].get("mechanism_hypothesis", "")[:80]
            prog_claims[key] = pc

    # Deduplicate by mechanism_hypothesis (keep latest)
    seen: dict[str, dict] = {}
    for claim in all_claims:
        key = claim.get("mechanism_hypothesis", "")[:80]
        if key:
            seen[key] = claim

    for key, claim in seen.items():
        tier = claim.get("claim_tier", 0)
        label = claim.get("claim_label", "")

        # Check progression status
        prog = prog_claims.get(key)
        if prog:
            status = prog.get("overall_status", "tracking")
            if status == "invalidated":
                invalidated.append({**claim, "progression_status": status})
            elif status == "progressing":
                persisted.append({**claim, "progression_status": status})
            elif status in ("reversed", "conflict"):
                invalidated.append({**claim, "progression_status": status})
            else:
                tracking.append({**claim, "progression_status": status})
        elif tier <= 1:
            stuck.append({**claim, "progression_status": "no_progression"})
        else:
            tracking.append({**claim, "progression_status": "untracked"})

    return {
        "persisted": persisted,
        "invalidated": invalidated,
        "stuck": stuck,
        "tracking": tracking,
    }


def build_summary() -> dict[str, Any]:
    """Build the full claim ladder summary."""
    now = datetime.now(UTC)
    all_claims = scan_all_run_claims()
    progression = load_json(PROGRESSION_PATH)
    classified = classify_claims(all_claims, progression)

    return {
        "schema_version": "claim_ladder_summary.v1",
        "generated_at": now.isoformat(),
        "total_claims_tracked": len(all_claims),
        "unique_hypotheses": len(set(
            c.get("mechanism_hypothesis", "")[:80] for c in all_claims if c.get("mechanism_hypothesis")
        )),
        "persisted": classified["persisted"],
        "invalidated": classified["invalidated"],
        "stuck_at_weak": classified["stuck"],
        "still_tracking": classified["tracking"],
    }


def format_markdown(summary: dict[str, Any]) -> str:
    """Format summary as markdown."""
    lines = [
        "# Claim Ladder Summary",
        "",
        f"**Generated:** {summary['generated_at']}",
        f"**Total claims tracked:** {summary['total_claims_tracked']}",
        f"**Unique hypotheses:** {summary['unique_hypotheses']}",
        "",
    ]

    # Persisted
    lines += ["## Persisted Hypotheses", ""]
    if summary["persisted"]:
        for c in summary["persisted"]:
            lines.append(f"- **Tier {c.get('claim_tier', '?')}** ({c.get('claim_label', '?')}): "
                        f"{c.get('mechanism_hypothesis', '')[:100]}")
            lines.append(f"  - Status: {c.get('progression_status', '?')}")
    else:
        lines.append("*None yet — insufficient run history for persistence confirmation.*")
    lines.append("")

    # Invalidated
    lines += ["## Invalidated Hypotheses", ""]
    if summary["invalidated"]:
        for c in summary["invalidated"]:
            lines.append(f"- **Tier {c.get('claim_tier', '?')}** ({c.get('claim_label', '?')}): "
                        f"{c.get('mechanism_hypothesis', '')[:100]}")
            lines.append(f"  - Reason: {c.get('progression_status', '?')}")
    else:
        lines.append("*None — no hypotheses have been explicitly invalidated.*")
    lines.append("")

    # Stuck at weak
    lines += ["## Stuck at Weak (Tier 0-1, No Progression)", ""]
    if summary["stuck_at_weak"]:
        for c in summary["stuck_at_weak"]:
            lines.append(f"- **Tier {c.get('claim_tier', '?')}** ({c.get('claim_label', '?')}): "
                        f"{c.get('mechanism_hypothesis', '')[:100]}")
    else:
        lines.append("*None — all claims have progression signals.*")
    lines.append("")

    # Still tracking
    lines += ["## Still Tracking", ""]
    if summary["still_tracking"]:
        for c in summary["still_tracking"]:
            lines.append(f"- **Tier {c.get('claim_tier', '?')}** ({c.get('claim_label', '?')}): "
                        f"{c.get('mechanism_hypothesis', '')[:100]}")
    else:
        lines.append("*None.*")
    lines.append("")

    lines += [
        "---",
        "",
        "*This summary aggregates claim ladder data across all runs.*",
        "*It does NOT modify current judgments.*",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(summary: dict[str, Any]) -> dict[str, Path]:
    """Write claim ladder summary."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "claim_ladder_summary.json"
    md_path = OUTPUT_DIR / "claim_ladder_summary.md"

    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(summary), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build claim ladder summary.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    summary = build_summary()
    paths = write_outputs(summary)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"Claim ladder summary: {paths['markdown']}")
        print(f"Total claims: {summary['total_claims_tracked']}")
        print(f"Persisted: {len(summary['persisted'])}")
        print(f"Invalidated: {len(summary['invalidated'])}")
        print(f"Stuck at weak: {len(summary['stuck_at_weak'])}")


if __name__ == "__main__":
    main()
