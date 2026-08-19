"""Strict public request DTOs for the terminal API.

The public HTTP boundary accepts provider and dataset identifiers only.  Raw
URLs, resource handles, metadata bags, and arbitrary extension fields are
deliberately not part of these models; provider adapters remain the only
owners of endpoint resolution.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
        str_strip_whitespace=True,
    )


_IDENTIFIER = Field(min_length=1, max_length=256)
_OPTIONAL_IDENTIFIER = Field(default=None, min_length=1, max_length=256)

ProviderName = Literal[
    "alpha_vantage",
    "bis",
    "cboe",
    "cftc",
    "ecb",
    "fed",
    "fed_h41",
    "ffiec",
    "fiscaldata",
    "fred",
    "h41",
    "imf",
    "nasdaq_data_link",
    "oecd",
    "massive",
    "sec",
    "stooq",
    "tiingo",
    "treasury",
    "treasury_fiscal",
]


class DateRangeQuery(BaseModel):
    """Bounded, causal date window used by public data routes."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
    )

    start: date = date(2026, 1, 1)
    end: date = date(2026, 4, 20)

    @model_validator(mode="after")
    def validate_window(self) -> "DateRangeQuery":
        if self.end < self.start:
            raise ValueError("end must be on or after start")
        if (self.end - self.start).days > 366:
            raise ValueError("date range cannot exceed 366 days")
        return self


class SnapshotRunRequest(_StrictRequest):
    """Validated request for the terminal snapshot execution route."""

    # Keep the wire representation as an ISO string so strict mode does not
    # silently coerce arbitrary JSON values into a date.
    run_date: str = Field(min_length=10, max_length=10)
    run_type: str = _IDENTIFIER

    @field_validator("run_date")
    @classmethod
    def validate_run_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("run_date must be an ISO date") from exc
        return value


_PRESET_NAME = Annotated[str, Field(min_length=1, max_length=256)]


class StructuralPresetRequest(_StrictRequest):
    """Validated preset-name batch for structural data routes."""

    preset_names: list[_PRESET_NAME] = Field(min_length=1, max_length=64)


class EvidenceRouteRequest(_StrictRequest):
    channel: str = _IDENTIFIER
    measurement_block: str | None = _OPTIONAL_IDENTIFIER
    evidence_role: str | None = _OPTIONAL_IDENTIFIER
    jurisdiction_or_scope: str | None = _OPTIONAL_IDENTIFIER
    frequency: str | None = _OPTIONAL_IDENTIFIER


class SeriesRequest(_StrictRequest):
    provider: ProviderName
    series_id: str | None = _OPTIONAL_IDENTIFIER
    dataset: str | None = _OPTIONAL_IDENTIFIER
    field: str | None = _OPTIONAL_IDENTIFIER
    cik: str | None = _OPTIONAL_IDENTIFIER
    key: str | None = _OPTIONAL_IDENTIFIER
    preset_name: str | None = _OPTIONAL_IDENTIFIER
    channel: str | None = _OPTIONAL_IDENTIFIER
    measurement_block: str | None = _OPTIONAL_IDENTIFIER
    evidence_role: str | None = _OPTIONAL_IDENTIFIER
    jurisdiction_or_scope: str | None = _OPTIONAL_IDENTIFIER


class EventRequest(_StrictRequest):
    provider: ProviderName
    dataset: str | None = _OPTIONAL_IDENTIFIER
    event_type: str | None = _OPTIONAL_IDENTIFIER
    preset_name: str | None = _OPTIONAL_IDENTIFIER
    channel: str | None = _OPTIONAL_IDENTIFIER
    measurement_block: str | None = _OPTIONAL_IDENTIFIER
    evidence_role: str | None = _OPTIONAL_IDENTIFIER
    jurisdiction_or_scope: str | None = _OPTIONAL_IDENTIFIER


class FilingRequest(_StrictRequest):
    provider: ProviderName
    cik: str | None = _OPTIONAL_IDENTIFIER
    form_types: list[str] = Field(default_factory=list, max_length=32)
    include_facts: bool = False
    preset_name: str | None = _OPTIONAL_IDENTIFIER
    channel: str | None = _OPTIONAL_IDENTIFIER
    measurement_block: str | None = _OPTIONAL_IDENTIFIER
    evidence_role: str | None = _OPTIONAL_IDENTIFIER
    jurisdiction_or_scope: str | None = _OPTIONAL_IDENTIFIER


class PositionRequest(_StrictRequest):
    provider: ProviderName
    dataset_id: str | None = _OPTIONAL_IDENTIFIER
    market_name: str | None = _OPTIONAL_IDENTIFIER
    market_code: str | None = _OPTIONAL_IDENTIFIER
    category: str | None = _OPTIONAL_IDENTIFIER
    preset_name: str | None = _OPTIONAL_IDENTIFIER
    channel: str | None = _OPTIONAL_IDENTIFIER
    measurement_block: str | None = _OPTIONAL_IDENTIFIER
    evidence_role: str | None = _OPTIONAL_IDENTIFIER
    jurisdiction_or_scope: str | None = _OPTIONAL_IDENTIFIER


def request_payload(value: _StrictRequest) -> dict[str, object]:
    """Convert a validated DTO into the legacy service's identifier mapping."""
    fields: tuple[str, ...]
    if isinstance(value, EvidenceRouteRequest):
        fields = (
            "channel",
            "measurement_block",
            "evidence_role",
            "jurisdiction_or_scope",
            "frequency",
        )
    elif isinstance(value, SeriesRequest):
        fields = (
            "provider",
            "series_id",
            "dataset",
            "field",
            "cik",
            "key",
            "preset_name",
            "channel",
            "measurement_block",
            "evidence_role",
            "jurisdiction_or_scope",
        )
    elif isinstance(value, EventRequest):
        fields = (
            "provider",
            "dataset",
            "event_type",
            "preset_name",
            "channel",
            "measurement_block",
            "evidence_role",
            "jurisdiction_or_scope",
        )
    elif isinstance(value, FilingRequest):
        fields = (
            "provider",
            "cik",
            "form_types",
            "include_facts",
            "preset_name",
            "channel",
            "measurement_block",
            "evidence_role",
            "jurisdiction_or_scope",
        )
    elif isinstance(value, PositionRequest):
        fields = (
            "provider",
            "dataset_id",
            "market_name",
            "market_code",
            "category",
            "preset_name",
            "channel",
            "measurement_block",
            "evidence_role",
            "jurisdiction_or_scope",
        )
    else:  # pragma: no cover - defensive boundary for future DTOs
        raise TypeError(f"unsupported public request DTO: {type(value).__name__}")
    return {name: getattr(value, name) for name in fields if getattr(value, name) is not None}
