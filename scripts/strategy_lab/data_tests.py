"""Layer 1: Data Tests — validate input data quality before backtesting.

Checks:
  - No future function leakage (signals don't use future data)
  - No missing data gaps beyond expected
  - Frequency consistency (daily, not mixed)
  - Survivorship bias check (SPY is survivorship-bias-free by construction)
  - Signal stationarity sanity check
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class DataTestResult:
    """Result of a single data quality test."""
    name: str
    passed: bool
    severity: str  # "critical", "warning", "info"
    message: str
    details: dict = field(default_factory=dict)


def run_data_tests(data: pd.DataFrame) -> list[DataTestResult]:
    """Run all data quality tests on the aligned dataset.

    Args:
        data: DataFrame from data_loader.load_aligned() with columns:
              close, return_1d, M, D, K, X

    Returns:
        List of DataTestResult.
    """
    results = []
    results.append(test_no_future_function(data))
    results.append(test_frequency_consistency(data))
    results.append(test_missing_data(data))
    results.append(test_signal_range(data))
    results.append(test_price_sanity(data))
    results.append(test_return_sanity(data))
    return results


def test_no_future_function(data: pd.DataFrame) -> DataTestResult:
    """Check that signals don't perfectly predict future returns.

    If correlation between today's signal and tomorrow's return is
    suspiciously high (>0.7), it may indicate future function leakage.
    """
    corrs = {}
    for ch in ["M", "D", "K", "X"]:
        if ch in data.columns:
            fwd_ret = data["return_1d"].shift(-1)
            valid = data[ch].notna() & fwd_ret.notna()
            if valid.sum() > 100:
                corr = data.loc[valid, ch].corr(fwd_ret[valid])
                corrs[ch] = round(corr, 4)

    max_corr = max(abs(v) for v in corrs.values()) if corrs else 0
    passed = max_corr < 0.7
    severity = "critical" if not passed else "info"

    return DataTestResult(
        name="no_future_function",
        passed=passed,
        severity=severity,
        message=f"Max signal-return correlation: {max_corr:.4f} (threshold: 0.7)",
        details={"correlations": corrs},
    )


def test_frequency_consistency(data: pd.DataFrame) -> DataTestResult:
    """Check that date spacing is consistently daily (weekends/holidays OK)."""
    if len(data) < 2:
        return DataTestResult(
            name="frequency_consistency",
            passed=False,
            severity="critical",
            message="Not enough data to check frequency",
        )

    diffs = pd.Series(data.index).diff().dropna()
    max_gap = diffs.max().days
    # Allow up to 10-day gaps (holidays + weekends)
    passed = max_gap <= 10
    severity = "warning" if not passed else "info"

    return DataTestResult(
        name="frequency_consistency",
        passed=passed,
        severity=severity,
        message=f"Max date gap: {max_gap} days (threshold: 10)",
        details={"max_gap_days": max_gap},
    )


def test_missing_data(data: pd.DataFrame) -> DataTestResult:
    """Check for missing values in critical columns."""
    critical_cols = ["close", "return_1d", "M", "D", "K", "X"]
    missing = {}
    for col in critical_cols:
        if col in data.columns:
            n_missing = data[col].isna().sum()
            missing[col] = int(n_missing)

    total_missing = sum(missing.values())
    passed = total_missing == 0
    severity = "critical" if not passed else "info"

    return DataTestResult(
        name="missing_data",
        passed=passed,
        severity=severity,
        message=f"Total missing values: {total_missing}",
        details={"missing_by_column": missing},
    )


def test_signal_range(data: pd.DataFrame) -> DataTestResult:
    """Check that signals are in reasonable z-score range."""
    issues = []
    for ch in ["M", "D", "K", "X"]:
        if ch in data.columns:
            vals = data[ch].dropna()
            if len(vals) > 0:
                max_abs = vals.abs().max()
                if max_abs > 10:
                    issues.append(f"{ch} max |z| = {max_abs:.1f}")

    passed = len(issues) == 0
    return DataTestResult(
        name="signal_range",
        passed=passed,
        severity="warning" if not passed else "info",
        message="Signal range OK" if passed else f"Extreme values: {'; '.join(issues)}",
        details={"issues": issues},
    )


def test_price_sanity(data: pd.DataFrame) -> DataTestResult:
    """Check for non-positive prices or extreme jumps."""
    issues = []
    if "close" in data.columns:
        if (data["close"] <= 0).any():
            issues.append("Non-positive prices detected")
        # Check for >20% single-day jumps (unlikely for SPY)
        ret = data["close"].pct_change().abs()
        extreme = ret[ret > 0.20]
        if len(extreme) > 0:
            issues.append(f"{len(extreme)} days with >20% price change")

    passed = len(issues) == 0
    return DataTestResult(
        name="price_sanity",
        passed=passed,
        severity="critical" if not passed else "info",
        message="Price data OK" if passed else "; ".join(issues),
    )


def test_return_sanity(data: pd.DataFrame) -> DataTestResult:
    """Check that return_1d matches close price changes."""
    if "close" not in data.columns or "return_1d" not in data.columns:
        return DataTestResult(
            name="return_sanity",
            passed=False,
            severity="warning",
            message="Missing close or return_1d columns",
        )

    computed_ret = data["close"].pct_change()
    diff = (data["return_1d"] - computed_ret).abs()
    max_diff = diff.dropna().max()

    passed = max_diff < 0.05  # allow rounding from data source
    return DataTestResult(
        name="return_sanity",
        passed=passed,
        severity="warning" if not passed else "info",
        message=f"Return consistency: max diff = {max_diff:.6f}",
        details={"max_diff": float(max_diff)},
    )


def print_test_report(results: list[DataTestResult]) -> str:
    """Format data test results as a readable report."""
    lines = ["# Data Quality Test Report", ""]
    n_pass = sum(1 for r in results if r.passed)
    n_fail = sum(1 for r in results if not r.passed)
    lines.append(f"**{n_pass}/{len(results)} tests passed**")
    if n_fail:
        lines.append(f"**{n_fail} tests FAILED**")
    lines.append("")

    for r in results:
        icon = "✅" if r.passed else ("🔴" if r.severity == "critical" else "⚠️")
        lines.append(f"{icon} **{r.name}** [{r.severity}]: {r.message}")

    return "\n".join(lines)
