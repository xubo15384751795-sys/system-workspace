"""Tests for build_sigma_vector — canonical four-channel plus daily readout.

Design principle (Finance-2.tex §4.1): M / D / K / X_agg are co-equal
primitive channels. A channel may legitimately be NOT_IMPLEMENTED (NaN), but
the joint Σ reading must never silently collapse a missing channel to 0.0 and
let the others dominate as if the four-channel state were complete.

The daily executive readout is a separate measurement-eligibility layer. Today
it is M/D primary; K/X_agg remain canonical but cannot drive primary daily
state until their measurement gates pass.
"""

from __future__ import annotations

import math

from workbench.governance.semantic import CANONICAL_CHANNELS, build_sigma_vector


class _StubRegistry:
    """Duck-typed SemanticRegistry: no semantic-distance metadata."""

    def get(self, concept: str):  # noqa: D401
        raise KeyError(concept)


def test_canonical_channel_set_is_the_four_primitives():
    assert CANONICAL_CHANNELS == ["M", "D", "K", "X_agg"]


def test_complete_when_all_four_live():
    scores = {"M": 0.9, "D": -0.4, "K": 0.2, "X_agg": 0.1}
    out = build_sigma_vector(scores, _StubRegistry())
    assert out["complete"] is True
    assert set(out["channels_live"]) == {"M", "D", "K", "X_agg"}
    assert out["channels_not_implemented"] == []
    assert out["dominant_channel"] == "M"
    assert out["primary_readout"]["state"] == "ANCHOR_DRIFT_PATH_OPEN"
    assert out["primary_readout"]["eligible_channels"] == ["M", "D"]
    assert not any("PARTIAL_CHANNEL_COVERAGE" in w for w in out["semantic_warning"])


def test_missing_channels_are_not_implemented_not_zero():
    # K and X_agg absent — the current real state.
    scores = {"M": 0.9, "D": -0.4}
    out = build_sigma_vector(scores, _StubRegistry())
    assert out["complete"] is False
    assert set(out["channels_not_implemented"]) == {"K", "X_agg"}
    # absent channels reported as null, NOT coerced to 0.0
    assert out["K"] is None
    assert out["X_agg"] is None
    # dominant/cofire computed only over live channels
    assert out["dominant_channel"] == "M"
    # loud partial-coverage flag present
    assert any("PARTIAL_CHANNEL_COVERAGE" in w for w in out["semantic_warning"])


def test_nan_is_treated_as_not_implemented():
    scores = {"M": 0.5, "D": 0.3, "K": float("nan"), "X_agg": float("nan")}
    out = build_sigma_vector(scores, _StubRegistry())
    assert set(out["channels_not_implemented"]) == {"K", "X_agg"}
    assert out["complete"] is False
    # a NaN channel must never become the dominant channel
    assert out["dominant_channel"] in {"M", "D"}


def test_missing_channel_cannot_dominate_even_if_others_weak():
    # M is weak but live; K would be huge but is absent → must not dominate.
    scores = {"M": 0.05, "D": 0.02}
    out = build_sigma_vector(scores, _StubRegistry())
    assert out["dominant_channel"] == "M"
    assert "K" in out["channels_not_implemented"]


def test_no_live_channels_yields_none_dominant():
    out = build_sigma_vector({}, _StubRegistry())
    assert out["dominant_channel"] is None
    assert out["complete"] is False
    assert set(out["channels_not_implemented"]) == set(CANONICAL_CHANNELS)


def test_retired_splits_are_not_in_output():
    out = build_sigma_vector({"M": 0.1, "D": 0.1, "K": 0.1, "X_agg": 0.1}, _StubRegistry())
    assert "X_PRE" not in out
    assert "X_REALIZED" not in out
    assert "X_agg" in out


def test_measurement_eligibility_retains_k_x_but_blocks_primary_daily_readout():
    out = build_sigma_vector({"M": 0.2, "D": -0.2, "K": 0.99, "X_agg": 0.95}, _StubRegistry())

    assert out["complete"] is True
    assert out["dominant_channel"] == "K"  # legacy diagnostic over canonical live channels
    assert out["primary_readout"]["state"] == "ANCHOR_STABLE_PATH_OPEN"
    assert out["primary_readout"]["blocked_from_primary"] == ["K", "X_agg"]
    assert out["measurement_eligibility"]["K"]["framework_role"] == "canonical_dimension"
    assert out["measurement_eligibility"]["K"]["readout_role"] == "diagnostic_rebuild"
    assert out["measurement_eligibility"]["X_agg"]["readout_role"] == "background_only"


def test_primary_readout_requires_m_and_d():
    out = build_sigma_vector({"M": 0.8, "K": 0.8, "X_agg": 0.8}, _StubRegistry())

    assert out["primary_readout"]["state"] == "PRIMARY_READOUT_UNAVAILABLE"
    assert out["primary_readout"]["channels_missing"] == ["D"]
