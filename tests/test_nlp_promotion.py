from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from nlp.export import write_event_card
from nlp.extraction import StructuralEventCard, VariableMapping
from nlp.promotion import promote_event_card, read_promotion_log


def _card(event_id: str, *, status: str = "candidate", score: float = 0.62) -> StructuralEventCard:
    return StructuralEventCard(
        event_id=event_id,
        event_name="Promotion Candidate",
        source_chunks=["chunk_promotion_001"],
        evidence_quotes=["SVB sold securities at a loss after deposit outflows intensified."],
        variable_mapping=VariableMapping(S=["SVB"], A=["securities"], L=["deposit outflows"]),
        confidence={"score": score},
        status=status,
    )


def test_valid_candidate_to_reviewed_transition_writes_log(tmp_path: Path) -> None:
    root = tmp_path / "event_cards"
    log_path = tmp_path / "ledgers" / "promotion_log.jsonl"
    from_path = write_event_card(_card("event_promote_reviewed"), out_dir=root / "candidate", write_ledger=False)

    to_path, entry = promote_event_card(
        from_path,
        new_status="reviewed",
        reviewer="human",
        reason="Quote is grounded and mapping is plausible.",
        preconditions={"schema_valid": True, "quote_grounded": True, "confidence_score": 0.62},
        event_cards_root=root,
        promotion_log_path=log_path,
    )

    assert to_path == root / "reviewed" / "event_promote_reviewed.json"
    assert to_path.exists()
    assert not from_path.exists()
    assert entry["old_status"] == "candidate"
    assert entry["new_status"] == "reviewed"
    assert read_promotion_log(promotion_log_path=log_path) == [entry]

    schema = json.loads((ROOT / "protocols" / "nlp_promotion_log.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(entry))
    assert not errors


def test_invalid_candidate_to_canonical_transition_rejected(tmp_path: Path) -> None:
    root = tmp_path / "event_cards"
    from_path = write_event_card(_card("event_invalid_direct"), out_dir=root / "candidate", write_ledger=False)

    with pytest.raises(ValueError, match="candidate -> canonical"):
        promote_event_card(
            from_path,
            new_status="canonical",
            reviewer="human",
            reason="Skip review.",
            preconditions={"schema_valid": True, "quote_grounded": True, "confidence_score": 0.7},
            event_cards_root=root,
            promotion_log_path=tmp_path / "promotion_log.jsonl",
        )


def test_reviewed_to_canonical_requires_grounding_and_review_reason(tmp_path: Path) -> None:
    root = tmp_path / "event_cards"
    reviewed_path = write_event_card(_card("event_canonical_gate", status="reviewed"), out_dir=root / "reviewed", write_ledger=False)

    with pytest.raises(ValueError, match="quote_grounded=true"):
        promote_event_card(
            reviewed_path,
            new_status="canonical",
            reviewer="human",
            reason="Looks good.",
            preconditions={"schema_valid": True, "quote_grounded": False, "confidence_score": 0.7},
            event_cards_root=root,
            promotion_log_path=tmp_path / "promotion_log.jsonl",
        )

    canonical_path, entry = promote_event_card(
        reviewed_path,
        new_status="canonical",
        reviewer="human",
        reason="Quote is grounded and candidate passed review.",
        preconditions={"schema_valid": True, "quote_grounded": True, "confidence_score": 0.7},
        event_cards_root=root,
        promotion_log_path=tmp_path / "promotion_log.jsonl",
    )

    assert canonical_path == root / "canonical" / "event_canonical_gate.json"
    assert entry["new_status"] == "canonical"
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert payload["status"] == "canonical"
