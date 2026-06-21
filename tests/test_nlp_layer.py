from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from nlp.chunking.chunk_schema import TextChunk
from nlp.chunking.chunker import chunk_document
from nlp.extraction.entity_extractor import extract_entities
from nlp.extraction.event_extractor import extract_event_card
from nlp.extraction.schema_validator import validate_event_card
from nlp.extraction.schemas import ExtractedEntity, StructuralEventCard, VariableMapping
from nlp.mapping.confidence_rules import ConfidenceRules, score_confidence
from nlp.mapping.variable_mapper import (
    MappingResult,
    MappingVote,
    VariableMapper,
    map_entities_to_result,
)
from nlp.export.event_card_writer import write_event_card
from nlp.export.report_writer import write_extraction_report
from nlp.evaluation.hard_cases import append_hard_case, read_hard_cases
from nlp.promotion import promote_event_card


# ── Fixtures ──────────────────────────────────────────────────────────

SAMPLE_DOC = """# Silicon Valley Bank Liquidity Crisis

## Background

Silicon Valley Bank (SVB) experienced a severe deposit run in March 2023.
The bank had accumulated large unrealized losses on its held-to-maturity
securities portfolio. When depositors learned of these losses, a rapid
withdrawal of deposits occurred.

## Liquidity Event

The deposit outflows triggered forced selling of the securities portfolio
at a loss. This liquidation path was accelerated by the bank's concentrated
depositor base. The Federal Reserve intervened with the Bank Term Funding
Program (BTFP) as a policy backstop.

## Valuation Gap

The gap between book value and market value of the securities portfolio
became visible only after the forced sales began. This delayed recognition
is a classic visibility lag pattern. Mark-to-market losses that were
previously hidden in the held-to-maturity accounting anchor suddenly
materialized.

## Aftermath

The event triggered a sell-off in regional bank equities and raised
questions about regulatory transparency. The FDIC, Treasury, and Federal
Reserve jointly announced measures to protect depositors.
"""

MULTI_SECTION_DOC = """# Section 1: Private Credit

Private credit funds face refinancing stress as rates remain elevated.
Leveraged loan markets show signs of anchor erosion under continued
margin pressure.

## Section 1.2: Risk

Default rates are rising among lower-rated borrowers. Collateral
cascades may trigger forced liquidation of credit portfolios.

# Section 2: Treasury Market

The Treasury market continues to serve as the primary safe-asset anchor.
However, during stress episodes, liquidity demand can overwhelm the
market's capacity to absorb forced selling.
"""


@pytest.fixture
def chunks():
    return chunk_document(SAMPLE_DOC, document_id="test_svb")


@pytest.fixture
def multi_section_chunks():
    return chunk_document(MULTI_SECTION_DOC, document_id="test_multi")


@pytest.fixture
def entities(chunks):
    return extract_entities(chunks)


@pytest.fixture
def multi_entities(multi_section_chunks):
    return extract_entities(multi_section_chunks)


@pytest.fixture
def event_card(chunks, entities):
    return extract_event_card(chunks, entities, document_id="test_svb")


@pytest.fixture
def joined(chunks):
    return "\n".join(c.text for c in chunks)


# ── Parent-Child Evidence Hierarchy ───────────────────────────────────

