from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from nlp.candidate_ledger import read_candidate_ledger  # noqa: E402
from nlp.export import write_event_card  # noqa: E402
from nlp.extraction import (  # noqa: E402
    StructuralEventCard,
    VariableMapping,
    validate_event_card,
)

from system_runtime.canonical_ids import validate_claim  # noqa: E402


def test_candidate_export_appends_schema_valid_ledger_entry(tmp_path: Path) -> None:
    source_text = "SVB sold securities at a loss after deposit outflows intensified."
    card = StructuralEventCard(
        event_id="event_ledger_candidate",
        event_name="Ledger Candidate",
        source_chunks=["chunk_ledger_001"],
        evidence_quotes=[source_text],
        variable_mapping=VariableMapping(S=["SVB"], A=["securities"], L=["deposit outflows"]),
        confidence={"score": 0.61},
        status="candidate",
    )
    validation = validate_event_card(card, source_text=source_text)
    ledger_path = tmp_path / "ledgers" / "candidate_ledger.jsonl"

    export_path = write_event_card(
        card,
        out_dir=tmp_path / "event_cards" / "candidate",
        ledger_path=ledger_path,
        validation=validation,
        source_text=source_text,
    )

    entries = read_candidate_ledger(ledger_path=ledger_path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["candidate_id"] == "event_ledger_candidate"
    assert entry["export_path"] == export_path.as_posix()
    assert entry["schema_valid"] is True
    assert entry["quote_grounded"] is True
    assert entry["chunk_hash"].startswith("sha256:")
    assert entry["source_hash"].startswith("sha256:")
    assert entry["candidate_variables"] == ["S", "A", "L"]
    assert entry["canonical_claim_id"].startswith("clm_")
    assert entry["canonical_claim_status"] == "WATCH"
    assert entry["canonical_claim_ceiling"] == "diagnostic_watch_only"
    assert entry["canonical_evidence_ids"] == []
    validate_claim(json.loads(export_path.read_text(encoding="utf-8"))["canonical_claim"])

    schema = json.loads((ROOT / "protocols" / "nlp_candidate_ledger.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(entry))
    assert not errors


def test_event_card_payload_keeps_diagnostic_claim_without_promoting_quote(tmp_path: Path) -> None:
    card = StructuralEventCard(
        event_id="event_canonical_compat",
        event_name="Liquidity pressure changed",
        source_chunks=["chunk_compat_001"],
        evidence_quotes=["Liquidity pressure changed after funding conditions tightened."],
        status="candidate",
    )
    export_path = write_event_card(card, out_dir=tmp_path / "event_cards" / "candidate", write_ledger=False)
    payload = json.loads(export_path.read_text(encoding="utf-8"))

    assert payload["canonical_claim_id"] == payload["canonical_claim"]["claim_id"]
    assert payload["canonical_claim"]["status"] == "WATCH"
    assert payload["canonical_claim"]["evidence_ids"] == []
    assert payload["canonical_claim"]["provenance"]["promotion_allowed"] is False
    validate_claim(payload["canonical_claim"])

    schema = json.loads((ROOT / "protocols" / "nlp_event_card.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert not errors
