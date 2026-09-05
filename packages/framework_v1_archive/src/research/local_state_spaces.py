from __future__ import annotations

from src.research.schemas import ClaimMaturityTag
from src.research.schemas import LocalStateSpace


DEFAULT_LOCAL_STATE_SPACES: tuple[LocalStateSpace, ...] = (
    LocalStateSpace(
        name="banking_MDKX",
        thesis="Bank fragility is local mismatch, funding degrees of freedom, balance-sheet curvature, and hidden loss realization pressure.",
        channels={
            "M": ("duration_loss_gap", "deposit_beta_gap", "asset_liability_anchor_gap"),
            "D": ("deposit_stability", "funding_access", "policy_backstop_access"),
            "K": ("bank_equity_dispersion", "rate_shock_convexity", "confidence_run_acceleration"),
            "X": ("AOCI_HTM_shadow_loss", "uninsured_deposit_pressure", "FHLB_dependency"),
        },
        default_variables=("banking_duration_mismatch", "deposit_pressure_gradient", "shadow_loss_over_funding_flexibility"),
        public_proxy_families=("KRE/KBE/XLF", "H8_deposits", "Call_Report", "FHLB_advances", "yield_curve_shock"),
        maturity=ClaimMaturityTag.PROXY_SUPPORTED,
        release_boundary="Public banking fragility surface; not a bank-run prediction.",
    ),
    LocalStateSpace(
        name="treasury_liquidity_MDKX",
        thesis="Treasury stress can emerge as local liquidity path compression before broad equity volatility fully reprices.",
        channels={
            "M": ("cash_futures_basis_gap", "on_off_the_run_gap"),
            "D": ("dealer_capacity", "market_depth", "repo_funding_access"),
            "K": ("rates_volatility", "liquidity_gap_acceleration"),
            "X": ("basis_trade_shadow_load", "leveraged_duration_crowding"),
        },
        default_variables=("low_vix_liquidity_gap", "dealer_capacity_compression", "basis_shadow_pressure"),
        public_proxy_families=("MOVE", "OFR_FSI", "Treasury_depth_proxy", "swap_spreads", "repo_proxy"),
        maturity=ClaimMaturityTag.HYPOTHESIS,
    ),
    LocalStateSpace(
        name="uk_rates_ldi_MDKX",
        thesis="LDI fragility is rates convexity plus collateral-call path compression under incomplete public leverage visibility.",
        channels={
            "M": ("liability_discount_gap", "long_gilt_drawdown"),
            "D": ("collateral_liquidity", "repo_or_swap_margin_flexibility"),
            "K": ("long_rate_shock", "GBP_swap_rate_convexity", "rates_volatility"),
            "X": ("unobserved_ldi_leverage", "pension_margin_call_shadow_load"),
        },
        default_variables=("gilt_convexity_pressure", "ldi_public_margin_proxy", "sterling_rates_stress_coupling"),
        public_proxy_families=("UK_gilts", "GBP_swaps", "sterling_stress", "BoE_events", "long_gilt_returns"),
        maturity=ClaimMaturityTag.HYPOTHESIS,
    ),
    LocalStateSpace(
        name="credit_carry_MDKX",
        thesis="Credit carry fragility is spread compression, liquidity path dependence, convex repricing, and hidden downgrade/default exposure.",
        channels={
            "M": ("spread_anchor_gap", "carry_vs_default_gap"),
            "D": ("secondary_liquidity", "refinancing_access"),
            "K": ("spread_acceleration", "downgrade_convexity"),
            "X": ("private_credit_shadow_load", "covenant_latency"),
        },
        default_variables=("carry_crowding_gap", "downgrade_curvature_pressure", "private_credit_shadow_proxy"),
        public_proxy_families=("HY_OAS", "IG_OAS", "LQD/HYG", "default_rate_proxy", "BDC_proxy"),
        maturity=ClaimMaturityTag.HYPOTHESIS,
    ),
    LocalStateSpace(
        name="fx_funding_MDKX",
        thesis="Dollar funding stress is cross-currency mismatch, swap-market degrees of freedom, basis curvature, and offshore shadow load.",
        channels={
            "M": ("cross_currency_basis_gap", "dollar_liability_gap"),
            "D": ("swap_market_access", "central_bank_swapline_access"),
            "K": ("basis_move_acceleration", "fx_volatility"),
            "X": ("offshore_usd_shadow_need", "unhedged_fx_liability_proxy"),
        },
        default_variables=("usd_funding_basis_pressure", "swapline_relief_gap", "offshore_dollar_shadow_need"),
        public_proxy_families=("cross_currency_basis", "DXY", "FX_vol", "swapline_usage", "EM_credit_proxy"),
        maturity=ClaimMaturityTag.HYPOTHESIS,
    ),
    LocalStateSpace(
        name="ai_capex_private_credit_MDKX",
        thesis="AI capex and private credit stress may appear as valuation-anchor mismatch plus opaque refinancing and concentration pressure.",
        channels={
            "M": ("capex_cashflow_anchor_gap", "valuation_duration_gap"),
            "D": ("refinancing_window", "private_credit_exit_liquidity"),
            "K": ("equity_dispersion", "earnings_revision_convexity"),
            "X": ("private_credit_opacity", "vendor_financing_shadow_load"),
        },
        default_variables=("ai_capex_anchor_gap", "private_credit_refi_pressure", "vendor_financing_shadow_load"),
        public_proxy_families=("AI_equity_basket", "credit_spreads", "BDC_proxy", "earnings_revision_proxy"),
        maturity=ClaimMaturityTag.HYPOTHESIS,
    ),
)


class LocalStateSpaceRegistry:
    def __init__(self, spaces: tuple[LocalStateSpace, ...] = DEFAULT_LOCAL_STATE_SPACES) -> None:
        self._spaces = {space.name: space for space in spaces}

    def all(self) -> tuple[LocalStateSpace, ...]:
        return tuple(self._spaces.values())

    def get(self, name: str) -> LocalStateSpace | None:
        return self._spaces.get(name)