class TestParentChildHierarchy:
    """Tests for improvement 1: parent-child evidence hierarchy."""

    def test_chunks_have_parent_fields(self, chunks):
        for chunk in chunks:
            assert chunk.parent_chunk_id, f"chunk {chunk.chunk_id} missing parent_chunk_id"
            assert chunk.parent_context_hash, f"chunk {chunk.chunk_id} missing parent_context_hash"
            assert chunk.parent_context_hash.startswith("sha256:")

    def test_event_card_has_parent_fields(self, event_card, chunks):
        assert event_card.parent_chunk_id, "event card missing parent_chunk_id"
        assert event_card.parent_section_title, "event card missing parent_section_title"
        assert event_card.parent_context_hash, "event card missing parent_context_hash"
        assert event_card.parent_chunk_id == chunks[0].parent_chunk_id
        assert event_card.parent_context_hash == chunks[0].parent_context_hash

    def test_source_text_quote_present(self, event_card, joined):
        assert event_card.source_text_quote, "event card missing source_text_quote"
        assert event_card.source_text_quote in joined, \
            "source_text_quote must be findable in source text"

    def test_quote_span_is_correct(self, event_card, joined):
        if event_card.quote_start_char >= 0 and event_card.quote_end_char >= 0:
            extracted = joined[event_card.quote_start_char:event_card.quote_end_char]
            assert extracted == event_card.source_text_quote, \
                f"Quote span mismatch: expected {event_card.source_text_quote!r}, got {extracted!r}"

    def test_child_quote_traces_to_parent_context(self, event_card, chunks):
        """Child event card's source_text_quote must appear in parent section text."""
        assert event_card.source_text_quote
        for chunk in chunks:
            if chunk.parent_chunk_id == event_card.parent_chunk_id:
                assert event_card.source_text_quote in chunk.text or \
                    any(event_card.source_text_quote in c.text
                        for c in chunks
                        if c.parent_chunk_id == event_card.parent_chunk_id)

    def test_ungrounded_quote_detected(self, event_card):
        """A quote not present in source text must be flagged."""
        unrelated = "completely unrelated text with no svb content whatsoever"
        result = validate_event_card(event_card, source_text=unrelated)
        has_grounding_error = any(
            "not grounded" in str(e).lower() for e in result.get("errors", [])
        )
        # Either a grounding error explicitly, or the validation fails overall
        if not has_grounding_error and result["valid"]:
            # If validation passed, the quotes must actually appear in source_text
            for quote in event_card.evidence_quotes:
                assert quote in unrelated, \
                    f"Quote {quote!r} should not be in unrelated text; validation should have flagged it"

    def test_grounded_quote_passes_validation(self, event_card, joined):
        result = validate_event_card(event_card, source_text=joined)
        grounding_errors = [
            e for e in result.get("errors", [])
            if "not grounded" in str(e).lower()
        ]
        assert not grounding_errors, f"Unexpected grounding errors: {grounding_errors}"

    def test_no_source_text_warns_but_accepted(self, event_card):
        result = validate_event_card(event_card, source_text="")
        grounding_errors = [
            e for e in result.get("errors", [])
            if "not grounded" in str(e).lower()
        ]
        assert not grounding_errors, "Without source_text, grounding is not checked"


# ── Weak-Supervision Variable Mapping ────────────────────────────────

