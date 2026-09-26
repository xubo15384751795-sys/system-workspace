"""Series registry loader.

Reads the canonical series_registry.yaml and provides typed access to
series definitions, provider routing, and release requirements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from system_runtime.context import RuntimeContext


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegistrySeries:
    canonical_id: str
    provider_priority: tuple[str, ...]
    measurement_block: str
    structural_role: str
    frequency: str
    unit: str = ""
    required_for_release: bool = False
    required_for_model_input: bool = False
    status: str = "active"  # active, retired_reference, experimental
    retired_date: str | None = None
    allowed_use: tuple[str, ...] = ()
    forbidden_use: tuple[str, ...] = ()
    replacements: dict[str, str] = field(default_factory=dict)
    derived: bool = False
    synthetic_proxy: bool = False
    formula: str = ""
    inputs: tuple[str, ...] = ()
    allow_synthetic_proxy: bool = False
    synthetic_proxy_id: str = ""
    quality_expectation: str = "observed"
    description: str = ""
    source_series_id: str = ""  # provider-native series id (defaults to canonical_id)

    @property
    def is_retired(self) -> bool:
        return self.status == "retired_reference"

    @property
    def is_derived(self) -> bool:
        return self.derived

    @property
    def is_synthetic(self) -> bool:
        return self.synthetic_proxy

    @property
    def is_required(self) -> bool:
        return self.required_for_release

    @property
    def is_model_input(self) -> bool:
        return self.required_for_model_input

    @classmethod
    def from_dict(cls, canonical_id: str, data: dict[str, Any]) -> RegistrySeries:
        return cls(
            canonical_id=canonical_id,
            provider_priority=tuple(data.get("provider_priority", [])),
            measurement_block=data.get("measurement_block", ""),
            structural_role=data.get("structural_role", ""),
            frequency=data.get("frequency", ""),
            unit=data.get("unit", ""),
            required_for_release=bool(data.get("required_for_release", False)),
            required_for_model_input=bool(data.get("required_for_model_input", False)),
            status=data.get("status", "active"),
            retired_date=data.get("retired_date"),
            allowed_use=tuple(data.get("allowed_use", ())),
            forbidden_use=tuple(data.get("forbidden_use", ())),
            replacements=data.get("replacements", {}),
            derived=bool(data.get("derived", False)),
            synthetic_proxy=bool(data.get("synthetic_proxy", False)),
            formula=data.get("formula", ""),
            inputs=tuple(data.get("inputs", ())),
            allow_synthetic_proxy=bool(data.get("allow_synthetic_proxy", False)),
            synthetic_proxy_id=data.get("synthetic_proxy_id", ""),
            quality_expectation=data.get("quality_expectation", "observed"),
            description=data.get("description", ""),
            source_series_id=data.get("source_series_id", canonical_id),
        )


@dataclass(frozen=True)
class ProviderDef:
    source_id: str
    kind: str  # public_api, public_file, computed
    url: str = ""
    rate_limit_seconds: float = 0.0
    note: str = ""

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> ProviderDef:
        return cls(
            source_id=data.get("source_id", name),
            kind=data.get("kind", ""),
            url=data.get("url", ""),
            rate_limit_seconds=float(data.get("rate_limit_seconds", 0)),
            note=data.get("note", ""),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeriesRegistry:
    schema_version: str
    series: dict[str, RegistrySeries]
    providers: dict[str, ProviderDef]

    def get(self, canonical_id: str) -> RegistrySeries | None:
        return self.series.get(canonical_id)

    def required_series(self) -> list[RegistrySeries]:
        return [s for s in self.series.values() if s.required_for_release]

    def model_input_series(self) -> list[RegistrySeries]:
        return [s for s in self.series.values() if s.required_for_model_input]

    def retired_series(self) -> list[RegistrySeries]:
        return [s for s in self.series.values() if s.is_retired]

    def derived_series(self) -> list[RegistrySeries]:
        return [s for s in self.series.values() if s.is_derived]

    def active_series(self) -> list[RegistrySeries]:
        return [s for s in self.series.values() if not s.is_retired]

    def series_ids(self) -> list[str]:
        return sorted(self.series.keys())

    def series_by_provider(self, provider_name: str) -> list[RegistrySeries]:
        return [
            s for s in self.series.values()
            if provider_name in s.provider_priority
        ]

    def allowed_for_current_diagnostics(self, canonical_id: str) -> bool:
        series = self.get(canonical_id)
        if series is None:
            return False
        if series.is_retired:
            return "current_model_input" not in series.forbidden_use
        return True

    def allowed_for_historical_replay(self, canonical_id: str) -> bool:
        series = self.get(canonical_id)
        if series is None:
            return False
        if series.is_retired:
            return "historical_replay" in series.allowed_use
        return True


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def registry_path() -> Path:
    return RuntimeContext.current_context().workspace / "packages" / "harvester" / "configs" / "series_registry.yaml"


def load_registry(path: str | Path | None = None) -> SeriesRegistry:
    if path is None:
        path = registry_path()
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"series registry not found: {source}")

    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("series registry must be a YAML mapping")

    providers: dict[str, ProviderDef] = {}
    for name, data in raw.get("providers", {}).items():
        providers[name] = ProviderDef.from_dict(name, data)

    series: dict[str, RegistrySeries] = {}
    for canonical_id, data in raw.get("series", {}).items():
        series[canonical_id] = RegistrySeries.from_dict(canonical_id, data)

    return SeriesRegistry(
        schema_version=str(raw.get("schema_version", "1.0")),
        series=series,
        providers=providers,
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_RELEASE_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")
_ACCESS_PROTOCOL_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-r\d+$")


def is_valid_release_id(release_id: str) -> bool:
    return bool(_RELEASE_ID_PATTERN.match(release_id) or _ACCESS_PROTOCOL_PATTERN.match(release_id))


def validate_retired_policy(series: RegistrySeries) -> list[str]:
    """Validate that a retired series has its retirement policy correctly specified."""
    issues: list[str] = []
    if series.is_retired:
        if not series.retired_date:
            issues.append(f"{series.canonical_id}: retired but no retired_date")
        if not series.allowed_use:
            issues.append(f"{series.canonical_id}: retired but no allowed_use specified")
        if "current_model_input" not in series.forbidden_use:
            issues.append(f"{series.canonical_id}: retired but current_model_input not forbidden")
        if not series.replacements:
            issues.append(f"{series.canonical_id}: retired but no replacements defined")
    return issues


__all__ = [
    "ProviderDef",
    "RegistrySeries",
    "SeriesRegistry",
    "load_registry",
    "registry_path",
    "validate_retired_policy",
    "is_valid_release_id",
]
