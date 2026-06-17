#!/usr/bin/env python3
"""Build incentive review — which explorations were rewarded or promoted.

Reads from experimental_submission_registry.yaml and incentive_policy.yaml.
Outputs: Output/system_learning/latest/incentive_review.md

Usage:
    python3 scripts/build_incentive_review.py
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS_PATH = ROOT / "governance" / "experimental_submission_registry.yaml"
POLICY_PATH = ROOT / "governance" / "incentive_policy.yaml"
OUTPUT_PATH = ROOT / "Output" / "system_learning" / "latest" / "incentive_review.md"


def main() -> None:
    submissions = yaml.safe_load(SUBMISSIONS_PATH.read_text(encoding="utf-8")).get("submissions", [])
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Incentive Review",
        "",
        f"**Generated:** {now}",
        "",
        "## Core Principle",
        "",
        f"> {policy.get('core_principle', '').strip()}",
        "",
        "## Priority Levels",
        "",
        "| Level | Meaning | Can Enter Current | Can Affect Core |",
        "|-------|---------|-------------------|-----------------|",
    ]

    for level, info in policy.get("priority_levels", {}).items():
        cj = "✅" if info.get("can_affect_core_judgment") else "—"
        cc = "✅" if info.get("can_enter_current") else "—"
        lines.append(f"| {level} | {info.get('meaning', '')[:50]} | {cc} | {cj} |")

    lines += [
        "",
        "## Credit Sources",
        "",
        "| Source | Points | Rule | Promotes To |",
        "|--------|--------|------|-------------|",
    ]

    for source, info in policy.get("credit_sources", {}).items():
        lines.append(f"| {source} | {info.get('points', 0)} | {info.get('rule', '')[:50]} | {info.get('promotes_to', '—')} |")

    lines += [
        "",
        "## Experimental Submissions",
        "",
    ]

    if not submissions:
        lines.append("No submissions yet.")
    else:
        lines.append("| ID | Submitted By | Status | Priority | Decision |")
        lines.append("|----|-------------|--------|----------|----------|")
        for sub in submissions:
            lines.append(
                f"| {sub.get('submission_id', '—')} "
                f"| {sub.get('submitted_by', '—')} "
                f"| {sub.get('status', '—')} "
                f"| {sub.get('current_priority', '—')} "
                f"| {sub.get('decision', 'pending')} |"
            )

    lines += [
        "",
        "## Anti-Gaming Rules",
        "",
        "Rewarded:",
    ]
    for item in policy.get("anti_gaming", {}).get("rewarded", []):
        lines.append(f"- ✅ {item}")

    lines += ["", "Not rewarded:"]
    for item in policy.get("anti_gaming", {}).get("not_rewarded", []):
        lines.append(f"- ❌ {item}")

    lines += [
        "",
        "---",
        "",
        "*This document is auto-generated from governance/incentive_policy.yaml "
        "and governance/experimental_submission_registry.yaml.*",
    ]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
