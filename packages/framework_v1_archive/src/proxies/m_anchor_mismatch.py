from __future__ import annotations

from src.proxies.proxy_base import ProxyGroup, ProxyInput, StructuralProxyDefinition


M_PROXY_DEFINITION = StructuralProxyDefinition(
    channel="M",
    label="anchor_mismatch",
    construction_boundary=(
        "M maps anchor-implied states against operative market states. "
        "Aggregate stress indices are excluded and may only enter benchmarks or controls."
    ),
    groups=(
        ProxyGroup(
            name="M_POLICY_ANCHOR",
            interpretation="Market-implied policy path versus current or guided policy anchor.",
            inputs=(
                ProxyInput("M_POLICY_ANCHOR", "stress"),
                ProxyInput("M_MARKET_POLICY_PATH_GAP", "stress"),
                ProxyInput("M_POLICY_GUIDANCE_GAP", "stress"),
                ProxyInput("SOFR_FFR", "stress"),
                ProxyInput("LIBOR_OIS_3M", "stress"),
            ),
        ),
        ProxyGroup(
            name="M_FUNDING_ANCHOR",
            interpretation="Secured and unsecured funding dislocations relative to policy anchors.",
            inputs=(
                ProxyInput("M_FUNDING_ANCHOR", "stress"),
                ProxyInput("M_REPO_IMPLIED_FUNDING_GAP", "stress"),
                ProxyInput("M_PRICE_FUNDING_GAP", "stress"),
                ProxyInput("SOFR_TBILL_3M", "stress"),
            ),
        ),
        ProxyGroup(
            name="M_COLLATERAL_ANCHOR",
            interpretation="Collateral price, liquidity premium, and basis divergence.",
            inputs=(
                ProxyInput("M_COLLATERAL_ANCHOR", "stress"),
                ProxyInput("M_TREASURY_BASIS", "stress"),
                ProxyInput("M_SWAP_SPREAD", "stress"),
                ProxyInput("M_CASH_FUTURES_BASIS", "stress"),
                ProxyInput("M_ON_OFF_THE_RUN_SPREAD", "stress"),
            ),
        ),
        ProxyGroup(
            name="M_CREDIT_ANCHOR",
            interpretation="Credit spread moves not explained by default-expectation proxies.",
            inputs=(
                ProxyInput("M_CREDIT_ANCHOR", "stress"),
                ProxyInput("M_CREDIT_SPREAD_DEFAULT_GAP", "stress"),
                ProxyInput("M_CDS_BOND_BASIS", "stress"),
                ProxyInput("HY_IG_GAP", "stress"),
                ProxyInput("BBB_IG_GAP", "stress"),
            ),
        ),
        ProxyGroup(
            name="M_VERIFIABILITY_ANCHOR",
            interpretation="Market-value versus accounting or reported balance-sheet stability.",
            inputs=(
                ProxyInput("M_VERIFIABILITY_ANCHOR", "stress"),
                ProxyInput("M_PRICE_VERIFIABILITY_GAP", "stress"),
                ProxyInput("M_ACCOUNTING_MARKET_VALUE_GAP", "stress"),
                ProxyInput("M_BANK_EQUITY_BALANCE_SHEET_GAP", "stress"),
                ProxyInput("M_ETF_NAV_DISCOUNT_PREMIUM", "stress"),
            ),
        ),
        ProxyGroup(
            name="M_PRICE_LIQUIDATION_GAP",
            interpretation="Legacy liquidation-anchor basket retained for backward compatibility.",
            inputs=(
                ProxyInput("M_PRICE_LIQUIDATION_GAP", "stress"),
                ProxyInput("M_FIRE_SALE_DISCOUNT", "stress"),
                ProxyInput("M_DEPTH_ADJUSTED_LIQUIDATION_COST", "stress"),
                ProxyInput("M_BID_WANTED_PRESSURE", "stress"),
            ),
        ),
    ),
)
