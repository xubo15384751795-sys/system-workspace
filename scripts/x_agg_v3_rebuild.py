#!/usr/bin/env python3
"""X_agg Rebuild — Shadow Leverage.

Rebuilds X_agg using real leverage data instead of vol proxies.

X_agg_old: OFR_FSI (r=0.88 with VIX) + Treasury Debt + dead series
X_agg_new: broker-dealer leverage + hedge fund leverage + bank credit + reserves

Components:
  X_agg_leverage_daily:   RRP, Treasury Cash, SOFR-IORB (daily)
  X_agg_leverage_weekly:  Bank Credit, Reserve Balances, Fed Assets, TGA (weekly)
  X_agg_leverage_slow:    Broker-Dealer Margin, Hedge Fund Prime Brokerage, 
                          Dealer Debt Securities (quarterly, 1945+)

Output: Data/benchmarks/X_agg_v3/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Data" / "benchmarks" / "X_agg_v3"
PANEL_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"

# ── Component definitions ──────────────────────────────────────────────

DAILY_SERIES = {
    "FRED:RRPONTSYD": "RRP",
    "TREASURY:daily_treasury_statement:open_today_bal": "Treasury_Cash",
    "DERIVED:SOFR_IORB_SPREAD": "SOFR_IORB",
}

WEEKLY_SERIES = {
    "FRED:TOTBKCR": "Bank_Credit",
    "FRED:WRESBAL": "Reserve_Balances",
    "FRED:WALCL": "Fed_Assets",
    "FRED:WTREGEN": "TGA",
    "FRED:NFCILEVERAGE": "NFCI_Leverage",
}

SLOW_SERIES = {
    "FRED:BOGZ1FL663067003Q": "BD_Margin_Loans",
    "FRED:BOGZ1FL624123035Q": "HF_Prime_Brokerage",
    "FRED:SBDDSA": "BD_Debt_Securities",
}

ASSETS = ["SPY", "XLF", "KRE", "HYG", "LQD", "TLT"]
HORIZONS = [20, 60, 120]


def load_panel() -> pd.DataFrame:
    bp = pd.read_parquet(PANEL_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    return bp


def load_etf() -> pd.DataFrame:
    etf = pd.read_parquet(ETF_PANEL)
    etf["date"] = pd.to_datetime(etf["date"])
    return etf


def extract_series(panel: pd.DataFrame, series_id: str) -> pd.Series:
    subset = panel[panel["series_id"] == series_id].copy()
    if subset.empty:
        return pd.Series(dtype=float)
    subset = subset.sort_values("date").drop_duplicates("date")
    return subset.set_index("date")["value"]


def rolling_zscore(series: pd.Series, window: int = 252) -> pd.Series:
    mu = series.rolling(window, min_periods=60).mean()
    sigma = series.rolling(window, min_periods=60).std().replace(0, np.nan)
    return ((series - mu) / sigma).clip(-5, 5)


def build_component(panel: pd.DataFrame, series_map: dict, name: str) -> tuple[pd.Series, dict]:
    """Build a component from multiple series. Returns (z_series, metadata)."""
    zscores = []
    meta = {"name": name, "series": [], "coverage": 0}

    for sid, label in series_map.items():
        s = extract_series(panel, sid)
        if s.empty:
            meta["series"].append({"id": sid, "label": label, "rows": 0, "status": "MISSING"})
            continue
        z = rolling_zscore(s)
        zscores.append(z)
        meta["series"].append({
            "id": sid,
            "label": label,
            "rows": int(s.notna().sum()),
            "start": s.dropna().index.min().strftime("%Y-%m-%d") if s.notna().any() else None,
            "end": s.dropna().index.max().strftime("%Y-%m-%d") if s.notna().any() else None,
            "last_value": round(float(s.dropna().iloc[-1]), 4) if s.notna().any() else None,
            "last_z": round(float(z.dropna().iloc[-1]), 4) if z.notna().any() else None,
        })

    if not zscores:
        return pd.Series(dtype=float), meta

    df = pd.concat(zscores, axis=1)
    component = df.mean(axis=1, skipna=True)
    component.name = name
    meta["coverage"] = round(component.notna().mean(), 4)
    return component, meta


def build_x_agg_v3(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Build X_agg v3 from leverage data."""
    daily, daily_meta = build_component(panel, DAILY_SERIES, "X_agg_daily")
    weekly, weekly_meta = build_component(panel, WEEKLY_SERIES, "X_agg_weekly")
    slow, slow_meta = build_component(panel, SLOW_SERIES, "X_agg_slow")

    components = pd.DataFrame({
        "X_agg_daily": daily,
        "X_agg_weekly": weekly,
        "X_agg_slow": slow,
    })

    # Composite: mean of all available
    components["X_agg_composite"] = components.mean(axis=1, skipna=True)
    components["X_agg_coverage"] = components[["X_agg_daily", "X_agg_weekly", "X_agg_slow"]].notna().sum(axis=1) / 3

    metadata = [daily_meta, weekly_meta, slow_meta]
    return components, metadata


