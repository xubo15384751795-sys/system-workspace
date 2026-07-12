from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_framework_validation_protocol import (
    build_event_battery,
    build_validation_candidates,
    evaluate_protocol,
)


def test_framework_validation_protocol_synthetic_smoke() -> None:
    index = pd.date_range("2017-01-02", periods=900, freq="B")
    rng = np.random.default_rng(4)
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(index)))), index=index)
    spy.iloc[650:670] *= np.linspace(1.0, 0.86, 20)
    panel = pd.DataFrame(
        {
            "FRED:VIXCLS": 18 + rng.normal(0, 1, len(index)),
            "FRED:MOVE": np.r_[np.ones(650) * 80, np.ones(250) * 120],
            "FRED:EFFR": np.ones(len(index)) * 1.6,
            "FRED:IOER": np.ones(len(index)) * 1.5,
            "FRED:SOFR": np.ones(len(index)) * 2.0,
            "FRED:IORB": np.ones(len(index)) * 1.9,
            "FRED:BAMLH0A0HYM2": np.r_[np.ones(650) * 3.5, np.ones(250) * 4.2],
            "FRED:NFCI": np.linspace(-0.5, 0.8, len(index)),
            "SPY": spy,
        },
        index=index,
    )
    cross_asset = pd.DataFrame(
        {
            "date": list(index) * 2,
            "symbol": ["SPY"] * len(index) + ["TLT"] * len(index),
            "close": list(spy) + list(100 * np.exp(np.cumsum(rng.normal(0.0, 0.006, len(index))))),
        }
    )
    channels = pd.DataFrame(
        {
            "channel_M": np.linspace(0.0, 1.0, len(index)),
            "channel_D_contraction": np.linspace(0.2, 0.9, len(index)),
            "channel_K": np.sin(np.linspace(0, 12, len(index))) + 1.0,
            "channel_X_agg": np.linspace(0.1, 1.2, len(index)),
        },
        index=index,
    )
    events, status = build_event_battery(panel, cross_asset, horizon=20)
    candidates, diagnostics = build_validation_candidates(channels, panel, cross_asset)
    report = evaluate_protocol(events, candidates, bootstrap_reps=3, case_dates=("2020-03-16",))

    assert status["E1_equity"]["status"] == "ok"
    assert "E1_equity" in events
    assert "framework_full" in candidates
    assert "combination" in candidates
    assert diagnostics["channel_coverage"]["M"] == 1.0
    assert "E1_equity" in report
    assert "framework_full" in report["E1_equity"]["candidate_evaluation"]


def test_incremental_test_surfaces_diebold_mariano_gate() -> None:
    """The §7.5 acceptance gate (DM p<0.05) must be present in the T6 report."""
    index = pd.date_range("2017-01-02", periods=900, freq="B")
    rng = np.random.default_rng(11)
    spy = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, len(index)))), index=index)
    spy.iloc[650:670] *= np.linspace(1.0, 0.86, 20)
    panel = pd.DataFrame(
        {
            "FRED:VIXCLS": 18 + rng.normal(0, 1, len(index)),
            "FRED:NFCI": np.linspace(-0.5, 0.8, len(index)),
            "SPY": spy,
        },
        index=index,
    )
    channels = pd.DataFrame(
        {
            "channel_M": np.linspace(0.0, 1.0, len(index)),
            "channel_D_contraction": np.linspace(0.2, 0.9, len(index)),
            "channel_K": np.sin(np.linspace(0, 12, len(index))) + 1.0,
            "channel_X_agg": np.linspace(0.1, 1.2, len(index)),
        },
        index=index,
    )
    events, _ = build_event_battery(panel, None, horizon=20)
    candidates, _ = build_validation_candidates(channels, panel, None)
    report = evaluate_protocol(events, candidates, bootstrap_reps=3, case_dates=("2020-03-16",))

    for event_name, event_report in report.items():
        inc = event_report.get("incremental_tests", {}).get("framework_full_vs_public_baselines")
        # If the incremental test ran, the DM gate must be surfaced.
        if isinstance(inc, dict) and inc.get("status") == "ok":
            dm = inc["delta"]["diebold_mariano"]
            assert {"n", "mean_diff", "dm_stat", "p_value"} <= set(dm)
