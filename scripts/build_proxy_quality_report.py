#!/usr/bin/env python3
"""Build proxy quality report from registry metadata and governance rules.

Lightweight replacement for archived proxy_quality_scorer.py.  Reads
ProxySpec metadata from structural_replay_v2.py via AST (no import side
effects) and scores each proxy against governance/proxy_quality_rules.yaml.

Outputs:
    Output/system_learning/latest/proxy_quality_report.json
    Output/system_learning/latest/proxy_quality_report.md

Usage:
    python3 scripts/build_proxy_quality_report.py
    python3 scripts/build_proxy_quality_report.py --json
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _runtime_io import ROOT, ensure_dir, load_yaml, utc_now, write_json

RULES_PATH = ROOT / "governance" / "proxy_quality_rules.yaml"
REGISTRY_PATH = ROOT / "scripts" / "structural_replay_v2.py"
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"

NOT_IMPLEMENTED_FAMILY = "NOT_IMPLEMENTED"


def _extract_registry_metadata() -> list[dict[str, Any]]:
    """Parse PROXY_REGISTRY from structural_replay_v2.py via AST.

    Returns list of dicts with metadata fields only (no builder callable).
    """
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(REGISTRY_PATH))

    # Find the PROXY_REGISTRY assignment (plain or annotated)
    registry_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PROXY_REGISTRY":
                    registry_node = node.value
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "PROXY_REGISTRY":
                registry_node = node.value
                break
    if registry_node is None:
        return []

    proxies = []
    # Each element is a Call to ProxySpec(...)
    for item in ast.walk(registry_node):
        if not isinstance(item, ast.Call):
            continue
        # Check if it's a ProxySpec call
        func_name = ""
        if isinstance(item.func, ast.Name):
            func_name = item.func.id
        elif isinstance(item.func, ast.Attribute):
            func_name = item.func.attr
        if func_name != "ProxySpec":
            continue

        proxy: dict[str, Any] = {}
        for kw in item.keywords:
            if kw.arg in ("name", "target_variable", "tier", "freq",
                          "raw_family", "mechanism", "transform",
                          "canonical_status", "canonical_subbasket",
                          "independence_group", "note"):
                if isinstance(kw.value, ast.Constant):
                    proxy[kw.arg] = kw.value.value
                elif isinstance(kw.value, ast.Attribute):
                    proxy[kw.arg] = kw.value.attr
            elif kw.arg == "raw_series":
                if isinstance(kw.value, ast.Tuple):
                    proxy["raw_series"] = [
                        elt.value for elt in kw.value.elts
                        if isinstance(elt, ast.Constant)
                    ]

        # Extract positional args for name and target_variable if not in kwargs
        # ProxySpec(name, target_variable, tier, freq, raw_series, raw_family, mechanism, transform, builder)
        pos_fields = ["name", "target_variable", "tier", "freq", "raw_series",
                      "raw_family", "mechanism", "transform"]
        for i, arg in enumerate(item.args):
            if i < len(pos_fields) and pos_fields[i] not in proxy:
                if isinstance(arg, ast.Constant):
                    proxy[pos_fields[i]] = arg.value
                elif isinstance(arg, ast.Attribute):
                    proxy[pos_fields[i]] = arg.attr
                elif isinstance(arg, ast.Tuple) and pos_fields[i] == "raw_series":
                    proxy["raw_series"] = [
                        elt.value for elt in arg.elts
                        if isinstance(elt, ast.Constant)
                    ]

        if proxy.get("name"):
            proxies.append(proxy)

    return proxies


def _decide_tier(
    rules: dict,
    *,
    canonical_status: str,
    raw_family: str,
    frequency_fit: str,
    mechanism_clarity: str,
    channel_family_count: int,
) -> tuple[str, str]:
    """Apply quality tier decision table from rules."""
    tiers = rules.get("quality_tiers", [])
    for tier_def in tiers:
        tier_name = tier_def["tier"]
        reason = tier_def.get("reason", "")

        # Check canonical_status condition
        if "when_canonical_status_in" in tier_def:
            if canonical_status not in tier_def["when_canonical_status_in"]:
                continue

        # Check family condition
        if "when_family_equals" in tier_def:
            if raw_family != tier_def["when_family_equals"]:
                continue

        # Check requirements
        req = tier_def.get("require", {})
        if req:
            if req.get("frequency_fit") and frequency_fit != req["frequency_fit"]:
                continue
            if req.get("mechanism_clarity") and mechanism_clarity != req["mechanism_clarity"]:
                continue
            if req.get("min_channel_family_count") and channel_family_count < req["min_channel_family_count"]:
                continue

        req_any = tier_def.get("require_any_frequency_fit")
        if req_any and frequency_fit not in req_any:
            continue

        return tier_name, reason

    return "REJECTED", "unevaluated_or_unmatched"


def _score_to_float(tier: str) -> float:
    """Convert quality tier to numeric score for lifecycle evaluation."""
    return {
        "CORE_ELIGIBLE": 1.0,
        "CONSTRUCT_SUPPORT": 0.75,
        "DIAGNOSTIC_ONLY": 0.5,
        "BACKGROUND_ONLY": 0.25,
        "REJECTED": 0.0,
    }.get(tier, 0.0)


def build_report() -> dict[str, Any]:
    """Build the full proxy quality report."""
    rules = load_yaml(RULES_PATH) or {}
    criteria = rules.get("criteria", {})
    status_map = criteria.get("semantic_distance", {}).get("from_canonical_status", {})
    freq_map = criteria.get("frequency_fit", {}).get("from_freq", {})

    proxies_meta = _extract_registry_metadata()

    # Count distinct voting-eligible families per channel
    voting_statuses = {"canonical_voting", "canonical_primary"}
    channel_families: dict[str, set[str]] = defaultdict(set)
    for p in proxies_meta:
        if p.get("canonical_status") in voting_statuses and p.get("raw_family", "") != NOT_IMPLEMENTED_FAMILY:
            channel_families[p.get("target_variable", "?")].add(p.get("raw_family", ""))
    channel_family_counts = {ch: len(fams) for ch, fams in channel_families.items()}

    results = []
    for p in proxies_meta:
        name = p.get("name", "unknown")
        canonical_status = p.get("canonical_status", "unevaluated")
        raw_family = p.get("raw_family", "")
        freq = p.get("freq", "unknown")
        mechanism = p.get("mechanism", "")
        target_var = p.get("target_variable", "?")

        # Semantic distance
        semantic_distance = status_map.get(canonical_status, 3)

        # Frequency fit
        freq_class = freq_map.get(freq, "background")
        frequency_fit = {"full": "full", "conditional": "conditional"}.get(freq_class, "background")

        # Family diversity
        fam_count = channel_family_counts.get(target_var, 0)

        # Mechanism clarity
        has_mechanism = bool(mechanism.strip()) if isinstance(mechanism, str) else False
        has_subbasket = bool(p.get("canonical_subbasket", "").strip())
        if has_mechanism and has_subbasket:
            mechanism_clarity = "full"
        elif has_mechanism:
            mechanism_clarity = "partial"
        else:
            mechanism_clarity = "none"

        # Decide tier
        quality_tier, tier_reason = _decide_tier(
            rules,
            canonical_status=canonical_status,
            raw_family=raw_family,
            frequency_fit=frequency_fit,
            mechanism_clarity=mechanism_clarity,
            channel_family_count=fam_count,
        )

        results.append({
            "name": name,
            "channel": target_var,
            "canonical_status": canonical_status,
            "quality_tier": quality_tier,
            "overall_score": _score_to_float(quality_tier),
            "tier": quality_tier,
            "tier_reason": tier_reason,
            "sample_count": 0,  # Requires empirical data; not fabricated
            "mechanism_conflict_rate": 0.0,  # Requires empirical data
            "regime_inconsistency": False,  # Requires empirical data
            "semantic_distance": semantic_distance,
            "frequency_fit": frequency_fit,
            "mechanism_clarity": mechanism_clarity,
            "channel_family_count": fam_count,
        })

    summary = {
        "total": len(results),
        "core_eligible": sum(1 for r in results if r["quality_tier"] == "CORE_ELIGIBLE"),
        "construct_support": sum(1 for r in results if r["quality_tier"] == "CONSTRUCT_SUPPORT"),
        "diagnostic_only": sum(1 for r in results if r["quality_tier"] == "DIAGNOSTIC_ONLY"),
        "background_only": sum(1 for r in results if r["quality_tier"] == "BACKGROUND_ONLY"),
        "rejected": sum(1 for r in results if r["quality_tier"] == "REJECTED"),
    }

    return {
        "schema_version": "proxy_quality_report.v1",
        "generated_at": utc_now().isoformat(),
        "status": "ok",
        "summary": summary,
        "proxies": results,
    }


def write_outputs(report: dict[str, Any]) -> Path:
    """Write quality report JSON and markdown."""
    ensure_dir(OUTPUT_DIR)

    json_path = OUTPUT_DIR / "proxy_quality_report.json"
    write_json(json_path, report)

    md_path = OUTPUT_DIR / "proxy_quality_report.md"
    lines = [
        "# Proxy Quality Report",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Status:** {report['status']}",
        "",
    ]

    summary = report.get("summary", {})
    lines.append("## Summary")
    lines.append(f"- Total: {summary.get('total', 0)}")
    lines.append(f"- CORE_ELIGIBLE: {summary.get('core_eligible', 0)}")
    lines.append(f"- CONSTRUCT_SUPPORT: {summary.get('construct_support', 0)}")
    lines.append(f"- DIAGNOSTIC_ONLY: {summary.get('diagnostic_only', 0)}")
    lines.append(f"- BACKGROUND_ONLY: {summary.get('background_only', 0)}")
    lines.append(f"- REJECTED: {summary.get('rejected', 0)}")
    lines.append("")

    for proxy in report.get("proxies", []):
        icon = {
            "CORE_ELIGIBLE": "✅",
            "CONSTRUCT_SUPPORT": "🔵",
            "DIAGNOSTIC_ONLY": "🟡",
            "BACKGROUND_ONLY": "⚪",
            "REJECTED": "❌",
        }.get(proxy["quality_tier"], "?")
        lines.append(f"### {icon} {proxy['name']}")
        lines.append(f"- Channel: {proxy['channel']} | Status: {proxy['canonical_status']}")
        lines.append(f"- Tier: {proxy['quality_tier']} ({proxy['tier_reason']})")
        lines.append(f"- Semantic distance: {proxy['semantic_distance']} | Frequency: {proxy['frequency_fit']}")
        lines.append("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = build_report()
    json_path = write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        summary = report.get("summary", {})
        print(f"Proxy quality report: {json_path}")
        print(f"  Total: {summary.get('total', 0)}")
        print(f"  CORE_ELIGIBLE: {summary.get('core_eligible', 0)}")
        print(f"  REJECTED: {summary.get('rejected', 0)}")


if __name__ == "__main__":
    main()