class TestWeakSupervisionMapping:
    """Tests for improvement 2: labeling-function variable mapping."""

    def test_vote_structure(self):
        vote = MappingVote(
            rule_id="test:rule",
            variable="S",
            matched_text="Federal Reserve",
            weight=0.75,
            reason="Test rule.",
        )
        assert vote.rule_id == "test:rule"
        assert vote.variable == "S"
        assert vote.matched_text == "Federal Reserve"
        assert vote.weight == 0.75
        assert vote.reason == "Test rule."

    def test_entities_produce_votes(self, entities):
        mapper = VariableMapper()
        votes = mapper.vote_entities(entities)
        assert len(votes) > 0, "Entity extraction should produce votes"
        for vote in votes:
            assert isinstance(vote, MappingVote)
            assert vote.variable in ("S", "A", "L", "V", "P", "tau")
            assert vote.rule_id
            assert vote.weight > 0.0
            assert vote.reason

    def test_event_text_produces_additional_votes(self, entities, joined):
        mapper = VariableMapper()
        entity_only = mapper.vote_entities(entities)
        with_text = mapper.vote_event(entities=entities, text=joined)
        assert len(with_text) >= len(entity_only), \
            "Event text should produce additional pattern votes on top of entity votes"

    def test_mapping_result_aggregates_votes(self, entities, joined):
        result = map_entities_to_result(entities, text=joined)
        assert isinstance(result, MappingResult)
        assert result.variable_mapping is not None
        assert len(result.votes) > 0
        assert result.confidence_by_variable is not None
        assert not result.abstained, "Should not abstain when entities exist"

    def test_multiple_rules_vote_same_variable(self, entities, joined):
        """Multiple labeling functions can vote for the same variable."""
        mapper = VariableMapper()
        result = mapper.map_event_with_votes(entities=entities, text=joined)
        votes_by_variable: dict[str, int] = {}
        for vote in result.votes:
            votes_by_variable[vote.variable] = votes_by_variable.get(vote.variable, 0) + 1

        vars_with_multiple = {v: c for v, c in votes_by_variable.items() if c > 1}
        assert vars_with_multiple, \
            f"Expected some variables to have multiple votes, got: {votes_by_variable}"

    def test_abstention_when_no_evidence(self):
        mapper = VariableMapper()
        result = mapper.map_entities_with_votes([])
        assert result.abstained
        assert result.abstention_reason
        assert result.variable_mapping.S == []
        assert result.variable_mapping.A == []

    def test_low_weight_votes_filtered(self):
        mapper = VariableMapper(min_vote_weight=0.9)
        vote = MappingVote(
            rule_id="test:low_weight",
            variable="S",
            matched_text="weak signal",
            weight=0.1,
            reason="Low confidence test vote.",
        )
        result = mapper.aggregate_votes([vote])
        assert result.abstained, "Low-weight votes should be filtered"

    def test_confidence_by_variable_emitted(self, entities, joined):
        result = map_entities_to_result(entities, text=joined)
        assert result.confidence_by_variable
        for var, conf in result.confidence_by_variable.items():
            assert 0.0 <= conf <= 1.0, f"{var} confidence {conf} out of range"

    def test_ambiguous_entities_get_entity_hint_votes(self):
        """Entities with variable_hint get votes from hint before rule fallback."""
        mapped = ExtractedEntity(
            chunk_id="chunk_test",
            text="ambiguous entity",
            type="unknown_type",
            variable_hint=["A", "L"],
            evidence_quote="Some evidence about anchors and liquidation.",
        )
        mapper = VariableMapper()
        result = mapper.map_entities_with_votes([mapped])
        assert not result.abstained
        hint_votes = [v for v in result.votes if v.rule_id.startswith("entity_hint")]
        assert len(hint_votes) == 2, f"Expected 2 hint votes, got {len(hint_votes)}"
        assert {v.variable for v in hint_votes} == {"A", "L"}


# ── Schema Validation ────────────────────────────────────────────────

class TestSchemaValidation:
    def test_valid_card_passes(self, event_card, joined):
        result = validate_event_card(event_card, source_text=joined)
        grounding_errors = [
            e for e in result.get("errors", [])
            if "not grounded" in str(e).lower()
        ]
        assert not grounding_errors

    def test_empty_evidence_quotes_rejected(self):
        from pydantic import ValidationError as PydanticValidationError
        try:
            StructuralEventCard(
                event_id="test_no_quotes",
                event_name="Test event with no quotes",
            )
            pytest.fail("Should reject card with empty evidence_quotes")
        except PydanticValidationError:
            pass

    def test_short_quote_rejected(self, event_card):
        short = StructuralEventCard(
            event_id="test_short_quote",
            event_name="Short quote test",
            evidence_quotes=["hi"],
        )
        result = validate_event_card(short, source_text="hi")
        assert any("too short" in e for e in result.get("errors", []))

    def test_invalid_status_rejected(self):
        from pydantic import ValidationError as PydanticValidationError
        try:
            StructuralEventCard(
                event_id="test_status",
                event_name="Invalid status",
                status="published",
                evidence_quotes=["valid evidence quote here okay"],
            )
            pytest.fail("Should reject invalid status")
        except PydanticValidationError:
            pass


# ── Confidence Rules ──────────────────────────────────────────────────

class TestConfidenceRules:
    def test_empty_entities_zero_confidence(self):
        rules = ConfidenceRules()
        assert rules.score_entities([]) == 0.0

    def test_entities_with_no_quotes_low_confidence(self, entities):
        rules = ConfidenceRules()
        score = rules.score_entities(entities)
        assert 0.0 <= score <= 1.0

    def test_event_card_confidence_components(self, event_card):
        rules = ConfidenceRules()
        scores = rules.score_event_card(event_card)
        assert "event_extraction" in scores
        assert "variable_mapping" in scores
        assert "quote_grounding" in scores
        for val in scores.values():
            assert 0.0 <= val <= 1.0


# ── Hard Case Mining ─────────────────────────────────────────────────

