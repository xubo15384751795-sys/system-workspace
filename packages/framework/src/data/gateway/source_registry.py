from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def normalize_provider_name(name: str) -> str:
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


@dataclass
class SourceRegistry:
    series_adapters: dict[str, Any] = field(default_factory=dict)
    event_adapters: dict[str, Any] = field(default_factory=dict)
    filing_adapters: dict[str, Any] = field(default_factory=dict)
    position_adapters: dict[str, Any] = field(default_factory=dict)
    market_structure_adapters: dict[str, Any] = field(default_factory=dict)

    def register_series(self, provider: str, adapter: Any, aliases: tuple[str, ...] = ()) -> None:
        self._register(self.series_adapters, provider, adapter, aliases)

    def register_events(self, provider: str, adapter: Any, aliases: tuple[str, ...] = ()) -> None:
        self._register(self.event_adapters, provider, adapter, aliases)

    def register_filings(self, provider: str, adapter: Any, aliases: tuple[str, ...] = ()) -> None:
        self._register(self.filing_adapters, provider, adapter, aliases)

    def register_positions(self, provider: str, adapter: Any, aliases: tuple[str, ...] = ()) -> None:
        self._register(self.position_adapters, provider, adapter, aliases)

    def register_market_structure(self, provider: str, adapter: Any, aliases: tuple[str, ...] = ()) -> None:
        self._register(self.market_structure_adapters, provider, adapter, aliases)

    def resolve_series(self, provider: str) -> Any | None:
        return self.series_adapters.get(normalize_provider_name(provider))

    def resolve_events(self, provider: str) -> Any | None:
        return self.event_adapters.get(normalize_provider_name(provider))

    def resolve_filings(self, provider: str) -> Any | None:
        return self.filing_adapters.get(normalize_provider_name(provider))

    def resolve_positions(self, provider: str) -> Any | None:
        return self.position_adapters.get(normalize_provider_name(provider))

    def resolve_market_structure(self, provider: str) -> Any | None:
        return self.market_structure_adapters.get(normalize_provider_name(provider))

    def available(self) -> dict[str, list[str]]:
        return {
            "series": sorted(self.series_adapters),
            "events": sorted(self.event_adapters),
            "filings": sorted(self.filing_adapters),
            "positions": sorted(self.position_adapters),
            "market_structure": sorted(self.market_structure_adapters),
        }

    def _register(self, target: dict[str, Any], provider: str, adapter: Any, aliases: tuple[str, ...]) -> None:
        names = (provider, *aliases)
        for item in names:
            target[normalize_provider_name(item)] = adapter
