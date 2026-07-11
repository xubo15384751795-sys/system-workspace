"""K Measurement Gate — validate K proxy quality.

This module builds K v2 components and tests:
- Correlation with VIX
- Event coverage
- Correlation with M/D
- Rolling stability

Usage:
    from workbench.signals.k_gate import run_gate

    report = run_gate()
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
BP_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"


def _cross_asset_panel_path() -> Path:
    """Prefer fresher of Harvester canonical vs workspace mirror.

    Finalized Harvester releases are read-only; weekly mirror refresh can lead.
    """
    harvester = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "cross_asset_daily_panel.parquet"
    mirror = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    candidates = [path for path in (harvester, mirror) if path.exists()]
    if not candidates:
        return harvester
    if len(candidates) == 1:
        return candidates[0]

    def _max_date(path: Path) -> pd.Timestamp:
        frame = pd.read_parquet(path, columns=["date"])
        if frame.empty:
            return pd.Timestamp.min
        return pd.to_datetime(frame["date"]).max()

    return max(candidates, key=_max_date)
OUTPUT_DIR = ROOT / "Output" / "k_measurement"

EVENTS = {
    "GFC 2008": ("2008-06-01", "2009-03-01"),
    "Flash Crash 2010": ("2010-04-01", "2010-07-01"),
    "Taper Tantrum 2013": ("2013-05-01", "2013-09-01"),
    "China Deval 2015": ("2015-07-01", "2015-10-01"),
    "Volmageddon 2018": ("2018-01-01", "2018-04-01"),
    "COVID 2020": ("2020-02-01", "2020-05-01"),
    "SVB 2023": ("2023-02-01", "2023-05-01"),
    "Carry Unwind 2024": ("2024-07-01", "2024-09-01"),
}

MAX_VIX_CORRELATION = 0.85
MIN_EVENT_COVERAGE = 0.5
MAX_MD_CORRELATION = 0.7
MIN_ROLLING_STABILITY = 0.5
MIN_SAMPLE_DAYS = 500


def load_panel() -> pd.DataFrame:
    """Load the benchmark panel parquet file."""
    bp = pd.read_parquet(BP_PATH)
    bp["date"] = pd.to_datetime(bp["date"])
    return bp


def load_etf() -> pd.DataFrame:
    """Load the cross-asset daily ETF panel parquet file."""
    etf = pd.read_parquet(_cross_asset_panel_path())
    etf["date"] = pd.to_datetime(etf["date"])
    return etf


def get_series(panel: pd.DataFrame, series_id: str) -> pd.Series:
    """Extract a single time series from the benchmark panel by series_id."""
    subset = panel[panel["series_id"] == series_id].sort_values("date").drop_duplicates("date")
    if subset.empty:
        return pd.Series(dtype=float)
    return subset.set_index("date")["value"]


def rolling_z(series: pd.Series, window: int = 252) -> pd.Series:
    """Compute rolling z-score with clipping to [-5, 5]."""
    mu = series.rolling(window, min_periods=60).mean()
    sigma = series.rolling(window, min_periods=60).std().replace(0, np.nan)
    return ((series - mu) / sigma).clip(-5, 5)


def build_k_v2_components(panel: pd.DataFrame, etf: pd.DataFrame) -> dict[str, pd.Series]:
    """Build K v2 component series: implied_vol_surface, realized_transition, cross_asset_curvature, rates_vol."""
    components = {}

    # Implied vol surface
    skew = rolling_z(get_series(panel, "CBOE:SKEW"))
    vvix = rolling_z(get_series(panel, "CBOE:VVIX"))
    vix9d = rolling_z(get_series(panel, "CBOE:VIX9D"))
    vix3m = rolling_z(get_series(panel, "CBOE:VIX3M"))
    vix6m = rolling_z(get_series(panel, "CBOE:VIX6M"))
    vix_slope_short = vix9d - vix3m
    vix_slope_long = vix3m - vix6m
    components["implied_vol_surface"] = pd.concat([
        skew.rename("SKEW"), vvix.rename("VVIX"),
        vix_slope_short.rename("VIX_slope_short"), vix_slope_long.rename("VIX_slope_long"),
    ], axis=1).mean(axis=1, skipna=True)

    # Realized transition
    spy = etf[etf["symbol"] == "SPY"].set_index("date")["close"].astype(float)
    tlt = etf[etf["symbol"] == "TLT"].set_index("date")["close"].astype(float)
    ret = spy.pct_change()
    vol_5d = ret.rolling(5).std() * np.sqrt(252)
    vol_20d = ret.rolling(20).std() * np.sqrt(252)
    vol_jump = rolling_z(vol_5d - vol_20d)
    corr_spy_tlt = ret.rolling(60).corr(tlt.pct_change())
    corr_break = rolling_z(-corr_spy_tlt)
    sectors = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
    sector_rets = pd.DataFrame({
        sym: etf[etf["symbol"] == sym].set_index("date")["close"].astype(float).pct_change()
        for sym in sectors
    })
    sector_disp = rolling_z(sector_rets.rolling(20).std().mean(axis=1) * np.sqrt(252))
    components["realized_transition"] = pd.concat([
        vol_jump.rename("vol_jump"), corr_break.rename("corr_break"), sector_disp.rename("sector_disp"),
    ], axis=1).mean(axis=1, skipna=True)

    # Cross-asset curvature
    hyg = etf[etf["symbol"] == "HYG"].set_index("date")["close"].astype(float)
    kre = etf[etf["symbol"] == "KRE"].set_index("date")["close"].astype(float)
    xlf = etf[etf["symbol"] == "XLF"].set_index("date")["close"].astype(float)
    components["cross_asset_curvature"] = pd.concat([
        rolling_z(hyg / tlt).rename("HYG_TLT"),
        rolling_z(kre / spy).rename("KRE_SPY"),
        rolling_z(xlf / spy).rename("XLF_SPY"),
    ], axis=1).mean(axis=1, skipna=True)

    # Rates vol
    move = rolling_z(get_series(panel, "CBOE:MOVE"))
    tyvix = rolling_z(get_series(panel, "CBOE:TYVIX"))
    components["rates_vol"] = pd.concat([move.rename("MOVE"), tyvix.rename("TYVIX")], axis=1).mean(axis=1, skipna=True)

    return components


def build_k_composite(components: dict[str, pd.Series]) -> pd.Series:
    """Average all K component series into a single K composite."""
    df = pd.DataFrame(components)
    return df.mean(axis=1, skipna=True)


def test_vix_correlation(k: pd.Series, panel: pd.DataFrame) -> dict[str, Any]:
    """Test correlation with VIX."""
    # Try CBOE:VIX first, then FRED:VIXCLS as fallback
    vix = rolling_z(get_series(panel, "CBOE:VIX"))
    if vix.empty:
        vix = rolling_z(get_series(panel, "FRED:VIXCLS"))
        if vix.empty:
            return {"status": "NOT_AVAILABLE", "correlation": None, "reason": "No VIX data"}

    aligned = pd.DataFrame({"K": k, "VIX": vix}).dropna()
    if len(aligned) < 100:
        return {"status": "INSUFFICIENT_DATA", "correlation": None, "rows": len(aligned)}
    corr = aligned["K"].corr(aligned["VIX"])
    passed = abs(corr) < MAX_VIX_CORRELATION
    return {"status": "PASS" if passed else "FAIL", "correlation": round(corr, 4), "threshold": MAX_VIX_CORRELATION, "rows": len(aligned)}


def test_event_coverage(k: pd.Series) -> dict[str, Any]:
    """Test whether K has data coverage during major market stress events."""
    covered = 0
    total = len(EVENTS)
    details = {}
    for event_name, (start, end) in EVENTS.items():
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        window = k[(k.index >= start_ts) & (k.index <= end_ts)]
        has_data = len(window.dropna()) > 0
        if has_data:
            covered += 1
        details[event_name] = {"has_data": has_data, "observations": len(window.dropna())}
    coverage = covered / total if total > 0 else 0
    passed = coverage >= MIN_EVENT_COVERAGE
    return {"status": "PASS" if passed else "FAIL", "coverage": round(coverage, 3), "covered": covered, "total": total, "details": details}


def test_md_correlation(k: pd.Series, panel: pd.DataFrame) -> dict[str, Any]:
    """Test that K correlation with M and D proxies stays below threshold."""
    dff = rolling_z(get_series(panel, "FRED:DFF"))
    t10y2y = rolling_z(get_series(panel, "FRED:T10Y2Y"))
    m_proxy = rolling_z(dff - t10y2y)
    d_proxy = rolling_z(get_series(panel, "FRED:NFCI"))
    aligned = pd.DataFrame({"K": k, "M": m_proxy, "D": d_proxy}).dropna()
    if len(aligned) < 100:
        return {"status": "INSUFFICIENT_DATA", "correlations": None, "rows": len(aligned)}
    corr_m = aligned["K"].corr(aligned["M"])
    corr_d = aligned["K"].corr(aligned["D"])
    passed_m = abs(corr_m) < MAX_MD_CORRELATION
    passed_d = abs(corr_d) < MAX_MD_CORRELATION
    return {"status": "PASS" if (passed_m and passed_d) else "FAIL", "correlation_M": round(corr_m, 4), "correlation_D": round(corr_d, 4), "rows": len(aligned)}


def test_rolling_stability(k: pd.Series, window: int = 252) -> dict[str, Any]:
    """Test K rolling stability via autocorrelation and variance coefficient of variation."""
    if len(k.dropna()) < window * 2:
        return {"status": "INSUFFICIENT_DATA", "stability": None}

    # Use autocorrelation as stability metric
    # A stable series should have high autocorrelation
    autocorr = k.autocorr(lag=1)

    # Also check variance stability (rolling std should be relatively constant)
    rolling_std = k.rolling(window).std()
    std_cv = rolling_std.std() / rolling_std.mean() if rolling_std.mean() > 0 else float("inf")

    # Combined stability: high autocorrelation + low std variation
    stability = max(0, autocorr) * (1.0 / (1.0 + std_cv))

    passed = stability >= MIN_ROLLING_STABILITY
    return {"status": "PASS" if passed else "FAIL", "stability": round(stability, 4), "autocorrelation": round(autocorr, 4), "std_cv": round(std_cv, 4), "sample_days": len(k.dropna())}


def run_gate() -> dict[str, Any]:
    """Run the full K measurement gate: build components, run all tests, return verdict.

    Returns a dict with gate_verdict (PASS/FAIL/WATCH), individual test results,
    component statistics, and composite statistics.
    """
    panel = load_panel()
    etf = load_etf()
    components = build_k_v2_components(panel, etf)
    k = build_k_composite(components)
    vix_test = test_vix_correlation(k, panel)
    event_test = test_event_coverage(k)
    md_test = test_md_correlation(k, panel)
    stability_test = test_rolling_stability(k)
    tests = [vix_test, event_test, md_test, stability_test]
    statuses = [t["status"] for t in tests]
    if all(s == "PASS" for s in statuses):
        verdict = "PASS"
    elif any(s == "FAIL" for s in statuses):
        verdict = "FAIL"
    else:
        verdict = "WATCH"
    return {
        "schema_version": "system.k_measurement_gate.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "gate_verdict": verdict,
        "tests": {"vix_correlation": vix_test, "event_coverage": event_test, "md_correlation": md_test, "rolling_stability": stability_test},
        "components": {name: {"observations": len(s.dropna()), "mean": round(float(s.mean()), 4), "std": round(float(s.std()), 4)} for name, s in components.items()},
        "composite": {"observations": len(k.dropna()), "mean": round(float(k.mean()), 4), "std": round(float(k.std()), 4)},
    }


def format_markdown(report: dict[str, Any]) -> str:
    """Format a K gate report as Markdown for human consumption."""
    lines = [
        "# K Measurement Gate Report",
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
        if "coverage" in test and test["coverage"] is not None:
            details.append(f"coverage={test['coverage']:.1%}")
        if "stability" in test and test["stability"] is not None:
            details.append(f"stability={test['stability']:.3f}")
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
        "## Composite",
        "",
        f"- Observations: {report['composite']['observations']:,}",
        f"- Mean: {report['composite']['mean']:.3f}",
        f"- Std: {report['composite']['std']:.3f}",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    """Write K gate report as JSON and Markdown to Output/k_measurement/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "k_measurement_gate.json"
    md_path = OUTPUT_DIR / "K_MEASUREMENT_GATE.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
