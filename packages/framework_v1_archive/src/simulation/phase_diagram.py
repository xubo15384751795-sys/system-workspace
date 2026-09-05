from __future__ import annotations

import pandas as pd

from src.simulation.agent_based_lab import AgentBasedLab, ToyABMScenario


def leverage_funding_phase_diagram(
    leverage_speeds: list[float],
    funding_stresses: list[float],
    base: ToyABMScenario | None = None,
) -> pd.DataFrame:
    """Map stable/local-instability/global-instability regions over scenario parameters."""

    lab = AgentBasedLab()
    base_scenario = base or ToyABMScenario()
    rows: list[dict[str, float | int | str | None]] = []
    for speed in leverage_speeds:
        for funding in funding_stresses:
            scenario = ToyABMScenario(
                steps=base_scenario.steps,
                seed=base_scenario.seed,
                initial_leverage=base_scenario.initial_leverage,
                target_leverage=base_scenario.target_leverage,
                leverage_adjustment_speed=speed,
                funding_stress=funding,
                collateral_shock=base_scenario.collateral_shock,
                network_concentration=base_scenario.network_concentration,
                dealer_capacity=base_scenario.dealer_capacity,
                policy_delay=base_scenario.policy_delay,
                policy_backstop_strength=base_scenario.policy_backstop_strength,
            )
            summary = lab.summarize(lab.simulate(scenario))
            if summary.singular_probability > 0.25:
                regime = "GLOBAL_INSTABILITY"
            elif summary.max_sigma >= 2.0:
                regime = "LOCAL_INSTABILITY"
            else:
                regime = "STABLE"
            rows.append(
                {
                    "leverage_adjustment_speed": speed,
                    "funding_stress": funding,
                    "regime": regime,
                    "singular_probability": summary.singular_probability,
                    "max_sigma": summary.max_sigma,
                    "min_d": summary.min_d,
                    "max_k": summary.max_k,
                    "max_x": summary.max_x,
                    "max_mean_field_gap": summary.max_mean_field_gap,
                    "terminal_forced_realization_pressure": summary.terminal_forced_realization_pressure,
                    "first_singular_step": summary.first_singular_step,
                }
            )
    return pd.DataFrame.from_records(rows)
