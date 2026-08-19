from __future__ import annotations

from typing import Any

from harvester.providers.base import OfficialProvider, ProviderResult


class ProviderError(RuntimeError):
    """Raised when a provider encounters a non-recoverable error."""


def build_provider(name: str, **kwargs: Any) -> OfficialProvider:
    if name == "fred":
        from harvester.providers.fred import FredProvider

        return FredProvider(**kwargs)
    if name == "treasury":
        from harvester.providers.treasury import TreasuryProvider

        return TreasuryProvider(**kwargs)
    if name == "sec":
        from harvester.providers.sec import SecProvider

        sec_kwargs = {k: v for k, v in kwargs.items() if k in ("data_root", "cache", "user_agent")}
        return SecProvider(**sec_kwargs)
    if name == "h41":
        from harvester.providers.h41 import H41Provider

        return H41Provider(**kwargs)
    if name in {"cboe", "cboe_direct"}:
        from harvester.providers.cboe_direct import CboeDirectProvider

        return CboeDirectProvider(**kwargs)
    if name in {"tiingo", "massive", "etf_provider_chain"}:
        from harvester.providers.etf_market_data import (
            EtfProviderChain,
            MassiveEodProvider,
            TiingoEodProvider,
        )

        if name == "tiingo":
            return TiingoEodProvider(**kwargs)
        if name == "massive":
            return MassiveEodProvider(**kwargs)
        return EtfProviderChain(**kwargs)
    if name.startswith("openbb"):
        from harvester.providers.openbb_provider import OpenBBProvider

        openbb_provider = name.removeprefix("openbb").strip("_-")
        return OpenBBProvider(openbb_provider=openbb_provider, **kwargs)
    raise ProviderError(f"unknown provider: {name}")


__all__ = [
    "OfficialProvider",
    "ProviderError",
    "ProviderResult",
    "build_provider",
]
