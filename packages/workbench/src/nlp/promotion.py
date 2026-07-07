from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from uuid import uuid4

from nlp.evaluation.hard_cases import append_hard_case
from nlp.extraction.schemas import StructuralEventCard


ROOT = _workspace_root()
DATA_NLP = ROOT / "Data" / "nlp"
DEFAULT_EVENT_CARDS_ROOT = DATA_NLP / "event_cards"
DEFAULT_PROMOTION_LOG = DATA_NLP / "ledgers" / "promotion_log.jsonl"

STATUSES = {"candidate", "reviewed", "canonical", "rejected", "needs_revision"}
ALLOWED_TRANSITIONS = {
    "candidate": {"reviewed", "rejected", "needs_revision"},
    "reviewed": {"canonical", "rejected", "needs_revision"},
    "needs_revision": {"candidate", "rejected"},
    "rejected": set(),
    "canonical": set(),
}


def promote_event_card(
    from_path: Path,
    *,
    new_status: str,
    reviewer: str,
    reason: str,
    decision_type: str = "manual_review",
    preconditions: dict | None = None,
    event_cards_root: Path | None = None,
    promotion_log_path: Path | None = None,
    hard_cases_path: Path | None = None,
) -> tuple[Path, dict]:
    if new_status not in STATUSES:
        raise ValueError(f"Unknown status: {new_status}")
    card = StructuralEventCard(**json.loads(from_path.read_text(encoding="utf-8")))
    old_status = card.status
    if old_status not in STATUSES:
        raise ValueError(f"Cannot promote from unsupported status: {old_status}")
    if new_status not in ALLOWED_TRANSITIONS[old_status]:
        raise ValueError(f"Invalid NLP promotion transition: {old_status} -> {new_status}")

    checked = _normalize_preconditions(preconditions)
    if new_status == "canonical":
        _require_canonical_preconditions(checked, reviewer=reviewer, reason=reason)

    card.status = new_status
    root = event_cards_root or DEFAULT_EVENT_CARDS_ROOT
    target_dir = root / new_status
    target_dir.mkdir(parents=True, exist_ok=True)
    to_path = target_dir / from_path.name
    to_path.write_text(card.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if from_path.resolve() != to_path.resolve() and from_path.exists():
        from_path.unlink()

    entry = build_promotion_log_entry(
        card,
        old_status=old_status,
        new_status=new_status,
        reviewer=reviewer,
        reason=reason,
        decision_type=decision_type,
        preconditions=checked,
        from_path=from_path,
        to_path=to_path,
    )
    append_promotion_log(entry, promotion_log_path=promotion_log_path)
    if new_status in {"rejected", "needs_revision"}:
        append_hard_case(
            card,
            review_decision=new_status,
            failure_reason=reason,
            hard_cases_path=hard_cases_path,
        )
    return to_path, entry


def build_promotion_log_entry(
    card: StructuralEventCard,
    *,
    old_status: str,
    new_status: str,
    reviewer: str,
    reason: str,
    decision_type: str,
    preconditions: dict,
    from_path: Path,
    to_path: Path,
) -> dict:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "promotion_log_version": "nlp_promotion_log.v0.1",
        "promotion_entry_id": f"pro_{timestamp.replace('-', '').replace(':', '').replace('+', 'Z')}_{uuid4().hex[:8]}",
        "candidate_id": card.candidate_id or card.event_id,
        "old_status": old_status,
        "new_status": new_status,
        "reviewer": reviewer,
        "reason": reason,
        "decision_type": decision_type,
        "preconditions": preconditions,
        "from_path": from_path.as_posix(),
        "to_path": to_path.as_posix(),
        "timestamp": timestamp,
    }


def append_promotion_log(entry: dict, *, promotion_log_path: Path | None = None) -> Path:
    target = promotion_log_path or DEFAULT_PROMOTION_LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
    return target


def read_promotion_log(*, promotion_log_path: Path | None = None) -> list[dict]:
    target = promotion_log_path or DEFAULT_PROMOTION_LOG
    if not target.exists():
        return []
    return [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normalize_preconditions(preconditions: dict | None) -> dict:
    data = dict(preconditions or {})
    return {
        "schema_valid": bool(data.get("schema_valid", False)),
        "quote_grounded": bool(data.get("quote_grounded", False)),
        "confidence_score": float(data.get("confidence_score", 0.0)),
    }


def _require_canonical_preconditions(preconditions: dict, *, reviewer: str, reason: str) -> None:
    if not preconditions["schema_valid"]:
        raise ValueError("canonical promotion requires schema_valid=true")
    if not preconditions["quote_grounded"]:
        raise ValueError("canonical promotion requires quote_grounded=true")
    if not reviewer.strip():
        raise ValueError("canonical promotion requires reviewer")
    if not reason.strip():
        raise ValueError("canonical promotion requires reason")
