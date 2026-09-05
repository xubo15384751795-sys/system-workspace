from __future__ import annotations

from src.proxies.proxy_base import ProxyGroup, ProxyInput, StructuralProxyDefinition


D_PROXY_DEFINITION = StructuralProxyDefinition(
    channel="D",
    label="path_feasibility",
    construction_boundary=(
        "D is degrees of freedom: high D means executable paths remain open, "
        "while low D is path contraction. Sigma must use D_stress = -D."
    ),
    groups=(
        ProxyGroup(
            name="D_MARKET_DEPTH",
            interpretation="Tradable depth and price-impact capacity.",
            inputs=(
                ProxyInput("D_MARKET_DEPTH", "freedom"),
                ProxyInput("D_DEPTH", "freedom"),
                ProxyInput("D_ORDER_BOOK_DEPTH", "freedom"),
                ProxyInput("D_BID_ASK_SPREAD", "stress"),
                ProxyInput("D_AMIHUD_ILLIQUIDITY", "stress"),
                ProxyInput("D_PRICE_IMPACT", "stress"),
            ),
        ),
        ProxyGroup(
            name="D_HEDGE_BREADTH",
            interpretation="Availability and breadth of hedging paths across instruments and maturities.",
            inputs=(
                ProxyInput("D_HEDGE_BREADTH", "freedom"),
                ProxyInput("D_OPTION_OPEN_INTEREST_BREADTH", "freedom"),
                ProxyInput("D_STRIKE_MATURITY_COVERAGE", "freedom"),
                ProxyInput("D_HEDGE_AVAILABILITY", "freedom"),
                ProxyInput("D_HEDGE_INSTRUMENT_CORRELATION", "stress"),
            ),
        ),
        ProxyGroup(
            name="D_FUNDING_ACCESS",
            interpretation="Funding access, margin, haircut, and dealer balance-sheet capacity.",
            inputs=(
                ProxyInput("D_FUNDING_ACCESS", "freedom"),
                ProxyInput("D_DEALER_CAPACITY", "freedom"),
                ProxyInput("D_REPO_ACCESSIBILITY", "freedom"),
                ProxyInput("D_REPO_SPREAD", "stress"),
                ProxyInput("D_HAIRCUT_MARGIN", "stress"),
                ProxyInput("D_FUNDING_STRESS", "stress"),
            ),
        ),
        ProxyGroup(
            name="D_LIQUIDATION_PATHS",
            interpretation="Capacity to liquidate without single-route congestion or forced discounts.",
            inputs=(
                ProxyInput("D_LIQUIDATION_PATHS", "freedom"),
                ProxyInput("D_DEALER_INVENTORY_ABSORPTION", "freedom"),
                ProxyInput("D_PRIMARY_DEALER_CAPACITY", "freedom"),
                ProxyInput("D_MARKET_CONCENTRATION", "stress"),
                ProxyInput("D_ETF_NAV_DISLOCATION", "stress"),
            ),
        ),
    ),
)
