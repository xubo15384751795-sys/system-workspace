from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from nlp.rule_fingerprint import (
    CONFIDENCE_RULES_VERSION,
    ENTITY_EXTRACTOR_VERSION,
    EXTRACTOR_VERSION,
    SCHEMA_VALIDATOR_VERSION,
    VARIABLE_MAPPER_VERSION,
    mapping_rules_hash,
)

STRUCTURAL_VARIABLES = ("S", "A", "L", "V", "P", "tau")


class ExtractedEntity(BaseModel):
    chunk_id: str
    text: str
    type: str
    variable_hint: list[str] = Field(default_factory=list)
    evidence_quote: str = ""

    @field_validator("variable_hint")
    @classmethod
    def _valid_variables(cls, v: list[str]) -> list[str]:
        for item in v:
            if item not in STRUCTURAL_VARIABLES:
                raise ValueError(f"variable_hint must be subset of {STRUCTURAL_VARIABLES}, got {item!r}")
        return v

    @field_validator("evidence_quote")
    @classmethod
    def _non_empty_quote(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("evidence_quote is required for every extracted entity")
        return v


class VariableMapping(BaseModel):
    S: list[str] = Field(default_factory=list)
    A: list[str] = Field(default_factory=list)
    L: list[str] = Field(default_factory=list)
    V: list[str] = Field(default_factory=list)
    P: list[str] = Field(default_factory=list)
    tau: list[str] = Field(default_factory=list)


class StructuralEventCard(BaseModel):
    schema_version: str = "nlp_event_card.v0.2"
    candidate_id: str = ""
    event_id: str
    event_name: str
    source_chunks: list[str] = Field(default_factory=list)
    parent_chunk_id: str = ""
    parent_section_title: str = ""
    parent_context_hash: str = ""
    source_text_quote: str = ""
    quote_start_char: int = -1
    quote_end_char: int = -1
    actors: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    liquidity_paths: list[str] = Field(default_factory=list)
    visibility_shift: str = ""
    policy_response: list[str] = Field(default_factory=list)
    market_impact: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    variable_mapping: VariableMapping = Field(default_factory=VariableMapping)
    variable_votes: list[dict[str, Any]] = Field(default_factory=list)
    confidence_by_variable: dict[str, float] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    status: str = "candidate"
    extraction_notes: str = ""
    extraction: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def _status_is_candidate(cls, v: str) -> str:
        allowed = {"candidate", "reviewed", "canonical", "rejected", "needs_revision", "admitted"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}, got {v!r}")
        return v

    @model_validator(mode="after")
    def _finalize_candidate_metadata(self) -> "StructuralEventCard":
        if not self.evidence_quotes:
            raise ValueError("evidence_quotes is required — event cards must be grounded in source text")
        if not self.event_name.strip():
            raise ValueError("event_name is required")
        if not self.candidate_id:
            self.candidate_id = self.event_id
        if not self.source_text_quote and self.evidence_quotes:
            self.source_text_quote = self.evidence_quotes[0]
        defaults = {
            "extractor_version": EXTRACTOR_VERSION,
            "entity_extractor_version": ENTITY_EXTRACTOR_VERSION,
            "variable_mapper_version": VARIABLE_MAPPER_VERSION,
            "mapping_rules_hash": mapping_rules_hash(),
            "confidence_rules_version": CONFIDENCE_RULES_VERSION,
            "schema_validator_version": SCHEMA_VALIDATOR_VERSION,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        self.extraction = {**defaults, **self.extraction}
        return self


class EntityList(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
