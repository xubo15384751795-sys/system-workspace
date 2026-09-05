from __future__ import annotations

from src.proxies.proxy_base import ProxyGroup, ProxyInput, StructuralProxyDefinition


K_PROXY_DEFINITION = StructuralProxyDefinition(
    channel="K",
    label="transition_deformation",
    construction_boundary=(
        "K is transition-geometry deformation, not VIX. Volatility, jump, and tail "
        "benchmarks are controls used to test whether K collapses into generic stress."
    ),
    groups=(
        ProxyGroup(
            name="K_IV_SURFACE_DEFORMATION",
            interpretation="Skew, smile curvature, term-structure twist, and VRP instability.",
            inputs=(
                ProxyInput("K_IV_SURFACE_DEFORMATION", "stress"),
                ProxyInput("K_IV_DISTORTION", "stress"),
                ProxyInput("K_SKEW_SLOPE", "stress"),
                ProxyInput("K_SMILE_CURVATURE", "stress"),
                ProxyInput("K_TERM_STRUCTURE_TWIST", "stress"),
                ProxyInput("K_VARIANCE_RISK_PREMIUM_INSTABILITY", "stress"),
            ),
        ),
        ProxyGroup(
            name="K_JUMP_DISCONTINUITY",
            interpretation="Discontinuous realized paths and overnight gap pressure.",
            inputs=(
                ProxyInput("K_JUMP_DISCONTINUITY", "stress"),
                ProxyInput("K_REALIZED_JUMP", "stress"),
                ProxyInput("K_BIPOWER_GAP", "stress"),
                ProxyInput("K_OVERNIGHT_GAP_FREQUENCY", "stress"),
            ),
        ),
        ProxyGroup(
            name="K_TAIL_CONVEXITY",
            interpretation="Crash convexity, OTM put richness, and gamma stress.",
            inputs=(
                ProxyInput("K_TAIL_CONVEXITY", "stress"),
                ProxyInput("K_OTM_PUT_RICHNESS", "stress"),
                ProxyInput("K_CRASH_SKEW", "stress"),
                ProxyInput("K_VVIX", "stress"),
                ProxyInput("K_GAMMA_STRESS", "stress"),
            ),
        ),
        ProxyGroup(
            name="K_TRANSITION_INSTABILITY",
            interpretation="Rolling beta instability, covariance rotation, network rewiring, regime residuals.",
            inputs=(
                ProxyInput("K_TRANSITION_INSTABILITY", "stress"),
                ProxyInput("K_ROLLING_BETA_INSTABILITY", "stress"),
                ProxyInput("K_COVARIANCE_EIGENVECTOR_ROTATION", "stress"),
                ProxyInput("K_CORRELATION_NETWORK_REWIRING", "stress"),
                ProxyInput("K_REGIME_SWITCHING_RESIDUAL", "stress"),
            ),
        ),
    ),
)
