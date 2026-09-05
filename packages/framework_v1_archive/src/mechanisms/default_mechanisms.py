from __future__ import annotations

from src.mechanisms.base import MechanismRegistry, MechanismTerm


def build_default_mechanism_registry(enabled_families: list[str] | None = None) -> MechanismRegistry:
    enabled = set(enabled_families) if enabled_families else None
    return MechanismRegistry(terms=default_mechanism_terms(), enabled_families=enabled)


def default_mechanism_terms() -> list[MechanismTerm]:
    return [
        MechanismTerm(
            name="model_measurement_feedback_to_dof",
            family="danielsson_shin_zigrand",
            target_channel="D",
            driver="K_STRESS",
            coefficient=-0.04,
            description="Endogenous-risk measurement feedback tightens constraints as transition stress rises.",
        ),
        MechanismTerm(
            name="compression_error_to_curvature",
            family="danielsson_shin_zigrand",
            target_channel="K",
            driver="M_STRESS",
            coefficient=0.035,
            description="Model-mediated compression error amplifies path-order sensitivity.",
        ),
        MechanismTerm(
            name="procyclical_leverage_to_shadow_load",
            family="adrian_shin",
            target_channel="X",
            driver="leverage_pressure",
            coefficient=0.05,
            description="Procyclical intermediary leverage stores pressure in hidden balance-sheet channels.",
        ),
        MechanismTerm(
            name="intermediary_capacity_to_dof",
            family="adrian_shin",
            target_channel="D",
            driver="intermediary_capital_buffer",
            coefficient=0.06,
            description="Intermediary capital and balance-sheet capacity widen effective feasible paths.",
        ),
        MechanismTerm(
            name="funding_liquidity_spiral_to_dof",
            family="brunnermeier_pedersen",
            target_channel="D",
            driver="M_STRESS",
            coefficient=-0.05,
            description="Funding-price mismatch contracts market and funding liquidity jointly.",
        ),
        MechanismTerm(
            name="market_liquidity_gap_to_mismatch",
            family="brunnermeier_pedersen",
            target_channel="M",
            driver="D_CONTRACTION",
            coefficient=0.04,
            description="Liquidity path contraction increases price-funding and liquidation anchor gaps.",
        ),
        MechanismTerm(
            name="capital_constraint_to_dof",
            family="he_krishnamurthy",
            target_channel="D",
            driver="capital_constraint_pressure",
            coefficient=-0.055,
            description="Intermediary capital constraints reduce risk-bearing and hedging capacity.",
        ),
        MechanismTerm(
            name="collateral_leverage_cycle_to_shadow",
            family="geanakoplos",
            target_channel="X",
            driver="collateral_leverage_pressure",
            coefficient=0.05,
            description="Collateral-leverage cycles accumulate hidden deferred realization pressure.",
        ),
        MechanismTerm(
            name="collateral_anchor_gap_to_mismatch",
            family="geanakoplos",
            target_channel="M",
            driver="collateral_anchor_gap",
            coefficient=0.045,
            description="Collateral value and financing-anchor slippage raises mismatch intensity.",
        ),
        MechanismTerm(
            name="tranching_complexity_to_curvature",
            family="fostel_geanakoplos",
            target_channel="K",
            driver="X_STRESS",
            coefficient=0.035,
            description="Tranched and synthetic exposure converts hidden load into nonlinear propagation.",
        ),
        MechanismTerm(
            name="tranche_verifiability_gap_to_mismatch",
            family="fostel_geanakoplos",
            target_channel="M",
            driver="tranche_verifiability_gap",
            coefficient=0.05,
            description="Structured-credit opacity widens price-verifiability anchor gaps.",
        ),
        MechanismTerm(
            name="network_concentration_to_curvature",
            family="haldane_may_santa_fe",
            target_channel="K",
            driver="network_concentration",
            coefficient=0.055,
            description="Network concentration and overlap make local shock transport unstable.",
        ),
        MechanismTerm(
            name="policy_delay_to_latency_stress",
            family="santa_fe_complexity",
            target_channel="K",
            driver="policy_delay",
            coefficient=0.03,
            description="Delayed interventions increase path dependence and transition-map deformation.",
        ),
    ]
