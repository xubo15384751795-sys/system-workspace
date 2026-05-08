from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from nlp.extraction import StructuralEventCard, VariableMapping
from nlp.rule_fingerprint import confidence_rules_version, mapping_rules_hash


def test_mapping_rules_hash_changes_when_file_changes(tmp_path: Path) -> None:
    rules_path = tmp_path / "mapping_rules.yaml"
    rules_path.write_text("schema_version: one\n", encoding="utf-8")
    first = mapping_rules_hash(rules_path)
    rules_path.write_text("schema_version: two\n", encoding="utf-8")
    second = mapping_rules_hash(rules_path)

    assert first.startswith("sha256:")
    assert second.startswith("sha256:")
    assert first != second


def test_event_card_includes_rule_fingerprint_metadata() -> None:
    card = StructuralEventCard(
        event_id="event_fingerprint",
        event_name="Fingerprint Candidate",
        evidence_quotes=["SVB sold securities at a loss after deposit outflows intensified."],
        variable_mapping=VariableMapping(S=["SVB"], A=["securities"], L=["deposit outflows"]),
    )

    assert card.candidate_id == card.event_id
    assert card.extraction["mapping_rules_hash"].startswith("sha256:")
    assert card.extraction["confidence_rules_version"] == confidence_rules_version()
    assert card.extraction["extractor_version"] == "structural_nlp_v0.2"
