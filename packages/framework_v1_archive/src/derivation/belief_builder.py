from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt

import numpy as np

from src.core.interfaces import BeliefBuilderInterface
from src.core.models import ChannelBeliefState, DistributionState, ProxyReading, StructuralBeliefState
from src.operators.operator_schema import OperatorDiagnostics


CHANNELS: tuple[str, ...] = ("M", "D", "K", "X")
Z_Q10 = -1.2815515655446004
Z_Q90 = 1.2815515655446004
EPS = 1e-9


def _normal_cdf(value: float, mean: float, variance: float) -> float:
    safe_var = max(EPS, float(variance))
    z = (float(value) - float(mean)) / sqrt(2.0 * safe_var)
    return 0.5 * (1.0 + erf(z))


def _tail_prob_above(threshold: float, mean: float, variance: float) -> float:
    return float(max(0.0, min(1.0, 1.0 - _normal_cdf(threshold, mean, variance))))


def _tail_prob_below(threshold: float, mean: float, variance: float) -> float:
    return float(max(0.0, min(1.0, _normal_cdf(threshold, mean, variance))))


@dataclass
class DefaultBeliefBuilder(BeliefBuilderInterface):
    base_variance: float = 0.16
    variance_floor: float = 0.01
    evidence_blend: float = 0.65
    contradiction_scale: float = 0.25
    operator_uncertainty_scale: float = 0.12
    sigma_threshold: float = 2.0

    def build(
        self,
        proxy: ProxyReading,
        previous_belief: StructuralBeliefState | None = None,
        operator_diagnostics: OperatorDiagnostics | None = None,
    ) -> StructuralBeliefState:
        channels: dict[str, ChannelBeliefState] = {}
        for channel in CHANNELS:
            channels[channel] = self._build_channel_state(
                channel=channel,
                proxy=proxy,
                previous_state=previous_belief.channels.get(channel) if previous_belief is not None else None,
                operator_diagnostics=operator_diagnostics,
            )

        sigma_distribution = self._build_sigma_distribution(channels)
        channel_breach_probs = {
            channel: state.distribution.breach_prob for channel, state in channels.items()
        }
        channel_singular_mass = {
            channel: state.distribution.singular_mass for channel, state in channels.items()
        }
        escalation_metrics = {
            "sigma_breach_prob": sigma_distribution.breach_prob if sigma_distribution is not None else None,
            "sigma_q90": sigma_distribution.upper_q if sigma_distribution is not None else None,
            "channel_breach_probs": channel_breach_probs,
            "channel_singular_mass": channel_singular_mass,
            "max_channel_singular_mass": max(
                (float(value) for value in channel_singular_mass.values() if value is not None),
                default=0.0,
            ),
        }
        return StructuralBeliefState(
            run_date=proxy.run_date,
            channels=channels,
            joint_mode="independent",
            covariance=None,
            sigma_distribution=sigma_distribution,
            escalation_metrics=escalation_metrics,
        )

    def _build_channel_state(
        self,
        channel: str,
        proxy: ProxyReading,
        previous_state: ChannelBeliefState | None,
        operator_diagnostics: OperatorDiagnostics | None,
    ) -> ChannelBeliefState:
        raw_value = self._proxy_value(proxy, channel)
        transformed = self._transform(channel, raw_value)
        component_values = self._component_values(proxy, channel)
        disagreement = float(np.std(component_values, ddof=0)) if len(component_values) >= 2 else 0.0
        direct_weight = 1.0 if proxy.available.get(channel, False) else 0.0
        structural_weight = self._structural_weight(channel, operator_diagnostics)
        evidence_tags = ["proxy_snapshot"]
        if disagreement > 0.0:
            evidence_tags.append("component_divergence")
        if structural_weight > 0.0:
            evidence_tags.append("operator_path")

        prior_mean = previous_state.distribution.mean if previous_state is not None else transformed
        if prior_mean is None:
            prior_mean = transformed
        if prior_mean is None:
            prior_mean = 0.0
        prior_var = (
            previous_state.distribution.variance
            if previous_state is not None and previous_state.distribution.variance is not None
            else self.base_variance
        )
        process_var = self.base_variance * structural_weight
        obs_var = max(self.variance_floor, disagreement**2, self.base_variance * (1.0 - direct_weight * 0.5))
        alpha = self.evidence_blend if transformed is not None else 0.0
        posterior_mean = float((1.0 - alpha) * prior_mean + alpha * (transformed if transformed is not None else prior_mean))
        posterior_var = float(
            max(
                self.variance_floor,
                (1.0 - alpha) * (prior_var + process_var)
                + alpha * obs_var
                + self.contradiction_scale * disagreement**2
                + self.operator_uncertainty_scale * structural_weight,
            )
        )

        raw_variance = max(self.variance_floor, obs_var + self.operator_uncertainty_scale * structural_weight)
        lower_q = float(posterior_mean + Z_Q10 * sqrt(posterior_var))
        upper_q = float(posterior_mean + Z_Q90 * sqrt(posterior_var))
        breach_prob = self._breach_probability(channel, raw_value, raw_variance)
        confidence = max(0.05, min(0.99, 0.35 + 0.35 * direct_weight + 0.15 * (1.0 - min(1.0, disagreement)) + 0.15 * structural_weight))
        distribution = DistributionState(
            family="normal",
            transform=self._transform_name(channel),
            mean=posterior_mean,
            variance=posterior_var,
            raw_mean=raw_value,
            raw_variance=raw_variance,
            lower_q=lower_q,
            upper_q=upper_q,
            support_min=None,
            support_max=None,
            confidence=float(confidence),
            effective_n=float(max(1, len(component_values))),
            direct_evidence_weight=float(direct_weight),
            structural_evidence_weight=float(structural_weight),
            breach_prob=breach_prob,
            singular_mass=breach_prob,
            metadata={
                "component_count": len(component_values),
                "component_disagreement": disagreement,
            },
        )
        return ChannelBeliefState(
            channel=channel,
            raw_point=raw_value,
            transformed_point=transformed,
            distribution=distribution,
            evidence_tags=tuple(evidence_tags),
            last_update_source="proxy_plus_operator_path",
        )

    def _build_sigma_distribution(self, channels: dict[str, ChannelBeliefState]) -> DistributionState:
        sigma_mean = 0.0
        sigma_var = 0.0
        for channel, state in channels.items():
            raw_mean = float(state.distribution.raw_mean or 0.0)
            raw_var = float(state.distribution.raw_variance or self.variance_floor)
            if channel == "D":
                contribution = max(0.0, -raw_mean)
            else:
                contribution = max(0.0, raw_mean)
            sigma_mean += contribution
            sigma_var += raw_var
        sigma_var = max(self.variance_floor, sigma_var)
        sigma_q90 = float(sigma_mean + Z_Q90 * sqrt(sigma_var))
        sigma_breach_prob = _tail_prob_above(self.sigma_threshold, sigma_mean, sigma_var)
        return DistributionState(
            family="normal",
            transform="identity",
            mean=sigma_mean,
            variance=sigma_var,
            raw_mean=sigma_mean,
            raw_variance=sigma_var,
            lower_q=float(sigma_mean + Z_Q10 * sqrt(sigma_var)),
            upper_q=sigma_q90,
            confidence=float(np.mean([state.distribution.confidence for state in channels.values()])),
            effective_n=float(sum((state.distribution.effective_n or 1.0) for state in channels.values())),
            direct_evidence_weight=float(np.mean([state.distribution.direct_evidence_weight for state in channels.values()])),
            structural_evidence_weight=float(
                np.mean([state.distribution.structural_evidence_weight for state in channels.values()])
            ),
            breach_prob=sigma_breach_prob,
            singular_mass=sigma_breach_prob,
            metadata={"channel_count": len(channels)},
        )

    def _proxy_value(self, proxy: ProxyReading, channel: str) -> float | None:
        return getattr(proxy, channel, None)

    def _component_values(self, proxy: ProxyReading, channel: str) -> list[float]:
        values: list[float] = []
        for name, value in dict(proxy.components).items():
            if value is None:
                continue
            if name == channel or str(name).startswith(f"{channel}_"):
                numeric = float(value)
                if np.isfinite(numeric):
                    values.append(numeric)
        if not values and self._proxy_value(proxy, channel) is not None:
            values.append(float(self._proxy_value(proxy, channel) or 0.0))
        return values

    def _transform_name(self, channel: str) -> str:
        if channel == "M":
            return "signed_log1p"
        if channel == "D":
            return "capacity_log"
        return "log1p_pos"

    def _transform(self, channel: str, value: float | None) -> float | None:
        if value is None or not np.isfinite(value):
            return None
        x = float(value)
        if channel == "M":
            return float(np.sign(x) * np.log1p(abs(x)))
        if channel == "D":
            return float(np.log(max(EPS, 1.0 + x)))
        return float(np.log1p(max(0.0, x)))

    def _structural_weight(self, channel: str, operator_diagnostics: OperatorDiagnostics | None) -> float:
        if operator_diagnostics is None or operator_diagnostics.operator_count <= 0:
            return 0.0
        base = min(1.0, operator_diagnostics.non_commutativity_score + 0.2 * operator_diagnostics.irreversible_count)
        if channel == "D":
            base += max(0.0, 1.0 - float(operator_diagnostics.compression_ratio))
        if channel == "X":
            base += max(0.0, float(operator_diagnostics.shadow_transfer))
        if channel == "K":
            base += max(0.0, float(operator_diagnostics.curvature_amplification))
        if channel == "M":
            base += max(0.0, float(operator_diagnostics.mismatch_amplification))
        return float(min(1.0, max(0.0, base)))

    def _breach_probability(self, channel: str, raw_mean: float | None, raw_variance: float) -> float | None:
        if raw_mean is None:
            return None
        if channel == "D":
            return _tail_prob_below(-0.5, raw_mean, raw_variance)
        return _tail_prob_above(0.5, raw_mean, raw_variance)
