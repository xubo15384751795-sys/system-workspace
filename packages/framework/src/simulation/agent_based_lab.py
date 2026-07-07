from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ToyABMScenario:
    steps: int = 52
    seed: int = 7
    initial_leverage: float = 4.0
    target_leverage: float = 5.0
    leverage_adjustment_speed: float = 0.15
    funding_stress: float = 0.2
    collateral_shock: float = 0.0
    network_concentration: float = 0.3
    dealer_capacity: float = 1.0
    policy_delay: int = 8
    policy_backstop_strength: float = 0.25
    shadow_accumulation_speed: float = 1.0
    singular_d_threshold: float = -0.65
    singular_k_threshold: float = 0.65
    singular_x_threshold: float = 0.65


@dataclass(frozen=True)
class ScenarioSummary:
    singular_probability: float
    max_sigma: float
    min_d: float
    max_k: float
    max_x: float
    max_mean_field_gap: float
    terminal_forced_realization_pressure: float
    first_singular_step: int | None


class AgentBasedLab:
    """Santa Fe-style mechanism sandbox that coarse-grains all output to M/D/K/X."""

    def simulate(self, scenario: ToyABMScenario) -> pd.DataFrame:
        rng = np.random.default_rng(scenario.seed)
        leverage = float(scenario.initial_leverage)
        collateral_value = 1.0
        dealer_capacity = max(0.05, float(scenario.dealer_capacity))
        hidden_load = 0.0
        rows: list[dict[str, float | int | bool]] = []

        for step in range(scenario.steps):
            shock = 0.03 * rng.standard_normal()
            if step == 1 and scenario.collateral_shock:
                shock -= abs(scenario.collateral_shock)

            policy_active = step >= scenario.policy_delay
            backstop = scenario.policy_backstop_strength if policy_active else 0.0

            haircut = np.clip(
                scenario.funding_stress
                + 0.08 * max(0.0, leverage - scenario.target_leverage)
                + 0.06 * scenario.network_concentration
                - 0.5 * backstop,
                0.0,
                2.0,
            )
            collateral_value = max(0.05, collateral_value * (1.0 + shock - 0.05 * haircut))
            desired_leverage = max(1.0, scenario.target_leverage * (1.0 - 0.25 * haircut))
            leverage += scenario.leverage_adjustment_speed * (desired_leverage - leverage)

            liquidation_pressure = max(0.0, leverage - desired_leverage) + haircut
            dealer_capacity = max(0.02, dealer_capacity - 0.05 * liquidation_pressure + 0.03 * backstop)
            shadow_inflow = scenario.shadow_accumulation_speed * (
                0.08 * max(0.0, leverage - 3.0)
                + 0.06 * scenario.network_concentration
            )
            shadow_outflow = 0.04 * liquidation_pressure + 0.08 * backstop
            hidden_load = max(0.0, hidden_load + shadow_inflow - shadow_outflow)
            representative_shadow = max(0.0, hidden_load * (1.0 + 0.05 * scenario.funding_stress))
            coupled_shadow = hidden_load * (
                1.0
                + 0.20 * scenario.network_concentration
                + 0.25 * max(0.0, liquidation_pressure)
                + 0.15 * max(0.0, haircut)
            )
            mean_field_gap = abs(coupled_shadow - representative_shadow)
            forced_realization_pressure = coupled_shadow * (
                0.05
                + 0.55 * max(0.0, scenario.singular_d_threshold - _zlike(dealer_capacity - haircut - liquidation_pressure))
                + 0.45 * max(0.0, _zlike(scenario.network_concentration + liquidation_pressure + abs(shock)) - scenario.singular_k_threshold)
            )

            m_proxy = _zlike(haircut + abs(1.0 - collateral_value) + liquidation_pressure)
            d_proxy = _zlike(dealer_capacity - haircut - liquidation_pressure)
            k_proxy = _zlike(scenario.network_concentration + liquidation_pressure + abs(shock) + 0.2 * max(0, scenario.policy_delay - step))
            x_proxy = _zlike(coupled_shadow)
            sigma = max(0.0, m_proxy) + max(0.0, -d_proxy) + max(0.0, k_proxy) + max(0.0, x_proxy)

            rows.append(
                {
                    "step": step,
                    "M": m_proxy,
                    "D": d_proxy,
                    "K": k_proxy,
                    "X": x_proxy,
                    "Sigma": sigma,
                    "leverage": leverage,
                    "collateral_value": collateral_value,
                    "dealer_capacity": dealer_capacity,
                    "hidden_load": hidden_load,
                    "shadow_coupled_load": coupled_shadow,
                    "shadow_representative_load": representative_shadow,
                    "mean_field_gap": mean_field_gap,
                    "forced_realization_pressure": forced_realization_pressure,
                    "singular_flag": bool(
                        d_proxy <= scenario.singular_d_threshold
                        and k_proxy >= scenario.singular_k_threshold
                        and forced_realization_pressure >= scenario.singular_x_threshold
                    ),
                }
            )

        return pd.DataFrame.from_records(rows)

    def summarize(self, frame: pd.DataFrame) -> ScenarioSummary:
        if frame.empty:
            return ScenarioSummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None)
        singular = frame["singular_flag"].astype(bool)
        first = int(frame.loc[singular, "step"].iloc[0]) if singular.any() else None
        return ScenarioSummary(
            singular_probability=float(singular.mean()),
            max_sigma=float(frame["Sigma"].max()),
            min_d=float(frame["D"].min()),
            max_k=float(frame["K"].max()),
            max_x=float(frame["X"].max()),
            max_mean_field_gap=float(frame["mean_field_gap"].max()),
            terminal_forced_realization_pressure=float(frame["forced_realization_pressure"].iloc[-1]),
            first_singular_step=first,
        )


def _zlike(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return float(np.tanh(value))
