from __future__ import annotations

import json
from workbench.paths import workspace_root as _workspace_root
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from nlp.extraction.schemas import StructuralEventCard
from system_runtime.canonical_ids import validate_claim

ROOT = _workspace_root()
PROTOCOLS = ROOT / "protocols"


def validate_event_card(card: StructuralEventCard, *, source_text: str = "") -> dict:
    """Validate a StructuralEventCard against the protocol schema.

    Returns a dict with keys: valid (bool), errors (list[str]), warnings (list[str]).
    """
    result: dict = {"valid": True, "errors": [], "warnings": []}

    try:
        data = card.model_dump()
    except Exception as exc:
        result["valid"] = False
        result["errors"].append(f"Pydantic serialization failed: {exc}")
        return result

    schema_path = PROTOCOLS / "nlp_event_card.schema.json"
    if not schema_path.exists():
        result["warnings"].append(f"Schema file not found at {schema_path}, skipping jsonschema validation")
        return result

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(data))
        if errors:
            result["valid"] = False
            result["errors"].extend(str(e) for e in errors)
    except Exception as exc:
        result["warnings"].append(f"jsonschema validation failed: {exc}")

    if card.canonical_claim:
        try:
            validate_claim(card.canonical_claim)
            if card.canonical_claim_id != card.canonical_claim.get("claim_id"):
                result["valid"] = False
                result["errors"].append("canonical_claim_id does not match canonical_claim.claim_id")
        except Exception as exc:
            result["valid"] = False
            result["errors"].append(f"canonical_claim invalid: {exc}")

    if not card.evidence_quotes:
        result["valid"] = False
        result["errors"].append("evidence_quotes must not be empty")
    for idx, quote in enumerate(card.evidence_quotes):
        if len(quote.strip()) < 10:
            result["valid"] = False
            result["errors"].append(f"evidence_quote[{idx}] too short (< 10 chars): {quote!r}")
        if source_text and quote not in source_text:
            result["valid"] = False
            result["errors"].append(f"evidence_quote[{idx}] is not grounded in source text")
    if card.source_text_quote:
        if source_text and card.source_text_quote not in source_text:
            result["valid"] = False
            result["errors"].append("source_text_quote is not grounded in source text")
        if card.quote_start_char >= 0 or card.quote_end_char >= 0:
            if card.quote_start_char < 0 or card.quote_end_char < card.quote_start_char:
                result["valid"] = False
                result["errors"].append("quote span is invalid")
            elif source_text and source_text[card.quote_start_char : card.quote_end_char] != card.source_text_quote:
                result["valid"] = False
                result["errors"].append("quote span does not match source_text_quote")

    return result


def validate_entity_list(entities: list) -> dict:
    result: dict = {"valid": True, "errors": [], "warnings": []}
    for idx, entity in enumerate(entities):
        try:
            from nlp.extraction.schemas import ExtractedEntity

            ExtractedEntity(**entity)
        except (ValidationError, TypeError, ValueError) as exc:
            result["valid"] = False
            result["errors"].append(f"entity[{idx}] invalid: {exc}")
    return result
