from __future__ import annotations

from dataclasses import dataclass, field as dc_field, replace
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


def _metadata_copy(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _json_value(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        if not np.isfinite(value):
            return None
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def dataframe_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        payload = {"date": idx.strftime("%Y-%m-%d") if isinstance(idx, pd.Timestamp) else str(idx)}
        for column in frame.columns:
            payload[str(column)] = _json_value(row[column])
        rows.append(payload)
    return rows


@dataclass(frozen=True)
class SeriesRequest:
    provider: str
    series_id: str | None = None
    dataset: str | None = None
    field: str | None = None
    cik: str | None = None
    resource: str | None = None
    key: str | None = None
    preset_name: str | None = None
    channel: str | None = None
    measurement_block: str | None = None
    evidence_role: str | None = None
    jurisdiction_or_scope: str | None = None
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    @classmethod
    def from_input(cls, value: SeriesRequest | Mapping[str, Any]) -> SeriesRequest:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("series request must be a mapping or SeriesRequest")
        return cls(
            provider=str(value.get("provider", "")),
            series_id=_optional_str(value.get("series_id") or value.get("id")),
            dataset=_optional_str(value.get("dataset") or value.get("flow_ref")),
            field=_optional_str(value.get("field")),
            cik=_optional_str(value.get("cik")),
            resource=_optional_str(value.get("resource")),
            key=_optional_str(value.get("key")),
            preset_name=_optional_str(value.get("preset_name")),
            channel=_optional_str(value.get("channel")),
            measurement_block=_optional_str(value.get("measurement_block") or value.get("block")),
            evidence_role=_optional_str(value.get("evidence_role") or value.get("role")),
            jurisdiction_or_scope=_optional_str(value.get("jurisdiction_or_scope") or value.get("scope")),
            metadata=_metadata_copy(value.get("metadata")),
        )

    def request_key(self) -> str:
        provider = self.provider.strip().lower().replace("-", "_")
        if provider == "fred" and self.series_id:
            return f"FRED:{self.series_id}"
        if provider in {"fed", "fed_h41", "h41"} and self.field:
            return f"H41:{self.field}"
        if provider in {"treasury", "treasury_fiscal", "fiscaldata"} and self.dataset and self.field:
            return f"TFD:{self.dataset}:{self.field}"
        if provider == "sec" and self.cik:
            return f"SEC:{str(self.cik).zfill(10)}"
        if provider == "ecb":
            if self.series_id:
                return self.series_id
            if self.dataset and self.key:
                return f"{self.dataset}/{self.key}"
        if self.series_id:
            return self.series_id
        if self.key:
            return self.key
        if self.resource:
            return self.resource
        return provider

    def has_structural_semantics(self) -> bool:
        return all(
            [
                self.channel,
                self.measurement_block,
                self.evidence_role,
            ]
        )

    def structural_dict(self) -> dict[str, Any]:
        return {
            "preset_name": self.preset_name,
            "channel": self.channel,
            "measurement_block": self.measurement_block,
            "evidence_role": self.evidence_role,
            "jurisdiction_or_scope": self.jurisdiction_or_scope,
        }


@dataclass(frozen=True)
class EventRequest:
    provider: str
    dataset: str | None = None
    resource: str | None = None
    event_type: str | None = None
    preset_name: str | None = None
    channel: str | None = None
    measurement_block: str | None = None
    evidence_role: str | None = None
    jurisdiction_or_scope: str | None = None
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    @classmethod
    def from_input(cls, value: EventRequest | Mapping[str, Any]) -> EventRequest:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("event request must be a mapping or EventRequest")
        return cls(
            provider=str(value.get("provider", "")),
            dataset=_optional_str(value.get("dataset")),
            resource=_optional_str(value.get("resource")),
            event_type=_optional_str(value.get("event_type") or value.get("kind")),
            preset_name=_optional_str(value.get("preset_name")),
            channel=_optional_str(value.get("channel")),
            measurement_block=_optional_str(value.get("measurement_block") or value.get("block")),
            evidence_role=_optional_str(value.get("evidence_role") or value.get("role")),
            jurisdiction_or_scope=_optional_str(value.get("jurisdiction_or_scope") or value.get("scope")),
            metadata=_metadata_copy(value.get("metadata")),
        )

    def has_structural_semantics(self) -> bool:
        return all([self.channel, self.measurement_block, self.evidence_role])


@dataclass(frozen=True)
class FilingRequest:
    provider: str
    cik: str | None = None
    form_types: tuple[str, ...] = ()
    include_facts: bool = False
    preset_name: str | None = None
    channel: str | None = None
    measurement_block: str | None = None
    evidence_role: str | None = None
    jurisdiction_or_scope: str | None = None
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    @classmethod
    def from_input(cls, value: FilingRequest | Mapping[str, Any]) -> FilingRequest:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("filing request must be a mapping or FilingRequest")
        forms = value.get("forms") or value.get("form_types") or ()
        if isinstance(forms, str):
            forms = (forms,)
        return cls(
            provider=str(value.get("provider", "")),
            cik=_optional_str(value.get("cik")),
            form_types=tuple(str(item) for item in forms if str(item).strip()),
            include_facts=bool(value.get("include_facts", False)),
            preset_name=_optional_str(value.get("preset_name")),
            channel=_optional_str(value.get("channel")),
            measurement_block=_optional_str(value.get("measurement_block") or value.get("block")),
            evidence_role=_optional_str(value.get("evidence_role") or value.get("role")),
            jurisdiction_or_scope=_optional_str(value.get("jurisdiction_or_scope") or value.get("scope")),
            metadata=_metadata_copy(value.get("metadata")),
        )

    def has_structural_semantics(self) -> bool:
        return all([self.channel, self.measurement_block, self.evidence_role])


@dataclass(frozen=True)
class PositionRequest:
    provider: str
    resource: str | None = None
    dataset_id: str | None = None
    market_name: str | None = None
    market_code: str | None = None
    category: str | None = None
    preset_name: str | None = None
    channel: str | None = None
    measurement_block: str | None = None
    evidence_role: str | None = None
    jurisdiction_or_scope: str | None = None
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    @classmethod
    def from_input(cls, value: PositionRequest | Mapping[str, Any]) -> PositionRequest:
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("position request must be a mapping or PositionRequest")
        return cls(
            provider=str(value.get("provider", "")),
            resource=_optional_str(value.get("resource")),
            dataset_id=_optional_str(value.get("dataset_id")),
            market_name=_optional_str(value.get("market_name")),
            market_code=_optional_str(value.get("market_code")),
            category=_optional_str(value.get("category")),
            preset_name=_optional_str(value.get("preset_name")),
            channel=_optional_str(value.get("channel")),
            measurement_block=_optional_str(value.get("measurement_block") or value.get("block")),
            evidence_role=_optional_str(value.get("evidence_role") or value.get("role")),
            jurisdiction_or_scope=_optional_str(value.get("jurisdiction_or_scope") or value.get("scope")),
            metadata=_metadata_copy(value.get("metadata")),
        )

    def has_structural_semantics(self) -> bool:
        return all([self.channel, self.measurement_block, self.evidence_role])


@dataclass
class DataRequestError:
    kind: str
    provider: str
    request: dict[str, Any]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "provider": self.provider,
            "request": dict(self.request),
            "message": self.message,
        }


@dataclass
class SeriesResult:
    provider: str
    request_key: str
    frame: pd.DataFrame
    frequency: str | None = None
    unit: str | None = None
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        frame = self.frame.sort_index()
        return {
            "provider": self.provider,
            "request_key": self.request_key,
            "frequency": self.frequency,
            "unit": self.unit,
            "columns": [str(column) for column in frame.columns],
            "row_count": int(len(frame)),
            "rows": dataframe_rows(frame),
            "metadata": dict(self.metadata),
        }


@dataclass
class EventRecord:
    provider: str
    event_date: str
    event_type: str
    title: str
    summary: str | None = None
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "event_date": self.event_date,
            "event_type": self.event_type,
            "title": self.title,
            "summary": self.summary,
            "metadata": dict(self.metadata),
        }


