from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.data.contracts import StructuralPreset, default_structural_presets


@dataclass(frozen=True)
class EvidenceRequest:
    channel: str
    measurement_block: str | None = None
    evidence_role: str | None = None
    jurisdiction_or_scope: str | None = None
    frequency: str | None = None

    @classmethod
    def from_input(cls, value: Mapping[str, Any]) -> "EvidenceRequest":
        return cls(
            channel=str(value.get("channel", "")).strip().upper(),
            measurement_block=_optional_str(value.get("measurement_block") or value.get("block")),
            evidence_role=_optional_str(value.get("evidence_role") or value.get("role")),
            jurisdiction_or_scope=_optional_str(value.get("jurisdiction_or_scope") or value.get("scope")),
            frequency=_optional_str(value.get("frequency")),
        )


@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    channels: tuple[str, ...]
    evidence_roles: tuple[str, ...]
    measurement_blocks: tuple[str, ...] = ()
    frequencies: tuple[str, ...] = ()
    requires_key: bool = False
    stability: str = "medium"
    priority: int = 50
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def score(self, request: EvidenceRequest) -> int:
        score = self.priority
        if request.channel and request.channel in self.channels:
            score += 30
        if request.evidence_role and request.evidence_role in self.evidence_roles:
            score += 20
        if request.measurement_block and request.measurement_block in self.measurement_blocks:
            score += 20
        if request.frequency and request.frequency in self.frequencies:
            score += 5
        if self.stability == "high":
            score += 10
        if self.requires_key:
            score -= 5
        return score


@dataclass(frozen=True)
class EvidenceRoute:
    request: EvidenceRequest
    presets: tuple[StructuralPreset, ...]
    providers: tuple[str, ...]
    capability_scores: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": {
                "channel": self.request.channel,
                "measurement_block": self.request.measurement_block,
                "evidence_role": self.request.evidence_role,
                "jurisdiction_or_scope": self.request.jurisdiction_or_scope,
                "frequency": self.request.frequency,
            },
            "preset_names": [preset.name for preset in self.presets],
            "providers": list(self.providers),
            "capability_scores": dict(self.capability_scores),
        }


class EvidenceRouter:
    def __init__(
        self,
        presets: Sequence[StructuralPreset] | None = None,
        capabilities: Sequence[ProviderCapability] | None = None,
    ) -> None:
        self.presets = tuple(presets or default_structural_presets())
        self.capabilities = tuple(capabilities or default_provider_capabilities())

    def route(self, request: EvidenceRequest | Mapping[str, Any]) -> EvidenceRoute:
        req = request if isinstance(request, EvidenceRequest) else EvidenceRequest.from_input(request)
        candidates = tuple(preset for preset in self.presets if self._preset_matches(preset, req))
        providers = tuple(dict.fromkeys(request.provider for preset in candidates for request in preset.requests))
        scores = {
            capability.provider: capability.score(req)
            for capability in self.capabilities
            if capability.provider in providers
        }
        ordered_providers = tuple(
            provider for provider, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        )
        if ordered_providers:
            provider_rank = {provider: idx for idx, provider in enumerate(ordered_providers)}
            candidates = tuple(
                sorted(
                    candidates,
                    key=lambda preset: min(provider_rank.get(request.provider, 999) for request in preset.requests),
                )
            )
        return EvidenceRoute(
            request=req,
            presets=candidates,
            providers=ordered_providers or providers,
            capability_scores=scores,
        )

    def route_proxy_series(self, series_ids: Sequence[str]) -> dict[str, EvidenceRoute]:
        output: dict[str, EvidenceRoute] = {}
        for series_id in series_ids:
            matching = tuple(preset for preset in self.presets if preset.output_series_id == series_id)
            if not matching:
                continue
            channel = matching[0].channel
            output[series_id] = self.route({"channel": channel, "evidence_role": "proxy"})
        return output

    def capability_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "provider": item.provider,
                "channels": list(item.channels),
                "evidence_roles": list(item.evidence_roles),
                "measurement_blocks": list(item.measurement_blocks),
                "frequencies": list(item.frequencies),
                "requires_key": item.requires_key,
                "stability": item.stability,
                "priority": item.priority,
                "metadata": dict(item.metadata),
            }
            for item in self.capabilities
        ]

    def _preset_matches(self, preset: StructuralPreset, request: EvidenceRequest) -> bool:
        if request.channel and preset.channel != request.channel:
            return False
        if request.measurement_block and preset.measurement_block != request.measurement_block:
            return False
        if request.evidence_role and preset.evidence_role != request.evidence_role:
            return False
        if request.jurisdiction_or_scope and preset.jurisdiction_or_scope != request.jurisdiction_or_scope:
            return False
        return True


def default_provider_capabilities() -> tuple[ProviderCapability, ...]:
    return (
        ProviderCapability("fred", ("M", "D", "K"), ("proxy", "validation"), ("funding_gap", "depth", "hedge_breadth", "jump_instability"), ("daily", "weekly", "monthly"), stability="high", priority=95),
        ProviderCapability("fed_h41", ("D", "X"), ("proxy", "validation"), ("funding_access", "shadow_funding"), ("weekly",), stability="high", priority=96),
        ProviderCapability("treasury", ("K",), ("proxy", "validation"), ("refinancing_pressure", "liquidation_path_instability"), ("daily", "monthly"), stability="high", priority=94),
        ProviderCapability("sec", ("X",), ("proxy", "validation", "case_replay"), ("verifiability",), ("event", "quarterly"), stability="high", priority=90),
        ProviderCapability("ecb", ("M", "D", "K", "X"), ("proxy", "validation"), frequencies=("daily", "monthly", "quarterly"), stability="high", priority=88),
        ProviderCapability("cftc", ("D", "K"), ("validation", "position"), ("hedge_breadth", "positioning"), ("weekly",), stability="high", priority=86),
        ProviderCapability("ffiec", ("D", "X"), ("validation", "case_replay"), ("funding_access", "verifiability", "shadow_funding"), ("quarterly",), stability="high", priority=89),
        ProviderCapability("stooq", ("K",), ("proxy", "validation"), ("market_price", "jump_instability"), ("daily",), stability="medium", priority=65),
        ProviderCapability("tiingo", ("K",), ("proxy", "validation"), ("market_price",), ("daily",), requires_key=True, stability="medium", priority=62),
        ProviderCapability("alpha_vantage", ("K",), ("proxy", "validation"), ("market_price",), ("daily",), requires_key=True, stability="medium", priority=60),
        ProviderCapability("massive", ("K",), ("proxy", "validation"), ("market_price", "options"), ("daily",), requires_key=True, stability="medium", priority=58),
        ProviderCapability("nasdaq_data_link", ("M", "D", "K", "X"), ("proxy", "validation"), frequencies=("daily", "monthly", "quarterly"), requires_key=True, stability="medium", priority=57),
        ProviderCapability("cboe", ("K",), ("proxy", "validation"), ("volatility_surface", "jump_instability"), ("daily",), stability="high", priority=82),
        ProviderCapability("oecd", ("M", "D"), ("validation",), frequencies=("monthly", "quarterly", "annual"), stability="high", priority=75),
        ProviderCapability("bis", ("D", "X"), ("validation",), ("banking_system", "derivatives"), ("quarterly",), stability="high", priority=78),
        ProviderCapability("imf", ("M", "D", "X"), ("validation",), frequencies=("monthly", "quarterly", "annual"), stability="high", priority=76),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
