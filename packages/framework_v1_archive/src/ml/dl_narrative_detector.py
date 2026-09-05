from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np

from src.core.interfaces import NarrativeDetectorInterface
from src.core.models import NarrativeReading
from src.ml.ml_narrative import SentenceTransformerDetector


def _sentence_transformers_available() -> bool:
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401

        return True
    except Exception:
        return False


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


_AI_PROTOTYPES = [
    "AI startup overvaluation and burn rate concerns",
    "tech unicorn compression risk and stretched multiples",
    "venture-backed growth names trading on narrative not cash flows",
    "artificial intelligence hype cycle and crowded positioning",
    "private market marks disconnected from public comparables",
]

_CLO_PROTOTYPES = [
    "CLO and CMBS spread widening on heavy supply",
    "structured credit mezzanine losses and downgrade waves",
    "commercial real estate refinancing cliff and special servicing",
    "ABS market liquidity gaps and dealer balance sheet strain",
    "credit tranche correlation shock and correlation smile moves",
]

_POLICY_PROTOTYPES = [
    "central bank tightening and financial conditions impulse",
    "policy intervention risk and regulatory clampdown",
    "fiscal dominance and political pressure on the central bank",
    "macroprudential tightening and credit guidance",
    "liquidity facility usage and emergency policy backstop",
]


@dataclass
class PrototypeEmbeddingNarrativeDetector(NarrativeDetectorInterface):
    """Prototype embeddings via sentence-transformers with keyword fallback."""

    model_name: str = "all-MiniLM-L6-v2"
    _model: object | None = field(default=None, repr=False)
    _proto_ai: np.ndarray | None = field(default=None, repr=False)
    _proto_clo: np.ndarray | None = field(default=None, repr=False)
    _proto_pol: np.ndarray | None = field(default=None, repr=False)
    _fallback: SentenceTransformerDetector | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if _sentence_transformers_available():
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            self._proto_ai = self._encode_mean(_AI_PROTOTYPES)
            self._proto_clo = self._encode_mean(_CLO_PROTOTYPES)
            self._proto_pol = self._encode_mean(_POLICY_PROTOTYPES)
        else:
            self._fallback = SentenceTransformerDetector()

    def _encode_mean(self, sentences: list[str]) -> np.ndarray:
        assert self._model is not None
        model = cast(Any, self._model)
        vecs = model.encode(sentences, convert_to_numpy=True, show_progress_bar=False)
        return cast(np.ndarray, np.asarray(vecs, dtype=np.float64).mean(axis=0))

    def analyze(self, texts: list[dict], run_date: str) -> NarrativeReading:
        if self._fallback is not None:
            return self._fallback.analyze(texts, run_date)

        blob = " ".join(str(item.get("text", "")) for item in texts)
        if not blob.strip():
            return NarrativeReading(
                run_date=run_date,
                ai_unicorn="ANCHORED",
                clo_cmbs="ANCHORED",
                policy="ANCHORED",
                drift_scores={"ai_unicorn": 0.0, "clo_cmbs": 0.0, "policy": 0.0},
            )

        assert self._model is not None
        assert self._proto_ai is not None and self._proto_clo is not None and self._proto_pol is not None
        model = cast(Any, self._model)
        emb = np.asarray(
            model.encode([blob], convert_to_numpy=True, show_progress_bar=False)[0],
            dtype=np.float64,
        )
        s_ai = _cosine(emb, self._proto_ai)
        s_clo = _cosine(emb, self._proto_clo)
        s_pol = _cosine(emb, self._proto_pol)

        return NarrativeReading(
            run_date=run_date,
            ai_unicorn=self._label(s_ai),
            clo_cmbs=self._label(s_clo),
            policy=self._label(s_pol),
            drift_scores={
                "ai_unicorn": float(max(0.0, min(1.0, s_ai))),
                "clo_cmbs": float(max(0.0, min(1.0, s_clo))),
                "policy": float(max(0.0, min(1.0, s_pol))),
            },
        )

    def _label(self, score: float) -> str:
        if score >= 0.55:
            return "COMPRESSION_ILLUSION"
        if score >= 0.30:
            return "DRIFTING"
        return "ANCHORED"