@dataclass
class FilingRecord:
    provider: str
    cik: str
    filing_date: str
    form: str
    accession_number: str | None = None
    primary_document: str | None = None
    filing_url: str | None = None
    facts_url: str | None = None
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "cik": self.cik,
            "filing_date": self.filing_date,
            "form": self.form,
            "accession_number": self.accession_number,
            "primary_document": self.primary_document,
            "filing_url": self.filing_url,
            "facts_url": self.facts_url,
            "metadata": dict(self.metadata),
        }


@dataclass
class PositionRecord:
    provider: str
    report_date: str
    market_name: str
    market_code: str | None = None
    category: str | None = None
    long: float | None = None
    short: float | None = None
    spreading: float | None = None
    open_interest: float | None = None
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "report_date": self.report_date,
            "market_name": self.market_name,
            "market_code": self.market_code,
            "category": self.category,
            "long": self.long,
            "short": self.short,
            "spreading": self.spreading,
            "open_interest": self.open_interest,
            "metadata": dict(self.metadata),
        }


@dataclass
class FetchResult:
    kind: str
    items: Sequence[Any]
    errors: Sequence[DataRequestError] = ()
    metadata: Mapping[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        serialized_items = [item.to_dict() if hasattr(item, "to_dict") else item for item in self.items]
        return {
            "kind": self.kind,
            "request_count": len(serialized_items) + len(self.errors),
            "items": serialized_items,
            "errors": [err.to_dict() for err in self.errors],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class StructuralPreset:
    name: str
    channel: str
    measurement_block: str
    evidence_role: str
    jurisdiction_or_scope: str
    output_series_id: str
    requests: tuple[SeriesRequest, ...]
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "channel": self.channel,
            "measurement_block": self.measurement_block,
            "evidence_role": self.evidence_role,
            "jurisdiction_or_scope": self.jurisdiction_or_scope,
            "output_series_id": self.output_series_id,
            "description": self.description,
            "request_keys": [request.request_key() for request in self.requests],
        }


@dataclass(frozen=True)
class StructuralFetchPlan:
    requested_series_ids: tuple[str, ...]
    presets: tuple[StructuralPreset, ...]
    unresolved_series_ids: tuple[str, ...] = ()

    @property
    def preset_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.presets)

    @property
    def channels_touched(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.channel for item in self.presets))

    @property
    def blocks_touched(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.measurement_block for item in self.presets))

    @property
    def evidence_roles(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.evidence_role for item in self.presets))

    @property
    def expanded_request_keys(self) -> tuple[str, ...]:
        keys: list[str] = []
        for preset in self.presets:
            for request in preset.requests:
                keys.append(request.request_key())
        return tuple(dict.fromkeys(keys))

    def request_to_presets(self) -> dict[str, tuple[str, ...]]:
        mapping: dict[str, list[str]] = {}
        for preset in self.presets:
            for request in preset.requests:
                mapping.setdefault(request.request_key(), []).append(preset.name)
        return {key: tuple(values) for key, values in mapping.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_series_ids": list(self.requested_series_ids),
            "preset_names": list(self.preset_names),
            "channels_touched": list(self.channels_touched),
            "blocks_touched": list(self.blocks_touched),
            "evidence_roles": list(self.evidence_roles),
            "expanded_request_keys": list(self.expanded_request_keys),
            "unresolved_series_ids": list(self.unresolved_series_ids),
        }


