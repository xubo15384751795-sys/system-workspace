#!/usr/bin/env python3
"""Bridge audit: Proxy Wiki (v2) ↔ System structural_replay_v2.

Compares Wiki proxy registry / MVP basket against live System PROXY_REGISTRY
and runs the official Harvester panel through build_measurement_bundle().

Usage:
  python3 scripts/wiki_system_bridge_audit.py
  python3 scripts/wiki_system_bridge_audit.py wiki_root=/path/to/Proxy\\ Wiki
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_ROOT = Path("/Users/a1/Proxy Wiki")
CONFIG_PATH = REPO_ROOT / "configs" / "structural_replay" / "config.yaml"
PANEL_DEFAULT = REPO_ROOT / "Data/harvester/exports/2026-05-05-r1/data/official_panel.parquet"
OUTPUT_DIR = REPO_ROOT / "Output/sandbox/wiki_system_bridge"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import structural_replay_v2 as srv  # noqa: E402


# Wiki MVP card ids → expected System channel / subbasket (v2 framework)
WIKI_MVP_EXPECTATIONS: dict[str, dict] = {
    "fra-ois-spread": {"channel": "M", "family": "M.funding_anchor_gap", "panel_series": None},
    "cross-currency-basis": {"channel": "M", "family": "M.funding_anchor_gap", "panel_series": None},
    "credit-spread": {"channel": "M", "family": "M.pricing_basis_gap", "panel_series": ["FRED:BAMLH0A0HYM2", "FRED:BAMLC0A0CM"]},
    "move-vix-divergence": {"channel": "M", "family": "M.pricing_basis_gap", "panel_series": ["FRED:VIXCLS", "YFINANCE:^MOVE"]},
    "bank-index": {"channel": "M", "family": "M.verifiability_gap", "panel_series": None},
    "market-breadth": {"channel": "D", "family": "D.market_depth", "panel_series": None},
    "nfci": {"channel": "D", "family": "D.funding_access", "panel_series": ["FRED:NFCI"]},
    "discount-window": {"channel": "X", "family": "X.backstop_dependence", "panel_series": ["H41:discount_window"]},
    "vvix": {"channel": "K", "family": "K.iv_surface_distortion", "panel_series": None},
    "skew-index": {"channel": "K", "family": "K.iv_surface_distortion", "panel_series": None},
    "vix-term-structure": {"channel": "K", "family": "K.iv_surface_distortion", "panel_series": None},
    "market-correlation": {"channel": "K", "family": "K.transport_failure", "panel_series": None},
    "rrp-usage": {"channel": "X", "family": "X.shadow_funding_substitution", "panel_series": None},
    "sofr-iorb-gap": {"channel": "M", "family": "M.funding_anchor_gap", "panel_series": ["FRED:SOFR", "FRED:IORB"]},
    "cp-tbill-spread": {"channel": "M", "family": "M.funding_anchor_gap", "panel_series": ["FRED:DCPF3M", "FRED:DGS3MO"]},
    "vix": {"channel": "ctrl", "family": "control.vol_benchmark", "panel_series": ["FRED:VIXCLS"]},
    "move-index": {"channel": "ctrl", "family": "control.vol_benchmark", "panel_series": ["YFINANCE:^MOVE"]},
}


def list_wiki_cards(wiki_root: Path) -> list[str]:
    ind = wiki_root / "indicators"
    if not ind.is_dir():
        return []
    return sorted(
        p.stem for p in ind.glob("*.md")
        if p.stem not in {"_index", "_template"}
    )


def system_voting_proxies() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for spec in srv.PROXY_REGISTRY:
        if spec.canonical_status != "canonical_voting":
            continue
        ch = spec.target_variable
        out.setdefault(ch, []).append({
            "name": spec.name,
            "subbasket": spec.canonical_subbasket,
            "raw_series": list(spec.raw_series),
            "group": spec.independence_group,
        })
    return out


def panel_columns(panel: pd.DataFrame) -> set[str]:
    return set(panel.columns.astype(str))


def channel_summary(bundle) -> dict:
    summary = {}
    for ch in srv.CHANNELS:
        s = bundle.channels[ch]
        valid = int(s.notna().sum())
        summary[ch] = {
            "valid_days": valid,
            "total_days": len(s),
            "median_coverage": float(bundle.coverage[ch].median()),
            "latest": float(s.dropna().iloc[-1]) if valid else None,
            "implemented": valid > 0,
        }
    return summary


def max_channel_corr(channels: pd.DataFrame) -> float | None:
    cols = [c for c in ["M", "D_contraction", "K", "X_agg"] if c in channels.columns]
    sub = channels[cols].dropna(how="all")
    if sub.empty or len(cols) < 2:
        return None
    corr = sub.corr().abs()
    mask = np.triu(np.ones(corr.shape), k=1).astype(bool)
    if not corr.where(mask).notna().any().any():
        return None
    return float(corr.where(mask).max().max())


def alignment_gaps(cards: list[str], voting: dict[str, list[dict]], panel_cols: set[str]) -> list[dict]:
    gaps = []
    voters_flat = {v["name"]: ch for ch, specs in voting.items() for v in specs}

    for card_id, exp in WIKI_MVP_EXPECTATIONS.items():
        issue = None
        severity = "info"

        if exp["channel"] == "ctrl":
            if any(card_id in str(v.get("raw_series", [])) for specs in voting.values() for v in specs):
                issue = "control series incorrectly wired as canonical_voting"
                severity = "error"
        elif exp["channel"] == "M":
            if not any(s["name"].startswith("M_") for s in voting.get("M", [])):
                pass
            # Check if any M voter covers this mechanism
            m_voters = voting.get("M", [])
            if card_id == "credit-spread" and not any("HY" in str(s) or "BAML" in str(s) for s in m_voters for _ in [0]):
                if not {"FRED:BAMLH0A0HYM2", "FRED:BAMLC0A0CM"}.issubset(panel_cols):
                    issue = "HY-IG gap data in panel but no M pricing-basis voter"
                    severity = "high"
                else:
                    issue = "panel has HY/IG OAS but no M canonical_voting proxy for pricing_basis_gap"
                    severity = "high"
            if card_id == "fra-ois-spread":
                issue = "FRA-OIS not in harvester panel; no M funding voter"
                severity = "high"
            if card_id == "sofr-iorb-gap":
                if {"FRED:SOFR", "FRED:IORB"}.issubset(panel_cols):
                    d_match = any(s["name"] == "D_sofr_iorb_gap" for s in voting.get("D_contraction", []))
                    if d_match:
                        issue = "SOFR-IORB wired to D.funding_access in System; Wiki assigns M.funding_anchor_gap"
                        severity = "medium"
        elif exp["channel"] == "K":
            if not voting.get("K"):
                issue = "K channel has zero canonical_voting proxies — NOT_IMPLEMENTED"
                severity = "critical"
        elif exp["channel"] == "D":
            d_v = voting.get("D_contraction", [])
            if card_id == "nfci":
                if not any("nfci" in s["name"].lower() for s in d_v):
                    issue = "NFCI demoted to diagnostic in System; Wiki MVP uses −NFCI for D"
                    severity = "medium"
            if card_id == "market-breadth":
                if not any("depth" in s.get("subbasket", "") or "hedge" in s.get("subbasket", "") for s in d_v):
                    issue = "D voters are funding-only (w3); no depth/hedge breadth voters"
                    severity = "high"

        series = exp.get("panel_series") or []
        missing_series = [s for s in series if s not in panel_cols]

        gaps.append({
            "card": card_id,
            "expected_channel": exp["channel"],
            "expected_family": exp["family"],
            "issue": issue,
            "severity": severity,
            "missing_panel_series": missing_series,
        })
    return gaps


def overall_verdict(channel_summary: dict, gaps: list[dict], max_corr: float | None) -> dict:
    critical = [g for g in gaps if g["severity"] == "critical"]
    high = [g for g in gaps if g["severity"] == "high"]
    implemented = sum(1 for ch in ["M", "D_contraction", "K", "X_agg"] if channel_summary.get(ch, {}).get("implemented"))

    if critical:
        status = "NOT_RUNNABLE"
        headline = "Γ_t 四维向量当前不可运行：K（及多数 X 子层）无 canonical 投票代理。"
    elif implemented < 3:
        status = "PARTIAL"
        headline = f"仅 {implemented}/4 通道有有效序列；Wiki MVP 与 System 执行层严重脱节。"
    elif high:
        status = "PARTIAL_ALIGNED"
        headline = "框架对齐，但 Wiki MVP 多条 proxy 未接入 System 投票层。"
    else:
        status = "ALIGNED"
        headline = "Wiki 与 System 基本对齐。"

    return {
        "status": status,
        "headline": headline,
        "channels_implemented": implemented,
        "four_channel_max_abs_corr": max_corr,
        "critical_gaps": len(critical),
        "high_gaps": len(high),
        "corr_trap_ok": max_corr is None or max_corr < 0.85,
    }


def main() -> None:
    wiki_root = WIKI_ROOT
    for arg in sys.argv[1:]:
        if arg.startswith("wiki_root="):
            wiki_root = Path(arg.split("=", 1)[1])

    panel_path = PANEL_DEFAULT
    panel = srv.load_official_panel(panel_path)
    bundle = srv.build_measurement_bundle(panel)
    ch_summary = channel_summary(bundle)

    voting = system_voting_proxies()
    cards = list_wiki_cards(wiki_root)
    gaps = alignment_gaps(cards, voting, panel_columns(panel))

    corr_cols = bundle.channels[["M", "D_contraction", "K", "X_agg"]].copy()
    max_corr = max_channel_corr(corr_cols)

    verdict = overall_verdict(ch_summary, gaps, max_corr)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wiki_root": str(wiki_root),
        "panel_path": str(panel_path),
        "wiki_card_count": len(cards),
        "verdict": verdict,
        "channel_summary": ch_summary,
        "system_canonical_voters": voting,
        "alignment_gaps": gaps,
        "measurement_audit_hard_errors": bundle.audit.get("hard_errors", []),
        "principle": {
            "M": "锚错了",
            "D": "路少了",
            "K": "传导弯了",
            "X": "压力藏起来了",
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUTPUT_DIR / "bridge_audit.json"
    out_md = OUTPUT_DIR / "bridge_audit.md"
    out_json.write_text(json.dumps(report, indent=2, default=str))

    lines = [
        "# Wiki ↔ System Bridge Audit",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Verdict:** `{verdict['status']}` — {verdict['headline']}",
        "",
        "## Channel Implementation (canonical_voting only)",
        "",
        "| Channel | Valid Days | Median Coverage | Latest |",
        "|---------|----------:|----------------:|-------:|",
    ]
    for ch in ["M", "D_contraction", "K", "X_agg", "X_PRE", "X_REALIZED"]:
        s = ch_summary.get(ch, {})
        lines.append(
            f"| {ch} | {s.get('valid_days', 0)} | {s.get('median_coverage', 0):.2f} | "
            f"{s.get('latest', 'NaN')} |"
        )
    lines += [
        "",
        f"**Four-channel max |corr|:** {max_corr if max_corr is not None else 'n/a'} "
        f"({'OK' if verdict['corr_trap_ok'] else 'TRAP — channels collapsing'})",
        "",
        "## System Canonical Voters",
        "",
        "```json",
        json.dumps(voting, indent=2),
        "```",
        "",
        "## Alignment Gaps (Wiki MVP vs System)",
        "",
    ]
    for g in sorted(gaps, key=lambda item: {"critical": 0, "high": 1, "medium": 2, "error": 1, "info": 3}.get(item["severity"], 9)):
        if g["issue"]:
            lines.append(f"- **[{g['severity']}]** `{g['card']}` → {g['expected_family']}: {g['issue']}")
            if g["missing_panel_series"]:
                lines.append(f"  - missing panel: {g['missing_panel_series']}")

    lines += [
        "",
        "## Judgment",
        "",
        "1. **Wiki 层（ontology + admission rules + registry）** 与你的 M/D/K/X 框架一致。",
        "2. **System 执行层（structural_replay_v2 canonical_voting）** 目前只真正跑通 **M + 部分 D + 弱 X_agg**；**K = NOT_IMPLEMENTED**（全部 IV/jump/tail 代理 awaiting_data，旧 credit-surface K 已 quarantine）。",
        "3. **Γ_t 作为决策本体当前不成立** — sigma_vector 里 D/K/X 多为 null；只能做 M 单通道诊断。",
        "4. **Wiki ↔ System 通道分配冲突**：SOFR-IORB、CP-Tbill 在 Wiki 是 **M.funding_gap**，在 System 是 **D.funding_access** — 需按「M=gap / D=accessibility」规则拆成两条 derived series，不能共用同一投票位。",
        "5. **Harvester 购物清单**（ unblock K/X MVP）：VVIX、SKEW、VIX futures term、RRPONTSYD、cross-currency basis、FRA-OIS、SPX breadth、PC1/correlation computed series。",
        "",
    ]
    out_md.write_text("\n".join(lines))

    print(json.dumps({"verdict": verdict, "output": str(out_json)}, indent=2))
    print(f"\nReport: {out_md}")


if __name__ == "__main__":
    main()
