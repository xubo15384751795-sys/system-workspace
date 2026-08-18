from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from uuid import uuid4

from nlp.canonical_compat import attach_event_card_claim
from nlp.extraction.schema_validator import validate_event_card
from nlp.extraction.schemas import StructuralEventCard
from nlp.rule_fingerprint import text_sha256


ROOT = _workspace_root()
DATA_NLP = ROOT / "Data" / "nlp"
DEFAULT_LEDGER = DATA_NLP / "ledgers" / "candidate_ledger.jsonl"


def build_candidate_ledger_entry(
    card: StructuralEventCard,
    *,
    export_path: Path,
    validation: dict | None = None,
    source_text: str = "",
    corpus_id: str = "",
    release_id: str = "",
    source_path: str = "",
    source_hash: str = "",
    chunk_id: str = "",
    chunk_hash: str = "",
    event_type: str = "",
) -> dict:
    canonical_claim = attach_event_card_claim(card)
    validation_result = validation or validate_event_card(card, source_text=source_text)
    quote_grounded = _quote_grounded(validation_result, card, source_text)
    variables = _candidate_variables(card)
    confidence_score = _confidence_score(card)
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    first_quote = card.evidence_quotes[0] if card.evidence_quotes else ""

    return {
        "ledger_version": "nlp_candidate_ledger.v0.1",
        "ledger_entry_id": f"led_{created_at.replace('-', '').replace(':', '').replace('+', 'Z')}_{uuid4().hex[:8]}",
        "candidate_id": card.candidate_id or card.event_id,
        "status": card.status,
        "canonical_claim_id": canonical_claim["claim_id"],
        "canonical_claim_status": canonical_claim["status"],
        "canonical_claim_ceiling": canonical_claim["provenance"]["claim_ceiling"],
        "canonical_evidence_ids": canonical_claim["evidence_ids"],
        "corpus_id": corpus_id,
        "release_id": release_id,
        "source_path": source_path,
        "source_hash": source_hash or text_sha256(source_text or first_quote),
        "chunk_id": chunk_id or (card.source_chunks[0] if card.source_chunks else ""),
        "chunk_hash": chunk_hash or text_sha256(first_quote),
        "event_type": event_type or _infer_event_type(card),
        "candidate_variables": variables,
        "confidence_score": confidence_score,
        "confidence_label": _confidence_label(confidence_score),
        "schema_valid": bool(validation_result.get("valid")),
        "quote_grounded": quote_grounded,
        "export_path": export_path.as_posix(),
        "created_at": created_at,
    }


def append_candidate_ledger(entry: dict, *, ledger_path: Path | None = None) -> Path:
    target = ledger_path or DEFAULT_LEDGER
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
    return target


def record_candidate_export(
    card: StructuralEventCard,
    *,
    export_path: Path,
    ledger_path: Path | None = None,
    validation: dict | None = None,
    source_text: str = "",
    corpus_id: str = "",
    release_id: str = "",
    source_path: str = "",
    source_hash: str = "",
    chunk_id: str = "",
    chunk_hash: str = "",
    event_type: str = "",
) -> dict:
    entry = build_candidate_ledger_entry(
        card,
        export_path=export_path,
        validation=validation,
        source_text=source_text,
        corpus_id=corpus_id,
        release_id=release_id,
        source_path=source_path,
        source_hash=source_hash,
        chunk_id=chunk_id,
        chunk_hash=chunk_hash,
        event_type=event_type,
    )
    append_candidate_ledger(entry, ledger_path=ledger_path)
    return entry


def read_candidate_ledger(*, ledger_path: Path | None = None) -> list[dict]:
    target = ledger_path or DEFAULT_LEDGER
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]


def _candidate_variables(card: StructuralEventCard) -> list[str]:
    mapping = card.variable_mapping.model_dump()
    return [variable for variable in ("S", "A", "L", "V", "P", "tau") if mapping.get(variable)]


def _confidence_score(card: StructuralEventCard) -> float:
    if "score" in card.confidence:
        return round(float(card.confidence["score"]), 2)
    values = [float(value) for value in card.confidence.values() if isinstance(value, int | float)]
    if values:
        return round(sum(values) / len(values), 2)
    return 0.0


def _confidence_label(score: float) -> str:
    if score >= 0.67:
        return "high"
    if score >= 0.34:
        return "medium"
    return "low"


def _quote_grounded(validation: dict, card: StructuralEventCard, source_text: str) -> bool:
    if source_text:
        return bool(validation.get("valid")) and not any(
            "not grounded" in str(error) for error in validation.get("errors", [])
        )
    return bool(card.evidence_quotes)


def _infer_event_type(card: StructuralEventCard) -> str:
    haystack = " ".join([card.event_name, " ".join(card.triggers), card.visibility_shift]).lower()
    if "latency" in haystack or "lag" in haystack or "delay" in haystack:
        return "latency_gap"
    if "liquidity" in haystack or "deposit" in haystack or "withdrawal" in haystack:
        return "liquidity_stress"
    if "anchor" in haystack or "valuation" in haystack:
        return "anchor_mismatch"
    return "structural_event_candidate"
