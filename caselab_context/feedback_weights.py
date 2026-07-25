"""Feedback-driven retrieval adjustments from context review log."""
from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

FEEDBACK_LOG = Path(__file__).resolve().parent / "feedback_log.jsonl"

ACCEPTED_BOOST = 0.08
REJECTED_PENALTY = -0.12


@lru_cache(maxsize=1)
def load_feedback_title_weights() -> dict[str, float]:
    if not FEEDBACK_LOG.exists():
        return {}
    weights: dict[str, float] = defaultdict(float)
    for line in FEEDBACK_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = str(entry.get("review_status") or "")
        meaning = entry.get("contextual_meaning") or {}
        titles = meaning.get("historical_analogies") or []
        for title in titles:
            key = str(title).strip().lower()
            if not key:
                continue
            if status == "accepted":
                weights[key] += ACCEPTED_BOOST
            elif status == "rejected":
                weights[key] += REJECTED_PENALTY
    return dict(weights)


def feedback_boost(title: str) -> float:
    return load_feedback_title_weights().get(title.strip().lower(), 0.0)