@dataclass
class StructuralPresetResult:
    preset: StructuralPreset
    items: Sequence[SeriesResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset": self.preset.to_dict(),
            "items": [item.to_dict() for item in self.items],
        }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def default_structural_presets() -> tuple[StructuralPreset, ...]:
    presets = (
        _preset(
            name="mismatch_curve_shape_us",
            channel="M",
            measurement_block="funding_gap",
            jurisdiction_or_scope="us_rates",
            output_series_id="M_PROXY",
            description="First-round mismatch proxy for curve-shape stress against anchor funding conditions.",
            requests=(("fred", {"series_id": "T10Y2Y"}),),
        ),
        _preset(
            name="mismatch_policy_funding_gap_us",
            channel="M",
            measurement_block="funding_gap",
            jurisdiction_or_scope="us_policy",
            output_series_id="M_PROXY",
            description="Policy-rate component for anchor mismatch in funding conditions.",
            requests=(("fred", {"series_id": "DFF"}),),
        ),
        _preset(
            name="dof_credit_depth_us",
            channel="D",
            measurement_block="depth",
            jurisdiction_or_scope="us_credit",
            output_series_id="D_PROXY",
            description="Credit-spread proxy for effective market depth and financing room.",
            requests=(("fred", {"series_id": "BAMLH0A0HYM2"}),),
        ),
        _preset(
            name="dof_risk_transfer_breadth_us",
            channel="D",
            measurement_block="hedge_breadth",
            jurisdiction_or_scope="us_cross_asset",
            output_series_id="D_PROXY",
            description="Risk-transfer breadth proxy using volatility stress as a first-round compression signal.",
            requests=(("fred", {"series_id": "VIXCLS"}),),
        ),
        _preset(
            name="dof_funding_access_us",
            channel="D",
            measurement_block="funding_access",
            jurisdiction_or_scope="us_central_bank",
            output_series_id="D_PROXY",
            description="Discount-window dependence as a bounded proxy for shrinking funding freedom.",
            requests=(("fed_h41", {"field": "discount_window"}),),
        ),
        _preset(
            name="curvature_jump_instability_us",
            channel="K",
            measurement_block="jump_instability",
            jurisdiction_or_scope="us_cross_asset",
            output_series_id="K_PROXY",
            description="Volatility-based first-round proxy for transition-map jump instability.",
            requests=(("fred", {"series_id": "VIXCLS"}),),
        ),
        _preset(
            name="curvature_refinancing_pressure_us",
            channel="K",
            measurement_block="refinancing_pressure",
            jurisdiction_or_scope="us_treasury",
            output_series_id="K_PROXY",
            description="Public-debt pressure as a bounded curvature proxy for refinancing stress.",
            requests=(("treasury", {"dataset": "debt_to_penny", "field": "tot_pub_debt_out_amt"}),),
        ),
        _preset(
            name="curvature_treasury_cash_instability_us",
            channel="K",
            measurement_block="liquidation_path_instability",
            jurisdiction_or_scope="us_treasury",
            output_series_id="K_PROXY",
            description="Treasury cash-balance instability as a first-round curvature proxy.",
            requests=(("treasury", {"dataset": "daily_treasury_statement", "field": "open_today_bal"}),),
        ),
        _preset(
            name="shadow_emergency_credit_primary_us",
            channel="X",
            measurement_block="shadow_funding",
            jurisdiction_or_scope="us_central_bank",
            output_series_id="X_PROXY",
            description="Primary-credit usage as a visible trace of shadow funding substitution.",
            requests=(("fed_h41", {"field": "primary_credit"}),),
        ),
        _preset(
            name="shadow_term_funding_substitution_us",
            channel="X",
            measurement_block="shadow_funding",
            jurisdiction_or_scope="us_central_bank",
            output_series_id="X_PROXY",
            description="BTFP usage as a bounded proxy for shadow funding substitution pressure.",
            requests=(("fed_h41", {"field": "btfp"}),),
        ),
        _preset(
            name="shadow_verifiability_issuer_core",
            channel="X",
            measurement_block="verifiability",
            jurisdiction_or_scope="issuer_core",
            output_series_id="X_PROXY",
            description="Issuer filing pulse as a coarse trace of verifiability stress in hidden load.",
            requests=(("sec", {"cik": "0000072971"}),),
        ),
    )
    return presets


