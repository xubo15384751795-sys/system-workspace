from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src.core.interfaces import SingularDetectorInterface
from src.core.models import ProxyReading, ShadowMassState, StructuralBeliefState
from src.operators.operator_schema import OperatorDiagnostics


@dataclass
class SigmaVector:
    M: float
    D: float
    K: float
    X_PRE: float
    X_REALIZED: float
    operator_penalties: dict[str, float]
    dominant_channel: str
    cofire_count: int
    reduction_warning: str

    def to_dict(self) -> dict[str, float | int | str | dict[str, float]]:
        return {
            "M": self.M,
            "D": self.D,
            "K": self.K,
            "X_PRE": self.X_PRE,
            "X_REALIZED": self.X_REALIZED,
            "operator_penalties": dict(self.operator_penalties),
            "dominant_channel": self.dominant_channel,
            "cofire_count": self.cofire_count,
            "reduction_warning": self.reduction_warning,
        }


@dataclass
class SingularDetectionDiagnostics:
    sigma_t: float
    scalar_threshold_hit: bool
    joint_hitting: bool
    distributional_trigger: bool
    forced_realization_pressure: float
    structural_singular_time: float | None
    sigma_vector: SigmaVector | None = None

    def to_dict(self) -> dict[str, float | bool | None | dict]:
        return {
            "sigma_t": self.sigma_t,
            "scalar_threshold_hit": self.scalar_threshold_hit,
            "joint_hitting": self.joint_hitting,
            "distributional_trigger": self.distributional_trigger,
            "forced_realization_pressure": self.forced_realization_pressure,
            "structural_singular_time": self.structural_singular_time,
            "sigma_vector": self.sigma_vector.to_dict() if self.sigma_vector is not None else None,
        }


