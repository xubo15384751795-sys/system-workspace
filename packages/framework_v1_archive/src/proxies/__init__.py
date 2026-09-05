from __future__ import annotations

from src.proxies.d_path_feasibility import D_PROXY_DEFINITION
from src.proxies.k_transition_deformation import K_PROXY_DEFINITION
from src.proxies.m_anchor_mismatch import M_PROXY_DEFINITION
from src.proxies.x_shadow_accumulation import (
    X_PRE_PROXY_DEFINITION,
    X_PROXY_DEFINITION,
    X_REALIZED_PROXY_DEFINITION,
)


STRUCTURAL_PROXY_DEFINITIONS = (
    M_PROXY_DEFINITION,
    D_PROXY_DEFINITION,
    K_PROXY_DEFINITION,
    X_PRE_PROXY_DEFINITION,
    X_REALIZED_PROXY_DEFINITION,
)


def structural_basket_map() -> dict[str, dict[str, list[dict[str, object]]]]:
    return {definition.channel: definition.to_basket_map() for definition in STRUCTURAL_PROXY_DEFINITIONS}


__all__ = [
    "D_PROXY_DEFINITION",
    "K_PROXY_DEFINITION",
    "M_PROXY_DEFINITION",
    "STRUCTURAL_PROXY_DEFINITIONS",
    "X_PRE_PROXY_DEFINITION",
    "X_PROXY_DEFINITION",
    "X_REALIZED_PROXY_DEFINITION",
    "structural_basket_map",
]
