#!/usr/bin/env python3
"""X_agg Daily-Only Retest.

Retests X_agg using ONLY daily-frequency proxies (no quarterly forward-fill).
Validates whether X_agg_daily_component can produce meaningful daily triggers.

Output: Output/x_agg_daily_retest/
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Output" / "x_agg_daily_retest"
REPLAY_DIR = ROOT / "Output" / "sandbox" / "structural_replay_v2"
COMP_PATH = REPLAY_DIR / "proxy_components.parquet"
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"

# Only daily-frequency proxies
DAILY_PROXIES = [
    "X_agg_hidden_leverage_ofr",       # OFR_FSI, daily
    "X_agg_v1_treasury_debt_pressure",  # TREASURY_DEBT, daily
    "X_agg_v2_treasury_cash_balance",   # TREASURY_CASH, daily
    "X_agg_v3_sofr_iorb_spread",        # DERIVED_FUNDING, daily
]

ASSETS = ["SPY", "XLF", "KRE", "HYG", "LQD", "TLT"]
HORIZONS = [20, 60, 120]


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    comp = pd.read_parquet(COMP_PATH)
    if "date" not in comp.columns:
        comp = comp.reset_index()
        comp.rename(columns={comp.columns[0]: "date"}, inplace=True)
    comp["date"] = pd.to_datetime(comp["date"])

    etf = pd.read_parquet(ETF_PANEL)
    etf["date"] = pd.to_datetime(etf["date"])
    return comp, etf


def build_x_agg_daily(comp: pd.DataFrame) -> pd.Series:
    """Compute X_agg_daily as mean of daily proxies only."""
    available = [c for c in DAILY_PROXIES if c in comp.columns]
    if not available:
        raise ValueError("No daily X_agg proxies found in data")
    daily = comp[available].mean(axis=1, skipna=True)
    daily.index = comp["date"]
    return daily


def compute_zscore(series: pd.Series, window: int = 252) -> pd.Series:
    """Rolling z-score."""
    mu = series.rolling(window, min_periods=60).mean()
    sigma = series.rolling(window, min_periods=60).std().replace(0, np.nan)
    return ((series - mu) / sigma).clip(-5, 5)


def detect_triggers(z: pd.Series, threshold: float = 1.5) -> pd.DataFrame:
    """Detect days where z-score exceeds threshold."""
    triggers = z[z >= threshold].copy()
    triggers = triggers.reset_index()
    triggers.columns = ["date", "z_score"]
    triggers["trigger_type"] = "X_daily_positive_spike"
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
        # Find nearest trading day on or after trigger
        future = etf_asset[etf_asset.index >= trigger_date]
        if future.empty:
            continue

        base_price = future.iloc[0]["close"]
        rec = {
            "trigger_date": trigger_date,
            "z_score": row["z_score"],
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


def matched_control(
    triggers: pd.DataFrame, z: pd.Series, etf: pd.DataFrame,
    asset: str, horizon: int = 60
) -> pd.DataFrame:
    """Simple matched control: find non-trigger days with similar z-score range."""
    etf_asset = etf[etf["symbol"] == asset].set_index("date").sort_index()
    if etf_asset.empty:
        return pd.DataFrame()

    results = []
    for _, row in triggers.iterrows():
        trigger_date = row["date"]
        trigger_z = row["z_score"]

        # Find control: similar z-score but not a trigger (z < threshold)
        z_vals = z.dropna()
        control_candidates = z_vals[
            (z_vals >= trigger_z - 0.5) &
            (z_vals <= trigger_z + 0.5) &
            (z_vals < 1.0)  # not a trigger
        ]
        control_candidates = control_candidates[control_candidates.index != trigger_date]

        if control_candidates.empty:
            continue

        # Pick closest date
        control_date = control_candidates.index[
            np.argmin(np.abs((control_candidates.index - trigger_date).days))
        ]

        # Compute forward return for control
        future_ctrl = etf_asset[etf_asset.index >= control_date]
        if len(future_ctrl) <= horizon:
            continue

        ctrl_base = future_ctrl.iloc[0]["close"]
        ctrl_return = (future_ctrl.iloc[horizon]["close"] / ctrl_base - 1) * 100

        # Compute forward return for trigger
        future_trig = etf_asset[etf_asset.index >= trigger_date]
        if len(future_trig) <= horizon:
            continue

        trig_base = future_trig.iloc[0]["close"]
        trig_return = (future_trig.iloc[horizon]["close"] / trig_base - 1) * 100

        results.append({
            "trigger_date": trigger_date,
            "control_date": control_date,
            "trigger_z": trigger_z,
            "control_z": round(float(control_candidates.loc[control_date]), 3),
            "trigger_return": round(trig_return, 2),
            "control_return": round(ctrl_return, 2),
            "excess": round(trig_return - ctrl_return, 2),
        })

    return pd.DataFrame(results)


def coverage_by_year(z: pd.Series) -> dict:
    """Check data coverage by year."""
    nn = z.dropna()
    if nn.empty:
        return {}
    yearly = nn.groupby(nn.index.year).count()
    return {int(y): int(c) for y, c in yearly.items()}


def generate_report(
    x_daily: pd.Series,
    z: pd.Series,
    triggers: pd.DataFrame,
    fwd_returns: dict[str, pd.DataFrame],
    matched: dict[str, pd.DataFrame],
    cov_by_year: dict,
) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    nn = x_daily.notna().sum()
    total = len(x_daily)
    coverage = nn / total if total > 0 else 0

    lines = [
        "# X_agg Daily-Only Retest Report",
        "",
        f"**Generated:** {now}",
        f"**Purpose:** Validate X_agg_daily_component as standalone daily trigger source.",
        "",
        "---",
        "",
        "## 1. X_agg Daily Component Status",
        "",
        f"- **Proxies used:** {', '.join(DAILY_PROXIES)}",
        f"- **Total observations:** {nn}/{total} ({coverage*100:.1f}%)",
        f"- **Mean:** {x_daily.dropna().mean():.4f}",
        f"- **Std:** {x_daily.dropna().std():.4f}",
        f"- **Last value:** {x_daily.dropna().iloc[-1]:.4f}" if nn > 0 else "- **Last value:** N/A",
        "",
        "## 2. Coverage by Year",
        "",
        "| Year | Observations |",
        "|---|---:|",
    ]

    for year, count in sorted(cov_by_year.items()):
        lines.append(f"| {year} | {count} |")

    lines += [
        "",
        "## 3. Trigger Detection",
        "",
        f"- **Threshold:** z ≥ 1.5",
        f"- **Total triggers:** {len(triggers)}",
    ]

    if not triggers.empty:
        lines += [
            "",
            "| Date | Z-Score |",
            "|---|---:|",
        ]
        for _, row in triggers.head(20).iterrows():
            lines.append(f"| {row['date'].strftime('%Y-%m-%d')} | {row['z_score']:.3f} |")

    lines += [
        "",
        "## 4. Forward Returns",
        "",
    ]

    for asset, fwd in fwd_returns.items():
        if fwd.empty:
            lines.append(f"### {asset}: No data")
            continue

        lines += [
            f"### {asset}",
            "",
            "| Trigger Date | Z-Score | 20d | 60d | 120d |",
            "|---|---:|---:|---:|---:|",
        ]
        for _, row in fwd.head(15).iterrows():
            r20 = f"{row.get('return_20d', 'N/A')}%" if pd.notna(row.get('return_20d')) else "N/A"
            r60 = f"{row.get('return_60d', 'N/A')}%" if pd.notna(row.get('return_60d')) else "N/A"
            r120 = f"{row.get('return_120d', 'N/A')}%" if pd.notna(row.get('return_120d')) else "N/A"
            lines.append(
                f"| {row['trigger_date'].strftime('%Y-%m-%d')} | {row['z_score']:.3f} | {r20} | {r60} | {r120} |"
            )

        # Summary stats
        for h in HORIZONS:
            col = f"return_{h}d"
            valid = fwd[col].dropna()
            if not valid.empty:
                lines.append(f"\n**{h}d:** mean={valid.mean():.2f}%, n={len(valid)}, hit_rate={sum(valid > 0)/len(valid)*100:.0f}%")

    lines += [
        "",
        "## 5. Matched Control",
        "",
    ]

    for asset, mc in matched.items():
        if mc.empty:
            lines.append(f"### {asset}: No matched control data")
            continue

        lines += [
            f"### {asset} (60d horizon)",
            "",
            "| Trigger Date | Trigger Z | Control Z | Trigger Ret | Control Ret | Excess |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for _, row in mc.head(15).iterrows():
            lines.append(
                f"| {row['trigger_date'].strftime('%Y-%m-%d')} | {row['trigger_z']:.3f} | "
                f"{row['control_z']:.3f} | {row['trigger_return']:.2f}% | "
                f"{row['control_return']:.2f}% | {row['excess']:.2f}% |"
            )

        avg_excess = mc["excess"].mean()
        lines.append(f"\n**Average excess (trigger - control):** {avg_excess:.2f}%")

    lines += [
        "",
        "---",
        "",
        "## 6. Answers",
        "",
    ]

    # Q1: Sufficient sample?
    if nn > 500:
        lines.append("**Q: Sufficient sample?** YES — enough daily observations exist.")
    elif nn > 100:
        lines.append("**Q: Sufficient sample?** MARGINAL — some data exists but gaps are significant.")
    else:
        lines.append("**Q: Sufficient sample?** NO — insufficient daily observations.")

    # Q2: Daily trigger expression?
    if not triggers.empty and len(triggers) >= 5:
        lines.append(f"**Q: Daily-only X trigger exists?** YES — {len(triggers)} triggers detected at z≥1.5.")
    elif not triggers.empty:
        lines.append(f"**Q: Daily-only X trigger exists?** MARGINAL — only {len(triggers)} triggers.")
    else:
        lines.append("**Q: Daily-only X trigger exists?** NO — no triggers detected at z≥1.5.")

    # Q3: Can replace composite?
    lines.append("**Q: Can daily-only replace contaminated composite?**")
    lines.append("Pending forward return and matched control analysis above.")

    # Q4: What data to supplement?
    lines.append(
        "**Q: What daily data to supplement?** "
        "FINRA margin debt, ETF flows, repo/reverse-repo, commercial paper, dealer leverage proxy."
    )

    # Q5: Retain as diagnostic?
    lines.append("**Q: Retain X_daily as diagnostic candidate?**")
    if nn > 100 and not triggers.empty:
        lines.append("YES — retain as DAILY_DIAGNOSTIC_CANDIDATE with RESTRICTED status.")
    else:
        lines.append("INSUFFICIENT EVIDENCE — need more data before upgrading.")

    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    comp, etf = load_data()

    print("Building X_agg_daily component...")
    x_daily = build_x_agg_daily(comp)

    print("Computing z-scores...")
    z = compute_zscore(x_daily)

    print("Detecting triggers (z ≥ 1.5)...")
    triggers = detect_triggers(z, threshold=1.5)

    print(f"Found {len(triggers)} triggers.")

    print("Computing forward returns...")
    fwd_returns = {}
    for asset in ASSETS:
        fwd_returns[asset] = compute_forward_returns(triggers, etf, asset, HORIZONS)
        print(f"  {asset}: {len(fwd_returns[asset])} records")

    print("Running matched controls (60d)...")
    matched = {}
    for asset in ASSETS:
        matched[asset] = matched_control(triggers, z, etf, asset, horizon=60)
        print(f"  {asset}: {len(matched[asset])} pairs")

    print("Computing coverage by year...")
    cov = coverage_by_year(x_daily)

    # Write trigger sample
    trigger_path = OUTPUT / "x_daily_trigger_sample.csv"
    triggers.to_csv(trigger_path, index=False)
    print(f"Wrote: {trigger_path}")

    # Write forward returns
    all_fwd = pd.concat(fwd_returns.values(), ignore_index=True) if fwd_returns else pd.DataFrame()
    fwd_path = OUTPUT / "x_daily_forward_returns.csv"
    all_fwd.to_csv(fwd_path, index=False)
    print(f"Wrote: {fwd_path}")

    # Write matched control
    all_mc = pd.concat(matched.values(), ignore_index=True) if matched else pd.DataFrame()
    mc_path = OUTPUT / "x_daily_matched_control.csv"
    all_mc.to_csv(mc_path, index=False)
    print(f"Wrote: {mc_path}")

    # Write component series
    series_df = pd.DataFrame({"date": comp["date"], "X_agg_daily": x_daily.values, "z_score": z.values})
    series_path = OUTPUT / "x_daily_component_series.csv"
    series_df.to_csv(series_path, index=False)
    print(f"Wrote: {series_path}")

    # Generate report
    report = generate_report(x_daily, z, triggers, fwd_returns, matched, cov)
    report_path = OUTPUT / "X_AGG_DAILY_RETEST_REPORT.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote: {report_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
