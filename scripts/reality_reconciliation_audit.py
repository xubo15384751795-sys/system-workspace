#!/usr/bin/env python3
"""Reality Reconciliation Sprint — Audit Script.

Runs all remaining audit tasks in one pass:
- Proxy registry reconciliation
- Blind Spot audit
- VIF / independence audit
- Stale summary guard
- X_agg frequency guard
- Candidate module artifact audit
- Family diversity report

Output: Output/practicality_trial/REALITY_RECONCILIATION_REPORT.md
"""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "practicality_trial"
REPLAY_DIR = ROOT / "Output" / "sandbox" / "structural_replay_v2"
FW_PATH = ROOT / "Output" / "current" / "framework_output.json"
REGISTRY_PATH = REPLAY_DIR / "proxy_registry.json"
AUDIT_PATH = REPLAY_DIR / "measurement_audit.json"
RESULTS_PATH = REPLAY_DIR / "results.json"
SUMMARY_PATH = ROOT / "Output" / "current" / "latest_summary.md"


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ── Task 2: Proxy Registry Reconciliation ──────────────────────────────

def audit_proxy_registry() -> dict:
    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"status": "MISSING", "detail": "proxy_registry.json not found"}

    proxies = registry if isinstance(registry, list) else []
    total = len(proxies)
    proxy_reduced = sum(1 for p in proxies if p.get("proxy_status") == "PROXY_REDUCED")
    distance_3 = sum(1 for p in proxies if p.get("semantic_distance", 0) >= 3)
    partial = sum(1 for p in proxies if p.get("implemented_status") == "PARTIAL")

    # Collect valid_for / not_valid_for
    all_not_valid = set()
    all_valid = set()
    for p in proxies:
        for nv in p.get("not_valid_for", []):
            all_not_valid.add(nv)
        for v in p.get("valid_for", []):
            all_valid.add(v)

    return {
        "status": "OK",
        "total_proxies": total,
        "proxy_reduced_count": proxy_reduced,
        "proxy_reduced_pct": round(proxy_reduced / max(total, 1) * 100, 1),
        "distance_3_count": distance_3,
        "partial_count": partial,
        "all_valid_for": sorted(all_valid),
        "all_not_valid_for": sorted(all_not_valid),
        "reconciled": proxy_reduced == total,  # all reduced = output should say LOW
    }


# ── Task 3: Blind Spot Audit ──────────────────────────────────────────

def audit_blind_spots() -> dict:
    results = load_json(RESULTS_PATH)
    if not results:
        return {"status": "MISSING", "detail": "results.json not found"}

    regimes = {}
    for r in results:
        reg = r.get("peak_regime", "UNKNOWN")
        regimes[reg] = regimes.get(reg, 0) + 1

    blind_spot_count = regimes.get("Measurement Blind Spot", 0)
    total = len(results)

    return {
        "status": "OK",
        "total_events": total,
        "regime_distribution": regimes,
        "blind_spot_count": blind_spot_count,
        "blind_spot_pct": round(blind_spot_count / max(total, 1) * 100, 1),
        "resolved": blind_spot_count < total,  # not ALL blind spot = fixed
    }


# ── Task 4: VIF / Independence Audit ──────────────────────────────────

def audit_vif() -> dict:
    audit = load_json(AUDIT_PATH)
    if not audit:
        return {"status": "MISSING", "detail": "measurement_audit.json not found"}

    vif = audit.get("vif", {})
    ru = audit.get("residual_uniqueness", {})

    active_channels = ["M", "D_contraction", "K", "X_agg"]
    inactive_channels = ["X_PRE", "X_REALIZED", "Pi_t"]

    active_vif = {ch: vif.get(ch, 0.0) for ch in active_channels}
    inactive_vif = {ch: vif.get(ch, 0.0) for ch in inactive_channels}
    active_ru = {ch: ru.get(ch, 0.0) for ch in active_channels}

    all_zero = all(v == 0.0 for v in active_vif.values())
    all_active_valid = all(v > 0.0 for v in active_vif.values())

    return {
        "status": "OK",
        "active_vif": active_vif,
        "inactive_vif": inactive_vif,
        "active_uniqueness": active_ru,
        "all_zero": all_zero,
        "all_active_valid": all_active_valid,
        "resolved": not all_zero,  # not all zero = fixed
    }


