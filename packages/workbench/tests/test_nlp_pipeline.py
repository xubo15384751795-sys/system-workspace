"""Tests for the NLP pipeline — pure text processing and schema validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nlp.parsing.text_cleaner import clean_text, strip_references
from nlp.chunking.chunk_schema import TextChunk, ChunkManifest
from nlp.extraction.schemas import ExtractedEntity, VariableMapping
from nlp.mapping.confidence_rules import ConfidenceRules


# ---------------------------------------------------------------------------
# text_cleaner
# ---------------------------------------------------------------------------

class TestCleanText:
    def test_removes_excess_blank_lines(self):
        text = "line one\n\n\n\n\nline two"
        result = clean_text(text, remove_headers_footers=False)
        assert "\n\n\n\n" not in result

    def test_strips_leading_trailing_whitespace(self):
        result = clean_text("  hello world  ", remove_headers_footers=False)
        assert result == "hello world"

    def test_normalises_crlf(self):
        text = "line1\r\nline2\r\nline3"
        result = clean_text(text, remove_headers_footers=False)
        assert "\r" not in result

    def test_short_text_not_mutilated(self):
        text = "Short.\nTwo lines."
        result = clean_text(text, remove_headers_footers=False)
        assert "Short." in result
        assert "Two lines." in result

    def test_removes_page_numbers(self):
        text = "Some text.\n\n42\n\nMore text."
        result = clean_text(text, remove_headers_footers=False)
        assert "\n42\n" not in result


class TestStripReferences:
    def test_strips_references_section(self):
        text = "Main body.\n\nReferences\n\nSmith, J. (2020). A paper."
        result = strip_references(text)
        assert "Smith" not in result
        assert "Main body" in result

    def test_strips_bibliography(self):
        text = "Content here.\n\nBibliography\n\nSome ref."
        result = strip_references(text)
        assert "Some ref." not in result

    def test_no_references_section_unchanged(self):
        text = "Just content, nothing else."
        result = strip_references(text)
        assert result == text

    def test_case_insensitive(self):
        text = "Body.\n\nREFERENCES\n\nCitation."
        result = strip_references(text)
        assert "Citation" not in result


# ---------------------------------------------------------------------------
# TextChunk schema validation
# ---------------------------------------------------------------------------

class TestTextChunk:
    def _valid(self, **overrides):
        base = {
            "chunk_id": "c001",
            "document_id": "doc001",
            "text": "The Federal Reserve raised rates by 75 bps.",
            "chunk_type": "paragraph",
        }
        return {**base, **overrides}

    def test_valid_chunk_creates_ok(self):
        chunk = TextChunk(**self._valid())
        assert chunk.chunk_id == "c001"

    def test_empty_text_raises(self):
        with pytest.raises(ValidationError):
            TextChunk(**self._valid(text="   "))

    def test_invalid_chunk_type_raises(self):
        with pytest.raises(ValidationError):
            TextChunk(**self._valid(chunk_type="random"))

    def test_valid_chunk_types(self):
        for ct in ("section", "paragraph", "table", "sliding_window", "quote"):
            TextChunk(**self._valid(chunk_type=ct))


# ---------------------------------------------------------------------------
# ExtractedEntity schema validation
# ---------------------------------------------------------------------------

class TestExtractedEntity:
    def _valid(self, **overrides):
        base = {
            "chunk_id": "c001",
            "text": "Federal Reserve",
            "type": "institution",
            "evidence_quote": "The Federal Reserve raised rates.",
        }
        return {**base, **overrides}

    def test_valid_entity_ok(self):
        e = ExtractedEntity(**self._valid())
        assert e.type == "institution"

    def test_empty_evidence_quote_raises(self):
        with pytest.raises(ValidationError):
            ExtractedEntity(**self._valid(evidence_quote=""))

    def test_invalid_variable_hint_raises(self):
        with pytest.raises(ValidationError):
            ExtractedEntity(**self._valid(variable_hint=["UNKNOWN_VAR"]))

    def test_valid_variable_hints(self):
        e = ExtractedEntity(**self._valid(variable_hint=["S", "A"]))
        assert "S" in e.variable_hint


# ---------------------------------------------------------------------------
# ConfidenceRules
# ---------------------------------------------------------------------------

class TestConfidenceRulesEntities:
    def _entity(self, var_hint=None, quote="The central bank tightened policy sharply."):
        return ExtractedEntity(
            chunk_id="c1",
            text="Federal Reserve",
            type="institution",
            variable_hint=var_hint or [],
            evidence_quote=quote,
        )

    def test_empty_entities_zero_score(self):
        assert ConfidenceRules().score_entities([]) == 0.0

    def test_grounded_entities_score_higher_than_zero(self):
        score = ConfidenceRules().score_entities([self._entity()])
        assert 0 < score <= 0.9

    def test_diverse_types_increases_score(self):
        e1 = self._entity()
        e2 = ExtractedEntity(chunk_id="c2", text="yield", type="instrument",
                              evidence_quote="Yield spiked on the announcement.")
        score_one = ConfidenceRules().score_entities([e1])
        score_two = ConfidenceRules().score_entities([e1, e2])
        assert score_two >= score_one

    def test_score_capped_at_point_nine(self):
        entities = [
            ExtractedEntity(chunk_id=f"c{i}", text=f"ent{i}", type=f"type{i}",
                            evidence_quote="Evidence quote that is long enough to count.")
            for i in range(20)
        ]
        assert ConfidenceRules().score_entities(entities) <= 0.9


class TestConfidenceRulesMapping:
    def test_empty_mapping_zero_score(self):
        assert ConfidenceRules().score_mapping(VariableMapping()) == 0.0

    def test_populated_mapping_positive_score(self):
        mapping = VariableMapping(S=["Treasury yields"], A=["FOMC"])
        score = ConfidenceRules().score_mapping(mapping)
        assert 0 < score <= 0.85

    def test_more_variables_increases_score(self):
        m1 = VariableMapping(S=["x"])
        m2 = VariableMapping(S=["x"], A=["y"], L=["z"])
        assert ConfidenceRules().score_mapping(m2) >= ConfidenceRules().score_mapping(m1)


# ---------------------------------------------------------------------------
# NLP promotion state machine (pure transition logic)
# ---------------------------------------------------------------------------

from nlp.promotion import (
    ALLOWED_TRANSITIONS,
    STATUSES,
    _normalize_preconditions,
    _require_canonical_preconditions,
    build_promotion_log_entry,
)
from nlp.extraction.schemas import StructuralEventCard


class TestPromotionStateMachine:
    def test_all_statuses_have_transitions(self):
        for status in STATUSES:
            assert status in ALLOWED_TRANSITIONS

    def test_canonical_is_terminal(self):
        assert ALLOWED_TRANSITIONS["canonical"] == set()

    def test_rejected_is_terminal(self):
        assert ALLOWED_TRANSITIONS["rejected"] == set()

    def test_candidate_can_become_reviewed(self):
        assert "reviewed" in ALLOWED_TRANSITIONS["candidate"]

    def test_reviewed_can_become_canonical(self):
        assert "canonical" in ALLOWED_TRANSITIONS["reviewed"]


class TestNormalizePreconditions:
    def test_none_input_returns_defaults(self):
        result = _normalize_preconditions(None)
        assert result["schema_valid"] is False
        assert result["quote_grounded"] is False
        assert result["confidence_score"] == 0.0

    def test_values_cast_correctly(self):
        result = _normalize_preconditions({"schema_valid": 1, "confidence_score": "0.8"})
        assert result["schema_valid"] is True
        assert result["confidence_score"] == pytest.approx(0.8)


class TestRequireCanonicalPreconditions:
    def _ok(self):
        return {"schema_valid": True, "quote_grounded": True, "confidence_score": 0.7}

    def test_valid_preconditions_pass(self):
        _require_canonical_preconditions(self._ok(), reviewer="alice", reason="Verified.")

    def test_missing_schema_valid_raises(self):
        pre = {**self._ok(), "schema_valid": False}
        with pytest.raises(ValueError, match="schema_valid"):
            _require_canonical_preconditions(pre, reviewer="alice", reason="ok")

    def test_missing_quote_grounded_raises(self):
        pre = {**self._ok(), "quote_grounded": False}
        with pytest.raises(ValueError, match="quote_grounded"):
            _require_canonical_preconditions(pre, reviewer="alice", reason="ok")

    def test_empty_reviewer_raises(self):
        with pytest.raises(ValueError, match="reviewer"):
            _require_canonical_preconditions(self._ok(), reviewer="", reason="ok")

    def test_empty_reason_raises(self):
        with pytest.raises(ValueError, match="reason"):
            _require_canonical_preconditions(self._ok(), reviewer="alice", reason="")