def detect_triggers(z: pd.Series, threshold: float = 1.5, dedup_days: int = 30) -> pd.DataFrame:
    """Detect and deduplicate triggers."""
    raw = z[z >= threshold]
    if raw.empty:
        return pd.DataFrame()

    dates = raw.index.sort_values()
    keep = [dates[0]]
    for d in dates[1:]:
        if (d - keep[-1]).days >= dedup_days:
            keep.append(d)

    triggers = raw.loc[keep].reset_index()
    triggers.columns = ["date", "value"]
    triggers["threshold"] = threshold
    triggers["dedup_days"] = dedup_days
    return triggers


def compute_forward_returns(triggers: pd.DataFrame, etf: pd.DataFrame, asset: str) -> pd.DataFrame:
    etf_asset = etf[etf["symbol"] == asset].set_index("date").sort_index()
    if etf_asset.empty:
        return pd.DataFrame()

    results = []
    for _, row in triggers.iterrows():
        trigger_date = row["date"]
        future = etf_asset[etf_asset.index >= trigger_date]
        if future.empty:
            continue

        base = future.iloc[0]["close"]
        rec = {"trigger_date": trigger_date, "value": row["value"], "asset": asset, "base": base}
        for h in HORIZONS:
            if len(future) > h:
                ret = (future.iloc[h]["close"] / base - 1) * 100
                rec[f"return_{h}d"] = round(ret, 2)
            else:
                rec[f"return_{h}d"] = None
        results.append(rec)

    return pd.DataFrame(results)


def matched_control(triggers: pd.DataFrame, z: pd.Series, etf: pd.DataFrame, asset: str, horizon: int = 60) -> pd.DataFrame:
    etf_asset = etf[etf["symbol"] == asset].set_index("date").sort_index()
    if etf_asset.empty:
        return pd.DataFrame()

    results = []
    for _, row in triggers.iterrows():
        td = row["date"]
        tz = row["value"]

        k_vals = z.dropna()
        ctrl = k_vals[(k_vals >= tz - 0.5) & (k_vals <= tz + 0.5) & (k_vals < 1.5)]
        ctrl = ctrl[ctrl.index != td]
        if ctrl.empty:
            continue

        idx = np.argmin(np.abs((ctrl.index - td).days))
        cd = ctrl.index[idx]

        ft = etf_asset[etf_asset.index >= td]
        fc = etf_asset[etf_asset.index >= cd]
        if len(ft) <= horizon or len(fc) <= horizon:
            continue

        tr = (ft.iloc[horizon]["close"] / ft.iloc[0]["close"] - 1) * 100
        cr = (fc.iloc[horizon]["close"] / fc.iloc[0]["close"] - 1) * 100
        results.append({
            "trigger_date": td, "control_date": cd,
            "trigger_z": round(tz, 3), "control_z": round(float(ctrl.loc[cd]), 3),
            "trigger_return": round(tr, 2), "control_return": round(cr, 2),
            "excess": round(tr - cr, 2),
        })
    return pd.DataFrame(results)


def compare_with_old(panel: pd.DataFrame, x_new: pd.Series) -> dict:
    """Compare new X_agg with old OFR_FSI-based version."""
    ofr = extract_series(panel, "OFR_FSI")
    ofr_z = rolling_zscore(ofr)

    aligned = pd.DataFrame({"new": x_new, "old": ofr_z}).dropna()
    if len(aligned) < 100:
        return {"error": "insufficient aligned data"}

    corr = aligned["new"].corr(aligned["old"])
    return {
        "correlation": round(corr, 3),
        "aligned_rows": len(aligned),
        "new_mean": round(float(aligned["new"].mean()), 4),
        "old_mean": round(float(aligned["old"].mean()), 4),
        "new_last": round(float(aligned["new"].iloc[-1]), 4),
        "old_last": round(float(aligned["old"].iloc[-1]), 4),
    }


