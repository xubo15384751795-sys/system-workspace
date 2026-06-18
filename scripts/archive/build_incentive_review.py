#!/usr/bin/env python3
"""Build incentive review — observation report on explorations worth reviewing.

This script generates an OBSERVATION report, not an authority report.
Credit improves review priority, never grants authority.
Canonical entry requires code wiring + artifact contract + tests + data provenance.

Reads from experimental_submission_registry.yaml and incentive_policy.yaml.
Outputs:
  - Output/system_learning/latest/incentive_review.md
  - Output/system_learning/latest/incentive_review.json

Usage:
    python3 scripts/build_incentive_review.py
    python3 scripts/build_incentive_review.py --json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS_PATH = ROOT / "governance" / "experimental_submission_registry.yaml"
POLICY_PATH = ROOT / "governance" / "incentive_policy.yaml"
OUTPUT_PATH = ROOT / "Output" / "system_learning" / "latest" / "incentive_review.md"
OUTPUT_JSON = ROOT / "Output" / "system_learning" / "latest" / "incentive_review.json"

REQUIRED_SUBMISSION_FIELDS = [
    "submission_id", "submitted_by", "owner", "status",
    "current_priority", "rule_deviation", "affected_paths",
    "evidence_paths", "review_deadline", "reviewer",
    "decision", "decision_reason", "rollback_plan", "retire_after",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build incentive review observation report")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    submissions = yaml.safe_load(SUBMISSIONS_PATH.read_text(encoding="utf-8")).get("submissions", [])
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # ── Build observation report ──────────────────────────────────────────
    lines = [
        "# Incentive Review — Observation Report",
        "",
        f"**Generated:** {now}",
        "",
        "## Authority Boundary",
        "",
        "> Credit improves review priority, never grants authority.",
        "> Canonical entry requires: code wiring + artifact contract + tests + data provenance.",
        "",
    ]

    # Authority boundary from policy
    ab = policy.get("authority_boundary", {})
    if ab:
        lines += [
            "| Principle | Value |",
            "|-----------|-------|",
            f"| credit_never_grants_authority | {ab.get('credit_never_grants_authority', '—')} |",
            f"| governance_can_veto | {ab.get('governance_can_veto', '—')} |",
            f"| governance_can_grant_core_authority | {ab.get('governance_can_grant_core_authority', '—')} |",
            f"| canonical_authority_requires_runtime_wiring | {ab.get('canonical_authority_requires_runtime_wiring', '—')} |",
            "",
        ]

    # Priority levels
    lines += [
        "## Priority Levels",
        "",
        "| Level | Meaning | Can Enter Current | Can Affect Core |",
        "|-------|---------|-------------------|-----------------|",
    ]

    for level, info in policy.get("priority_levels", {}).items():
        cj = "✅" if info.get("can_affect_core_judgment") else "—"
        cc = "✅" if info.get("can_enter_authority_current", info.get("can_enter_current", False)) else "—"
        lines.append(f"| {level} | {info.get('meaning', '')[:50]} | {cc} | {cj} |")

    # Credit sources — now review signals
    lines += [
        "",
        "## Credit Sources (Review Signals)",
        "",
        "| Source | Review Weight | Rule | Suggests Review For |",
        "|--------|--------------|------|---------------------|",
    ]

    for source, info in policy.get("credit_sources", {}).items():
        lines.append(
            f"| {source} | {info.get('review_weight', 0)} "
            f"| {info.get('rule', '')[:50]} "
            f"| {info.get('suggests_review_for', '—')} |"
        )

    # Review candidates
    lines += [
        "",
        "## Review Candidates",
        "",
        "These explorations have earned review priority through credit signals.",
        "Review priority ≠ authority. None of these can enter core judgment without main chain wiring.",
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

    # Veto flags — things governance would block
    lines += [
        "",
        "## Veto Flags",
        "",
        "These patterns would be blocked by governance boundary rules:",
        "",
    ]

    veto_flags = []
    for sub in submissions:
        if sub.get("current_priority") == "low" and sub.get("decision") is None:
            veto_flags.append(f"Submission `{sub.get('submission_id', '—')}`: low priority, no decision — cannot affect core")
        if sub.get("status") == "submitted" and not sub.get("reviewer"):
            veto_flags.append(f"Submission `{sub.get('submission_id', '—')}`: no reviewer assigned")

    if veto_flags:
        for flag in veto_flags:
            lines.append(f"- ⚠️ {flag}")
    else:
        lines.append("No veto flags currently active.")

    # Missing runtime evidence
    lines += [
        "",
        "## Missing Runtime Evidence",
        "",
        "Explorations that lack evidence needed for integration consideration:",
        "",
    ]

    missing = []
    for sub in submissions:
        gaps = []
        for field in REQUIRED_SUBMISSION_FIELDS:
            if not sub.get(field):
                gaps.append(f"no {field}")
        if gaps:
            missing.append(f"- `{sub.get('submission_id', '—')}`: {', '.join(gaps)}")

    if missing:
        lines.extend(missing)
    else:
        lines.append("All submissions have complete metadata.")

    # Must remain research_only
    lines += [
        "",
        "## Must Remain Research Only",
        "",
        "These cannot enter authority current or affect core judgment:",
        "",
    ]

    research_only = [
        sub for sub in submissions
        if sub.get("current_priority") in ("low", None)
        or sub.get("decision") in ("keep_research_only", "reject", None)
    ]

    if research_only:
        for sub in research_only:
            lines.append(f"- `{sub.get('submission_id', '—')}`: {sub.get('decision', 'no decision yet')}")
    else:
        lines.append("No submissions currently restricted to research only.")

    # Integration recommendations
    lines += [
        "",
        "## Integration Recommendations",
        "",
        "These may be worth considering for main chain integration (manual wiring required):",
        "",
    ]

    integration_candidates = [
        sub for sub in submissions
        if sub.get("decision") == "accepted_for_manual_integration"
    ]

    if integration_candidates:
        for sub in integration_candidates:
            lines.append(
                f"- `{sub.get('submission_id', '—')}`: "
                f"accepted for manual integration — requires code wiring + tests + artifact contract"
            )
    else:
        lines.append("No submissions currently recommended for integration.")

    # Anti-gaming
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
        "*This is an OBSERVATION report, not an authority report.*",
        "*Credit improves review priority, never grants authority.*",
        "*Canonical entry requires code wiring + artifact contract + tests + data provenance.*",
        "",
        "*Generated by scripts/build_incentive_review.py*",
        "*Source: governance/incentive_policy.yaml, governance/experimental_submission_registry.yaml*",
    ]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {OUTPUT_PATH}")

    # ── JSON output (always written) ────────────────────────────────────
    result = {
        "timestamp": now,
        "authority_boundary": ab,
        "review_candidates": [
            {
                "id": sub.get("submission_id"),
                "submitted_by": sub.get("submitted_by"),
                "priority": sub.get("current_priority"),
                "decision": sub.get("decision"),
            }
            for sub in submissions
        ],
        "veto_flags": veto_flags,
        "missing_runtime_evidence": [
            {
                "id": sub.get("submission_id"),
                "gaps": [
                    field for field in REQUIRED_SUBMISSION_FIELDS
                    if not sub.get(field)
                ],
            }
            for sub in submissions
            if any(not sub.get(f) for f in REQUIRED_SUBMISSION_FIELDS)
        ],
        "must_remain_research_only": [
            sub.get("submission_id") for sub in research_only
        ],
        "manual_integration_required": [
            sub.get("submission_id") for sub in integration_candidates
        ],
        "note": (
            "This report provides review signals only. "
            "Credit never grants authority. "
            "Canonical entry requires code wiring + artifact contract + tests."
        ),
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote: {OUTPUT_JSON}")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
