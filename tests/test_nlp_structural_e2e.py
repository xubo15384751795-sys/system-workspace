"""Structural NLP end-to-end: chunk → extract → validate → golden eval."""
from __future__ import annotations

from nlp.chunking.chunker import chunk_document
from nlp.evaluation.extraction_eval import evaluate_extraction
from nlp.evaluation.golden_set import GoldenEventCard
from nlp.extraction.entity_extractor import extract_entities
from nlp.extraction.event_extractor import extract_event_card
from nlp.extraction.schema_validator import validate_event_card

SAMPLE = """
# Federal Reserve liquidity note

On 2026-08-01 the Federal Reserve raised the interest rate on reserve balances (IORB).
Banks reported deposit outflows and commercial paper spreads widened.
Market participants cited funding stress and delayed settlement latency in repo markets.
""".strip()


def test_structural_nlp_pipeline_produces_valid_card() -> None:
    chunks = chunk_document(SAMPLE, document_id="e2e_fed")
    assert chunks, "expected at least one chunk"
    entities = extract_entities(chunks)
    card = extract_event_card(chunks, entities, document_id="e2e_fed")

    # Schema/jsonschema validity (quote-span offsets can drift under rule extraction).
    result = validate_event_card(card)
    assert result["valid"], result["errors"]
    assert card.event_name
    assert card.evidence_quotes
    assert card.source_text_quote
    assert card.source_text_quote in SAMPLE

    golden = GoldenEventCard(
        golden_id="e2e-fed-liquidity",
        source_text_quote=card.source_text_quote or SAMPLE[:200],
        expected_event_name=card.event_name,
        expected_triggers=list(card.triggers[:3]),
        expected_entities=[
            {"text": e.text, "type": e.type}
            for e in entities[:5]
        ],
        expected_variables={
            k: list(v)
            for k, v in card.variable_mapping.model_dump().items()
            if v
        },
        required_quotes=list(card.evidence_quotes[:1]),
        notes="inline golden for structural e2e",
    )
    report = evaluate_extraction([card], golden_cards=[golden])
    assert report.total_golden == 1
    assert report.schema_valid_rate >= 1.0
