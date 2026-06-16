"""Retrieve similar Paper notes for a context query with reranking."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from caselab_context.embeddings_core import load_embeddings, search

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

    Ranking signals (additive on top of TF-IDF score):
      +0.15  actor name appears in title or text
      +0.10  verb appears in title or text
      +0.05  object token appears in title or text
      +0.10  risk_transfer terms overlap with text
      +0.05  same note type layer (case vs entity vs model)
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
        note_tags = set(item.get("tags") or [])

        bonus = 0.0

        # Actor match (strongest signal)
        actor_hit = any(t in combined for t in actor_tok if len(t) > 2)
        if actor_hit:
            bonus += 0.15

        # Verb match
        if any(t in combined for t in verb_tok if len(t) > 2):
            bonus += 0.10

        # Object token match
        obj_hit = any(t in combined for t in obj_tok if len(t) > 2)
        if obj_hit:
            bonus += 0.05

        # Risk transfer term overlap
        if risk_tok and any(t in combined for t in risk_tok if len(t) > 3):
            bonus += 0.10

        # Penalize surface-only object match without actor
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
    return search(payload, query, top_k=top_k)


def retrieve_similar_reranked(
    query: str,
    top_k: int = 5,
    actor: str = "",
    verb: str = "",
    obj: str = "",
    risk_from: str = "",
    risk_to: str = "",
) -> list[dict]:
    """Retrieve with TF-IDF then rerank by structural signals."""
    # Get more candidates than needed for reranking
    raw = retrieve_similar(query, top_k=top_k * 3)
    return _rerank(raw, actor=actor, verb=verb, obj=obj, risk_from=risk_from, risk_to=risk_to)[:top_k]


def merge_similar_into_packet(packet: dict, query: str, top_k: int = 5) -> dict:
    ctx = packet.setdefault("context_packet", packet)
    # Extract structural signals from the packet for reranking
    actor = ctx.get("actor", "")
    action = ctx.get("action") or {}
    verb = action.get("verb", "")
    obj = action.get("object", "")
    meaning = ctx.get("contextual_meaning") or {}
    rt = meaning.get("risk_transfer") or {}
    risk_from = rt.get("from", "")
    risk_to = rt.get("to", "")

    similar = retrieve_similar_reranked(
        query, top_k=top_k,
        actor=actor, verb=verb, obj=obj,
        risk_from=risk_from, risk_to=risk_to,
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
    results = retrieve_similar(args.query, top_k=args.top)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    for item in results:
        print(f"{item['score']:.3f} {item['title']} ({item['id']})")


if __name__ == "__main__":
    main()
