#!/usr/bin/env python3
"""Proxy Quality Scorer — measurement-grade gate over the canonical proxy registry.

Scores every wired proxy (scripts/structural_replay_v2.py :: PROXY_REGISTRY)
against governance/proxy_quality_rules.yaml and decides whether it is allowed to
vote into a canonical M/D/K/X construct. Implements the principle:

    high-quality proxies only — stop stuffing low-quality proxies into core.

The scorer is pure: it reads registry metadata (no network, no panel data).
Criteria that need price/return history are reported as `pending_empirical`,
never fabricated.

Outputs:
    Output/measurement/proxy_quality_scores.csv   — one row per proxy
    Output/measurement/proxy_quality_gate.json    — machine-readable gate
    Output/measurement/PROXY_QUALITY_REPORT.md    — human report

Usage:
    python3 scripts/proxy_quality_scorer.py
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RULES_PATH = ROOT / "governance" / "proxy_quality_rules.yaml"
OUT_DIR = ROOT / "Output" / "measurement"

from _workspace_imports import add_scripts
add_scripts()

# Registry imports are side-effect free (verified): they only construct dataclasses.
import structural_replay_v2 as srv2  # noqa: E402
import compute_proxies as legacy  # noqa: E402

NOT_IMPLEMENTED_FAMILY = "NOT_IMPLEMENTED"


def load_rules() -> dict:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def channel_family_counts(registry) -> dict[str, int]:
    """Distinct voting-eligible source families per target_variable."""
    voting = {"canonical_voting", "canonical_primary"}
    families: dict[str, set[str]] = defaultdict(set)
    for p in registry:
        if p.canonical_status in voting and p.raw_family != NOT_IMPLEMENTED_FAMILY:
            families[p.target_variable].add(p.raw_family)
    return {ch: len(fams) for ch, fams in families.items()}


def score_proxy(p, rules: dict, channel_family_count: int) -> dict:
    crit = rules["criteria"]

    semantic_distance = crit["semantic_distance"]["from_canonical_status"].get(
        p.canonical_status, 3
    )

    freq_class = crit["frequency_fit"]["from_freq"].get(p.freq, "background")
    frequency_fit = {"full": "full", "conditional": "conditional"}.get(
        freq_class, "background"
    )

    if channel_family_count >= 3:
        family_band = "high"
    elif channel_family_count == 2:
        family_band = "medium"
    else:
        family_band = "low"

    has_mechanism = bool(p.mechanism.strip())
    has_subbasket = bool(p.canonical_subbasket.strip())
    if has_mechanism and has_subbasket:
        mechanism_clarity = "full"
    elif has_mechanism:
        mechanism_clarity = "partial"
    else:
        mechanism_clarity = "none"

    has_series = len(p.raw_series) > 0
    has_real_family = p.raw_family not in ("", NOT_IMPLEMENTED_FAMILY)
    has_transform = bool(p.transform.strip())
    if has_series and has_real_family and has_transform:
        lineage = "full"
    elif has_series:
        lineage = "partial"
    else:
        lineage = "none"

    # Coarse data-availability flag (regime-coverage proper is pending_empirical).
    if p.canonical_status == "awaiting_data" or p.raw_family == NOT_IMPLEMENTED_FAMILY:
        data_availability = "no_data"
    else:
        data_availability = "data_present"

    tier, reason = decide_tier(
        rules,
        canonical_status=p.canonical_status,
        raw_family=p.raw_family,
        frequency_fit=frequency_fit,
        mechanism_clarity=mechanism_clarity,
        channel_family_count=channel_family_count,
    )

    declared_core = p.tier == "core"
    conflict = declared_core and tier not in ("CORE_ELIGIBLE",)

    return {
        "name": p.name,
        "channel": p.target_variable,
        "canonical_subbasket": p.canonical_subbasket,
        "declared_tier": p.tier,
        "canonical_status": p.canonical_status,
        "freq": p.freq,
        "raw_family": p.raw_family,
        "raw_series": "|".join(p.raw_series),
        "semantic_distance": semantic_distance,
        "frequency_fit": frequency_fit,
        "channel_family_count": channel_family_count,
        "family_band": family_band,
        "mechanism_clarity": mechanism_clarity,
        "lineage_completeness": lineage,
        "data_availability": data_availability,
        "regime_coverage": "pending_empirical",
        "discrimination_power": "pending_empirical",
        "baseline_increment": "pending_empirical",
        "quality_tier": tier,
        "tier_reason": reason,
        "declared_core_conflict": conflict,
    }


def decide_tier(
    rules: dict,
    *,
    canonical_status: str,
    raw_family: str,
    frequency_fit: str,
    mechanism_clarity: str,
    channel_family_count: int,
) -> tuple[str, str]:
    """Walk the quality_tiers decision table; first match wins."""
    for rule in rules["quality_tiers"]:
        in_set = rule.get("when_canonical_status_in")
        if in_set is not None and canonical_status not in in_set:
            continue
        fam_eq = rule.get("when_family_equals")
        if fam_eq is not None and raw_family != fam_eq:
            continue

        require = rule.get("require")
        if require is not None:
            if require.get("frequency_fit") and frequency_fit != require["frequency_fit"]:
                continue
            if require.get("mechanism_clarity") and mechanism_clarity != require["mechanism_clarity"]:
                continue
            min_fam = require.get("min_channel_family_count")
            if min_fam is not None and channel_family_count < min_fam:
                continue

        any_freq = rule.get("require_any_frequency_fit")
        if any_freq is not None and frequency_fit not in any_freq:
            continue

        return rule["tier"], rule.get("reason", "")
    return "REJECTED", "unevaluated_or_unmatched"


def scan_legacy(rules: dict) -> list[dict]:
    """Flag legacy compute_proxies.py PROXY_MAP entries that violate canonical
    exclusions (K=VIX, X=H41, M=T10Y2Y)."""
    findings = []
    for excl in rules["legacy_exclusions"]:
        channel = excl["channel"]
        token = excl["banned_series_token"]
        spec = legacy.PROXY_MAP.get(channel, {})
        for s in spec.get("series", []):
            sid = s.get("id", "")
            if token in sid:
                findings.append(
                    {
                        "channel": channel,
                        "series": sid,
                        "verdict": "REJECTED",
                        "flag": "legacy_drift",
                        "reason": excl["reason"],
                    }
                )
    return findings


def write_csv(rows: list[dict], path: Path) -> None:
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build_gate(rows: list[dict]) -> dict:
    """Machine-readable gate: which proxies may vote into each channel core."""
    core_by_channel: dict[str, list[str]] = defaultdict(list)
    support_by_channel: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r["quality_tier"] == "CORE_ELIGIBLE":
            core_by_channel[r["channel"]].append(r["name"])
        elif r["quality_tier"] == "CONSTRUCT_SUPPORT":
            support_by_channel[r["channel"]].append(r["name"])
    return {
        "core_eligible": dict(core_by_channel),
        "construct_support": dict(support_by_channel),
    }


def write_report(rows: list[dict], legacy_findings: list[dict], gate: dict, path: Path) -> None:
    tier_counts = Counter(r["quality_tier"] for r in rows)
    conflicts = [r for r in rows if r["declared_core_conflict"]]
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    tier_order = [
        "CORE_ELIGIBLE",
        "CONSTRUCT_SUPPORT",
        "DIAGNOSTIC_ONLY",
        "BACKGROUND_ONLY",
        "REJECTED",
    ]

    lines: list[str] = []
    lines.append("# Proxy Quality Report")
    lines.append("")
    lines.append(f"_Generated {ts} by scripts/proxy_quality_scorer.py_")
    lines.append("")
    lines.append(
        "Gate over the wired canonical registry "
        "(`scripts/structural_replay_v2.py::PROXY_REGISTRY`), scored against "
        "`governance/proxy_quality_rules.yaml`. Decides which proxies may vote "
        "into a canonical M/D/K/X construct. Empirical criteria (regime "
        "coverage, discrimination, baseline increment) are reported as "
        "`pending_empirical`, not scored here."
    )
    lines.append("")

    lines.append("## Tier summary")
    lines.append("")
    lines.append("| Tier | Count |")
    lines.append("|---|---|")
    for t in tier_order:
        lines.append(f"| {t} | {tier_counts.get(t, 0)} |")
    lines.append(f"| **total** | **{len(rows)}** |")
    lines.append("")

    lines.append("## Core-eligible proxies by channel")
    lines.append("")
    if gate["core_eligible"]:
        for ch in sorted(gate["core_eligible"]):
            names = ", ".join(gate["core_eligible"][ch])
            lines.append(f"- **{ch}**: {names}")
    else:
        lines.append("- _(none)_")
    lines.append("")

    lines.append("## Declared-core conflicts")
    lines.append("")
    if conflicts:
        lines.append(
            "Proxies declared `tier=core` in the registry but scored below "
            "CORE_ELIGIBLE — drift between declared importance and quality:"
        )
        lines.append("")
        lines.append("| Proxy | Channel | Quality tier | Reason |")
        lines.append("|---|---|---|---|")
        for r in conflicts:
            lines.append(
                f"| {r['name']} | {r['channel']} | {r['quality_tier']} | {r['tier_reason']} |"
            )
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Legacy proxy-first drift (scripts/compute_proxies.py)")
    lines.append("")
    if legacy_findings:
        lines.append(
            "Series wired in the legacy `compute_proxies.py` that violate a "
            "canonical exclusion the red line already supersedes:"
        )
        lines.append("")
        lines.append("| Channel | Series | Verdict | Reason |")
        lines.append("|---|---|---|---|")
        for f in legacy_findings:
            lines.append(f"| {f['channel']} | {f['series']} | {f['verdict']} | {f['reason']} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Full scores")
    lines.append("")
    lines.append(
        "| Proxy | Channel | Status | Freq | Sem.dist | Freq fit | Fam | Mech | Tier |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x["channel"], tier_order.index(x["quality_tier"]) if x["quality_tier"] in tier_order else 99)):
        lines.append(
            f"| {r['name']} | {r['channel']} | {r['canonical_status']} | {r['freq']} "
            f"| {r['semantic_distance']} | {r['frequency_fit']} | {r['channel_family_count']} "
            f"| {r['mechanism_clarity']} | {r['quality_tier']} |"
        )
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rules = load_rules()
    registry = srv2.PROXY_REGISTRY
    fam_counts = channel_family_counts(registry)

    rows = [score_proxy(p, rules, fam_counts.get(p.target_variable, 0)) for p in registry]
    legacy_findings = scan_legacy(rules)
    gate = build_gate(rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "proxy_quality_scores.csv"
    gate_path = OUT_DIR / "proxy_quality_gate.json"
    report_path = OUT_DIR / "PROXY_QUALITY_REPORT.md"

    write_csv(rows, csv_path)
    gate_payload = {
        "schema_version": "proxy_quality_gate.v1",
        "generated_utc": datetime.now(UTC).isoformat(),
        "rules": "governance/proxy_quality_rules.yaml",
        "channel_family_counts": fam_counts,
        "gate": gate,
        "legacy_drift": legacy_findings,
    }
    gate_path.write_text(json.dumps(gate_payload, indent=2), encoding="utf-8")
    write_report(rows, legacy_findings, gate, report_path)

    tier_counts = Counter(r["quality_tier"] for r in rows)
    print(f"Scored {len(rows)} proxies across {len(fam_counts)} channels.")
    for t in ["CORE_ELIGIBLE", "CONSTRUCT_SUPPORT", "DIAGNOSTIC_ONLY", "BACKGROUND_ONLY", "REJECTED"]:
        print(f"  {t}: {tier_counts.get(t, 0)}")
    print(f"Legacy drift findings: {len(legacy_findings)}")
    print(f"Wrote:\n  {csv_path}\n  {gate_path}\n  {report_path}")


if __name__ == "__main__":
    main()