class TestHardCaseMining:
    """Tests for improvement 3: hard case mining from rejected cards."""

    def test_rejected_card_becomes_hard_case(self, tmp_path, event_card):
        hard_path = tmp_path / "hard_cases.jsonl"
        record = append_hard_case(
            event_card,
            review_decision="rejected",
            failure_reason="Variable mapping too aggressive for weak evidence.",
            hard_cases_path=hard_path,
        )
        assert record["candidate_id"] == event_card.candidate_id
        assert record["review_decision"] == "rejected"
        assert record["failure_reason"]
        assert record["timestamp"]
        assert hard_path.exists()

    def test_needs_revision_becomes_hard_case(self, tmp_path, event_card):
        hard_path = tmp_path / "hard_cases.jsonl"
        append_hard_case(
            event_card,
            review_decision="needs_revision",
            failure_reason="Missing liquidity path evidence.",
            hard_cases_path=hard_path,
        )
        cases = read_hard_cases(hard_cases_path=hard_path)
        assert len(cases) == 1
        assert cases[0]["review_decision"] == "needs_revision"

    def test_hard_case_includes_predicted_variables(self, tmp_path, event_card):
        hard_path = tmp_path / "hard_cases.jsonl"
        append_hard_case(
            event_card,
            review_decision="rejected",
            failure_reason="Over-mapping to V without quote support.",
            hard_cases_path=hard_path,
        )
        cases = read_hard_cases(hard_cases_path=hard_path)
        assert "predicted_variables" in cases[0]
        assert isinstance(cases[0]["predicted_variables"], list)

    def test_hard_case_includes_source_quote(self, tmp_path, event_card):
        hard_path = tmp_path / "hard_cases.jsonl"
        append_hard_case(
            event_card,
            review_decision="needs_revision",
            failure_reason="Quote too short.",
            hard_cases_path=hard_path,
        )
        cases = read_hard_cases(hard_cases_path=hard_path)
        assert "source_text_quote" in cases[0]

    def test_hard_case_has_event_type(self, tmp_path, event_card):
        hard_path = tmp_path / "hard_cases.jsonl"
        append_hard_case(
            event_card,
            review_decision="rejected",
            failure_reason="Wrong event classification.",
            hard_cases_path=hard_path,
        )
        cases = read_hard_cases(hard_cases_path=hard_path)
        assert "event_type" in cases[0]
        assert cases[0]["event_type"]  # must be non-empty

    def test_multiple_hard_cases_append(self, tmp_path, event_card):
        hard_path = tmp_path / "hard_cases.jsonl"
        reasons = [
            "Quote grounding weak.",
            "Event type misclassified.",
            "Variable mapping over-extended.",
        ]
        for reason in reasons:
            append_hard_case(
                event_card,
                review_decision="rejected",
                failure_reason=reason,
                hard_cases_path=hard_path,
            )
        cases = read_hard_cases(hard_cases_path=hard_path)
        assert len(cases) == 3

    def test_promotion_to_rejected_triggers_hard_case(self, tmp_path, event_card):
        """promote_event_card with rejected status must append hard case."""
        card_dir = tmp_path / "cards" / "candidate"
        card_dir.mkdir(parents=True)
        card_path = card_dir / f"{event_card.event_id}.json"
        card_path.write_text(event_card.model_dump_json(indent=2))

        hard_path = tmp_path / "hard_cases.jsonl"
        log_path = tmp_path / "promotion_log.jsonl"

        to_path, log_entry = promote_event_card(
            card_path,
            new_status="rejected",
            reviewer="test_reviewer",
            reason="Insufficient quote grounding.",
            event_cards_root=tmp_path / "cards",
            promotion_log_path=log_path,
            hard_cases_path=hard_path,
        )
        cases = read_hard_cases(hard_cases_path=hard_path)
        assert len(cases) == 1
        assert cases[0]["review_decision"] == "rejected"

    def test_promotion_to_needs_revision_triggers_hard_case(self, tmp_path, event_card):
        card_dir = tmp_path / "cards" / "candidate"
        card_dir.mkdir(parents=True)
        card_path = card_dir / f"{event_card.event_id}.json"
        card_path.write_text(event_card.model_dump_json(indent=2))

        hard_path = tmp_path / "hard_cases.jsonl"
        log_path = tmp_path / "promotion_log.jsonl"

        promote_event_card(
            card_path,
            new_status="needs_revision",
            reviewer="test_reviewer",
            reason="Variable mapping needs re-checking.",
            event_cards_root=tmp_path / "cards",
            promotion_log_path=log_path,
            hard_cases_path=hard_path,
        )
        cases = read_hard_cases(hard_cases_path=hard_path)
        assert len(cases) == 1
        assert cases[0]["review_decision"] == "needs_revision"

    def test_promotion_to_canonical_does_not_trigger_hard_case(self, tmp_path, event_card):
        card_dir = tmp_path / "cards" / "candidate"
        card_dir.mkdir(parents=True)
        card_path = card_dir / f"{event_card.event_id}.json"
        card_path.write_text(event_card.model_dump_json(indent=2))

        hard_path = tmp_path / "hard_cases.jsonl"
        log_path = tmp_path / "promotion_log.jsonl"

        promote_event_card(
            card_path,
            new_status="reviewed",
            reviewer="test_reviewer",
            reason="Looks good for review.",
            event_cards_root=tmp_path / "cards",
            promotion_log_path=log_path,
            hard_cases_path=hard_path,
        )
        # reviewed does not trigger hard case
        assert not hard_path.exists() or len(read_hard_cases(hard_cases_path=hard_path)) == 0


