"""Machine-readable note schemas for Paper index validation."""
from __future__ import annotations

NOTE_SCHEMAS: dict[str, list[str]] = {
    "case": ["type", "quality", "review_status"],
    "entity": ["type", "canonical_name", "review_status"],
    "trade_idea": ["type", "ticker", "signal", "confidence", "review_status"],
    "context-action": ["type", "actor", "verb", "object", "review_status"],
    "context-regime": ["type", "as_of", "review_status"],
    "model": ["type", "canonical_name", "review_status"],
}


def required_fields(note_type: str) -> list[str]:
    return NOTE_SCHEMAS.get(note_type, ["type", "review_status"])
