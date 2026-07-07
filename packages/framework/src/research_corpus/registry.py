from __future__ import annotations

from src.research_corpus.taxonomy import ProviderGroup


PROVIDER_GROUPS: dict[ProviderGroup, tuple[str, ...]] = {
    ProviderGroup.MACRO_FUNDS: (
        "Bridgewater",
        "Brevan Howard",
        "PIMCO",
        "BlackRock",
    ),
    ProviderGroup.QUANT_SYSTEMATIC: (
        "AQR",
        "Man AHL",
        "Two Sigma",
        "Research Affiliates",
    ),
    ProviderGroup.MULTI_STRATEGY_CREDIT: (
        "D. E. Shaw",
        "Citadel",
        "Elliott",
    ),
    ProviderGroup.PUBLIC_INSTITUTIONS: (
        "BIS",
        "OFR",
        "Fed",
        "IMF",
        "Treasury",
    ),
}


def provider_group_for(provider: str) -> ProviderGroup | None:
    normalized = _normalize(provider)
    for group, providers in PROVIDER_GROUPS.items():
        if normalized in {_normalize(item) for item in providers}:
            return group
    return None


def provider_slug(provider: str) -> str:
    return (
        provider.lower()
        .replace("&", "and")
        .replace(".", "")
        .replace(" ", "_")
        .replace("/", "_")
    )


def _normalize(value: str) -> str:
    return value.casefold().replace(".", "").replace(" ", "")


__all__ = ["PROVIDER_GROUPS", "provider_group_for", "provider_slug"]
