from __future__ import annotations

from src.proxies.proxy_base import ProxyGroup, ProxyInput, StructuralProxyDefinition


X_PRE_PROXY_DEFINITION = StructuralProxyDefinition(
    channel="X_PRE",
    label="shadow_accumulation_pre_realization",
    construction_boundary=(
        "X_PRE is hidden stock and deferred pressure before official realization. "
        "Slow-moving monthly or weekly inputs may be forward-filled, but should remain "
        "marked as slow stock variables. Official support usage is excluded."
    ),
    groups=(
        ProxyGroup(
            name="X_HIDDEN_LEVERAGE",
            interpretation="Margin debt, dealer leverage, broker-dealer assets, repo reuse.",
            inputs=(
                ProxyInput("X_HIDDEN_LEVERAGE", "stress", frequency="monthly"),
                ProxyInput("X_MARGIN_DEBT", "stress", frequency="monthly"),
                ProxyInput("X_DEALER_LEVERAGE_PROXY", "stress", frequency="weekly"),
                ProxyInput("X_BROKER_DEALER_ASSETS", "stress", frequency="weekly"),
                ProxyInput("X_REPO_VOLUME_COLLATERAL_REUSE", "stress", frequency="weekly"),
                ProxyInput("X_OBS_ASSETS", "stress", frequency="quarterly"),
            ),
        ),
        ProxyGroup(
            name="X_SHADOW_SUBSTITUTION",
            interpretation="Private credit, nonbank lending, MMF/repo substitution.",
            inputs=(
                ProxyInput("X_SHADOW_SUBSTITUTION", "stress", frequency="monthly"),
                ProxyInput("X_SHADOW_FUNDING", "stress", frequency="weekly"),
                ProxyInput("X_PRIVATE_CREDIT_GROWTH", "stress", frequency="monthly"),
                ProxyInput("X_NONBANK_LENDING_GROWTH", "stress", frequency="monthly"),
                ProxyInput("X_MMF_REPO_INTERMEDIATION", "stress", frequency="weekly"),
            ),
        ),
        ProxyGroup(
            name="X_MATURITY_MISMATCH",
            interpretation="Short funding reliance, maturity walls, deposits, duration mismatch.",
            inputs=(
                ProxyInput("X_MATURITY_MISMATCH", "stress", frequency="monthly"),
                ProxyInput("X_SHORT_TERM_FUNDING_RELIANCE", "stress", frequency="weekly"),
                ProxyInput("X_MATURITY_WALL", "stress", frequency="monthly"),
                ProxyInput("X_DEPOSIT_BETA_UNINSURED_STRESS", "stress", frequency="weekly"),
                ProxyInput("X_ASSET_LIABILITY_DURATION_MISMATCH", "stress", frequency="monthly"),
            ),
        ),
        ProxyGroup(
            name="X_VALUATION_LAG",
            interpretation="Stale marks and balance-sheet losses whose realization is deferred.",
            inputs=(
                ProxyInput("X_VALUATION_LAG", "stress", frequency="quarterly"),
                ProxyInput("X_PRIVATE_ASSET_VALUATION_LAG", "stress", frequency="quarterly"),
                ProxyInput("X_HTM_UNREALIZED_LOSS_PROXY", "stress", frequency="quarterly"),
                ProxyInput("X_CRE_STALE_MARKS", "stress", frequency="quarterly"),
                ProxyInput("X_PRIVATE_CREDIT_STALE_MARKS", "stress", frequency="quarterly"),
            ),
        ),
    ),
)


X_REALIZED_PROXY_DEFINITION = StructuralProxyDefinition(
    channel="X_REALIZED",
    label="shadow_forced_realization",
    construction_boundary=(
        "X_REALIZED is forced shadow release and official support usage. It is not "
        "hidden accumulation and must not be interpreted as a leading X_PRE stock proxy."
    ),
    groups=(
        ProxyGroup(
            name="X_OFFICIAL_SUPPORT_USAGE",
            interpretation="Emergency liquidity usage and official support facilities.",
            inputs=(
                ProxyInput("X_OFFICIAL_SUPPORT_USAGE", "stress", frequency="weekly"),
                ProxyInput("X_PRIMARY_CREDIT", "stress", frequency="weekly"),
                ProxyInput("X_DISCOUNT_WINDOW", "stress", frequency="weekly"),
                ProxyInput("X_BTFP", "stress", frequency="weekly"),
                ProxyInput("primary_credit", "stress", frequency="weekly"),
                ProxyInput("discount_window", "stress", frequency="weekly"),
                ProxyInput("btfp", "stress", frequency="weekly"),
            ),
        ),
        ProxyGroup(
            name="X_SUPPORT_SUBSTITUTION",
            interpretation="Realized substitution from private funding paths into official liquidity backstops.",
            inputs=(
                ProxyInput("X_SUPPORT_SUBSTITUTION", "stress", frequency="weekly"),
                ProxyInput("X_FED_LIQUIDITY_FACILITY_USAGE", "stress", frequency="weekly"),
                ProxyInput("X_EMERGENCY_LIQUIDITY_USAGE", "stress", frequency="weekly"),
            ),
        ),
    ),
)


# Backward-compatible alias for imports that still ask for the old symbol. The
# basket map now exposes X_PRE and X_REALIZED separately; DefaultProxyBuilder
# creates legacy X as a compatibility aggregate.
X_PROXY_DEFINITION = X_PRE_PROXY_DEFINITION
