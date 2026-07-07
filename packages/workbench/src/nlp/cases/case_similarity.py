from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from nlp.cases.case_registry import CaseProfile, CaseRegistry, STRUCTURAL_VARIABLES
from nlp.embeddings.embedder import DEFAULT_MODEL, Embedder
from nlp.embeddings.vector_store import VectorStore

if TYPE_CHECKING:
    from ml.graph_embed import GraphEmbedder
    from nlp.narrative.graph_builder import StructuralGraph


class CaseSimilarityResult(BaseModel):
    case_id: str
    case_name: str
    score: float
    variable_overlap: dict[str, float] = Field(default_factory=dict)
    shared_tags: list[str] = Field(default_factory=list)
    shared_patterns: list[str] = Field(default_factory=list)
    narrative_match: str = ""
    graph_score: float | None = None  # structural graph similarity, when available


class CaseSimilarityEngine:
    """Multi-dimensional case similarity engine.

    Computes similarity between a new event and the canonical case library
    using up to four overlapping signals:

    1. Variable vector cosine similarity (structural alignment)
    2. Tag/pattern overlap (categorical match)
    3. Text embedding similarity (semantic proximity, optional)
    4. Graph structural similarity via Node2Vec/SVD embeddings (optional)

    The final score is a weighted blend of all available signals.
    When a ``graph_embedder`` is supplied and per-case graphs are provided to
    ``find_similar``, the graph weight is carved out of the other three weights
    proportionally so that all weights still sum to 1.
    """

    def __init__(
        self,
        registry: CaseRegistry,
        *,
        embedder: Embedder | None = None,
        graph_embedder: "GraphEmbedder | None" = None,
        variable_weight: float = 0.45,
        tag_weight: float = 0.25,
        text_weight: float = 0.30,
        graph_weight: float = 0.15,
    ) -> None:
        self.registry = registry
        self.embedder = embedder or Embedder()
        self.graph_embedder = graph_embedder
        self.variable_weight = variable_weight
        self.tag_weight = tag_weight
        self.text_weight = text_weight
        self.graph_weight = graph_weight

    def find_similar(
        self,
        *,
        variable_vector: dict[str, float],
        tags: list[str] | None = None,
        event_patterns: list[str] | None = None,
        event_text: str = "",
        query_graph: "StructuralGraph | None" = None,
        case_graphs: "dict[str, StructuralGraph] | None" = None,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[CaseSimilarityResult]:
        """Find the most structurally similar historical cases.

        Parameters
        ----------
        variable_vector:
            S-A-L-V-P-tau intensity profile for the query event.
        tags / event_patterns:
            Categorical descriptors for the query event.
        event_text:
            Free-text narrative for semantic similarity (requires embedder).
        query_graph:
            ``StructuralGraph`` for the query event. Activates the graph signal
            when combined with ``case_graphs`` and a ``graph_embedder``.
        case_graphs:
            Pre-built ``StructuralGraph`` objects keyed by ``case_id``. Only
            used when both ``query_graph`` and ``self.graph_embedder`` are set.
        top_k / min_score:
            Result filtering.
        """
        tags = tags or []
        event_patterns = event_patterns or []
        use_graph = (
            self.graph_embedder is not None
            and query_graph is not None
            and bool(case_graphs)
        )
        results: list[CaseSimilarityResult] = []

        for case_id, profile in self.registry._cases.items():
            var_score = _cosine_similarity(
                _vector_to_list(variable_vector),
                _vector_to_list(profile.variable_vector),
            )
            tag_score = _jaccard_similarity(
                set(tags) | set(event_patterns),
                set(profile.tags) | set(profile.event_patterns),
            )
            text_score = 0.0
            if event_text.strip():
                text_score = self._text_similarity(event_text, profile.narrative_summary)

            graph_score: float | None = None
            if use_graph and case_id in (case_graphs or {}):
                try:
                    graph_score = self.graph_embedder.graph_similarity(  # type: ignore[union-attr]
                        query_graph, case_graphs[case_id]  # type: ignore[index]
                    )
                except Exception:
                    graph_score = None

            combined = _blend(
                var_score=var_score,
                tag_score=tag_score,
                text_score=text_score,
                graph_score=graph_score,
                variable_weight=self.variable_weight,
                tag_weight=self.tag_weight,
                text_weight=self.text_weight,
                graph_weight=self.graph_weight,
            )
            if combined < min_score:
                continue

            shared_tags = [t for t in tags if t in profile.tags]
            shared_patterns = [p for p in event_patterns if p in profile.event_patterns]
            var_overlap = {
                v: min(variable_vector.get(v, 0.0), profile.variable_vector.get(v, 0.0))
                for v in STRUCTURAL_VARIABLES
            }
            signals = f"var={var_score:.2f} tag={tag_score:.2f} text={text_score:.2f}"
            if graph_score is not None:
                signals += f" graph={graph_score:.2f}"

            results.append(
                CaseSimilarityResult(
                    case_id=case_id,
                    case_name=profile.case_name,
                    score=round(combined, 4),
                    variable_overlap=var_overlap,
                    shared_tags=shared_tags,
                    shared_patterns=shared_patterns,
                    narrative_match=signals,
                    graph_score=graph_score,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _text_similarity(self, text_a: str, text_b: str) -> float:
        if not text_b.strip():
            return 0.0
        try:
            vecs = self.embedder.embed([text_a[:2000], text_b[:2000]])
            return float(_cosine_similarity(vecs[0], vecs[1]))
        except Exception:
            return 0.0


def compute_case_similarity(
    *,
    variable_vector: dict[str, float],
    tags: list[str] | None = None,
    event_patterns: list[str] | None = None,
    event_text: str = "",
    registry: CaseRegistry | None = None,
    top_k: int = 5,
) -> list[CaseSimilarityResult]:
    if registry is None:
        registry = CaseRegistry()
        registry.load()
    engine = CaseSimilarityEngine(registry)
    return engine.find_similar(
        variable_vector=variable_vector,
        tags=tags,
        event_patterns=event_patterns,
        event_text=event_text,
        top_k=top_k,
    )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(ai * bi for ai, bi in zip(a, b))
    norm_a = sum(ai * ai for ai in a) ** 0.5
    norm_b = sum(bi * bi for bi in b) ** 0.5
    denom = norm_a * norm_b
    if denom < 1e-10:
        return 0.0
    return max(0.0, min(1.0, dot / denom))


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _vector_to_list(vec: dict[str, float]) -> list[float]:
    return [vec.get(v, 0.0) for v in STRUCTURAL_VARIABLES]


def _blend(
    *,
    var_score: float,
    tag_score: float,
    text_score: float,
    graph_score: float | None,
    variable_weight: float,
    tag_weight: float,
    text_weight: float,
    graph_weight: float,
) -> float:
    """Blend signal scores into a single [0, 1] similarity value.

    When ``graph_score`` is available the graph weight is carved out of the
    other three weights proportionally, keeping the total at 1.0.
    """
    if graph_score is not None:
        scale = 1.0 - graph_weight
        return (
            variable_weight * var_score * scale
            + tag_weight * tag_score * scale
            + text_weight * text_score * scale
            + graph_weight * graph_score
        )
    return (
        variable_weight * var_score
        + tag_weight * tag_score
        + text_weight * text_score
    )
