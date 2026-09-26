"""Channel-coverage degradation in the regime gate and the shadow card.

An unobserved channel is not a channel reading "no stress". Before this,
`evaluate_day` counted unknown channels toward neither n_stress nor n_relief,
so a day with one observed channel fell through to NEUTRAL/FULL — 9210 of the
14589 historical NEUTRAL days had fewer than two channels observed.
"""
from __future__ import annotations

import numpy as np
from strategy_lab.risk_gate import CONSENSUS_MIN, evaluate_day

NAN = float("nan")


class TestEvaluateDayCoverage:
    def test_single_observed_channel_degrades(self):
        state = evaluate_day(NAN, -0.77, NAN, NAN)
        assert state.regime == "INSUFFICIENT_COVERAGE"
        assert state.action_gate == "NO_TRADE"
        assert state.position_size == 0.0
        assert "1/4 observed" in state.risk_flags[0]
        assert "M, K, X" in state.risk_flags[0]

    def test_no_observed_channels_degrades(self):
        state = evaluate_day(NAN, NAN, NAN, NAN)
        assert state.regime == "INSUFFICIENT_COVERAGE"
        assert state.position_size == 0.0

    def test_at_threshold_uses_normal_regime_rules(self):
        """Exactly CONSENSUS_MIN observations is enough to classify."""
        assert CONSENSUS_MIN == 2
        state = evaluate_day(-0.5, -0.5, NAN, NAN)
        assert state.regime != "INSUFFICIENT_COVERAGE"

    def test_full_coverage_unaffected(self):
        calm = evaluate_day(-0.5, -0.5, -0.5, -0.5)
        assert calm.regime == "ALL_CLEAR"
        assert calm.position_size == 1.0

    def test_stress_still_detected_with_adequate_coverage(self):
        stressed = evaluate_day(0.9, 0.9, 0.9, 0.9)
        assert stressed.regime != "INSUFFICIENT_COVERAGE"
        assert stressed.position_size < 1.0

    def test_none_counts_as_unobserved(self):
        state = evaluate_day(None, -0.5, None, None)
        assert state.regime == "INSUFFICIENT_COVERAGE"

    def test_numpy_nan_counts_as_unobserved(self):
        state = evaluate_day(np.nan, -0.5, np.nan, np.nan)
        assert state.regime == "INSUFFICIENT_COVERAGE"


class TestShadowCardCoverage:
    def test_card_reports_coverage_and_withholds_full_size(self, monkeypatch):
        """The card must not present a full-size call built on one channel."""
        import pandas as pd
        from strategy_lab import shadow_card as sc

        idx = pd.date_range("2026-05-01", periods=40, freq="B")
        # Only D is resolved; M/K/X absent, as load_signals() returns today.
        signals = pd.DataFrame({"D": np.linspace(-0.8, -0.7, len(idx))}, index=idx)
        monkeypatch.setattr(sc, "load_signals", lambda *a, **k: signals)
        monkeypatch.setattr(sc, "load_aligned", lambda *a, **k: pd.DataFrame())
        monkeypatch.setattr(sc.rio, "load_json", lambda *a, **k: None)

        card = sc.generate_shadow_card()

        assert card["channel_coverage"]["available"] == ["D"]
        assert card["channel_coverage"]["missing"] == ["M", "K", "X"]
        assert card["channel_coverage"]["complete"] is False
        assert card["channel_readings"]["K"] is None
        assert card["recommendation"]["sizing_label"] == "INSUFFICIENT_COVERAGE"
        assert card["recommendation"]["suggested_size"] == 0.0
        assert card["recommendation"]["allow_open"] is False
        # The raw velocity reading stays visible for the audit trail.
        assert "position" in card["velocity_gate"]

    def test_card_json_has_no_bare_nan(self, monkeypatch):
        """NaN is not valid JSON; missing readings must serialize as null."""
        import json

        import pandas as pd
        from strategy_lab import shadow_card as sc

        idx = pd.date_range("2026-05-01", periods=40, freq="B")
        signals = pd.DataFrame(
            {"M": [np.nan] * len(idx), "D": np.linspace(-0.8, -0.7, len(idx))},
            index=idx,
        )
        monkeypatch.setattr(sc, "load_signals", lambda *a, **k: signals)
        monkeypatch.setattr(sc, "load_aligned", lambda *a, **k: pd.DataFrame())
        monkeypatch.setattr(sc.rio, "load_json", lambda *a, **k: None)

        card = sc.generate_shadow_card()

        assert "NaN" not in json.dumps(card)
        assert card["channel_readings"]["M"] is None
        assert "M" in card["channel_coverage"]["missing"]
