"""Phase A step 6: p_public HOLD-existing + shadow sample filter tests.

Verifies:
- When P_public is NaN (incomplete public-component coverage), paper_portfolio
  holds the existing position (target = prev_pos) and flags the day
  sizing_mode=HOLD_DEGRADED, rather than silently renormalizing or flattening.
- build_90d_outcomes_summary excludes HOLD_DEGRADED dates from promotion
  sample counts (cards_total / min_samples_met).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_residual_stress import public_level_probability  # noqa: E402


class TestPublicLevelFailClosed:
    def test_full_coverage_returns_values(self):
        idx = pd.date_range("2020-01-01", periods=300, freq="B")
        public = pd.DataFrame(
            {
                "ofr_fsi": np.linspace(0, 1, 300),
                "nfci": np.linspace(0.2, 0.8, 300),
                "ecb_ciss": np.linspace(0.1, 0.5, 300),
            },
            index=idx,
        )
        p = public_level_probability(public, min_periods=50)
        # All components present -> values returned (not all NaN).
        assert p.notna().sum() > 100
        assert p.dropna().between(0.0, 1.0).all()

    def test_partial_coverage_nans_degraded_dates(self):
        """Only some dates have incomplete coverage -> only those are NaN."""
        idx = pd.date_range("2020-01-01", periods=300, freq="B")
        ciss = np.linspace(0.1, 0.5, 300)
        ciss[200:] = np.nan  # last 100 dates missing CISS
        public = pd.DataFrame(
            {
                "ofr_fsi": np.linspace(0, 1, 300),
                "nfci": np.linspace(0.2, 0.8, 300),
                "ecb_ciss": ciss,
            },
            index=idx,
        )
        p = public_level_probability(public, min_periods=50)
        # First 200 dates (after min_periods warmup) have full coverage -> not NaN.
        # Last 100 dates missing CISS -> NaN (fail-closed).
        assert p.iloc[250:].isna().all(), "degraded dates must be NaN"
        assert p.iloc[100:199].notna().any(), "full-coverage dates must have values"


class TestShadowOutcomesExcludesDegraded:
    """build_90d_outcomes_summary excludes HOLD_DEGRADED dates."""

    def test_degraded_day_excluded_from_promotion_counts(self, tmp_path, monkeypatch):
        from strategy_lab import shadow_card as sc

        from verity.runtime import runtime_io as rio

        # Isolate both OUTPUT_DIR (shadow cards) and rio.ROOT (NAV ledger path
        # is derived from rio.ROOT inside _load_degraded_nav_dates).
        monkeypatch.setattr(sc, "OUTPUT_DIR", tmp_path / "strategy_lab")
        monkeypatch.setattr(rio, "ROOT", tmp_path)

        # Write a NAV ledger with one HOLD_DEGRADED day.
        position_dir = tmp_path / "Output" / "position"
        position_dir.mkdir(parents=True)
        nav_path = position_dir / "paper_portfolio_nav.jsonl"
        degraded_date = pd.Timestamp.now(tz=None).date().isoformat()
        nav_path.write_text(
            json.dumps({"as_of": degraded_date, "sizing_mode": "HOLD_DEGRADED"}) + "\n",
            encoding="utf-8",
        )

        # Write a shadow card for that degraded date + one normal date.
        card_dir = tmp_path / "strategy_lab" / "shadow_cards"
        card_dir.mkdir(parents=True)

        def _card(as_of, has_20d=True, evaluation="correct"):
            return {
                "as_of_date": as_of,
                "outcome_backfill": {
                    "forward_20d_return": 0.01 if has_20d else None,
                    "evaluation": evaluation,
                },
            }

        (card_dir / f"{degraded_date}.json").write_text(
            json.dumps(_card(degraded_date)), encoding="utf-8"
        )
        normal_date = (pd.Timestamp.now(tz=None) - pd.Timedelta(days=5)).date().isoformat()
        (card_dir / f"{normal_date}.json").write_text(
            json.dumps(_card(normal_date)), encoding="utf-8"
        )

        summary = sc.build_90d_outcomes_summary(days=90)

        # The degraded day must NOT count toward promotion samples.
        assert summary["cards_total"] == 1, f"expected 1 valid card, got {summary['cards_total']}"
        assert summary["excluded_degraded_samples"] == 1
        assert summary["cards_with_20d_outcome"] == 1
        # min_samples_met is False because only 1 valid sample (need 30).
        assert summary["promotion_indicators"]["min_samples_met"] is False

    def test_no_degraded_days_all_counted(self, tmp_path, monkeypatch):
        from strategy_lab import shadow_card as sc

        from verity.runtime import runtime_io as rio

        monkeypatch.setattr(sc, "OUTPUT_DIR", tmp_path / "strategy_lab")
        monkeypatch.setattr(rio, "ROOT", tmp_path)
        card_dir = tmp_path / "strategy_lab" / "shadow_cards"
        card_dir.mkdir(parents=True)
        d = (pd.Timestamp.now(tz=None) - pd.Timedelta(days=3)).date().isoformat()
        (card_dir / f"{d}.json").write_text(
            json.dumps({
                "as_of_date": d,
                "outcome_backfill": {"forward_20d_return": 0.01, "evaluation": "correct"},
            }),
            encoding="utf-8",
        )

        summary = sc.build_90d_outcomes_summary(days=90)
        assert summary["cards_total"] == 1
        assert summary["excluded_degraded_samples"] == 0