def generate_report(components: pd.DataFrame, metadata: list, triggers: dict, fwd_returns: dict,
                     matched: dict, comparison: dict) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    x_composite = components["X_agg_composite"]

    lines = [
        "# X_agg v3 — Shadow Leverage Rebuild",
        "",
        f"**Generated:** {now}",
        f"**Concept:** X_agg measures shadow leverage accumulation using real leverage data.",
        f"**Replaces:** X_agg_old (OFR_FSI + Treasury Debt, r=0.88 with VIX)",
        "",
        "---",
        "",
        "## 1. Components",
        "",
    ]

    for meta in metadata:
        name = meta["name"]
        cov = meta["coverage"]
        lines += [
            f"### {name} (coverage={cov*100:.1f}%)",
            "",
            "| Series | Rows | Last Value | Last Z | Period |",
            "|---|---:|---:|---:|---|",
        ]
        for s in meta["series"]:
            rows = s.get("rows", 0)
            lv = f"{s['last_value']:.2f}" if s.get("last_value") is not None else "N/A"
            lz = f"{s['last_z']:.2f}" if s.get("last_z") is not None else "N/A"
            period = f"{s.get('start', '?')} to {s.get('end', '?')}" if rows > 0 else "NO DATA"
            lines.append(f"| {s['label']} | {rows:,} | {lv} | {lz} | {period} |")
        lines.append("")

    # Composite stats
    nn = x_composite.notna().sum()
    lines += [
        "## 2. X_agg Composite",
        "",
        f"- **Observations:** {nn:,}",
        f"- **Mean:** {x_composite.dropna().mean():.4f}",
        f"- **Std:** {x_composite.dropna().std():.4f}",
        f"- **Last value:** {x_composite.dropna().iloc[-1]:.4f}" if nn > 0 else "",
        "",
    ]

    # Comparison with old
    if comparison and "error" not in comparison:
        lines += [
            "## 3. Comparison with Old X_agg (OFR_FSI)",
            "",
            f"- **Correlation:** {comparison['correlation']}",
            f"- **Old last z:** {comparison['old_last']}",
            f"- **New last z:** {comparison['new_last']}",
            f"- **Old mean:** {comparison['old_mean']}",
            f"- **New mean:** {comparison['new_mean']}",
            "",
        ]
        if abs(comparison["correlation"]) < 0.5:
            lines.append("**New X_agg is substantially different from old OFR_FSI-based version.**")
        else:
            lines.append("**New X_agg is correlated with old version — may need further differentiation.**")
        lines.append("")

    # Triggers
    lines += ["## 4. Triggers (z ≥ 1.5, 30d dedup)", ""]
    for comp_name, trig_df in triggers.items():
        lines.append(f"### {comp_name}: {len(trig_df)} triggers")
        if not trig_df.empty:
            lines += ["", "| Date | Value |", "|---|---:|"]
            for _, row in trig_df.head(15).iterrows():
                d = row['date'].strftime('%Y-%m-%d')
                v = row['value']
                lines.append(f"| {d} | {v:.3f} |")
        lines.append("")

    # Forward returns
    lines += ["## 5. Forward Returns", ""]
    for comp_name, fwd_dict in fwd_returns.items():
        lines.append(f"### {comp_name}")
        for asset, fwd in fwd_dict.items():
            if fwd.empty:
                continue
            lines += [
                f"#### {asset}",
                "",
                "| Trigger | Value | 20d | 60d | 120d |",
                "|---|---:|---:|---:|---:|",
            ]
            for _, row in fwd.iterrows():
                r20 = f"{row.get('return_20d', 'N/A')}%" if pd.notna(row.get('return_20d')) else "N/A"
                r60 = f"{row.get('return_60d', 'N/A')}%" if pd.notna(row.get('return_60d')) else "N/A"
                r120 = f"{row.get('return_120d', 'N/A')}%" if pd.notna(row.get('return_120d')) else "N/A"
                td = row['trigger_date'].strftime('%Y-%m-%d')
                tv = row['value']
                lines.append(f"| {td} | {tv:.3f} | {r20} | {r60} | {r120} |")
            for h in HORIZONS:
                col = f"return_{h}d"
                valid = fwd[col].dropna()
                if not valid.empty:
                    lines.append(f"\n**{h}d:** mean={valid.mean():.2f}%, n={len(valid)}, hit_rate={sum(valid > 0)/len(valid)*100:.0f}%")
            lines.append("")

    # Matched control
    lines += ["## 6. Matched Control (60d)", ""]
    for comp_name, mc_dict in matched.items():
        lines.append(f"### {comp_name}")
        for asset, mc in mc_dict.items():
            if mc.empty:
                lines.append(f"#### {asset}: No data")
                continue
            lines += [
                f"#### {asset}",
                "",
                "| Trigger | Trig Z | Ctrl Z | Trig Ret | Ctrl Ret | Excess |",
                "|---|---:|---:|---:|---:|---:|",
            ]
            for _, row in mc.iterrows():
                lines.append(
                    f"| {row['trigger_date'].strftime('%Y-%m-%d')} | {row['trigger_z']:.3f} | "
                    f"{row['control_z']:.3f} | {row['trigger_return']:.2f}% | "
                    f"{row['control_return']:.2f}% | {row['excess']:.2f}% |"
                )
            avg_excess = mc["excess"].mean()
            beats = (mc["excess"] > 0).sum()
            lines.append(f"\n**Average excess:** {avg_excess:.2f}%, **beats control:** {beats}/{len(mc)} ({beats/len(mc)*100:.0f}%)")
        lines.append("")

    # Status
    lines += [
        "---",
        "",
        "## 7. Status",
        "",
        "- **X_agg_v3 artifact:** BUILT",
        "- **Status:** DAILY_DIAGNOSTIC_CANDIDATE",
        "- **Replaces:** X_agg_old (OFR_FSI-based, DISABLED)",
        "- **Not yet in voting:** needs robustness validation",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    panel = load_panel()
    etf = load_etf()

    print("Building X_agg v3 components...")
    components, metadata = build_x_agg_v3(panel)
    x_composite = components["X_agg_composite"]
    print(f"  Composite: {x_composite.notna().sum()} obs, last={x_composite.dropna().iloc[-1]:.4f}")

    print("Comparing with old X_agg (OFR_FSI)...")
    comparison = compare_with_old(panel, x_composite)
    print(f"  Correlation: {comparison.get('correlation', 'N/A')}")

    print("Detecting triggers...")
    triggers = {}
    for comp_name in ["X_agg_daily", "X_agg_weekly", "X_agg_slow", "X_agg_composite"]:
        trig = detect_triggers(components[comp_name], threshold=1.5, dedup_days=30)
        triggers[comp_name] = trig
        print(f"  {comp_name}: {len(trig)} triggers")

    print("Computing forward returns...")
    fwd_returns = {}
    for comp_name, trig_df in triggers.items():
        if trig_df.empty:
            fwd_returns[comp_name] = {}
            continue
        fwd_returns[comp_name] = {}
        for asset in ASSETS:
            fwd_returns[comp_name][asset] = compute_forward_returns(trig_df, etf, asset)

    print("Running matched controls (60d)...")
    matched = {}
    for comp_name, trig_df in triggers.items():
        if trig_df.empty:
            matched[comp_name] = {}
            continue
        matched[comp_name] = {}
        for asset in ASSETS:
            matched[comp_name][asset] = matched_control(trig_df, components[comp_name], etf, asset, horizon=60)

    # Write artifacts
    components.to_csv(OUTPUT / "x_agg_v3_component_series.csv")
    print(f"Wrote: {OUTPUT / 'x_agg_v3_component_series.csv'}")

    meta_path = OUTPUT / "x_agg_v3_metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {meta_path}")

    # Write triggers
    for comp_name, trig_df in triggers.items():
        trig_df.to_csv(OUTPUT / f"triggers_{comp_name}.csv", index=False)

    # Write comparison
    comp_path = OUTPUT / "x_agg_v3_comparison.json"
    comp_path.write_text(json.dumps(comparison, indent=2, default=str), encoding="utf-8")
    print(f"Wrote: {comp_path}")

    # Generate report
    report = generate_report(components, metadata, triggers, fwd_returns, matched, comparison)
    (OUTPUT / "X_AGG_V3_REPORT.md").write_text(report, encoding="utf-8")
    print(f"Wrote: {OUTPUT / 'X_AGG_V3_REPORT.md'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