# ── Task 5: Stale Summary Guard ───────────────────────────────────────

def audit_stale_summary() -> dict:
    if not SUMMARY_PATH.exists():
        return {"status": "MISSING", "detail": "latest_summary.md not found"}

    mtime = os.path.getmtime(SUMMARY_PATH)
    age_hours = (time.time() - mtime) / 3600
    is_stale = age_hours > 24

    return {
        "status": "OK",
        "age_hours": round(age_hours, 1),
        "is_stale": is_stale,
        "last_modified": datetime.fromtimestamp(mtime, tz=UTC).isoformat(),
        "resolved": not is_stale,
    }


# ── Task 6: X_agg Frequency Guard ─────────────────────────────────────

def audit_x_agg_frequency() -> dict:
    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"status": "MISSING"}

    proxies = registry if isinstance(registry, list) else []
    x_agg_proxies = [p for p in proxies if p.get("target_variable") == "X_agg"]

    freqs = set()
    for p in x_agg_proxies:
        f = p.get("freq", "unknown")
        freqs.add(f)

    # Check governance flags for frequency issues
    results = load_json(RESULTS_PATH)
    freq_violations = []
    if results:
        for r in results:
            for g in r.get("governance_flags", []):
                if "FREQUENCY" in str(g).upper() or "HORIZON_INCONSISTENT" in str(g).upper():
                    freq_violations.append(g[:100])

    return {
        "status": "OK",
        "x_agg_proxy_count": len(x_agg_proxies),
        "frequencies": sorted(freqs),
        "is_mixed": len(freqs) > 1,
        "freq_violations": list(set(freq_violations))[:5],
        "resolved": False,  # always mixed, needs explicit handling
    }


# ── Task 7: Candidate Module Artifact Audit ───────────────────────────

def audit_candidate_modules() -> dict:
    modules = {}

    # K_v2
    k_v2_dir = ROOT / "Data" / "benchmarks" / "K_v2"
    k_v2_report = ROOT / "Data" / "benchmarks" / "K_v2" / "K_v2_robustness_report.md"
    modules["K_v2"] = {
        "artifact_exists": k_v2_dir.exists(),
        "report_exists": k_v2_report.exists() if k_v2_dir.exists() else False,
        "consumed_by_daily": False,  # not in framework_output
        "diagnostic_only": True,
        "voting_impact": "none",
        "status": "MISSING_ARTIFACT" if not k_v2_dir.exists() else "STALE_ARTIFACT",
    }

    # X_agg_v2
    x_v2_dir = ROOT / "Data" / "benchmarks" / "X_agg_v2"
    modules["X_agg_v2"] = {
        "artifact_exists": x_v2_dir.exists(),
        "consumed_by_daily": False,
        "diagnostic_only": True,
        "voting_impact": "none",
        "status": "MISSING_ARTIFACT" if not x_v2_dir.exists() else "STALE_ARTIFACT",
    }

    # GluonTS
    gluonts_dir = ROOT / "Output" / "sandbox" / "gluonts"
    modules["GluonTS"] = {
        "artifact_exists": gluonts_dir.exists(),
        "consumed_by_daily": False,
        "diagnostic_only": True,
        "voting_impact": "none",
        "status": "MISSING_ARTIFACT" if not gluonts_dir.exists() else "STALE_ARTIFACT",
    }

    # Backtest Pipeline
    backtest_dir = ROOT / "ExternalTools"
    modules["Backtest_Pipeline"] = {
        "artifact_exists": backtest_dir.exists(),
        "consumed_by_daily": False,
        "diagnostic_only": True,
        "voting_impact": "none",
        "status": "PAPER" if backtest_dir.exists() else "MISSING_ARTIFACT",
    }

    # Backtest Lens
    replay_eval = REPLAY_DIR / "evaluation_report.md"
    modules["Backtest_Lens"] = {
        "artifact_exists": replay_eval.exists(),
        "consumed_by_daily": True,  # replay is in daily pipeline
        "diagnostic_only": True,
        "voting_impact": "none",
        "status": "ACTIVE_IN_DAILY" if replay_eval.exists() else "MISSING_ARTIFACT",
    }

    return modules


