#!/usr/bin/env python3
"""Pending Evaluation — write evaluation records for feedback loop.

Every judgment and trade decision writes a record to
Output/evaluations/pending.jsonl so that future windows (1d/1w/1m)
can evaluate whether the system's predictions were correct.

Usage:
    from pending_evaluation import write_pending_evaluation

Output:
    Output/evaluations/pending.jsonl  — append-only evaluation queue
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "Output" / "evaluations"
PENDING_PATH = EVAL_DIR / "pending.jsonl"


def _make_eval_id(source: str, date_str: str, timestamp: str) -> str:
    """Deterministic eval_id from source + date + timestamp."""
    raw = f"{source}:{date_str}:{timestamp}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"eval_{date_str}_{short_hash}"


def _compute_eval_windows(date_str: str) -> dict[str, str]:
    """Compute evaluation window dates (1d, 1w, 1m)."""
    try:
        base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        base = datetime.now(UTC)
    return {
        "eval_after_1d": (base + timedelta(days=1)).strftime("%Y-%m-%d"),
        "eval_after_1w": (base + timedelta(weeks=1)).strftime("%Y-%m-%d"),
        "eval_after_1m": (base + timedelta(days=30)).strftime("%Y-%m-%d"),
    }


def write_pending_evaluation(
    source: str,
    card: dict[str, Any],
) -> Path:
    """Append a pending evaluation record to the JSONL queue.

    Args:
        source: "judgment_layer" or "trade_decision_layer"
        card: the judgment card or trade decision dict

    Returns:
        Path to the pending.jsonl file
    """
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    date_str = card.get("date") or card.get("as_of") or datetime.now(UTC).strftime("%Y-%m-%d")
    timestamp = card.get("generated_at", datetime.now(UTC).isoformat())
    decision = card.get("decision", "UNKNOWN")
    confidence = card.get("confidence", "unknown")
    # confidence may be a dict (judgment) or string (trade decision)
    if isinstance(confidence, dict):
        confidence = confidence.get("level", "unknown")

    eval_id = _make_eval_id(source, date_str, timestamp)
    windows = _compute_eval_windows(date_str)

    record = {
        "eval_id": eval_id,
        "source": source,
        "date": date_str,
        "decision": decision,
        "confidence": confidence,
        "generated_at": timestamp,
        **windows,
        "status": "pending",
        "evaluations": {
            "1d": None,
            "1w": None,
            "1m": None,
        },
    }

    with PENDING_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return PENDING_PATH
