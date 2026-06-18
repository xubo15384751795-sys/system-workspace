#!/usr/bin/env python3
"""Evaluate proxy lifecycle — suggest keep/watch/downgrade/retire.

Reads proxy quality scores and the lifecycle policy from
governance/proxy_quality_rules.yaml to suggest lifecycle transitions.

Usage:
    python3 scripts/evaluate_proxy_lifecycle.py
    python3 scripts/evaluate_proxy_lifecycle.py --json

Output:
    Output/system_learning/latest/proxy_lifecycle_report.json
    Output/system_learning/latest/proxy_lifecycle_report.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
from _runtime_io import ensure_dir, load_json, load_yaml, utc_now, write_json

QUALITY_REPORT = ROOT / "Output" / "system_learning" / "latest" / "proxy_quality_report.json"
POLICY_PATH = ROOT / "governance" / "proxy_quality_rules.yaml"
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"


def evaluate_proxy_lifecycle() -> dict[str, Any]:
    """Evaluate each proxy against lifecycle criteria."""
    policy = load_yaml(POLICY_PATH) or {}
    lifecycle = policy.get("lifecycle", {})

    quality_report = load_json(QUALITY_REPORT)
    if not quality_report:
        return {
            "schema_version": "proxy_lifecycle.v1",
            "generated_at": utc_now().isoformat(),
            "status": "no_quality_report",
            "proxies": [],
        }

    proxies = quality_report.get("proxies", [])
    results = []

    for proxy in proxies:
        name = proxy.get("name", "unknown")
        score = proxy.get("overall_score", 0)
        tier = proxy.get("tier", "unknown")
        samples = proxy.get("sample_count", 0)

        # Determine lifecycle recommendation
        recommendation = "keep"
        reasons = []

        # Retire conditions
        retire_triggers = lifecycle.get("retire", {}).get("triggers", [])
        if samples >= 100 and score < 0.3:
            recommendation = "retire"
            reasons.append(f"Low score ({score:.2f}) over {samples} samples")
        elif proxy.get("canonical_status") == "unknown":
            recommendation = "retire"
            reasons.append("canonical_status unknown")

        # Downgrade conditions
        if recommendation == "keep":
            downgrade_triggers = lifecycle.get("downgrade", {}).get("triggers", [])
            if samples >= 50 and score < 0.5:
                recommendation = "downgrade"
                reasons.append(f"Below threshold score ({score:.2f}) over {samples} samples")
            elif proxy.get("mechanism_conflict_rate", 0) > 0.4:
                recommendation = "downgrade"
                reasons.append(f"High mechanism conflict rate ({proxy.get('mechanism_conflict_rate', 0):.2f})")

        # Watch conditions
        if recommendation == "keep":
            if samples >= 30 and score < 0.6:
                recommendation = "watch"
                reasons.append(f"Borderline score ({score:.2f})")
            elif proxy.get("regime_inconsistency", False):
                recommendation = "watch"
                reasons.append("Inconsistent across regimes")

        results.append({
            "name": name,
            "current_tier": tier,
            "overall_score": score,
            "sample_count": samples,
            "recommendation": recommendation,
            "reasons": reasons,
        })

    return {
        "schema_version": "proxy_lifecycle.v1",
        "generated_at": utc_now().isoformat(),
        "status": "ok",
        "summary": {
            "total": len(results),
            "keep": sum(1 for r in results if r["recommendation"] == "keep"),
            "watch": sum(1 for r in results if r["recommendation"] == "watch"),
            "downgrade": sum(1 for r in results if r["recommendation"] == "downgrade"),
            "retire": sum(1 for r in results if r["recommendation"] == "retire"),
        },
        "proxies": results,
    }


def write_outputs(report: dict[str, Any]) -> Path:
    """Write lifecycle report."""
    ensure_dir(OUTPUT_DIR)

    json_path = OUTPUT_DIR / "proxy_lifecycle_report.json"
    write_json(json_path, report)

    md_path = OUTPUT_DIR / "proxy_lifecycle_report.md"
    lines = [
        "# Proxy Lifecycle Report",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Status:** {report['status']}",
        "",
    ]

    summary = report.get("summary", {})
    if summary:
        lines.append("## Summary")
        lines.append(f"- Keep: {summary.get('keep', 0)}")
        lines.append(f"- Watch: {summary.get('watch', 0)}")
        lines.append(f"- Downgrade: {summary.get('downgrade', 0)}")
        lines.append(f"- Retire: {summary.get('retire', 0)}")
        lines.append("")

    for proxy in report.get("proxies", []):
        icon = {"keep": "✅", "watch": "⚠️", "downgrade": "⬇️", "retire": "🗑️"}.get(proxy["recommendation"], "?")
        lines.append(f"## {icon} {proxy['name']}")
        lines.append(f"- Score: {proxy['overall_score']:.2f} | Samples: {proxy['sample_count']} | Tier: {proxy['current_tier']}")
        lines.append(f"- **Recommendation:** {proxy['recommendation']}")
        if proxy["reasons"]:
            for reason in proxy["reasons"]:
                lines.append(f"  - {reason}")
        lines.append("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = evaluate_proxy_lifecycle()
    write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        summary = report.get("summary", {})
        print(f"Proxy lifecycle: {report['status']}")
        print(f"  Keep: {summary.get('keep', 0)}")
        print(f"  Watch: {summary.get('watch', 0)}")
        print(f"  Downgrade: {summary.get('downgrade', 0)}")
        print(f"  Retire: {summary.get('retire', 0)}")


if __name__ == "__main__":
    main()
