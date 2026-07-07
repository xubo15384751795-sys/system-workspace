from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from nlp.evaluation.golden_set import GoldenQuery, read_golden_queries
from nlp.embeddings.semantic_search import SearchResult


@dataclass
class RetrievalEvalReport:
    total_queries: int = 0
    top_k_recall_at_5: float = 0.0
    top_k_recall_at_10: float = 0.0
    mean_reciprocal_rank: float = 0.0
    mean_average_precision: float = 0.0
    noise_ratio: float = 0.0
    per_query_details: list[dict] = field(default_factory=list)
    summary: str = ""


def evaluate_retrieval(
    search_results: dict[str, list[SearchResult]],
    *,
    golden_queries: list[GoldenQuery] | None = None,
    eval_dir: Path | None = None,
) -> RetrievalEvalReport:
    """Evaluate semantic search against golden queries.

    search_results is a dict mapping query_text -> list of SearchResult from the engine.
    """
    if golden_queries is None:
        golden_queries = read_golden_queries(eval_dir=eval_dir)

    if not golden_queries:
        return RetrievalEvalReport(summary="No golden queries available.")

    report = RetrievalEvalReport(total_queries=len(golden_queries))
    total_recall_5 = 0.0
    total_recall_10 = 0.0
    total_mrr = 0.0
    total_map = 0.0
    total_noise = 0.0
    matched = 0

    for gq in golden_queries:
        results = search_results.get(gq.query_text, [])
        if not results:
            report.per_query_details.append({
                "query_id": gq.query_id,
                "query_text": gq.query_text,
                "results_found": 0,
                "top_k_recall_5": 0.0,
                "top_k_recall_10": 0.0,
                "mrr": 0.0,
                "map": 0.0,
                "noise_ratio": 0.0,
            })
            continue

        matched += 1
        expected = set(gq.expected_chunk_ids)

        k5 = results[:5]
        k10 = results[:10]
        recall_5 = len(set(r.chunk_id for r in k5) & expected) / max(1, len(expected))
        recall_10 = len(set(r.chunk_id for r in k10) & expected) / max(1, len(expected))

        mrr = 0.0
        for rank, r in enumerate(results, 1):
            if r.chunk_id in expected:
                mrr = 1.0 / rank
                break

        ap = 0.0
        hits = 0
        for rank, r in enumerate(results, 1):
            if r.chunk_id in expected:
                hits += 1
                ap += hits / rank
        map_val = ap / max(1, len(expected))

        noise = 1.0 - (len(set(r.chunk_id for r in results[:10]) & expected) / max(1, len(set(r.chunk_id for r in results[:10]))))

        total_recall_5 += recall_5
        total_recall_10 += recall_10
        total_mrr += mrr
        total_map += map_val
        total_noise += noise

        report.per_query_details.append({
            "query_id": gq.query_id,
            "query_text": gq.query_text[:120],
            "results_found": len(results),
            "top_k_recall_5": round(recall_5, 4),
            "top_k_recall_10": round(recall_10, 4),
            "mrr": round(mrr, 4),
            "map": round(map_val, 4),
            "noise_ratio": round(noise, 4),
        })

    n = max(1, matched)
    report.top_k_recall_at_5 = round(total_recall_5 / n, 4)
    report.top_k_recall_at_10 = round(total_recall_10 / n, 4)
    report.mean_reciprocal_rank = round(total_mrr / n, 4)
    report.mean_average_precision = round(total_map / n, 4)
    report.noise_ratio = round(total_noise / n, 4)
    report.summary = (
        f"Recall@5={report.top_k_recall_at_5:.3f}, "
        f"Recall@10={report.top_k_recall_at_10:.3f}, "
        f"MRR={report.mean_reciprocal_rank:.3f}, "
        f"MAP={report.mean_average_precision:.3f}, "
        f"Noise={report.noise_ratio:.3f}"
    )
    return report