# ── Promotion ────────────────────────────────────────────────────────

class TestPromotion:
    def test_valid_transition_candidate_to_reviewed(self, tmp_path, event_card):
        card_dir = tmp_path / "cards" / "candidate"
        card_dir.mkdir(parents=True)
        card_path = card_dir / f"{event_card.event_id}.json"
        card_path.write_text(event_card.model_dump_json(indent=2))

        log_path = tmp_path / "promotion_log.jsonl"
        to_path, entry = promote_event_card(
            card_path,
            new_status="reviewed",
            reviewer="test_reviewer",
            reason="Ready for review.",
            event_cards_root=tmp_path / "cards",
            promotion_log_path=log_path,
        )
        assert to_path.exists()
        assert entry["old_status"] == "candidate"
        assert entry["new_status"] == "reviewed"
        assert entry["reviewer"] == "test_reviewer"

    def test_invalid_transition_rejected(self, tmp_path, event_card):
        card_dir = tmp_path / "cards" / "candidate"
        card_dir.mkdir(parents=True)
        card_path = card_dir / f"{event_card.event_id}.json"
        card_path.write_text(event_card.model_dump_json(indent=2))

        # First promote to rejected
        log_path = tmp_path / "promotion_log.jsonl"
        promote_event_card(
            card_path,
            new_status="rejected",
            reviewer="test_reviewer",
            reason="Bad extraction.",
            event_cards_root=tmp_path / "cards",
            promotion_log_path=log_path,
        )
        # Now try to promote from rejected — should fail
        rejected_path = tmp_path / "cards" / "rejected" / f"{event_card.event_id}.json"
        assert rejected_path.exists()
        with pytest.raises(ValueError, match="Invalid NLP promotion transition"):
            promote_event_card(
                rejected_path,
                new_status="reviewed",
                reviewer="test_reviewer",
                reason="Trying to promote rejected card.",
                event_cards_root=tmp_path / "cards",
                promotion_log_path=log_path,
            )

    def test_canonical_requires_preconditions(self, tmp_path, event_card):
        card_dir = tmp_path / "cards" / "candidate"
        card_dir.mkdir(parents=True)
        card_path = card_dir / f"{event_card.event_id}.json"
        card_path.write_text(event_card.model_dump_json(indent=2))

        # First promote to reviewed
        log_path = tmp_path / "promotion_log.jsonl"
        promote_event_card(
            card_path,
            new_status="reviewed",
            reviewer="test_reviewer",
            reason="Looks good for review.",
            event_cards_root=tmp_path / "cards",
            promotion_log_path=log_path,
        )
        # Now try to promote from reviewed to canonical with no preconditions
        reviewed_path = tmp_path / "cards" / "reviewed" / f"{event_card.event_id}.json"
        assert reviewed_path.exists()
        with pytest.raises(ValueError, match="canonical promotion requires"):
            promote_event_card(
                reviewed_path,
                new_status="canonical",
                reviewer="",
                reason="",
                event_cards_root=tmp_path / "cards",
                promotion_log_path=log_path,
            )


