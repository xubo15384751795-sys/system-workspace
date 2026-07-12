"""Tests for strategy_lab paper portfolio (Phase 5)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strategy_lab.paper_portfolio import (  # noqa: E402
    DEFAULT_CONFIG,
    _maybe_alert,
    simulate_day,
)


def test_default_config_is_public_residual_paper_path() -> None:
    assert DEFAULT_CONFIG["momentum_lookback"] == 63
    assert DEFAULT_CONFIG["velocity_threshold"] == 1.5
    assert DEFAULT_CONFIG["cofire_n"] == 3
    assert DEFAULT_CONFIG["bull_modulation"] is True
    assert DEFAULT_CONFIG["continuous_sizing"] is True
    assert DEFAULT_CONFIG["sizing_mode"] == "public_residual"
    assert DEFAULT_CONFIG["residual_mode"] == "velocity"
    assert DEFAULT_CONFIG["onset_lambda"] == 0.0
    assert DEFAULT_CONFIG["scale_by_effective_size"] is True
    assert DEFAULT_CONFIG["cost_bps"] == 3.0
    assert DEFAULT_CONFIG["slippage_bps"] == 2.0


def test_position_scale_uses_effective_size_on_latest_only() -> None:
    from strategy_lab.paper_portfolio import _position_scale_for_day

    cfg = {"scale_by_effective_size": True}
    assert _position_scale_for_day(
        config=cfg,
        effective_size=0.5,
        date_s="2026-07-11",
        latest_date="2026-07-11",
        backfill_days=0,
    ) == 0.5
    assert _position_scale_for_day(
        config=cfg,
        effective_size=0.5,
        date_s="2026-06-01",
        latest_date="2026-07-11",
        backfill_days=90,
    ) == 1.0
    assert _position_scale_for_day(
        config={"scale_by_effective_size": False},
        effective_size=0.25,
        date_s="2026-07-11",
        latest_date="2026-07-11",
        backfill_days=0,
    ) == 1.0


def test_continuous_sizing_scales_below_binary_full(monkeypatch) -> None:
    from strategy_lab import paper_portfolio as pp

    index = pd.date_range("2020-01-01", periods=400, freq="B")
    rng = np.random.default_rng(1)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))), index=index)
    data = pd.DataFrame(
        {
            "close": close,
            "M": rng.normal(0, 1, 400),
            "D": rng.normal(0, 1, 400),
            "K": rng.normal(0, 1, 400),
            "X": rng.normal(0, 1, 400),
        },
        index=index,
    )
    # Inject synthetic public levels so the test does not depend on harvest panels.
    public = pd.DataFrame(
        {
            "ofr_fsi": np.linspace(0.1, 0.9, 400),
            "nfci": np.linspace(0.2, 0.7, 400),
            "ecb_ciss": np.linspace(0.15, 0.8, 400),
        },
        index=index,
    )
    monkeypatch.setattr(pp, "_load_public_levels", lambda idx, path: public.reindex(idx))
    config = dict(DEFAULT_CONFIG)
    overlay, gate, stress = pp._compute_target_series(data, config)
    assert {"p_public", "p_onset", "position"}.issubset(stress.columns)
    assert stress["p_public"].dropna().between(0.0, 1.0).all()
    assert stress["p_onset"].dropna().between(0.0, 1.0).all()
    warmed = overlay.iloc[200:].dropna()
    assert warmed.between(0.0, 1.0).all()
    assert ((warmed > 0.05) & (warmed < 0.95)).any() or (gate.iloc[200:] < 1.0).any()


def test_simulate_day_applies_prior_position_and_turnover_cost() -> None:
    state = {
        "config": DEFAULT_CONFIG,
        "nav": 1.0,
        "benchmark_nav": 1.0,
        "position": 1.0,
        "benchmark_spy_weight": 0.6,
        "benchmark_tlt_weight": 0.4,
        "days_since_bench_rebalance": 0,
    }
    day = simulate_day(
        state=state,
        as_of="2026-07-10",
        spy_ret=0.01,
        tlt_ret=0.0,
        target_position=0.0,  # flatten → turnover 1.0
        gate_position=0.0,
        momentum=0.05,
        stance="RISK_OFF",
        size=0.0,
    )
    # pnl = 1.0 * 0.01; cost = 1.0 * 5bp = 0.0005; nav = 1 * (1.01 - 0.0005)
    assert day["velocity_gate_state"] == "EXIT"
    assert day["cost"] == pytest.approx(0.0005)
    assert day["nav"] == pytest.approx(1.0095)
    assert day["position"] == 0.0


def test_alert_on_exit_flip(monkeypatch) -> None:
    called = []

    def _fake(title: str, message: str) -> bool:
        called.append((title, message))
        return True

    monkeypatch.setattr("strategy_lab.paper_portfolio.notify_alert", _fake)
    alerts = _maybe_alert(
        prev_vg="FULL",
        new_vg="EXIT",
        prev_level="CALM",
        new_level="CALM",
        prev_stance="RISK_ON",
        new_stance="RISK_ON",
        as_of="2026-07-10",
        dry_run=False,
    )
    assert len(alerts) == 1
    assert "onset" in alerts[0]
    assert "EXIT" in alerts[0]
    assert called and "Onset" in called[0][0]


def test_alert_on_level_elevated(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        "strategy_lab.paper_portfolio.notify_alert",
        lambda t, m: called.append((t, m)) or True,
    )
    alerts = _maybe_alert(
        prev_vg="FULL",
        new_vg="FULL",
        prev_level="CALM",
        new_level="ELEVATED",
        prev_stance="RISK_ON",
        new_stance="RISK_ON",
        as_of="2026-07-10",
        dry_run=False,
    )
    assert len(alerts) == 1
    assert "level" in alerts[0]
    assert called and "Level" in called[0][0]


def test_alert_on_stance_change(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        "strategy_lab.paper_portfolio.notify_alert",
        lambda t, m: called.append((t, m)) or True,
    )
    alerts = _maybe_alert(
        prev_vg="FULL",
        new_vg="FULL",
        prev_level="CALM",
        new_level="CALM",
        prev_stance="RISK_ON",
        new_stance="RISK_REDUCE",
        as_of="2026-07-10",
        dry_run=False,
    )
    assert len(alerts) == 1
    assert "RISK_REDUCE" in alerts[0]
    assert called


def test_no_alert_when_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(
        "strategy_lab.paper_portfolio.notify_alert",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not notify")),
    )
    alerts = _maybe_alert(
        prev_vg="FULL",
        new_vg="FULL",
        prev_level="CALM",
        new_level="CALM",
        prev_stance="RISK_ON",
        new_stance="RISK_ON",
        as_of="2026-07-10",
        dry_run=False,
    )
    assert alerts == []


def test_daily_sequence_includes_paper_portfolio() -> None:
    from _daily_run_sequence import step_ids

    ids = step_ids()
    assert "paper_portfolio" in ids
    assert ids.index("paper_portfolio") == ids.index("record_trade_decision") + 1
