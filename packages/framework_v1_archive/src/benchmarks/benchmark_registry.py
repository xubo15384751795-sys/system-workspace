from __future__ import annotations

BENCHMARK_FAMILIES: dict[str, dict[str, list[str]]] = {
    "aggregate_stress": {
        "primary": ["NFCI", "ANFCI", "STLFSI4", "OFR_FSI"],
        "secondary": ["KCFSI", "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE"],
    },
    "volatility": {
        "equity": ["VIX", "VVIX"],
        "rates": ["MOVE"],
        "realized": ["SPX_realized_vol_21d", "TY_realized_vol_21d"],
    },
    "credit": {
        "spreads": ["BAMLH0A0HYM2_HY_OAS", "BAMLC0A0CM_IG_OAS", "BAA_AAA_spread"],
    },
    "liquidity": {
        "treasury": ["on_off_the_run_spread", "treasury_liquidity_proxy"],
        "market": ["bid_ask_proxy", "amihud_illiq"],
    },
    "funding": {
        "secured": ["SOFR_related_spread", "repo_stress_proxy"],
        "unsecured": ["commercial_paper_spread", "FRA_OIS_or_historical_equivalent"],
    },
    "leverage_shadow": {
        "public": ["NFCILEVERAGE", "margin_debt", "broker_dealer_assets", "repo_volume"],
        "slow_shadow": ["private_credit_proxy", "MMF_repo_proxy", "HTM_unrealized_loss_proxy"],
    },
    "portfolio": {
        "baselines": ["SPY_only", "60_40_SPY_AGG", "risk_parity", "T_bill"],
        "overlays": [
            "NFCI_overlay",
            "VIX_overlay",
            "Sigma_overlay",
            "Sigma_residual_overlay",
            "component_morphology_overlay",
        ],
    },
}


COMPONENT_RIVALS: dict[str, str] = {
    "M_proxy": "basis_spread_only_mismatch_index",
    "D_proxy": "liquidity_only_index",
    "K_proxy": "volatility_jump_tail_index",
    "X_proxy": "leverage_only_index",
    "Sigma_t": "NFCI_STLFSI_OFR_FSI",
}


def family_series(family: str) -> list[str]:
    groups = BENCHMARK_FAMILIES.get(family, {})
    out: list[str] = []
    for values in groups.values():
        out.extend(values)
    return out


__all__ = ["BENCHMARK_FAMILIES", "COMPONENT_RIVALS", "family_series"]
