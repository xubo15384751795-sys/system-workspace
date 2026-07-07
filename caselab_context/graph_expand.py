"""Graph-aware expansion for retrieval candidates."""
from __future__ import annotations

from typing import Any

from caselab_context.graph_core import CHAIN_RELATIONS, n_hop_neighbors


def expand_with_graph(
    results: list[dict[str, Any]],
    graph: dict[str, Any],
    docs: list[dict[str, Any]],
    *,
    max_hops: int = 2,
    hop_decay: float = 0.7,
    max_neighbors_per_hop: int = 4,
    chain_bonus: float = 0.02,
) -> list[dict[str, Any]]:
    if not results or not graph:
        return results

    doc_by_id = {doc["id"]: doc for doc in docs}
    merged: dict[str, dict[str, Any]] = {}
    for item in results:
        merged[item["id"]] = dict(item)

    for item in results:
        parent_score = float(item.get("score") or 0.0)
        if parent_score <= 0:
            continue
        neighbors = n_hop_neighbors(
            graph,
            item["id"],
            max_hops=max_hops,
            max_per_hop=max_neighbors_per_hop,
        )
        for neighbor in neighbors:
            neighbor_doc = doc_by_id.get(neighbor["id"])
            if neighbor_doc is None:
                continue
            hop = int(neighbor.get("hop") or 1)
            bonus = round(parent_score * (hop_decay**hop), 4)
            if neighbor.get("chain_link") and neighbor.get("relation") in CHAIN_RELATIONS:
                bonus = round(bonus + chain_bonus, 4)
            existing = merged.get(neighbor["id"])
            enriched = {
                **neighbor_doc,
                "score": bonus,
                "graph_boost": True,
                "graph_from": neighbor.get("from") or item["id"],
                "graph_relation": neighbor.get("relation"),
                "graph_hop": hop,
            }
            if existing is None or bonus > float(existing.get("score") or 0.0):
                merged[neighbor["id"]] = enriched

    rescored = sorted(merged.values(), key=lambda row: float(row.get("score") or 0.0), reverse=True)
    return rescored
