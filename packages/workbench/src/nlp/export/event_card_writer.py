from __future__ import annotations

import json
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root

from nlp.canonical_compat import attach_event_card_claim, event_card_payload
from nlp.candidate_ledger import record_candidate_export
from nlp.extraction.schemas import StructuralEventCard


ROOT = _workspace_root()
DATA_NLP = ROOT / "Data" / "nlp"


def write_event_card(
    card: StructuralEventCard,
    *,
    status: str | None = None,
    out_dir: Path | None = None,
    ledger_path: Path | None = None,
    write_ledger: bool = True,
    validation: dict | None = None,
    source_text: str = "",
) -> Path:
    """Write a structural event card as candidate/reviewed/canonical JSON.

    The default path is candidate-only so NLP outputs never enter canonical
    evidence by accident.
    """
    card_status = status or card.status or "candidate"
    allowed = {"candidate", "reviewed", "canonical", "rejected", "needs_revision", "admitted"}
    if card_status not in allowed:
        raise ValueError(f"status must be one of {allowed}, got {card_status!r}")

    target_dir = out_dir or DATA_NLP / "event_cards" / card_status
    target_dir.mkdir(parents=True, exist_ok=True)
    card.status = card_status
    attach_event_card_claim(card)
    out_path = target_dir / f"{card.event_id}.json"
    out_path.write_text(json.dumps(event_card_payload(card), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    if write_ledger and card_status == "candidate":
        effective_ledger_path = ledger_path
        if effective_ledger_path is None and out_dir is not None:
            effective_ledger_path = out_dir.parent / "ledgers" / "candidate_ledger.jsonl"
        record_candidate_export(
            card,
            export_path=out_path,
            ledger_path=effective_ledger_path,
            validation=validation,
            source_text=source_text,
        )
    return out_path
