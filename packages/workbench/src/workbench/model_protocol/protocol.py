"""Generic measurement-model protocol and the first capability ports.

The public result deliberately has no model-specific fields.  A model may
keep its complete private payload behind ``model_payload``; consumers must
use ``DecisionEvidence`` instead of reaching through that payload.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

import pandas as pd

PROTOCOL_VERSION = "measurement.model.v1"


class ModelProtocolError(ValueError):
    """Raised when a model or host violates the protocol contract."""


@runtime_checkable
class DataAccess(Protocol):
    """Read an already-authorized model input.

    Path/workspace resolution belongs to the application boundary.  A model
    receives an opaque input reference and can only use this supplied port.
    """

    def read_table(self, input_ref: str) -> Any:
        """Return the data object addressed by ``input_ref``."""


@dataclass(frozen=True)
class FileDataAccess:
    """Minimal host implementation for parquet model inputs."""

    def read_table(self, input_ref: str) -> pd.DataFrame:
        path = Path(input_ref).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"model input does not exist: {path}")
        if path.suffix.lower() != ".parquet":
            raise ModelProtocolError(f"unsupported model input format: {path.suffix}")
        return pd.read_parquet(path)


@dataclass(frozen=True)
class ModelManifest:
    """Authoring metadata for one measurement model."""

    model_id: str
    model_version: str
    protocol_version: str
    input_contract: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    required_data: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    failure_semantics: str
    determinism_policy: str
    reference: str
    implementation_digest: str
    fixture_version: str

    def validate(self) -> None:
        required_text = {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "protocol_version": self.protocol_version,
            "failure_semantics": self.failure_semantics,
            "determinism_policy": self.determinism_policy,
            "reference": self.reference,
            "implementation_digest": self.implementation_digest,
            "fixture_version": self.fixture_version,
        }
        missing = [name for name, value in required_text.items() if not str(value).strip()]
        if missing:
            raise ModelProtocolError(f"manifest missing required fields: {missing}")
        if self.protocol_version != PROTOCOL_VERSION:
            raise ModelProtocolError(
                f"unsupported model protocol {self.protocol_version!r}; "
                f"expected {PROTOCOL_VERSION!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "protocol_version": self.protocol_version,
            "input_contract": dict(self.input_contract),
            "output_contract": dict(self.output_contract),
            "required_data": list(self.required_data),
            "required_capabilities": list(self.required_capabilities),
            "failure_semantics": self.failure_semantics,
            "determinism_policy": self.determinism_policy,
            "reference": self.reference,
            "implementation_digest": self.implementation_digest,
            "fixture_version": self.fixture_version,
        }


@dataclass(frozen=True)
class MeasurementRequest:
    """A single bounded evaluation request."""

    request_id: str
    input_ref: str
    as_of: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.request_id.strip():
            raise ModelProtocolError("measurement request requires request_id")
        if not self.input_ref.strip():
            raise ModelProtocolError("measurement request requires input_ref")


@dataclass(frozen=True)
class ModelContext:
    """Explicit capability context supplied by the model host."""

    data_access: DataAccess
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class MeasurementModel(Protocol):
    manifest: ModelManifest

    def evaluate(self, request: MeasurementRequest, context: ModelContext) -> "ModelResult":
        """Evaluate one request without owning orchestration or publication."""


@dataclass(frozen=True)
class ModelResult:
    """Generic result envelope shared by every measurement model."""

    protocol_version: str
    model_id: str
    model_version: str
    as_of: str | None
    available_at: str | None
    status: str
    confidence: float | None
    state: str | None
    scores: Mapping[str, float | None]
    diagnostics: Mapping[str, Any]
    model_payload: Mapping[str, Any]
    provenance: Mapping[str, Any]
    input_digest: str
    implementation_digest: str
    authority: str
    claim_ceiling: str
    diagnostic_only: bool
    runtime_artifacts: Mapping[str, Any] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def validate(self) -> None:
        required_text = {
            "protocol_version": self.protocol_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "status": self.status,
            "authority": self.authority,
            "claim_ceiling": self.claim_ceiling,
            "input_digest": self.input_digest,
            "implementation_digest": self.implementation_digest,
        }
        missing = [name for name, value in required_text.items() if not str(value).strip()]
        if missing:
            raise ModelProtocolError(f"model result missing required fields: {missing}")
        if self.protocol_version != PROTOCOL_VERSION:
            raise ModelProtocolError(
                f"result protocol {self.protocol_version!r} does not match "
                f"{PROTOCOL_VERSION!r}"
            )
        if not isinstance(self.scores, Mapping):
            raise ModelProtocolError("model result scores must be a mapping")
        if not isinstance(self.model_payload, Mapping):
            raise ModelProtocolError("model result model_payload must be a mapping")
        if not self.diagnostic_only:
            raise ModelProtocolError(
                "model results cannot grant production authority; "
                "an explicit promotion boundary is required"
            )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "protocol_version": self.protocol_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "as_of": self.as_of,
            "available_at": self.available_at,
            "status": self.status,
            "confidence": self.confidence,
            "state": self.state,
            "scores": dict(self.scores),
            "diagnostics": dict(self.diagnostics),
            "model_payload": dict(self.model_payload),
            "provenance": dict(self.provenance),
            "input_digest": self.input_digest,
            "implementation_digest": self.implementation_digest,
            "authority": self.authority,
            "claim_ceiling": self.claim_ceiling,
            "diagnostic_only": self.diagnostic_only,
        }


@dataclass(frozen=True)
class DecisionEvidence:
    """Generic state adapter output consumed by judgment."""

    protocol_version: str
    model_id: str
    model_version: str
    state: str | None
    scores: Mapping[str, float | None]
    confidence: float | None
    diagnostics: Mapping[str, Any]
    provenance: Mapping[str, Any]
    authority: str
    claim_ceiling: str
    research_only: bool
    diagnostic_only: bool
    adapter_id: str
    adapter_version: str

    def validate(self) -> None:
        if self.protocol_version != PROTOCOL_VERSION:
            raise ModelProtocolError("decision evidence uses an unsupported protocol")
        if not self.model_id or not self.adapter_id:
            raise ModelProtocolError("decision evidence requires model and adapter ids")
        if not self.diagnostic_only:
            raise ModelProtocolError("decision evidence cannot grant production authority")
        if not isinstance(self.scores, Mapping):
            raise ModelProtocolError("decision evidence scores must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "protocol_version": self.protocol_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "state": self.state,
            "scores": dict(self.scores),
            "confidence": self.confidence,
            "diagnostics": dict(self.diagnostics),
            "provenance": dict(self.provenance),
            "authority": self.authority,
            "claim_ceiling": self.claim_ceiling,
            "research_only": self.research_only,
            "diagnostic_only": self.diagnostic_only,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
        }


@runtime_checkable
class StateAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    approved: bool

    def adapt(self, result: ModelResult) -> DecisionEvidence:
        """Map a model result to generic decision evidence."""


@dataclass(frozen=True)
class ModelEvaluation:
    """Host output; runtime artifacts stay in-memory until the host writes them."""

    result: ModelResult
    evidence: DecisionEvidence


class ModelHost:
    """Resolve capabilities, validate one model call, and bound authority."""

    def evaluate(
        self,
        model: MeasurementModel,
        request: MeasurementRequest,
        context: ModelContext,
        *,
        adapter: StateAdapter | None = None,
    ) -> ModelEvaluation:
        manifest = model.manifest
        manifest.validate()
        request.validate()
        for capability in manifest.required_capabilities:
            if capability == "data_access" and not isinstance(context.data_access, DataAccess):
                raise ModelProtocolError("required capability data_access is unavailable")
            if capability != "data_access":
                raise ModelProtocolError(f"unresolved model capability: {capability}")

        result = model.evaluate(request, context)
        result.validate()
        # Authority is host policy, never a model decision.  Keep the model's
        # diagnostic ceiling but force the public authority to the safe value.
        bounded = replace(
            result,
            authority="DIAGNOSTIC_ONLY",
            diagnostic_only=True,
        )
        bounded.validate()

        if adapter is None:
            evidence = DecisionEvidence(
                protocol_version=PROTOCOL_VERSION,
                model_id=bounded.model_id,
                model_version=bounded.model_version,
                state=bounded.state,
                scores=dict(bounded.scores),
                confidence=bounded.confidence,
                diagnostics={"adapter": "none", "model_status": bounded.status},
                provenance=dict(bounded.provenance),
                authority="DIAGNOSTIC_ONLY",
                claim_ceiling="research_only",
                research_only=True,
                diagnostic_only=True,
                adapter_id="none",
                adapter_version="0",
            )
        else:
            evidence = adapter.adapt(bounded)
            evidence.validate()
            if not adapter.approved:
                evidence = replace(evidence, research_only=True, diagnostic_only=True)
        return ModelEvaluation(result=bounded, evidence=evidence)


def digest_mapping(value: Mapping[str, Any]) -> str:
    """Stable digest helper for small request/provenance metadata mappings."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "PROTOCOL_VERSION",
    "DataAccess",
    "DecisionEvidence",
    "FileDataAccess",
    "MeasurementModel",
    "MeasurementRequest",
    "ModelContext",
    "ModelEvaluation",
    "ModelHost",
    "ModelManifest",
    "ModelProtocolError",
    "ModelResult",
    "StateAdapter",
    "digest_mapping",
    "utc_now",
]
