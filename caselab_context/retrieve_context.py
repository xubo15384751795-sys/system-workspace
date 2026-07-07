"""Retrieve similar Paper notes for a context query with reranking."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from caselab_context.embeddings_core import load_embeddings, search
from caselab_context.graph_expand import expand_with_graph
from caselab_context.quality_weights import quality_bonus

EMBEDDINGS_PATH = Path(__file__).resolve().parents[1] / "Data" / "caselab_context" / "embeddings.json"

_TOKEN = re.compile(r"[a-z0-9_]{2,}")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def _rerank(
    results: list[dict],
    actor: str = "",
    verb: str = "",
    obj: str = "",
    risk_from: str = "",
    risk_to: str = "",
) -> list[dict]:
    """Boost results that match actor, action, or risk transfer terms.

    Ranking signals (additive on top of retrieval score):
      +0.15  actor name appears in title or text
      +0.10  verb appears in title or text
      +0.05  object token appears in title or text
      +0.10  risk_transfer terms overlap with text
      +0.05  graph-expanded neighbor
      +0.03  ontology chain link (exhibits/defines/observed_by)
      +quality boost from note quality metadata
      -0.05  only surface object match, no actor (penalize noise)
    """
    if not results:
        return results

    actor_tok = _tokens(actor)
    verb_tok = _tokens(verb)
    obj_tok = _tokens(obj)
    risk_tok = _tokens(risk_from) | _tokens(risk_to)

    rescored: list[tuple[float, dict]] = []
    for item in results:
        base = item["score"]
        title_lower = (item.get("title") or "").lower()
        text_lower = (item.get("text") or "").lower()
        combined = title_lower + " " + text_lower

        bonus = 0.0

        actor_hit = any(t in combined for t in actor_tok if len(t) > 2)
        if actor_hit:
            bonus += 0.15

        if any(t in combined for t in verb_tok if len(t) > 2):
            bonus += 0.10

        obj_hit = any(t in combined for t in obj_tok if len(t) > 2)
        if obj_hit:
            bonus += 0.05

        if risk_tok and any(t in combined for t in risk_tok if len(t) > 3):
            bonus += 0.10

        if item.get("graph_boost"):
            bonus += 0.05
            if int(item.get("graph_hop") or 1) == 2:
                bonus += 0.02
            if item.get("graph_relation") in {"exhibits", "defines", "observed_by", "feeds"}:
                bonus += 0.03

        bonus += quality_bonus(item.get("quality"))

        if obj_hit and not actor_hit:
            bonus -= 0.05

        rescored.append((base + bonus, item))

    rescored.sort(key=lambda x: x[0], reverse=True)
    for score, item in rescored:
        item["score"] = round(score, 4)
    return [item for _, item in rescored]


def retrieve_similar(query: str, top_k: int = 5) -> list[dict]:
    if not EMBEDDINGS_PATH.exists():
        return []
    payload = load_embeddings(EMBEDDINGS_PATH)
    results = search(payload, query, top_k=top_k * 3)
    graph = payload.get("graph")
    docs = payload.get("docs") or []
    if graph and docs:
        results = expand_with_graph(results, graph, docs, max_hops=2)
    return results[: top_k * 3]


def retrieve_similar_reranked(
    query: str,
    top_k: int = 5,
    actor: str = "",
    verb: str = "",
    obj: str = "",
    risk_from: str = "",
    risk_to: str = "",
) -> list[dict]:
    """Retrieve with hybrid/dense/sparse search, graph expansion, then rerank."""
    raw = retrieve_similar(query, top_k=top_k)
    return _rerank(raw, actor=actor, verb=verb, obj=obj, risk_from=risk_from, risk_to=risk_to)[:top_k]


def merge_similar_into_packet(packet: dict, query: str, top_k: int = 5) -> dict:
    ctx = packet.setdefault("context_packet", packet)
    actor = ctx.get("actor", "")
    action = ctx.get("action") or {}
    verb = action.get("verb", "")
    obj = action.get("object", "")
    meaning = ctx.get("contextual_meaning") or {}
    rt = meaning.get("risk_transfer") or {}
    risk_from = rt.get("from", "")
    risk_to = rt.get("to", "")

    similar = retrieve_similar_reranked(
        query,
        top_k=top_k,
        actor=actor,
        verb=verb,
        obj=obj,
        risk_from=risk_from,
        risk_to=risk_to,
    )
    ctx["similar_notes"] = similar
    analogies = list(meaning.get("historical_analogies") or [])
    for item in similar:
        title = item.get("title")
        if title and title not in analogies:
            analogies.append(title)
    meaning["historical_analogies"] = analogies[: top_k + 3]
    return packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrieve similar Paper notes.")
    parser.add_argument("query")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = retrieve_similar(args.query, top_k=args.top)[: args.top]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    for item in results:
        suffix = ""
        if item.get("graph_boost"):
            suffix = f" [graph:{item.get('graph_relation')}]"
        print(f"{item['score']:.3f} {item['title']} ({item['id']}){suffix}")


if __name__ == "__main__":
    main()