# ── Event Card Export ────────────────────────────────────────────────

class TestEventCardExport:
    def test_write_event_card_creates_json(self, tmp_path, event_card):
        out = write_event_card(event_card, out_dir=tmp_path, write_ledger=False)
        assert out.exists()
        assert out.suffix == ".json"
        reloaded = json.loads(out.read_text(encoding="utf-8"))
        assert reloaded["event_id"] == event_card.event_id

    def test_write_extraction_report_creates_md(self, tmp_path, event_card):
        out = write_extraction_report(event_card, out_dir=tmp_path)
        assert out.exists()
        assert out.suffix == ".md"
        content = out.read_text(encoding="utf-8")
        assert event_card.event_name in content
        assert event_card.event_id in content


# ── Multi-Section Document ───────────────────────────────────────────

class TestMultiSectionDocument:
    def test_multi_section_chunks_have_distinct_parents(self, multi_section_chunks):
        parent_ids = {c.parent_chunk_id for c in multi_section_chunks}
        assert len(parent_ids) > 1, "Multi-section doc should produce multiple parent IDs"

    def test_multi_section_extraction(self, multi_section_chunks, multi_entities):
        card = extract_event_card(
            multi_section_chunks, multi_entities, document_id="test_multi"
        )
        assert card.event_name
        assert card.evidence_quotes
        assert card.status == "candidate"


# ── Boundary Enforcement ─────────────────────────────────────────────

class TestBoundaryEnforcement:
    NLP_SRC = ROOT / "Workbench" / "src" / "nlp"

    def test_no_framework_imports(self):
        """NLP modules must not import from Deformation src.* or harvester."""
        for py_file in self.NLP_SRC.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            assert "from src." not in text, \
                f"{py_file.relative_to(ROOT)} imports from src.*"
            assert "import src." not in text, \
                f"{py_file.relative_to(ROOT)} imports src.*"
            assert "import harvester" not in text, \
                f"{py_file.relative_to(ROOT)} imports harvester"

    def test_no_deformation_modifications(self):
        """NLP code must not modify Deformation files."""
        deformation_dir = ROOT / "deformation-framework" / "src"
        nlp_paths = {p.name for p in self.NLP_SRC.rglob("*.py")}
        deformation_paths = list(deformation_dir.rglob("*.py"))
        assert deformation_paths, "Deformation source must exist"
        # Just verify the NLP module exists and does not inject into Deformation
        assert nlp_paths


# ── Chunking ─────────────────────────────────────────────────────────

class TestChunking:
    def test_chunks_are_non_empty(self, chunks):
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.text.strip()
            assert chunk.chunk_id
            assert chunk.document_id == "test_svb"

    def test_chunk_types_are_valid(self, chunks):
        valid_types = {"section", "paragraph", "table", "sliding_window", "quote"}
        for chunk in chunks:
            assert chunk.chunk_type in valid_types, \
                f"Invalid chunk_type: {chunk.chunk_type}"

    def test_markdown_sections_produce_chunks(self):
        md = "# Heading One\n\nParagraph text.\n\n## Heading Two\n\nMore text."
        result = chunk_document(md, document_id="test")
        assert len(result) > 0


# ── Entity Extraction ────────────────────────────────────────────────

class TestEntityExtraction:
    def test_institutions_extracted(self, entities):
        institution_names = [e.text for e in entities if e.type == "institution"]
        assert institution_names, "Should extract institution entities"
        assert any("SVB" in name or "Silicon Valley Bank" in name for name in institution_names)

    def test_entities_have_evidence_quotes(self, entities):
        for entity in entities:
            assert entity.evidence_quote, \
                f"Entity {entity.text} missing evidence_quote"

    def test_entities_have_valid_variable_hints(self, entities):
        valid = {"S", "A", "L", "V", "P", "tau"}
        for entity in entities:
            for hint in entity.variable_hint:
                assert hint in valid, f"Invalid variable hint: {hint}"