@dataclass
class ThresholdSingularDetector(SingularDetectorInterface):
    sigma_threshold: float = 2.0
    w_mismatch: float = 1.0
    w_dof: float = 1.0
    w_curvature: float = 1.0
    w_shadow: float = 1.0
    state_pressure_weight: float = 0.0
    distributional_prob_threshold: float = 0.60
    distributional_singular_mass_threshold: float = 0.75
    joint_hitting_enabled: bool = True
    dof_collapse_threshold: float = -0.65
    curvature_spike_threshold: float = 0.65
    forced_realization_threshold: float = 0.65
    shadow_realization_weight: float = 1.0
    operator_realization_weight: float = 0.5
    last_diagnostics: SingularDetectionDiagnostics | None = field(default=None, init=False)

    def detect(
        self,
        proxy: ProxyReading,
        z: np.ndarray,
        belief_state: StructuralBeliefState | None = None,
        op_diag: Optional[OperatorDiagnostics] = None,
        shadow_mass_state: ShadowMassState | None = None,
    ) -> tuple[float, bool]:
        mismatch = self._positive_or_zero(proxy.M)
        dof_contraction = self._positive_or_zero(-(proxy.D or 0.0))
        curvature = self._positive_or_zero(proxy.K)
        shadow = self._shadow_pre(proxy)
        state_pressure = float(np.linalg.norm(z))
        sigma_t = (
            self.w_mismatch * mismatch
            + self.w_dof * dof_contraction
            + self.w_curvature * curvature
            + self.w_shadow * shadow
            + self.state_pressure_weight * state_pressure
        )
        operator_penalties = {
            "squeeze": 0.0,
            "noncomm": 0.0,
            "irreversible": 0.0,
        }
        # Operator-sequence contribution: a chain of irreversible, compressive,
        # non-commuting operators raises structural risk even before proxy values
        # cross their own thresholds.
        if op_diag is not None and op_diag.operator_count > 0:
            total_ops = op_diag.operator_count
            squeeze_penalty = max(0.0, 1.0 - op_diag.compression_ratio) * 0.5
            noncomm_penalty = op_diag.non_commutativity_score * 0.3
            irreversible_risk = (op_diag.irreversible_count / total_ops) * 0.4
            operator_penalties = {
                "squeeze": float(squeeze_penalty),
                "noncomm": float(noncomm_penalty),
                "irreversible": float(irreversible_risk),
            }
            sigma_t += squeeze_penalty + noncomm_penalty + irreversible_risk
        scalar_hit = sigma_t >= self.sigma_threshold
        singular_flag = scalar_hit
        joint_hit = False
        realization_pressure = self._forced_realization_pressure(proxy, op_diag, shadow_mass_state)
        if self.joint_hitting_enabled:
            joint_hit = self._joint_hitting_trigger(
                proxy,
                op_diag,
                shadow_mass_state,
                realization_pressure=realization_pressure,
            )
            singular_flag = singular_flag or joint_hit
        distributional_hit = False
        if belief_state is not None:
            distributional_hit = self._distributional_trigger(belief_state)
            singular_flag = singular_flag or distributional_hit
        self.last_diagnostics = SingularDetectionDiagnostics(
            sigma_t=float(sigma_t),
            scalar_threshold_hit=bool(scalar_hit),
            joint_hitting=bool(joint_hit),
            distributional_trigger=bool(distributional_hit),
            forced_realization_pressure=float(realization_pressure),
            structural_singular_time=0.0 if joint_hit else None,
            sigma_vector=self._sigma_vector(
                mismatch=mismatch,
                dof_contraction=dof_contraction,
                curvature=curvature,
                shadow_pre=shadow,
                shadow_realized=self._shadow_realized(proxy),
                operator_penalties=operator_penalties,
            ),
        )
        return sigma_t, singular_flag

    def _sigma_vector(
        self,
        *,
        mismatch: float,
        dof_contraction: float,
        curvature: float,
        shadow_pre: float,
        shadow_realized: float,
        operator_penalties: dict[str, float],
    ) -> SigmaVector:
        channels = {
            "M": float(self.w_mismatch * mismatch),
            "D": float(self.w_dof * dof_contraction),
            "K": float(self.w_curvature * curvature),
            "X_PRE": float(self.w_shadow * shadow_pre),
            "X_REALIZED": float(self.w_shadow * shadow_realized),
        }
        active_channels = [name for name, value in channels.items() if value > 0.0]
        dominant = max(channels, key=lambda name: abs(channels[name])) if channels else "NONE"
        return SigmaVector(
            M=channels["M"],
            D=channels["D"],
            K=channels["K"],
            X_PRE=channels["X_PRE"],
            X_REALIZED=channels["X_REALIZED"],
            operator_penalties=operator_penalties,
            dominant_channel=dominant if channels[dominant] > 0.0 else "NONE",
            cofire_count=len(active_channels),
            reduction_warning=(
                "Sigma scalar is an additive compressed warning surface; use SigmaVector "
                "for channel co-firing, operator penalties, and dominant-channel context."
            ),
        )

    def _positive_or_zero(self, value: float | None) -> float:
        if value is None or not np.isfinite(value):
            return 0.0
        return float(max(0.0, value))

    def _distributional_trigger(self, belief_state: StructuralBeliefState) -> bool:
        metrics = dict(belief_state.escalation_metrics)
        sigma_breach_prob = metrics.get("sigma_breach_prob")
        sigma_q90 = metrics.get("sigma_q90")
        max_singular_mass = metrics.get("max_channel_singular_mass")
        if sigma_breach_prob is not None and float(sigma_breach_prob) >= self.distributional_prob_threshold:
            return True
        if sigma_q90 is not None and float(sigma_q90) >= self.sigma_threshold:
            return True
        if (
            max_singular_mass is not None
            and sigma_q90 is not None
            and float(max_singular_mass) >= self.distributional_singular_mass_threshold
            and float(sigma_q90) >= 0.75 * self.sigma_threshold
        ):
            return True
        return False

    def _joint_hitting_trigger(
        self,
        proxy: ProxyReading,
        op_diag: OperatorDiagnostics | None,
        shadow_mass_state: ShadowMassState | None = None,
        realization_pressure: float | None = None,
    ) -> bool:
        dof = proxy.D
        curvature = proxy.K
        if dof is None or curvature is None:
            return False
        if realization_pressure is None:
            realization_pressure = self._forced_realization_pressure(proxy, op_diag, shadow_mass_state)
        return bool(
            float(dof) <= self.dof_collapse_threshold
            and float(curvature) >= self.curvature_spike_threshold
            and realization_pressure >= self.forced_realization_threshold
        )

    def _forced_realization_pressure(
        self,
        proxy: ProxyReading,
        op_diag: OperatorDiagnostics | None,
        shadow_mass_state: ShadowMassState | None = None,
    ) -> float:
        if shadow_mass_state is not None:
            return float(shadow_mass_state.forced_realization_pressure)
        realized = self._shadow_realized(proxy)
        shadow = self.shadow_realization_weight * (realized if realized > 0 else self._shadow_pre(proxy))
        if op_diag is None:
            return shadow
        operator_release = (
            max(0.0, float(op_diag.shadow_transfer))
            + max(0.0, float(op_diag.curvature_amplification))
            + max(0.0, 1.0 - float(op_diag.compression_ratio))
        )
        return float(shadow + self.operator_realization_weight * operator_release)

    def _shadow_pre(self, proxy: ProxyReading) -> float:
        value = getattr(proxy, "X_PRE", None)
        if value is None:
            value = proxy.X
        return self._positive_or_zero(value)

    def _shadow_realized(self, proxy: ProxyReading) -> float:
        return self._positive_or_zero(getattr(proxy, "X_REALIZED", None))
