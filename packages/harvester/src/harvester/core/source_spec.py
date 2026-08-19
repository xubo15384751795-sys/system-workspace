"""Typed SourceSpec/SourceRoute contract for measurement routing.

The existing series registry answers *which* provider adapter to call. This
contract answers whether a route is semantically equivalent, merely a
transport fallback, or diagnostic-only. It is additive and does not rewrite
already staged release bytes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_VERSION = "system.source_registry.v1"
_FALLBACK_KINDS = frozenset(
    {"primary", "equivalent_source", "transport_fallback", "proxy_evidence", "cache_reuse"}
)


class SourceRegistryValidationError(ValueError):
    """Raised when source identity or route semantics are ambiguous."""


@dataclass(frozen=True)
class SourceRoute:
    route_id: str
    source_id: str
    tier: int
    transport: str
    fallback_kind: str
    claim_ceiling: str
    diagnostic_only: bool
    requires_parity_certification: bool = False
    notes: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceRoute":
        return cls(
            route_id=str(value["route_id"]),
            source_id=str(value["source_id"]),
            tier=int(value["tier"]),
            transport=str(value["transport"]),
            fallback_kind=str(value["fallback_kind"]),
            claim_ceiling=str(value["claim_ceiling"]),
            diagnostic_only=bool(value["diagnostic_only"]),
            requires_parity_certification=bool(value.get("requires_parity_certification", False)),
            notes=str(value.get("notes", "")),
        )


@dataclass(frozen=True)
class SourceSpec:
    series_id: str
    dataset_id: str
    semantic_equivalence_group: str
    frequency: str
    adjustment_policy: str
    primary_key: tuple[str, ...]
    routes: tuple[SourceRoute, ...]
    required_for_decision: bool = False

    @property
    def authoritative_routes(self) -> tuple[SourceRoute, ...]:
        return tuple(route for route in self.routes if not route.diagnostic_only)

    @property
    def diagnostic_routes(self) -> tuple[SourceRoute, ...]:
        return tuple(route for route in self.routes if route.diagnostic_only)

    def route_for(self, source_id: str) -> SourceRoute | None:
        normalized = str(source_id).strip().lower()
        return next(
            (route for route in self.routes if route.source_id.lower() == normalized),
            None,
        )

    @classmethod
    def from_mapping(cls, series_id: str, value: Mapping[str, Any]) -> "SourceSpec":
        return cls(
            series_id=str(series_id),
            dataset_id=str(value["dataset_id"]),
            semantic_equivalence_group=str(value["semantic_equivalence_group"]),
            frequency=str(value["frequency"]),
            adjustment_policy=str(value["adjustment_policy"]),
            primary_key=tuple(str(item) for item in value["primary_key"]),
            routes=tuple(SourceRoute.from_mapping(route) for route in value["routes"]),
            required_for_decision=bool(value.get("required_for_decision", False)),
        )


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    authority_id: str
    authority_class: str
    official_url: str
    notes: str = ""

    @classmethod
    def from_mapping(cls, source_id: str, value: Mapping[str, Any]) -> "SourceDefinition":
        return cls(
            source_id=str(source_id),
            authority_id=str(value["authority_id"]),
            authority_class=str(value["authority_class"]),
            official_url=str(value["official_url"]),
            notes=str(value.get("notes", "")),
        )


@dataclass(frozen=True)
class SourceRegistry:
    schema_version: str
    sources: dict[str, SourceDefinition]
    series: dict[str, SourceSpec]

    def source(self, source_id: str) -> SourceDefinition | None:
        return self.sources.get(str(source_id).strip().lower())

    def get(self, series_id: str) -> SourceSpec | None:
        return self.series.get(str(series_id))

    def route(self, series_id: str, source_id: str) -> SourceRoute | None:
        spec = self.get(series_id)
        return spec.route_for(source_id) if spec else None

    def authority_id(self, source_id: str) -> str | None:
        source = self.source(source_id)
        return source.authority_id if source else None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def registry_path() -> Path:
    return repo_root() / "configs" / "source_registry.yaml"


def schema_path() -> Path:
    return repo_root() / "protocols" / "source_registry.schema.json"


def _validate_schema(payload: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(schema_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceRegistryValidationError(
            f"source registry schema unavailable: {schema_path()}"
        ) from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(dict(payload)),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise SourceRegistryValidationError(f"source registry failed schema validation: {detail}")


def validate_source_registry(payload: Mapping[str, Any]) -> None:
    """Validate schema plus semantic route invariants."""
    _validate_schema(payload)
    sources = payload["sources"]
    series = payload["series"]
    source_ids = {str(source_id).lower() for source_id in sources}
    for source_id, value in sources.items():
        if str(source_id).lower() != str(value["authority_id"]).lower():
            raise SourceRegistryValidationError(
                f"source {source_id!r} must have matching authority_id, "
                f"got {value['authority_id']!r}"
            )
    seen_routes: set[str] = set()
    for series_id, value in series.items():
        routes = value["routes"]
        tiers: list[int] = []
        authoritative = 0
        for route in routes:
            route_id = str(route["route_id"])
            if route_id in seen_routes:
                raise SourceRegistryValidationError(f"duplicate route_id: {route_id}")
            seen_routes.add(route_id)
            source_id = str(route["source_id"]).lower()
            if source_id not in source_ids:
                raise SourceRegistryValidationError(
                    f"{series_id}: route {route_id} references unknown source {source_id}"
                )
            fallback_kind = str(route["fallback_kind"])
            if fallback_kind not in _FALLBACK_KINDS:
                raise SourceRegistryValidationError(
                    f"{series_id}: unsupported fallback_kind {fallback_kind!r}"
                )
            tiers.append(int(route["tier"]))
            authoritative += int(not bool(route["diagnostic_only"]))
        if tiers != sorted(tiers) or len(set(tiers)) != len(tiers):
            raise SourceRegistryValidationError(
                f"{series_id}: route tiers must be unique and ascending"
            )
        if bool(value.get("required_for_decision")) and authoritative == 0:
            raise SourceRegistryValidationError(
                f"{series_id}: decision series needs an authoritative route"
            )


def load_source_registry(path: Path | str | None = None) -> SourceRegistry:
    target = Path(path) if path is not None else registry_path()
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SourceRegistryValidationError(f"source registry cannot be read: {target}") from exc
    if not isinstance(payload, Mapping):
        raise SourceRegistryValidationError("source registry must be a mapping")
    validate_source_registry(payload)
    return SourceRegistry(
        schema_version=str(payload["schema_version"]),
        sources={
            str(key).lower(): SourceDefinition.from_mapping(str(key).lower(), value)
            for key, value in payload["sources"].items()
        },
        series={
            str(key): SourceSpec.from_mapping(str(key), value)
            for key, value in payload["series"].items()
        },
    )


__all__ = [
    "SCHEMA_VERSION",
    "SourceDefinition",
    "SourceRegistry",
    "SourceRegistryValidationError",
    "SourceRoute",
    "SourceSpec",
    "load_source_registry",
    "registry_path",
    "schema_path",
    "validate_source_registry",
]
