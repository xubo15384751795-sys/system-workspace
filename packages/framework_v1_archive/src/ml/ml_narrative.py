from __future__ import annotations

from dataclasses import dataclass

from src.core.interfaces import NarrativeDetectorInterface
from src.core.models import NarrativeReading


@dataclass
class SentenceTransformerDetector(NarrativeDetectorInterface):
    def analyze(self, texts: list[dict], run_date: str) -> NarrativeReading:
        payload = " ".join(str(item.get("text", "")) for item in texts).lower()
        ai_score = self._score(payload, ["ai", "unicorn", "valuation", "burn"])
        clo_score = self._score(payload, ["clo", "cmbs", "spread", "downgrade"])
        policy_score = self._score(payload, ["policy", "fed", "tightening", "intervention"])

        return NarrativeReading(
            run_date=run_date,
            ai_unicorn=self._label(ai_score),
            clo_cmbs=self._label(clo_score),
            policy=self._label(policy_score),
            drift_scores={
                "ai_unicorn": ai_score,
                "clo_cmbs": clo_score,
                "policy": policy_score,
            },
        )

    def _score(self, text: str, keywords: list[str]) -> float:
        if not text:
            return 0.0
        matches = sum(1 for key in keywords if key in text)
        return float(matches) / float(len(keywords))

    def _label(self, score: float) -> str:
        if score >= 0.6:
            return "COMPRESSION_ILLUSION"
        if score >= 0.25:
            return "DRIFTING"
        return "ANCHORED"
