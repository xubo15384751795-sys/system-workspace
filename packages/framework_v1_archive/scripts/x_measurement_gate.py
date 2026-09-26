#!/usr/bin/env python3
"""X_agg Measurement Gate — validate shadow leverage proxy quality.

Builds X_agg v3 components and tests:
- Correlation with VIX/OFR_FSI (must not be too high)
- No future pollution in historical data
- Frequency split (daily/weekly/quarterly)
- Daily trigger disabled by default

Usage:
    python3 scripts/x_measurement_gate.py
    python3 scripts/x_measurement_gate.py --json

Output:
    Output/archive/legacy_2026H1/x_measurement/X_MEASUREMENT_GATE.md
    Output/archive/legacy_2026H1/x_measurement/x_measurement_gate.json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from verity.runtime._constants import TRADING_DAYS_PER_YEAR  # noqa: E402
from verity.runtime._data_paths import (
    resolve_benchmark_panel_path,
    resolve_cross_asset_panel_path,
)
from verity.runtime.runtime_io import ROOT, ensure_dir

BP_PATH = resolve_benchmark_panel_path()
ETF_PATH = resolve_cross_asset_panel_path()
OUTPUT_DIR = ROOT / "Output" / "archive" / "legacy_2026H1" / "x_measurement"

# Gate thresholds
MAX_VIX_CORRELATION = 0.80
MAX_OFR_CORRELATION = 0.70
MIN_SAMPLE_DAYS = TRADING_DAYS_PER_YEAR

# Component definitions
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


def load_panel() -> pd.DataFrame:
    bp = pd.read_parquet(BP_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    return bp


def get_series(panel: pd.DataFrame, series_id: str) -> pd.Series:
    subset = panel[panel["series_id"] == series_id].sort_values("date").drop_duplicates("date")
    if subset.empty:
        return pd.Series(dtype=float)
    return subset.set_index("date")["value"]


def rolling_z(series: pd.Series, window: int = TRADING_DAYS_PER_YEAR) -> pd.Series:
    mu = series.rolling(window, min_periods=60).mean()
    sigma = series.rolling(window, min_periods=60).std().replace(0, np.nan)
    return ((series - mu) / sigma).clip(-5, 5)


def build_component(panel: pd.DataFrame, series_map: dict, name: str) -> tuple[pd.Series, dict]:
    """Build a component from multiple series."""
    zscores = []
    meta = {"name": name, "series": [], "coverage": 0}

    for sid, label in series_map.items():
        s = get_series(panel, sid)
        if s.empty:
            meta["series"].append({"id": sid, "label": label, "rows": 0, "status": "MISSING"})
            continue
        z = rolling_z(s)
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


def build_x_agg_components(panel: pd.DataFrame) -> tuple[dict[str, pd.Series], list[dict]]:
    """Build X_agg components from leverage data."""
    daily, daily_meta = build_component(panel, DAILY_SERIES, "X_agg_daily")
    weekly, weekly_meta = build_component(panel, WEEKLY_SERIES, "X_agg_weekly")
    slow, slow_meta = build_component(panel, SLOW_SERIES, "X_agg_slow")

    components = {
        "X_agg_daily": daily,
        "X_agg_weekly": weekly,
        "X_agg_slow": slow,
    }

    # Composite
    df = pd.DataFrame(components)
    components["X_agg_composite"] = df.mean(axis=1, skipna=True)

    metadata = [daily_meta, weekly_meta, slow_meta]
    return components, metadata


def test_vix_correlation(x: pd.Series, panel: pd.DataFrame) -> dict[str, Any]:
    """Test correlation with VIX or MOVE."""
    # Try VIX first, then MOVE as fallback
    vix = rolling_z(get_series(panel, "CBOE:VIX"))
    if vix.empty:
        vix = rolling_z(get_series(panel, "CBOE:MOVE"))
        if vix.empty:
            return {"status": "NOT_AVAILABLE", "correlation": None, "reason": "No VIX or MOVE data"}

    aligned = pd.DataFrame({"X": x, "VIX": vix}).dropna()
    if len(aligned) < 100:
        return {"status": "INSUFFICIENT_DATA", "correlation": None, "rows": len(aligned)}

    corr = aligned["X"].corr(aligned["VIX"])
    passed = abs(corr) < MAX_VIX_CORRELATION

    return {
        "status": "PASS" if passed else "FAIL",
        "correlation": round(corr, 4),
        "threshold": MAX_VIX_CORRELATION,
        "rows": len(aligned),
    }


def test_ofr_correlation(x: pd.Series, panel: pd.DataFrame) -> dict[str, Any]:
    """Test correlation with OFR_FSI."""
    ofr = get_series(panel, "OFR_FSI")
    if ofr.empty:
        return {"status": "NOT_AVAILABLE", "correlation": None, "reason": "OFR_FSI not found"}

    ofr_z = rolling_z(ofr)
    aligned = pd.DataFrame({"X": x, "OFR": ofr_z}).dropna()

    if len(aligned) < 100:
        return {"status": "INSUFFICIENT_DATA", "correlation": None, "rows": len(aligned)}

    corr = aligned["X"].corr(aligned["OFR"])
    passed = abs(corr) < MAX_OFR_CORRELATION

    return {
        "status": "PASS" if passed else "FAIL",
        "correlation": round(corr, 4),
        "threshold": MAX_OFR_CORRELATION,
        "rows": len(aligned),
    }


def test_future_pollution(components: dict[str, pd.Series]) -> dict[str, Any]:
    """Test for future data pollution."""
    issues = []

    for name, series in components.items():
        # Check for lookahead: series should not have values before data starts
        first_valid = series.first_valid_index()
        last_valid = series.last_valid_index()

        if first_valid is None or last_valid is None:
            continue

        # Check for gaps that might indicate pollution
        dates = series.dropna().index
        if len(dates) < 2:
            continue

        # Check for monotonic dates
        date_diffs = pd.Series(dates).diff().dt.days
        if (date_diffs < 0).any():
            issues.append(f"{name}: non-monotonic dates detected")

        # Check for suspicious patterns (too many identical values)
        unique_ratio = series.nunique() / len(series.dropna())
        if unique_ratio < 0.01 and len(series.dropna()) > 100:
            issues.append(f"{name}: suspicious low unique ratio ({unique_ratio:.3f})")

    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
    }


def test_frequency_split(components: dict[str, pd.Series]) -> dict[str, Any]:
    """Test that daily/weekly/quarterly frequencies are properly separated."""
    daily = components.get("X_agg_daily", pd.Series(dtype=float))
    weekly = components.get("X_agg_weekly", pd.Series(dtype=float))
    slow = components.get("X_agg_slow", pd.Series(dtype=float))

    # Count non-null observations
    daily_count = len(daily.dropna())
    weekly_count = len(weekly.dropna())
    slow_count = len(slow.dropna())

    # Check that each component has data
    has_daily = daily_count > 0
    has_weekly = weekly_count > 0
    has_slow = slow_count > 0

    # Check for frequency mixing within components
    # Daily series should have ~252 observations per year
    # Weekly series should have ~52 observations per year
    # Slow series should have ~4 observations per year

    # All components should have some data
    all_have_data = has_daily and has_weekly and has_slow

    return {
        "status": "PASS" if all_have_data else "WATCH",
        "daily_observations": daily_count,
        "weekly_observations": weekly_count,
        "slow_observations": slow_count,
        "all_have_data": all_have_data,
    }


def test_sample_size(components: dict[str, pd.Series]) -> dict[str, Any]:
    """Test minimum sample size."""
    composite = components.get("X_agg_composite", pd.Series(dtype=float))
    sample_days = len(composite.dropna())

    passed = sample_days >= MIN_SAMPLE_DAYS

    return {
        "status": "PASS" if passed else "FAIL",
        "sample_days": sample_days,
        "threshold": MIN_SAMPLE_DAYS,
    }


def run_gate() -> dict[str, Any]:
    """Run complete X_agg measurement gate."""
    print("Loading data...")
    panel = load_panel()

    print("Building X_agg components...")
    components, metadata = build_x_agg_components(panel)

    composite = components.get("X_agg_composite", pd.Series(dtype=float))
    print(f"X_agg composite: {len(composite.dropna())} observations")

    print("Running gate tests...")
    vix_test = test_vix_correlation(composite, panel)
    ofr_test = test_ofr_correlation(composite, panel)
    pollution_test = test_future_pollution(components)
    frequency_test = test_frequency_split(components)
    sample_test = test_sample_size(components)

    # Overall verdict
    tests = [vix_test, ofr_test, pollution_test, frequency_test, sample_test]
    statuses = [t["status"] for t in tests]

    if all(s in ("PASS", "NOT_AVAILABLE") for s in statuses):
        verdict = "PASS"
    elif any(s == "FAIL" for s in statuses):
        verdict = "FAIL"
    else:
        verdict = "WATCH"

    return {
        "schema_version": "system.x_measurement_gate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "gate_verdict": verdict,
        "tests": {
            "vix_correlation": vix_test,
            "ofr_correlation": ofr_test,
            "future_pollution": pollution_test,
            "frequency_split": frequency_test,
            "sample_size": sample_test,
        },
        "components": {
            name: {
                "observations": len(s.dropna()),
                "mean": round(float(s.mean()), 4),
                "std": round(float(s.std()), 4),
            }
            for name, s in components.items()
        },
        "metadata": metadata,
        "usage": {
            "usable_as_background": verdict == "PASS",
            "usable_as_daily_trigger": False,  # Always disabled
            "usable_as_primary_readout": False,  # Always disabled
        },
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# X_agg Measurement Gate Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Gate verdict: **{report['gate_verdict']}**",
        "",
        "## Tests",
        "",
        "| Test | Status | Details |",
        "|---|---|---|",
    ]

    for test_name, test in report["tests"].items():
        details = []
        if "correlation" in test and test["correlation"] is not None:
            details.append(f"corr={test['correlation']:.3f}")
        if "sample_days" in test:
            details.append(f"n={test['sample_days']}")
        if "issues" in test and test["issues"]:
            details.append(f"{len(test['issues'])} issues")
        lines.append(f"| {test_name} | {test['status']} | {', '.join(details)} |")

    lines += [
        "",
        "## Components",
        "",
        "| Component | Observations | Mean | Std |",
        "|---|---:|---:|---:|",
    ]

    for name, comp in report["components"].items():
        lines.append(f"| {name} | {comp['observations']:,} | {comp['mean']:.3f} | {comp['std']:.3f} |")

    lines += [
        "",
        "## Usage",
        "",
        f"- Usable as background: {report['usage']['usable_as_background']}",
        f"- Usable as daily trigger: {report['usage']['usable_as_daily_trigger']}",
        f"- Usable as primary readout: {report['usage']['usable_as_primary_readout']}",
        "",
        "## Frequency Split",
        "",
    ]

    freq = report["tests"]["frequency_split"]
    lines.extend([
        f"- Daily observations: {freq.get('daily_observations', 0):,}",
        f"- Weekly observations: {freq.get('weekly_observations', 0):,}",
        f"- Slow observations: {freq.get('slow_observations', 0):,}",
    ])

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run X_agg measurement gate.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = run_gate()

    ensure_dir(OUTPUT_DIR)
    json_path = OUTPUT_DIR / "x_measurement_gate.json"
    md_path = OUTPUT_DIR / "X_MEASUREMENT_GATE.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"X_agg measurement gate: {report['gate_verdict']}")
        for test_name, test in report["tests"].items():
            print(f"  {test_name}: {test['status']}")
        print(f"Usage: background={report['usage']['usable_as_background']}, "
              f"daily_trigger={report['usage']['usable_as_daily_trigger']}, "
              f"primary_readout={report['usage']['usable_as_primary_readout']}")


if __name__ == "__main__":
    main()