def build_structural_fetch_plan(
    series_ids: Sequence[str],
    presets: Sequence[StructuralPreset] | None = None,
) -> StructuralFetchPlan:
    catalog = tuple(presets or default_structural_presets())
    matched: list[StructuralPreset] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    request_index: dict[str, list[StructuralPreset]] = {}
    output_index: dict[str, list[StructuralPreset]] = {}
    for preset in catalog:
        output_index.setdefault(preset.output_series_id, []).append(preset)
        for request in preset.requests:
            request_index.setdefault(request.request_key(), []).append(preset)

    for series_id in series_ids:
        candidates = output_index.get(series_id, [])
        if not candidates:
            candidates = request_index.get(series_id, [])
        if not candidates:
            unresolved.append(str(series_id))
            continue
        for preset in candidates:
            if preset.name in seen:
                continue
            seen.add(preset.name)
            matched.append(preset)
    return StructuralFetchPlan(
        requested_series_ids=tuple(str(item) for item in series_ids),
        presets=tuple(matched),
        unresolved_series_ids=tuple(unresolved),
    )


def _preset(
    name: str,
    channel: str,
    measurement_block: str,
    jurisdiction_or_scope: str,
    output_series_id: str,
    description: str,
    requests: Sequence[tuple[str, dict[str, Any]]],
    evidence_role: str = "proxy",
) -> StructuralPreset:
    series_requests = tuple(
        SeriesRequest(
            provider=provider,
            preset_name=name,
            channel=channel,
            measurement_block=measurement_block,
            evidence_role=evidence_role,
            jurisdiction_or_scope=jurisdiction_or_scope,
            **payload,
        )
        for provider, payload in requests
    )
    return StructuralPreset(
        name=name,
        channel=channel,
        measurement_block=measurement_block,
        evidence_role=evidence_role,
        jurisdiction_or_scope=jurisdiction_or_scope,
        output_series_id=output_series_id,
        requests=series_requests,
        description=description,
    )


def enrich_series_request_from_preset(request: SeriesRequest, preset: StructuralPreset) -> SeriesRequest:
    structural: dict[str, Any] = {
        "preset_name": request.preset_name or preset.name,
        "channel": request.channel or preset.channel,
        "measurement_block": request.measurement_block or preset.measurement_block,
        "evidence_role": request.evidence_role or preset.evidence_role,
        "jurisdiction_or_scope": request.jurisdiction_or_scope or preset.jurisdiction_or_scope,
    }
    return replace(request, **structural)
