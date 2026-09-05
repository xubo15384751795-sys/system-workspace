from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class MorphologyState:
    label: str
    confidence: float
    interpretation: str

    def to_dict(self) -> dict[str, float | str]:
        return {
            "label": self.label,
            "confidence": self.confidence,
            "interpretation": self.interpretation,
        }


def classify_morphology(
    components: Mapping[str, float | None],
    residuals: Mapping[str, float | None] | None = None,
    benchmarks: Mapping[str, float | None] | None = None,
    threshold: float = 0.5,
) -> MorphologyState:
    residuals = residuals or {}
    benchmarks = benchmarks or {}

    m = _pick(residuals, "M_resid_vs_NFCI", components.get("M_anchor_mismatch"))
    d = _pick(residuals, "D_resid_vs_NFCI", components.get("D_path_feasibility"))
    k = _pick(residuals, "K_resid_vs_vol_jump_tail", components.get("K_transition_deformation"))
    x = _pick(residuals, "X_resid_vs_leverage", components.get("X_shadow_accumulation"))
    nfci = _coerce(benchmarks.get("NFCI"))
    d_stress = _coerce(components.get("D_stress"))
    if d_stress == 0.0 and d is not None:
        d_stress = max(0.0, -float(d))

    if m >= threshold and d_stress >= threshold:
        return MorphologyState(
            label="anchor_mismatch_plus_path_contraction",
            confidence=_confidence(m, d_stress),
            interpretation=(
                "Stress is driven less by generic financial tightening than by anchor mismatch "
                "and reduced executable paths."
            ),
        )
    if k >= threshold and d_stress >= threshold:
        return MorphologyState(
            label="transition_deformation_with_path_collapse",
            confidence=_confidence(k, d_stress),
            interpretation="Transition geometry is unstable while executable hedging or funding paths contract.",
        )
    if x >= threshold and k >= threshold:
        return MorphologyState(
            label="shadow_stock_with_transition_deformation",
            confidence=_confidence(x, k),
            interpretation="Deferred pressure stock is paired with nonlinear transition deformation.",
        )
    if x >= threshold and nfci < threshold:
        return MorphologyState(
            label="latent_shadow_accumulation",
            confidence=_confidence(x, threshold - nfci),
            interpretation="Hidden or deferred stock pressure is elevated while aggregate stress remains muted.",
        )
    if nfci >= threshold and max(abs(m), abs(d), abs(k), abs(x)) < threshold:
        return MorphologyState(
            label="generic_aggregate_stress",
            confidence=min(1.0, abs(nfci)),
            interpretation="Aggregate stress is elevated but structural residual channels are weak.",
        )
    return MorphologyState(
        label="mixed_or_low_structural_signal",
        confidence=0.35,
        interpretation="No dominant structural morphology cleared the residual threshold.",
    )


def _pick(primary: Mapping[str, float | None], key: str, fallback: float | None) -> float:
    value = primary.get(key)
    if value is None:
        value = fallback
    return _coerce(value)


def _coerce(value: float | None) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _confidence(a: float, b: float) -> float:
    return float(max(0.0, min(1.0, (abs(a) + abs(b)) / 2.0)))
