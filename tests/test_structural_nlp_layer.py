from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from nlp.chunking import chunk_document
from nlp.export import write_event_card, write_extraction_report
from nlp.extraction import (
    StructuralEventCard,
    VariableMapping,
    extract_entities,
    extract_event_card,
    validate_event_card,
)
from nlp.mapping import map_entities_to_variables, score_confidence


def test_structural_nlp_modules_import() -> None:
    import nlp.export
    import nlp.extraction
    import nlp.mapping

    assert nlp.extraction.StructuralEventCard
    assert nlp.mapping.VariableMapper
    assert nlp.export.write_event_card


def test_chunking_preserves_section_metadata() -> None:
    text = """# Case Note

## Liquidity Stress

Silicon Valley Bank disclosed unrealized losses and deposit outflows intensified.
The Federal Reserve later introduced BTFP as a backstop facility.
"""

    chunks = chunk_document(text, document_id="doc_svb", max_chars=500)

    assert chunks
    assert chunks[0].section_id == "doc_svb_sec_001"
    assert chunks[0].metadata["heading"] == "Liquidity Stress"
    assert any("Silicon Valley Bank" in chunk.text for chunk in chunks)


def test_rule_based_event_card_stays_candidate_and_grounded() -> None:
    text = """# SVB Liquidity Stress

Silicon Valley Bank disclosed unrealized losses after deposit outflows intensified.
SVB sold Treasuries and securities at a loss, turning book value into a market-value anchor problem.
The Federal Reserve introduced BTFP as a policy backstop facility.
"""
    chunks = chunk_document(text, document_id="svb_2023", max_chars=500)
    entities = extract_entities(chunks)
    joined = "\n".join(c.text for c in chunks)
    mapping = map_entities_to_variables(entities, text=joined)
    card = extract_event_card(chunks, entities, document_id="svb_2023")
    validation = validate_event_card(card, source_text=joined)

    assert entities
    assert mapping.S
    assert mapping.A
    assert card.status == "candidate"
    assert card.evidence_quotes
    assert validation["valid"], validation
    assert all(" " in quote for quote in card.evidence_quotes)


def test_invalid_event_card_without_quotes_is_rejected() -> None:
    with pytest.raises(ValueError, match="evidence_quotes is required"):
        StructuralEventCard(
            event_id="event_bad",
            event_name="Bad Event",
            evidence_quotes=[],
            variable_mapping=VariableMapping(),
        )


def test_candidate_event_card_export(tmp_path: Path) -> None:
    card = StructuralEventCard(
        event_id="event_test_candidate",
        event_name="Test Candidate",
        source_chunks=["chunk_001"],
        evidence_quotes=["SVB sold securities at a loss after deposit outflows intensified."],
        variable_mapping=VariableMapping(S=["SVB"], A=["securities"], L=["deposit outflows"]),
        status="candidate",
    )

    card_path = write_event_card(card, out_dir=tmp_path / "event_cards")
    report_path = write_extraction_report(card, validation=validate_event_card(card), out_dir=tmp_path / "reports")
    confidence = score_confidence(card)

    assert card_path.exists()
    assert report_path.exists()
    assert "candidate" in report_path.read_text(encoding="utf-8")
    assert confidence["quote_grounding"] > 0
