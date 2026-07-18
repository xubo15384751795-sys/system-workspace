"""Layer 2: Signal Tests — validate M/D/K/X signal stability and quality.

Checks:
  - Signal stability: are M/D/K/X readings consistent across time?
  - State classification stability: does the regime router produce
    consistent classifications for similar input?
  - Discrimination: do signals actually differentiate between states?
  - No degenerate signals (constant, or all same value)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from scripts.strategy_lab.risk_gate import evaluate_day


@dataclass
class SignalTestResult:
    """Result of a single signal quality test."""
    name: str
    passed: bool
    severity: str
    message: str
    details: dict = field(default_factory=dict)


def run_signal_tests(data: pd.DataFrame) -> list[SignalTestResult]:
    """Run all signal quality tests.

    Args:
        data: DataFrame from data_loader.load_aligned().

    Returns:
        List of SignalTestResult.
    """
    results = []
    results.append(test_signal_variance(data))
    results.append(test_regime_distribution(data))
    results.append(test_regime_persistence(data))
    results.append(test_channel_independence(data))
    results.append(test_state_coverage(data))
    return results


def test_signal_variance(data: pd.DataFrame) -> SignalTestResult:
    """Check that each channel has meaningful variance (not degenerate)."""
    low_var = []
    for ch in ["M", "D", "K", "X"]:
        if ch in data.columns:
            std = data[ch].std()
            if std < 0.05:
                low_var.append(f"{ch} (std={std:.4f})")

    passed = len(low_var) == 0
    return SignalTestResult(
        name="signal_variance",
        passed=passed,
        severity="warning" if not passed else "info",
        message="All channels have meaningful variance" if passed else f"Low variance: {', '.join(low_var)}",
        details={ch: float(data[ch].std()) for ch in ["M", "D", "K", "X"] if ch in data.columns},
    )


def test_regime_distribution(data: pd.DataFrame) -> SignalTestResult:
    """Check that risk gate regimes are distributed (not all one regime)."""
    regimes = []
    for _, row in data[["M", "D", "K", "X"]].iterrows():
        state = evaluate_day(row["M"], row["D"], row["K"], row["X"])
        regimes.append(state.regime)

    dist = pd.Series(regimes).value_counts(normalize=True)
    max_prop = dist.iloc[0]
    dominant = dist.index[0]

    # If one regime dominates >90%, the gate may be too unbalanced
    passed = max_prop < 0.90
    return SignalTestResult(
        name="regime_distribution",
        passed=passed,
        severity="warning" if not passed else "info",
        message=f"Dominant regime: {dominant} ({max_prop:.1%})",
        details=dist.to_dict(),
    )


def test_regime_persistence(data: pd.DataFrame) -> SignalTestResult:
    """Check that regimes have reasonable persistence (not flipping daily).

    If regimes change every single day, the gate is noise.
    If a regime persists for >1 year, it may be stuck.
    """
    regimes = []
    for _, row in data[["M", "D", "K", "X"]].iterrows():
        state = evaluate_day(row["M"], row["D"], row["K"], row["X"])
        regimes.append(state.regime)

    regime_series = pd.Series(regimes, index=data.index)
    changes = (regime_series != regime_series.shift(1)).sum()
    change_rate = changes / len(regime_series)

    # Compute average regime duration
    groups = (regime_series != regime_series.shift(1)).cumsum()
    durations = regime_series.groupby(groups).size()
    avg_duration = durations.mean()
    max_duration = durations.max()

    # Reasonable: change rate between 1% and 30%, avg duration 3-100 days
    passed = 0.01 < change_rate < 0.30
    severity = "info" if passed else "warning"

    return SignalTestResult(
        name="regime_persistence",
        passed=passed,
        severity=severity,
        message=f"Regime change rate: {change_rate:.2%}, avg duration: {avg_duration:.0f}d, max: {max_duration}d",
        details={
            "change_rate": round(change_rate, 4),
            "avg_duration_days": round(avg_duration, 1),
            "max_duration_days": int(max_duration),
            "n_changes": int(changes),
        },
    )


def test_channel_independence(data: pd.DataFrame) -> SignalTestResult:
    """Check that channels are not perfectly correlated (redundancy check)."""
    channels = [c for c in ["M", "D", "K", "X"] if c in data.columns]
    if len(channels) < 2:
        return SignalTestResult(
            name="channel_independence",
            passed=True,
            severity="info",
            message="Not enough channels to check independence",
        )

    corr_matrix = data[channels].corr()
    # Find max off-diagonal correlation
    max_corr = 0
    pair = ("", "")
    for i, c1 in enumerate(channels):
        for j, c2 in enumerate(channels):
            if i < j:
                c = abs(corr_matrix.loc[c1, c2])
                if c > max_corr:
                    max_corr = c
                    pair = (c1, c2)

    # If correlation > 0.9, channels may be redundant
    passed = max_corr < 0.9
    return SignalTestResult(
        name="channel_independence",
        passed=passed,
        severity="warning" if not passed else "info",
        message=f"Max channel correlation: {max_corr:.3f} ({pair[0]}-{pair[1]})",
        details={"max_correlation": round(max_corr, 4), "pair": list(pair)},
    )


def test_state_coverage(data: pd.DataFrame) -> SignalTestResult:
    """Check that the risk gate produces all position size tiers at least once."""
    sizes_seen = set()
    for _, row in data[["M", "D", "K", "X"]].iterrows():
        state = evaluate_day(row["M"], row["D"], row["K"], row["X"])
        sizes_seen.add(state.position_size)

    expected = {0.0, 0.25, 0.5, 1.0}
    missing = expected - sizes_seen

    passed = len(missing) == 0
    return SignalTestResult(
        name="state_coverage",
        passed=passed,
        severity="info" if passed else "warning",
        message=f"Position tiers seen: {sorted(sizes_seen)}" + (f", missing: {sorted(missing)}" if missing else ""),
        details={"sizes_seen": sorted(sizes_seen), "missing": sorted(missing)},
    )


def print_signal_test_report(results: list[SignalTestResult]) -> str:
    """Format signal test results as a readable report."""
    lines = ["# Signal Quality Test Report", ""]
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
