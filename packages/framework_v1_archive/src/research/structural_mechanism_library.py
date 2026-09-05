from __future__ import annotations

from src.research.schemas import ClaimMaturityTag
from src.research.schemas import StructuralMechanism


DEFAULT_MECHANISMS: tuple[StructuralMechanism, ...] = (
    StructuralMechanism(
        name="policy_backstop_operator",
        description="Policy support restores degrees of freedom while potentially moving stress into shadow load.",
        operator_names=("POLICY_BACKSTOP", "LIQUIDITY_FACILITY"),
        local_state_space="global_policy_reaction",
        maturity=ClaimMaturityTag.PROXY_SUPPORTED,
        proxy_requirements=("central_bank_events", "liquidity_facility_usage", "funding_spreads"),
        output_claim_boundary="Mechanism generator, not proof of risk removal.",
    ),
    StructuralMechanism(
        name="deposit_run_operator",
        description="Deposit flight compresses bank funding paths and raises local mismatch/curvature.",
        operator_names=("DEPOSIT_RUN", "DEPOSIT_GUARANTEE"),
        local_state_space="banking_MDKX",
        maturity=ClaimMaturityTag.PROXY_SUPPORTED,
        proxy_requirements=("H8_deposits", "KRE", "KBE", "bank_equity_dispersion"),
        output_claim_boundary="Public banking fragility surface, not bank-run prediction.",
    ),
    StructuralMechanism(
        name="collateral_spiral_operator",
        description="Falling collateral values trigger margin calls, forced selling, and curvature amplification.",
        operator_names=("MARGIN_CALL", "FUNDING_HAIRCUT", "FORCED_SELLING"),
        local_state_space="collateral_liquidity_MDKX",
        maturity=ClaimMaturityTag.CASE_SUPPORTED,
        proxy_requirements=("collateral_price_drawdown", "funding_spreads", "dealer_capacity"),
        output_claim_boundary="Forensic path generator unless validated against forward stress targets.",
    ),
    StructuralMechanism(
        name="duration_loss_operator",
        description="Rate shocks create duration losses that may become funding fragility when confidence or liquidity weakens.",
        operator_names=("RATE_HIKE", "BASIS_DISLOCATION", "DEPOSIT_RUN"),
        local_state_space="banking_duration_MDKX",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        proxy_requirements=("yield_curve_shock", "AOCI_proxy", "HTM_proxy", "deposit_pressure"),
        output_claim_boundary="Candidate local state-space mapping, not a precise balance-sheet claim.",
    ),
    StructuralMechanism(
        name="liquidity_evaporation_operator",
        description="Market depth and balance-sheet capacity vanish before broad volatility fully reprices.",
        operator_names=("LIQUIDITY_WITHDRAWAL", "DEALER_CAPACITY_DROP"),
        local_state_space="treasury_liquidity_MDKX",
        maturity=ClaimMaturityTag.PROXY_SUPPORTED,
        proxy_requirements=("bid_ask_proxy", "OFR_FSI", "Treasury_depth", "MOVE"),
        output_claim_boundary="Liquidity-path hypothesis requiring public-data validation.",
    ),
    StructuralMechanism(
        name="narrative_acceleration_operator",
        description="Narrative spread changes confidence/run intensity faster than slow balance-sheet data updates.",
        operator_names=("RUN_EVENT", "CORRELATION_BREAK"),
        local_state_space="confidence_run_MDKX",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        proxy_requirements=("news_intensity", "search_interest", "equity_dispersion"),
        output_claim_boundary="Speculative narrative mechanism; never a standalone validated warning.",
    ),
    StructuralMechanism(
        name="basis_dislocation_operator",
        description="Normally anchored relative-value relationships detach, widening mismatch and convexity.",
        operator_names=("BASIS_DISLOCATION", "DEALER_CAPACITY_DROP"),
        local_state_space="basis_MDKX",
        maturity=ClaimMaturityTag.CASE_SUPPORTED,
        proxy_requirements=("basis_spread", "dealer_capacity", "funding_spreads"),
        output_claim_boundary="Case-supported forensic mechanism until OOS tested.",
    ),
    StructuralMechanism(
        name="dealer_balance_sheet_compression_operator",
        description="Intermediary capacity drops and the same shock maps to worse D/K outcomes.",
        operator_names=("DEALER_CAPACITY_DROP", "LIQUIDITY_WITHDRAWAL"),
        local_state_space="dealer_capacity_MDKX",
        maturity=ClaimMaturityTag.PROXY_SUPPORTED,
        proxy_requirements=("primary_dealer_positions", "Treasury_depth", "funding_spreads"),
        output_claim_boundary="Structural capacity hypothesis, not direct trading advice.",
    ),
    StructuralMechanism(
        name="policy_reaction_delay_operator",
        description="Policy support arrives after the local path has already compressed, creating sequence-dependent outcomes.",
        operator_names=("LIQUIDITY_WITHDRAWAL", "POLICY_BACKSTOP"),
        local_state_space="global_policy_reaction",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        proxy_requirements=("policy_event_time", "stress_index", "facility_usage"),
        output_claim_boundary="Scenario timing mechanism, not a policy forecast.",
    ),
    StructuralMechanism(
        name="collateral_reuse_break_operator",
        description="Collateral reuse chains shorten, making the same asset shock produce larger D contraction.",
        operator_names=("COLLATERAL_TRANSFORMATION", "FUNDING_HAIRCUT", "MARGIN_CALL"),
        local_state_space="collateral_liquidity_MDKX",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        proxy_requirements=("repo_proxy", "collateral_haircut_proxy", "dealer_capacity"),
        output_claim_boundary="Collateral plumbing hypothesis requiring proxy construction.",
    ),
    StructuralMechanism(
        name="vol_suppression_snapback_operator",
        description="Low realized volatility can store leverage and make later K jumps sharper.",
        operator_names=("SYNTHETIC_EXPOSURE_BUILDUP", "VOL_SURFACE_KINK", "CORRELATION_BREAK"),
        local_state_space="volatility_carry_MDKX",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        proxy_requirements=("VIX", "VVIX", "realized_vol", "vol_control_proxy"),
        output_claim_boundary="Volatility-carry hypothesis, not a short-vol timing signal.",
    ),
    StructuralMechanism(
        name="sovereign_bank_feedback_operator",
        description="Sovereign rate or spread shock weakens banks, and bank stress feeds back into sovereign funding conditions.",
        operator_names=("BASIS_DISLOCATION", "DEPOSIT_RUN", "POLICY_BACKSTOP"),
        local_state_space="sovereign_bank_MDKX",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        proxy_requirements=("sovereign_spreads", "bank_equity", "deposit_proxy", "policy_events"),
        output_claim_boundary="Feedback-loop hypothesis, not a country-risk forecast.",
    ),
    StructuralMechanism(
        name="private_credit_valuation_lag_operator",
        description="Stale private marks delay visible stress while public credit and listed lenders begin moving.",
        operator_names=("OFF_BALANCE_SHEET_SHIFT", "RATING_CASCADE", "TRANCHE_REPRICING"),
        local_state_space="credit_carry_MDKX",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        proxy_requirements=("BDC_proxy", "HY_OAS", "IG_OAS", "default_proxy"),
        output_claim_boundary="Public proxy for opacity, not private-book valuation certainty.",
    ),
    StructuralMechanism(
        name="commodity_margin_squeeze_operator",
        description="Commodity price jumps create margin pressure that transmits into liquidity and dealer capacity.",
        operator_names=("MARGIN_CALL", "FUNDING_HAIRCUT", "DEALER_CAPACITY_DROP"),
        local_state_space="commodity_margin_MDKX",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        proxy_requirements=("commodity_vol", "futures_curve_stress", "funding_spreads"),
        output_claim_boundary="Margin-path mechanism, not commodity trading advice.",
    ),
)


class StructuralMechanismLibrary:
    def __init__(self, mechanisms: tuple[StructuralMechanism, ...] = DEFAULT_MECHANISMS) -> None:
        self._mechanisms = {mechanism.name: mechanism for mechanism in mechanisms}

    def all(self) -> tuple[StructuralMechanism, ...]:
        return tuple(self._mechanisms.values())

    def get(self, name: str) -> StructuralMechanism | None:
        return self._mechanisms.get(name)

    def by_state_space(self, state_space: str) -> tuple[StructuralMechanism, ...]:
        return tuple(item for item in self._mechanisms.values() if item.local_state_space == state_space)
