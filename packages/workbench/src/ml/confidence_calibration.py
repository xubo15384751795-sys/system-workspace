"""Probability calibration wrapper for HMM regime detection.

Separates raw HMM posterior probability from usable calibrated confidence.
The raw posterior can be 99.96% — that's the model's math. But the system
cannot use that as confidence because:
  1. Posterior entropy may be too low (overconfident)
  2. Historical calibration samples may be insufficient
  3. State distribution may be too narrow
  4. Rolling refit may be unstable

Until calibration passes, usable confidence is capped.

Usage:
    from ml.confidence_calibration import calibrate_confidence

    result = calibrate_confidence(
        raw_probability=0.9996,
        posterior_entropy=0.02,
        sample_days=756,
        feature_count=12,
        state_distribution={"compression": 0.85, "volatile": 0.10, "crisis": 0.05},
        rolling_refit_agreement=0.8,
        label_stability=0.7,
        calibration_history_length=5,
    )
    # result.raw_probability == 0.9996
    # result.calibrated_confidence == "low"  (capped until calibration passes)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Calibration thresholds — conservative by design
_ENTROPY_FLOOR = 0.1          # below this: overconfident
_ENTROPY_IDEAL = 0.5          # above this: well-calibrated
_MIN_SAMPLE_DAYS = 252        # 1 year of trading days
_MIN_FEATURE_COUNT = 3
_MAX_DOMINANT_STATE_SHARE = 0.90
_MIN_REFIT_AGREEMENT = 0.7
_MIN_LABEL_STABILITY = 0.6
_MIN_CALIBRATION_HISTORY = 10  # minimum historical samples for Brier-like check

# Confidence levels (ordered)
_LEVELS = ["very_low", "low", "medium_low", "medium", "medium_high", "high"]

# Maximum usable confidence when calibration is incomplete
_UNCALIBRATED_CAP = "medium_low"


@dataclass
class CalibrationResult:
    """Output of probability calibration."""
    raw_probability: float
    calibrated_confidence: str
    calibration_passed: bool
    cap_applied: str | None  # why confidence was capped, or None
    degradation_reasons: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_probability": round(self.raw_probability, 6),
            "calibrated_confidence": self.calibrated_confidence,
            "calibration_passed": self.calibration_passed,
            "cap_applied": self.cap_applied,
            "degradation_reasons": self.degradation_reasons,
            "diagnostics": self.diagnostics,
        }


def _level_index(level: str) -> int:
    """Return numeric index for a confidence level."""
    try:
        return _LEVELS.index(level)
    except ValueError:
        return 0


def _cap_level(desired: str, cap: str) -> str:
    """Return min(desired, cap) by ordinal."""
    return _LEVELS[min(_level_index(desired), _level_index(cap))]


def _raw_to_confidence(prob: float) -> str:
    """Map raw probability to a naive confidence level."""
    if prob >= 0.95:
        return "high"
    if prob >= 0.85:
        return "medium_high"
    if prob >= 0.70:
        return "medium"
    if prob >= 0.50:
        return "medium_low"
    return "low"


def calibrate_confidence(
    *,
    raw_probability: float,
    posterior_entropy: float,
    sample_days: int,
    feature_count: int,
    state_distribution: dict[str, float] | None = None,
    rolling_refit_agreement: float = 0.0,
    label_stability: float = 0.0,
    calibration_history_length: int = 0,
) -> CalibrationResult:
    """Calibrate HMM raw posterior into usable system confidence.

    Parameters
    ----------
    raw_probability : float
        The raw posterior probability from HMM for the current state.
    posterior_entropy : float
        Shannon entropy (bits) of the posterior distribution.
    sample_days : int
        Number of training samples used.
    feature_count : int
        Number of features after engineering.
    state_distribution : dict or None
        Fraction of time spent in each state across the full sequence.
    rolling_refit_agreement : float
        Agreement rate between consecutive HMM fits (0-1).
    label_stability : float
        Stability of regime labels over recent window (0-1).
    calibration_history_length : int
        Number of historical calibration samples available.

    Returns
    -------
    CalibrationResult
        Contains raw_probability, calibrated_confidence, and diagnostics.
    """
    reasons: list[str] = []
    cap = None  # None means no cap applied yet

    # --- Check 1: Posterior entropy ---
    if posterior_entropy < _ENTROPY_FLOOR:
        reasons.append(
            f"Posterior entropy {posterior_entropy:.3f} < {_ENTROPY_FLOOR:.1f} "
            f"— overconfident posterior, degrading"
        )
        cap = "low"

    # --- Check 2: Sample days ---
    if sample_days < _MIN_SAMPLE_DAYS:
        reasons.append(
            f"Sample days {sample_days} < {_MIN_SAMPLE_DAYS} "
            f"— insufficient training data"
        )
        cap = _cap_level(cap or "high", "medium_low")

    # --- Check 3: Feature count ---
    if feature_count < _MIN_FEATURE_COUNT:
        reasons.append(
            f"Feature count {feature_count} < {_MIN_FEATURE_COUNT} "
            f"— may be underfitting"
        )
        cap = _cap_level(cap or "high", "medium_low")

    # --- Check 4: State distribution ---
    if state_distribution:
        max_share = max(state_distribution.values()) if state_distribution else 0
        if max_share > _MAX_DOMINANT_STATE_SHARE:
            reasons.append(
                f"Dominant state share {max_share:.1%} > {_MAX_DOMINANT_STATE_SHARE:.0%} "
                f"— state collapse, distribution too narrow"
            )
            cap = _cap_level(cap or "high", "low")

    # --- Check 5: Rolling refit agreement ---
    if rolling_refit_agreement < _MIN_REFIT_AGREEMENT and rolling_refit_agreement > 0:
        reasons.append(
            f"Rolling refit agreement {rolling_refit_agreement:.3f} < {_MIN_REFIT_AGREEMENT} "
            f"— unstable across refits"
        )
        cap = _cap_level(cap or "high", "medium_low")

    # --- Check 6: Label stability ---
    if label_stability < _MIN_LABEL_STABILITY and label_stability > 0:
        reasons.append(
            f"Label stability {label_stability:.3f} < {_MIN_LABEL_STABILITY} "
            f"— regime labels unstable"
        )
        cap = _cap_level(cap or "high", "medium_low")

    # --- Check 7: Calibration history ---
    if calibration_history_length < _MIN_CALIBRATION_HISTORY:
        reasons.append(
            f"Calibration history {calibration_history_length} < {_MIN_CALIBRATION_HISTORY} "
            f"— insufficient samples for reliable calibration"
        )
        # Apply uncalibrated cap
        cap = _cap_level(cap or "high", _UNCALIBRATED_CAP)

    # --- Determine final confidence ---
    naive_confidence = _raw_to_confidence(raw_probability)

    if cap is not None:
        calibrated = _cap_level(naive_confidence, cap)
        calibration_passed = False
        cap_reason = cap
    else:
        calibrated = naive_confidence
        calibration_passed = True
        cap_reason = None

    if not reasons:
        reasons.append("All calibration checks passed")

    return CalibrationResult(
        raw_probability=raw_probability,
        calibrated_confidence=calibrated,
        calibration_passed=calibration_passed,
        cap_applied=cap_reason,
        degradation_reasons=reasons,
        diagnostics={
            "naive_confidence": naive_confidence,
            "posterior_entropy": round(posterior_entropy, 4),
            "sample_days": sample_days,
            "feature_count": feature_count,
            "state_distribution": state_distribution or {},
            "rolling_refit_agreement": round(rolling_refit_agreement, 4),
            "label_stability": round(label_stability, 4),
            "calibration_history_length": calibration_history_length,
        },
    )
