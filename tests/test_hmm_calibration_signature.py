"""HMM calibration signature — compatible history grouping."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hmm_stability_audit import _filter_history_by_signature, _get_model_signature


def _sample(method: str = "hmm_3state_hmmlearn", train_window: int = 756, *,
            feature_count: int = 180, hmm_dims: int = 5,
            calibration_signature: str | None = None) -> dict:
    stability = {"train_window": train_window, "feature_count": feature_count}
    if calibration_signature:
        stability["calibration_signature"] = calibration_signature
    return {
        "method": method,
        "stability": stability,
        "provenance": {"hmm_input_dimensions": hmm_dims},
    }


def test_signature_uses_hmm_dims_not_feature_count():
    a = _sample(feature_count=180)
    b = _sample(feature_count=174)
    assert _get_model_signature(a) == _get_model_signature(b) == "hmm_3state_hmmlearn:756:5"


def test_explicit_calibration_signature_wins():
    payload = _sample(calibration_signature="custom:756:5")
    assert _get_model_signature(payload) == "custom:756:5"


def test_filter_groups_panel_width_drift():
    history = [_sample(feature_count=180), _sample(feature_count=174)]
    current = _sample(feature_count=172)
    sig = _get_model_signature(current)
    compatible = _filter_history_by_signature(history, sig)
    assert len(compatible) == 2
