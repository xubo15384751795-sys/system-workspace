from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from nlp.candidate_ledger import read_candidate_ledger
from nlp.export import write_event_card
from nlp.extraction import StructuralEventCard, VariableMapping, validate_event_card


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

    schema = json.loads((ROOT / "protocols" / "nlp_candidate_ledger.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(entry))
    assert not errors
