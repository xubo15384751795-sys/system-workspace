"""Enhanced similarity engine with keyword + mechanism matching.

Wraps the existing CaseSimilarityEngine and adds structural keyword
similarity and mechanism-type matching on top of variable vector +
tag matching.

Usage:
    from nlp.caselab.enhanced_similarity import EnhancedSimilarityEngine

    engine = EnhancedSimilarityEngine("/Users/a1/Paper")
    results = engine.find_similar(
        variable_vector={...},
        tags=[...],
        event_text="funding liquidity spiral collateral leverage...",
        mechanism_context={"mechanism_types": ["anchor_drift", "funding_path_stress"]},
        top_k=10,
    )
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from nlp.caselab.text_match import (
    extract_structural_keywords,
    keyword_cosine_similarity,
    top_shared_concepts,
)
from nlp.cases.case_registry import CaseProfile, CaseRegistry
from nlp.cases.case_similarity import CaseSimilarityEngine, CaseSimilarityResult



# ── Mechanism type definitions ──────────────────────────────────────────
# Each mechanism type has: required concepts, optional concepts, and
# structural vector signatures that indicate the mechanism.

MECHANISM_TYPES: dict[str, dict[str, Any]] = {
    "anchor_drift": {
        "description": "M anchor geometry drifting from fundamental value",
        "required_concepts": ["stress", "valuation", "dislocation"],
        "vector_signature": {"S": (0.3, 1.0), "P": (0.3, 1.0)},
        "case_patterns": ["anchor", "valuation", "mispricing", "fundamental"],
    },
    "funding_path_stress": {
        "description": "Funding/lubricity path under stress",
        "required_concepts": ["liquidity", "leverage", "repo"],
        "vector_signature": {"S": (0.3, 1.0), "L": (0.3, 1.0), "tau": (0.2, 1.0)},
        "case_patterns": ["funding", "liquidity", "repo", "spiral"],
    },
    "liquidity_compression": {
        "description": "Volatility compression masking underlying stress",
        "required_concepts": ["compression", "volatility"],
        "vector_signature": {"V": (0.0, 0.4), "S": (0.0, 0.5)},
        "case_patterns": ["compression", "low vol", "calm", "quiet"],
    },
    "leverage_unwind": {
        "description": "Leverage positions being unwound",
        "required_concepts": ["leverage", "forced_selling"],
        "vector_signature": {"L": (0.3, 1.0), "S": (0.2, 1.0)},
        "case_patterns": ["leverage", "unwind", "deleverage", "forced"],
    },
    "volatility_regime_mismatch": {
        "description": "HMM regime and structural signals disagree",
        "required_concepts": ["volatility"],
        "vector_signature": {"V": (0.0, 1.0)},
        "case_patterns": ["divergence", "mismatch", "conflict", "regime"],
    },
    "relief_decompression": {
        "description": "Stress relief with volatility decompression",
        "required_concepts": ["relief", "decompression"],
        "vector_signature": {"S": (0.0, 0.4), "V": (0.0, 0.4)},
        "case_patterns": ["relief", "recovery", "stabilization", "easing"],
    },
    "cross_market_contagion": {
        "description": "Cross-market stress transmission",
        "required_concepts": ["contagion", "correlation"],
        "vector_signature": {"L": (0.3, 1.0), "A": (0.3, 1.0)},
        "case_patterns": ["contagion", "spillover", "cross-market"],
    },
    "policy_delay_stress": {
        "description": "Policy response delay creating time pressure",
        "required_concepts": ["policy"],
        "vector_signature": {"tau": (0.4, 1.0), "S": (0.2, 1.0)},
        "case_patterns": ["policy", "delay", "regulation", "intervention"],
    },
}


@dataclass
class EnhancedResult:
    """Similarity result with text matching breakdown."""
    case_id: str
    case_name: str
    score: float
    var_score: float = 0.0
    tag_score: float = 0.0
    text_score: float = 0.0
    mechanism_score: float = 0.0
    matched_mechanisms: list[str] = field(default_factory=list)
    shared_tags: list[str] = field(default_factory=list)
    shared_concepts: list[tuple[str, float]] = field(default_factory=list)
    narrative_summary: str = ""


class EnhancedSimilarityEngine:
    """CaseSimilarityEngine + structural keyword text + mechanism matching.

    Blends four signals:
    1. Variable vector cosine (S-A-L-V-P-tau) — 25%
    2. Tag/pattern Jaccard overlap — 5%
    3. Structural keyword cosine (Chinese/English text) — 15%
    4. Mechanism type matching — 55%

    Weights favor mechanism matching because mechanism similarity is a
    stronger structural signal than keyword overlap for analogy quality.
    Keyword matching can return 0.0 when cases are in different domains
    (e.g. AI regulation vs financial stress) despite structural similarity.
    """

    def __init__(
        self,
        vault_path: str | Path,
        *,
        var_weight: float = 0.25,
        tag_weight: float = 0.05,
        keyword_weight: float = 0.15,
        mechanism_weight: float = 0.55,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.var_weight = var_weight
        self.tag_weight = tag_weight
        self.keyword_weight = keyword_weight
        self.mechanism_weight = mechanism_weight

        # Load registry
        self.registry = CaseRegistry(
            case_dir=self.vault_path / "Data" / "nlp" / "caselab_library"
            if not (self.vault_path / "01_Cases").exists()
            else self.vault_path / "Data" / "nlp" / "caselab_library"
        )
        self.registry.load()

        # Precompute keyword vectors for all cases
        self._case_keywords: dict[str, str] = {}
        for case_id, profile in self.registry._cases.items():
            text_parts = [
                profile.narrative_summary,
                " ".join(profile.tags),
                " ".join(profile.event_patterns),
            ]
            self._case_keywords[case_id] = " ".join(text_parts)

        # Base engine for variable + tag similarity
        self._base_engine = CaseSimilarityEngine(self.registry)

    def find_similar(
        self,
        *,
        variable_vector: dict[str, float],
        tags: list[str] | None = None,
        event_text: str = "",
        mechanism_context: dict[str, Any] | None = None,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[EnhancedResult]:
        """Find most similar cases using all available signals.

        Parameters
        ----------
        mechanism_context : dict, optional
            Context packet with mechanism types, e.g.:
            {"mechanism_types": ["anchor_drift", "funding_path_stress"],
             "context_description": "..."}
        """
        tags = tags or []
        results: list[EnhancedResult] = []
        query_mechanisms = set((mechanism_context or {}).get("mechanism_types", []))

        for case_id, profile in self.registry._cases.items():
            # Signal 1: variable vector cosine
            var_score = self._var_similarity(variable_vector, profile.variable_vector)

            # Signal 2: tag Jaccard
            query_tags = set(tags)
            case_tags = set(profile.tags) | set(profile.event_patterns)
            tag_score = self._jaccard(query_tags, case_tags)

            # Signal 3: keyword text similarity
            text_score = 0.0
            shared_concepts: list[tuple[str, float]] = []
            if event_text.strip():
                case_text = self._case_keywords.get(case_id, "")
                if case_text:
                    text_score = keyword_cosine_similarity(event_text, case_text)
                    shared_concepts = top_shared_concepts(event_text, case_text, 5)

            # Signal 4: mechanism type matching
            mechanism_score = 0.0
            matched_mechanisms: list[str] = []
            if query_mechanisms:
                mechanism_score, matched_mechanisms = self._mechanism_similarity(
                    variable_vector, query_mechanisms, profile, case_tags
                )

            # Blend
            combined = (
                self.var_weight * var_score
                + self.tag_weight * tag_score
                + self.keyword_weight * text_score
                + self.mechanism_weight * mechanism_score
            )

            if combined >= min_score:
                results.append(EnhancedResult(
                    case_id=case_id,
                    case_name=profile.case_name,
                    score=round(combined, 4),
                    var_score=round(var_score, 4),
                    tag_score=round(tag_score, 4),
                    text_score=round(text_score, 4),
                    mechanism_score=round(mechanism_score, 4),
                    matched_mechanisms=matched_mechanisms,
                    shared_tags=sorted(query_tags & case_tags),
                    shared_concepts=shared_concepts,
                    narrative_summary=profile.narrative_summary[:200],
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _mechanism_similarity(
        query_vector: dict[str, float],
        query_mechanisms: set[str],
        profile: CaseProfile,
        case_tags: set[str],
    ) -> tuple[float, list[str]]:
        """Score mechanism-type similarity between query and case.

        Two-pronged matching:
        1. Pattern keyword overlap with mechanism case patterns
        2. Vector signature match (does the case vector fall in the
           mechanism's expected range?)

        Returns (score, matched_mechanism_names).
        """
        if not query_mechanisms:
            return 0.0, []

        scores = []
        matched = []

        for mech_name in query_mechanisms:
            mech = MECHANISM_TYPES.get(mech_name)
            if not mech:
                continue

            # Pattern overlap: case tags vs mechanism patterns
            mech_patterns = set(mech.get("case_patterns", []))
            pattern_overlap = len(case_tags & mech_patterns)
            pattern_score = min(1.0, pattern_overlap / max(len(mech_patterns), 1))

            # Vector signature match: check if case vector falls in expected range
            sig = mech.get("vector_signature", {})
            sig_matches = 0
            sig_total = len(sig)
            case_vec = profile.variable_vector or {}
            for dim, (lo, hi) in sig.items():
                val = case_vec.get(dim, 0.5)
                if lo <= val <= hi:
                    sig_matches += 1
            sig_score = sig_matches / max(sig_total, 1)

            # Combined mechanism score for this type
            mech_score = 0.4 * pattern_score + 0.6 * sig_score
            scores.append(mech_score)
            if mech_score > 0.3:
                matched.append(mech_name)

        if not scores:
            return 0.0, []

        # Return the best mechanism match
        best_score = max(scores)
        return best_score, matched

    @staticmethod
    def _var_similarity(a: dict[str, float], b: dict[str, float]) -> float:
        keys = sorted(set(a) | set(b))
        va = np.array([a.get(k, 0) for k in keys], dtype=float)
        vb = np.array([b.get(k, 0) for k in keys], dtype=float)
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na < 1e-8 or nb < 1e-8:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))

    @staticmethod
    def _jaccard(a: set[str], b: set[str]) -> float:
        if not a and not b:
            return 0.0
        return len(a & b) / len(a | b)
