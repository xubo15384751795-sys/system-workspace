#!/usr/bin/env python3
"""K_v2 Robustness — z≥2.0 with matched control.

Enhanced version: stricter threshold, trigger deduplication, matched control.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Data" / "benchmarks" / "K_v2"
K_V2_SERIES = OUTPUT / "k_v2_component_series.csv"
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"

ASSETS = ["SPY", "XLF", "KRE", "HYG", "LQD", "TLT"]
HORIZONS = [20, 60, 120]
THRESHOLD = 2.0
DEDUP_GAP_DAYS = 30  # only keep first trigger within 30 days


def load_data() -> tuple[pd.Series, pd.DataFrame]:
    k2 = pd.read_csv(K_V2_SERIES, index_col=0, parse_dates=True)
    k_v2 = k2["K_v2"].dropna()

    etf = pd.read_parquet(ETF_PANEL)
    etf["date"] = pd.to_datetime(etf["date"])
    return k_v2, etf


def deduplicate_triggers(triggers: pd.Series, min_gap_days: int = 30) -> pd.Series:
    """Keep only first trigger in a cluster (min_gap_days between triggers)."""
    if triggers.empty:
        return triggers
    dates = triggers.index.sort_values()
    keep = [dates[0]]
    for d in dates[1:]:
        if (d - keep[-1]).days >= min_gap_days:
            keep.append(d)
    return triggers.loc[keep]


def detect_triggers(k_v2: pd.Series, threshold: float) -> pd.DataFrame:
    """Detect and deduplicate triggers."""
    raw = k_v2[k_v2 >= threshold]
    deduped = deduplicate_triggers(raw, DEDUP_GAP_DAYS)

    triggers = deduped.reset_index()
    triggers.columns = ["date", "K_v2_value"]
    triggers["trigger_type"] = "K_v2_pos_stress"
    triggers["threshold"] = threshold
    triggers["dedup_gap_days"] = DEDUP_GAP_DAYS
    return triggers


def compute_forward_returns(
    triggers: pd.DataFrame, etf: pd.DataFrame, asset: str, horizons: list[int]
) -> pd.DataFrame:
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


def matched_control(
    triggers: pd.DataFrame, k_v2: pd.Series, etf: pd.DataFrame,
    asset: str, horizon: int = 60
) -> pd.DataFrame:
    """Matched control: find non-trigger days with similar K_v2 value."""
    etf_asset = etf[etf["symbol"] == asset].set_index("date").sort_index()
    if etf_asset.empty:
        return pd.DataFrame()

    results = []
    for _, row in triggers.iterrows():
        trigger_date = row["date"]
        trigger_z = row["K_v2_value"]

        # Find control: similar K_v2 but below threshold
        k_vals = k_v2.dropna()
        control_candidates = k_vals[
            (k_vals >= trigger_z - 0.5) &
            (k_vals <= trigger_z + 0.5) &
            (k_vals < THRESHOLD)
        ]
        control_candidates = control_candidates[control_candidates.index != trigger_date]

        if control_candidates.empty:
            continue

        # Pick closest date
        idx = np.argmin(np.abs((control_candidates.index - trigger_date).days))
        control_date = control_candidates.index[idx]

        # Compute forward returns
        future_ctrl = etf_asset[etf_asset.index >= control_date]
        future_trig = etf_asset[etf_asset.index >= trigger_date]

        if len(future_ctrl) <= horizon or len(future_trig) <= horizon:
            continue

        ctrl_base = future_ctrl.iloc[0]["close"]
        ctrl_return = (future_ctrl.iloc[horizon]["close"] / ctrl_base - 1) * 100

        trig_base = future_trig.iloc[0]["close"]
        trig_return = (future_trig.iloc[horizon]["close"] / trig_base - 1) * 100

        results.append({
            "trigger_date": trigger_date,
            "control_date": control_date,
            "trigger_z": round(trigger_z, 3),
            "control_z": round(float(control_candidates.loc[control_date]), 3),
            "trigger_return": round(trig_return, 2),
            "control_return": round(ctrl_return, 2),
            "excess": round(trig_return - ctrl_return, 2),
        })

    return pd.DataFrame(results)


def generate_report(
    k_v2: pd.Series,
    triggers: pd.DataFrame,
    fwd_returns: dict[str, pd.DataFrame],
    matched: dict[str, pd.DataFrame],
) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# K_v2 Robustness — z≥2.0 with Matched Control",
        "",
        f"**Generated:** {now}",
        f"**Threshold:** z ≥ {THRESHOLD}",
        f"**Dedup gap:** {DEDUP_GAP_DAYS} days",
        "",
        "---",
        "",
        "## 1. Trigger Summary",
        "",
        f"- **Total deduplicated triggers:** {len(triggers)}",
        f"- **Date range:** {triggers['date'].min().strftime('%Y-%m-%d')} to {triggers['date'].max().strftime('%Y-%m-%d')}" if not triggers.empty else "",
        "",
    ]

    if not triggers.empty:
        lines += [
            "| Date | K_v2 Value |",
            "|---|---:|",
        ]
        for _, row in triggers.iterrows():
            lines.append(f"| {row['date'].strftime('%Y-%m-%d')} | {row['K_v2_value']:.3f} |")

    lines += [
        "",
        "## 2. Forward Returns",
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
        for _, row in fwd.iterrows():
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
        "## 3. Matched Control (60d)",
        "",
    ]

    for asset, mc in matched.items():
        if mc.empty:
            lines.append(f"### {asset}: No matched control data")
            continue

        lines += [
            f"### {asset}",
            "",
            "| Trigger Date | Trig Z | Ctrl Z | Trig Ret | Ctrl Ret | Excess |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for _, row in mc.iterrows():
            lines.append(
                f"| {row['trigger_date'].strftime('%Y-%m-%d')} | {row['trigger_z']:.3f} | "
                f"{row['control_z']:.3f} | {row['trigger_return']:.2f}% | "
                f"{row['control_return']:.2f}% | {row['excess']:.2f}% |"
            )

        avg_excess = mc["excess"].mean()
        n_positive = (mc["excess"] > 0).sum()
        lines.append(f"\n**Average excess (trigger - control):** {avg_excess:.2f}%")
        lines.append(f"**Trigger beats control:** {n_positive}/{len(mc)} ({n_positive/len(mc)*100:.0f}%)")

    lines += [
        "",
        "---",
        "",
        "## 4. Interpretation",
        "",
    ]

    # SPY summary
    spy_fwd = fwd_returns.get("SPY", pd.DataFrame())
    spy_mc = matched.get("SPY", pd.DataFrame())
    if not spy_fwd.empty:
        r60 = spy_fwd["return_60d"].dropna()
        lines.append(f"**SPY 60d:** mean={r60.mean():.2f}%, n={len(r60)}, hit_rate={sum(r60 > 0)/len(r60)*100:.0f}%")
    if not spy_mc.empty:
        lines.append(f"**SPY matched excess:** {spy_mc['excess'].mean():.2f}%, beats control {sum(spy_mc['excess'] > 0)}/{len(spy_mc)}")

    lines += [
        "",
        "## 5. Status",
        "",
        "- **K_v2 artifact:** REBUILT",
        "- **Status:** DAILY_DIAGNOSTIC_CANDIDATE",
        f"- **Triggers at z≥{THRESHOLD}:** {len(triggers)} (deduplicated)",
        "- **Not yet in voting:** K_v2 does not affect cofire_count or dominant_channel",
        "",
    ]

    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    k_v2, etf = load_data()

    print(f"K_v2: {len(k_v2)} observations, mean={k_v2.mean():.3f}, std={k_v2.std():.3f}")

    print(f"Detecting triggers (z ≥ {THRESHOLD}, dedup {DEDUP_GAP_DAYS}d)...")
    triggers = detect_triggers(k_v2, THRESHOLD)
    print(f"Found {len(triggers)} triggers.")

    print("Computing forward returns...")
    fwd_returns = {}
    for asset in ASSETS:
        fwd_returns[asset] = compute_forward_returns(triggers, etf, asset, HORIZONS)
        print(f"  {asset}: {len(fwd_returns[asset])} records")

    print("Running matched controls (60d)...")
    matched = {}
    for asset in ASSETS:
        matched[asset] = matched_control(triggers, k_v2, etf, asset, horizon=60)
        print(f"  {asset}: {len(matched[asset])} pairs")

    # Write triggers
    triggers.to_csv(OUTPUT / "k_v2_triggers_z2.csv", index=False)
    print(f"Wrote: {OUTPUT / 'k_v2_triggers_z2.csv'}")

    # Write forward returns
    all_fwd = pd.concat(fwd_returns.values(), ignore_index=True) if fwd_returns else pd.DataFrame()
    all_fwd.to_csv(OUTPUT / "k_v2_forward_returns_z2.csv", index=False)
    print(f"Wrote: {OUTPUT / 'k_v2_forward_returns_z2.csv'}")

    # Write matched control
    all_mc = pd.concat(matched.values(), ignore_index=True) if matched else pd.DataFrame()
    all_mc.to_csv(OUTPUT / "k_v2_matched_control_z2.csv", index=False)
    print(f"Wrote: {OUTPUT / 'k_v2_matched_control_z2.csv'}")

    # Generate report
    report = generate_report(k_v2, triggers, fwd_returns, matched)
    (OUTPUT / "K_V2_ROBUSTNESS_Z2_REPORT.md").write_text(report, encoding="utf-8")
    print(f"Wrote: {OUTPUT / 'K_V2_ROBUSTNESS_Z2_REPORT.md'}")

    print("\nDone.")


if __name__ == "__main__":
    main()
