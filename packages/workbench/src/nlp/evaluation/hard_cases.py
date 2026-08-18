from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root

from nlp.canonical_compat import build_event_card_claim
from nlp.extraction.schemas import StructuralEventCard


ROOT = _workspace_root()
DATA_NLP = ROOT / "Data" / "nlp"
DEFAULT_HARD_CASES = DATA_NLP / "eval" / "hard_cases.jsonl"


def append_hard_case(
    card: StructuralEventCard,
    *,
    review_decision: str,
    failure_reason: str,
    hard_cases_path: Path | None = None,
) -> dict:
    entry = build_hard_case_record(
        card,
        review_decision=review_decision,
        failure_reason=failure_reason,
    )
    target = hard_cases_path or DEFAULT_HARD_CASES
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
    return entry


def read_hard_cases(*, hard_cases_path: Path | None = None) -> list[dict]:
    target = hard_cases_path or DEFAULT_HARD_CASES
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_hard_case_record(
    card: StructuralEventCard,
    *,
    review_decision: str,
    failure_reason: str,
) -> dict:
    canonical_claim = build_event_card_claim(card, legacy_status=review_decision)
    return {
        "candidate_id": card.candidate_id or card.event_id,
        "canonical_claim_id": canonical_claim["claim_id"],
        "canonical_claim_status": canonical_claim["status"],
        "canonical_claim_ceiling": canonical_claim["provenance"]["claim_ceiling"],
        "canonical_evidence_ids": canonical_claim["evidence_ids"],
        "source_text_quote": card.source_text_quote or (card.evidence_quotes[0] if card.evidence_quotes else ""),
        "predicted_variables": _candidate_variables(card),
        "event_type": _infer_event_type(card),
        "review_decision": review_decision,
        "failure_reason": failure_reason,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _candidate_variables(card: StructuralEventCard) -> list[str]:
    mapping = card.variable_mapping.model_dump()
    return [variable for variable in ("S", "A", "L", "V", "P", "tau") if mapping.get(variable)]


def _infer_event_type(card: StructuralEventCard) -> str:
    haystack = " ".join([card.event_name, " ".join(card.triggers), card.visibility_shift]).lower()
    if "latency" in haystack or "lag" in haystack or "delay" in haystack:
        return "latency_gap"
    if "liquidity" in haystack or "deposit" in haystack or "withdrawal" in haystack:
        return "liquidity_stress"
    if "anchor" in haystack or "valuation" in haystack:
        return "anchor_mismatch"
    return "structural_event_candidate"
