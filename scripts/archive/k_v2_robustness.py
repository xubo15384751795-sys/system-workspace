#!/usr/bin/env python3
"""K_v2 Robustness Rebuild.

Builds K_v2 as a cross-asset regime stress indicator from available
credit, funding, and financial stress series.

K_v1 = implied tail risk (VIX term structure, SKEW, VVIX)
K_v2 = cross-asset regime stress (credit spreads, funding, financial stress)

Output: Data/benchmarks/K_v2/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Data" / "benchmarks" / "K_v2"
PANEL_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
REPLAY_DIR = ROOT / "Output" / "sandbox" / "structural_replay_v2"

# K_v2 component series
CREDIT_SERIES = [
    "FRED:BAMLH0A0HYM2",   # HY OAS
    "FRED:BAMLC0A0CM",     # IG OAS
    "FRED:BAMLC0A4CBBB",   # BBB OAS
]

FUNDING_SERIES = [
    "FRED:NFCI",            # Financial conditions
    "FRED:NFCILEVERAGE",    # Leverage sub-index
    "FRED:DCPF3M",          # CP rate
    "FRED:DGS3MO",          # T-bill rate
]

STRESS_SERIES = [
    "OFR_FSI",              # OFR Financial Stress Index
    "CISS",                 # Composite Indicator of Systemic Stress
    "FRED:STLFSI4",         # STL Fed Financial Stress
]

CURVE_SERIES = [
    "FRED:T10Y2Y",          # Yield curve shape
    "FRED:BAA10YM",         # Credit spread to Treasury
]

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
    """Extract a single series from the benchmark panel."""
    subset = panel[panel["series_id"] == series_id].copy()
    if subset.empty:
        return pd.Series(dtype=float)
    subset = subset.sort_values("date").drop_duplicates("date")
    return subset.set_index("date")["value"]


def rolling_zscore(series: pd.Series, window: int = 252) -> pd.Series:
    """Rolling z-score."""
    mu = series.rolling(window, min_periods=60).mean()
    sigma = series.rolling(window, min_periods=60).std().replace(0, np.nan)
    return ((series - mu) / sigma).clip(-5, 5)


def build_component(panel: pd.DataFrame, series_ids: list[str], name: str) -> pd.Series:
    """Build a component from multiple series by averaging z-scores."""
    zscores = []
    for sid in series_ids:
        s = extract_series(panel, sid)
        if s.empty:
            continue
        z = rolling_zscore(s)
        zscores.append(z)

    if not zscores:
        return pd.Series(dtype=float)

    # Combine into DataFrame and average
    df = pd.concat(zscores, axis=1)
    component = df.mean(axis=1, skipna=True)
    component.name = name
    return component


def build_k_v2(panel: pd.DataFrame) -> pd.DataFrame:
    """Build K_v2 from cross-asset components."""
    credit = build_component(panel, CREDIT_SERIES, "credit_stress")
    funding = build_component(panel, FUNDING_SERIES, "funding_stress")
    stress = build_component(panel, STRESS_SERIES, "financial_stress")
    curve = build_component(panel, CURVE_SERIES, "curve_stress")

    # Combine all components
    components = pd.DataFrame({
        "credit_stress": credit,
        "funding_stress": funding,
        "financial_stress": stress,
        "curve_stress": curve,
    })

    # K_v2 = mean of all components
    components["K_v2"] = components.mean(axis=1, skipna=True)
    components["K_v2_coverage"] = components.notna().sum(axis=1) / 4

    return components


def detect_triggers(k_v2: pd.Series, threshold: float = 1.5) -> pd.DataFrame:
    """Detect K_v2 stress triggers."""
    triggers = k_v2[k_v2 >= threshold].copy()
    triggers = triggers.reset_index()
    triggers.columns = ["date", "K_v2_value"]
    triggers["trigger_type"] = "K_v2_pos_stress"
    triggers["threshold"] = threshold
    return triggers


def compute_forward_returns(
    triggers: pd.DataFrame, etf: pd.DataFrame, asset: str, horizons: list[int]
) -> pd.DataFrame:
    """Compute forward returns for each trigger date."""
    etf_asset = etf[etf["symbol"] == asset].set_index("date").sort_index()
    if etf_asset.empty:
        return pd.DataFrame()

    results = []
    for _, row in triggers.iterrows():
        trigger_date = row["date"]
        future = etf_asset[etf_asset.index >= trigger_date]
        if future.empty:
            continue

        base_price = future.iloc[0]["close"]
        rec = {
            "trigger_date": trigger_date,
            "K_v2_value": row["K_v2_value"],
            "asset": asset,
            "base_price": base_price,
        }

        for h in horizons:
            if len(future) > h:
                fwd_price = future.iloc[h]["close"]
                ret = (fwd_price / base_price - 1) * 100
                rec[f"return_{h}d"] = round(ret, 2)
            else:
                rec[f"return_{h}d"] = None

        results.append(rec)

    return pd.DataFrame(results)


def generate_report(
    k_v2_components: pd.DataFrame,
    triggers: pd.DataFrame,
    fwd_returns: dict[str, pd.DataFrame],
) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    k_v2 = k_v2_components["K_v2"]
    nn = k_v2.notna().sum()
    total = len(k_v2)

    lines = [
        "# K_v2 Robustness Report — Cross-Asset Regime Stress",
        "",
        f"**Generated:** {now}",
        f"**Concept:** K_v2 measures cross-asset regime stress (credit + funding + financial stress + curve).",
        f"**Different from K_v1:** K_v1 = implied tail risk (VIX term structure, SKEW, VVIX).",
        "",
        "---",
        "",
        "## 1. K_v2 Component Status",
        "",
        "| Component | Series | Coverage | Mean | Last |",
        "|---|---|---:|---:|---:|",
    ]

    for col in ["credit_stress", "funding_stress", "financial_stress", "curve_stress"]:
        s = k_v2_components[col]
        nn_c = s.notna().sum()
        mean_c = s.dropna().mean() if nn_c > 0 else 0
        last_c = s.dropna().iloc[-1] if nn_c > 0 else 0
        series_map = {
            "credit_stress": "HY OAS, IG OAS, BBB OAS",
            "funding_stress": "NFCI, NFCI Leverage, CP rate, T-bill rate",
            "financial_stress": "OFR FSI, CISS, STLFSI4",
            "curve_stress": "T10Y2Y, BAA10YM",
        }
        lines.append(f"| {col} | {series_map.get(col, '?')} | {nn_c}/{total} ({nn_c/total*100:.1f}%) | {mean_c:.3f} | {last_c:.3f} |")

    lines += [
        "",
        f"**K_v2 overall:** {nn}/{total} ({nn/total*100:.1f}%)",
        f"**Mean:** {k_v2.dropna().mean():.4f}",
        f"**Std:** {k_v2.dropna().std():.4f}",
        f"**Last value:** {k_v2.dropna().iloc[-1]:.4f}" if nn > 0 else "",
        "",
        "## 2. Trigger Detection",
        "",
        f"- **Threshold:** K_v2 ≥ 1.5",
        f"- **Total triggers:** {len(triggers)}",
    ]

    if not triggers.empty:
        lines += [
            "",
            "| Date | K_v2 Value |",
            "|---|---:|",
        ]
        for _, row in triggers.head(20).iterrows():
            lines.append(f"| {row['date'].strftime('%Y-%m-%d')} | {row['K_v2_value']:.3f} |")

    lines += [
        "",
        "## 3. Forward Returns",
        "",
    ]

    for asset, fwd in fwd_returns.items():
        if fwd.empty:
            lines.append(f"### {asset}: No data")
            continue

        lines += [
            f"### {asset}",
            "",
            "| Trigger Date | K_v2 | 20d | 60d | 120d |",
            "|---|---:|---:|---:|---:|",
        ]
        for _, row in fwd.head(15).iterrows():
            r20 = f"{row.get('return_20d', 'N/A')}%" if pd.notna(row.get('return_20d')) else "N/A"
            r60 = f"{row.get('return_60d', 'N/A')}%" if pd.notna(row.get('return_60d')) else "N/A"
            r120 = f"{row.get('return_120d', 'N/A')}%" if pd.notna(row.get('return_120d')) else "N/A"
            lines.append(
                f"| {row['trigger_date'].strftime('%Y-%m-%d')} | {row['K_v2_value']:.3f} | {r20} | {r60} | {r120} |"
            )

        for h in HORIZONS:
            col = f"return_{h}d"
            valid = fwd[col].dropna()
            if not valid.empty:
                lines.append(f"\n**{h}d:** mean={valid.mean():.2f}%, n={len(valid)}, hit_rate={sum(valid > 0)/len(valid)*100:.0f}%")

    lines += [
        "",
        "---",
        "",
        "## 4. K_v1 vs K_v2 Comparison",
        "",
        "K_v1 and K_v2 measure different dimensions:",
        "- **K_v1:** Options market pricing of tail risk (VIX term structure, SKEW, VVIX)",
        "- **K_v2:** Actual cross-asset stress (credit spreads, funding conditions, financial stress indices)",
        "",
        "They should have low correlation because they measure different things.",
        "",
    ]

    # Compute correlation if both available
    k_v1_series = extract_series(pd.read_parquet(PANEL_PATH), "CBOE:SKEW")  # proxy for K_v1
    if not k_v1_series.empty:
        k_v1_z = rolling_zscore(k_v1_series)
        # Align dates
        aligned = pd.DataFrame({"K_v1": k_v1_z, "K_v2": k_v2}).dropna()
        if len(aligned) > 100:
            corr = aligned["K_v1"].corr(aligned["K_v2"])
            lines.append(f"**K_v1 (SKEW z-score) vs K_v2 correlation:** {corr:.3f}")

    lines += [
        "",
        "---",
        "",
        "## 5. Status",
        "",
        "- **K_v2 artifact:** REBUILT",
        "- **Status:** DAILY_DIAGNOSTIC_CANDIDATE",
        "- **Not yet in voting:** K_v2 does not affect cofire_count or dominant_channel",
        "- **Requires:** Forward return validation, matched control, robustness check",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    panel = load_panel()
    etf = load_etf()

    print("Building K_v2 components...")
    k_v2_components = build_k_v2(panel)

    print(f"K_v2: {k_v2_components['K_v2'].notna().sum()} non-null observations")

    print("Detecting triggers (K_v2 ≥ 1.5)...")
    triggers = detect_triggers(k_v2_components["K_v2"], threshold=1.5)
    print(f"Found {len(triggers)} triggers.")

    print("Computing forward returns...")
    fwd_returns = {}
    for asset in ASSETS:
        fwd_returns[asset] = compute_forward_returns(triggers, etf, asset, HORIZONS)
        print(f"  {asset}: {len(fwd_returns[asset])} records")

    # Write component series
    k_v2_components.to_csv(OUTPUT / "k_v2_component_series.csv")
    print(f"Wrote: {OUTPUT / 'k_v2_component_series.csv'}")

    # Write triggers
    triggers.to_csv(OUTPUT / "k_v2_triggers.csv", index=False)
    print(f"Wrote: {OUTPUT / 'k_v2_triggers.csv'}")

    # Write forward returns
    all_fwd = pd.concat(fwd_returns.values(), ignore_index=True) if fwd_returns else pd.DataFrame()
    all_fwd.to_csv(OUTPUT / "k_v2_forward_returns.csv", index=False)
    print(f"Wrote: {OUTPUT / 'k_v2_forward_returns.csv'}")

    # Write metadata
    metadata = {
        "k_v2_version": "1.0",
        "concept": "cross_asset_regime_stress",
        "components": ["credit_stress", "funding_stress", "financial_stress", "curve_stress"],
        "series_used": CREDIT_SERIES + FUNDING_SERIES + STRESS_SERIES + CURVE_SERIES,
        "threshold": 1.5,
        "total_triggers": len(triggers),
        "status": "DAILY_DIAGNOSTIC_CANDIDATE",
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (OUTPUT / "k_v2_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Wrote: {OUTPUT / 'k_v2_metadata.json'}")

    # Generate report
    report = generate_report(k_v2_components, triggers, fwd_returns)
    (OUTPUT / "K_V2_ROBUSTNESS_REPORT.md").write_text(report, encoding="utf-8")
    print(f"Wrote: {OUTPUT / 'K_V2_ROBUSTNESS_REPORT.md'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