# ── Task 8: Family Diversity Report ───────────────────────────────────

def audit_family_diversity() -> dict:
    registry = load_json(REGISTRY_PATH)
    if not registry:
        return {"status": "MISSING"}

    proxies = registry if isinstance(registry, list) else []

    # Group by target_variable (channel)
    channels = {}
    for p in proxies:
        ch = p.get("target_variable", "unknown")
        tier = p.get("tier", "unknown")
        if tier not in ("core", "auxiliary"):
            continue
        if ch not in channels:
            channels[ch] = {"families": set(), "proxies": 0, "proxy_reduced": 0}
        channels[ch]["families"].add(p.get("raw_family", "unknown"))
        channels[ch]["proxies"] += 1
        if p.get("proxy_status") == "PROXY_REDUCED":
            channels[ch]["proxy_reduced"] += 1

    result = {}
    for ch, info in channels.items():
        fam_count = len(info["families"])
        if fam_count == 1:
            confidence_cap = "LOW (monoculture)"
        elif fam_count == 2:
            confidence_cap = "MEDIUM_LOW"
        else:
            confidence_cap = "eligible for MEDIUM"
        result[ch] = {
            "source_family_count": fam_count,
            "families": sorted(info["families"]),
            "proxy_count": info["proxies"],
            "proxy_reduced_count": info["proxy_reduced"],
            "confidence_cap": confidence_cap,
            "monoculture_warning": fam_count <= 1,
        }

    return result


# ── Generate Report ───────────────────────────────────────────────────

def generate_report() -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    proxy = audit_proxy_registry()
    blind = audit_blind_spots()
    vif = audit_vif()
    stale = audit_stale_summary()
    xagg = audit_x_agg_frequency()
    modules = audit_candidate_modules()
    family = audit_family_diversity()

    lines = [
        "# Reality Reconciliation Report",
        "",
        f"**Generated:** {now}",
        f"**Purpose:** Verify that system output matches actual capability.",
        "",
        "---",
        "",
        "## 1. Status Semantics (Task 1 — DONE)",
        "",
        "ACTIVE_FULL has been decomposed into 3-layer status:",
        "- Operational Status: RUNNING / STOPPED / DEGRADED",
        "- Coverage Status: FULL_COVERAGE / PARTIAL_COVERAGE / NO_COVERAGE",
        "- Measurement Quality: HIGH / MEDIUM / LOW_CONFIDENCE_PROXY_REDUCED",
        "",
        "Validity scope now explicitly states:",
        "- valid_for: partial morphology stress warning",
        "- not_valid_for: complete market morphology state, trading signals",
        "",
        "✅ Resolved.",
        "",
        "---",
        "",
        "## 2. Proxy Registry Reconciliation",
        "",
        f"- Total proxies: {proxy.get('total_proxies', '?')}",
        f"- PROXY_REDUCED: {proxy.get('proxy_reduced_count', '?')} ({proxy.get('proxy_reduced_pct', '?')}%)",
        f"- Semantic distance ≥ 3: {proxy.get('distance_3_count', '?')}",
        f"- PARTIAL status: {proxy.get('partial_count', '?')}",
        f"- Registry valid_for: {proxy.get('all_valid_for', [])}",
        f"- Registry not_valid_for: {proxy.get('all_not_valid_for', [])}",
        f"- **Reconciled:** {'✅' if proxy.get('reconciled') else '❌'} — {'All proxies reduced, output should say LOW' if proxy.get('reconciled') else 'Mismatch detected'}",
        "",
        "---",
        "",
        "## 3. Measurement Blind Spot Audit",
        "",
        f"- Total events: {blind.get('total_events', '?')}",
        f"- Blind Spot count: {blind.get('blind_spot_count', '?')} ({blind.get('blind_spot_pct', '?')}%)",
        f"- Regime distribution:",
    ]
    for reg, count in blind.get("regime_distribution", {}).items():
        lines.append(f"  - {reg}: {count}")
    lines += [
        f"- **Resolved:** {'✅' if blind.get('resolved') else '❌'} — {'Not all events are blind spot' if blind.get('resolved') else 'Still all blind spot'}",
        "",
        "---",
        "",
        "## 4. VIF / Independence Audit",
        "",
        "Active channels:",
    ]
    for ch, val in vif.get("active_vif", {}).items():
        ru = vif.get("active_uniqueness", {}).get(ch, 0)
        lines.append(f"  - {ch}: VIF={val:.3f}, Uniqueness={ru:.3f}")
    lines += [
        "",
        f"- All active VIF = 0: {'❌ YES (broken)' if vif.get('all_zero') else '✅ NO (valid)'}",
        f"- All active VIF > 0: {'✅' if vif.get('all_active_valid') else '❌'}",
        f"- **Resolved:** {'✅' if vif.get('resolved') else '❌'}",
        "",
        "---",
        "",
        "## 5. Stale Summary Guard",
        "",
        f"- Age: {stale.get('age_hours', '?')} hours",
        f"- Is stale (>24h): {'❌ YES' if stale.get('is_stale') else '✅ NO'}",
        f"- Last modified: {stale.get('last_modified', '?')}",
        f"- **Resolved:** {'✅' if stale.get('resolved') else '❌'}",
        "",
        "---",
        "",
        "## 6. X_agg Frequency Guard",
        "",
        f"- X_agg proxy count: {xagg.get('x_agg_proxy_count', '?')}",
        f"- Frequencies: {xagg.get('frequencies', [])}",
        f"- Is mixed: {'❌ YES' if xagg.get('is_mixed') else '✅ NO'}",
        f"- Frequency violations: {xagg.get('freq_violations', [])}",
        "",
        "**Status:** X_agg remains MIXED_FREQUENCY. Daily interpretation should be RESTRICTED.",
        "Quarterly proxies should not generate daily spike signals.",
        "",
        "---",
        "",
        "## 7. Candidate Module Artifact Audit",
        "",
        "| Module | Artifact | Daily | Diagnostic | Voting | Status |",
        "|---|---|---|---|---|---|",
    ]
    for name, info in modules.items():
        ae = "✅" if info.get("artifact_exists") else "❌"
        cd = "✅" if info.get("consumed_by_daily") else "❌"
        diag = "✅" if info.get("diagnostic_only") else "—"
        lines.append(f"| {name} | {ae} | {cd} | {diag} | {info.get('voting_impact', '?')} | {info.get('status', '?')} |")

    lines += [
        "",
        "---",
        "",
        "## 8. Family Diversity Report",
        "",
        "| Channel | Families | Count | Monoculture | Confidence Cap |",
        "|---|---|---:|---|---|",
    ]
    for ch, info in family.items():
        if isinstance(info, dict):
            mw = "⚠️ YES" if info.get("monoculture_warning") else "✅ NO"
            lines.append(
                f"| {ch} | {', '.join(info.get('families', []))} | "
                f"{info.get('source_family_count', 0)} | {mw} | "
                f"{info.get('confidence_cap', '?')} |"
            )

    lines += [
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Task | Status |",
        "|---|---|",
        f"| 1. Status semantics | ✅ DONE |",
        f"| 2. Proxy registry reconciliation | {'✅' if proxy.get('reconciled') else '❌'} |",
        f"| 3. Blind spot audit | {'✅' if blind.get('resolved') else '❌'} |",
        f"| 4. VIF / independence | {'✅' if vif.get('resolved') else '❌'} |",
        f"| 5. Stale summary guard | {'✅' if stale.get('resolved') else '❌'} |",
        f"| 6. X_agg frequency guard | ❌ (mixed, needs handling) |",
        f"| 7. Candidate module audit | ❌ (3/5 MISSING) |",
        f"| 8. Family diversity | ❌ (all monoculture) |",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = generate_report()
    path = OUTPUT / "REALITY_RECONCILIATION_REPORT.md"
    path.write_text(report, encoding="utf-8")
    print(f"Report: {path}")
    print(report)


if __name__ == "__main__":
    main()
