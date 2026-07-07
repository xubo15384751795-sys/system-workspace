"""Typed note graph from Paper index records."""
from __future__ import annotations

import re
from typing import Any

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]]*)?\]\]")

RELATION_HINTS: dict[str, str] = {
    "mechanisms": "exhibits",
    "related_mechanisms": "exhibits",
    "related_entities": "participates_in",
    "related_cases": "related",
    "related_models": "feeds",
    "related_variables": "defines",
    "related_indicators": "observed_by",
    "main_entity": "participates_in",
    "aliases": "alias",
}


def _normalize_title(value: str) -> str:
    return re.sub(r"[\s_-]+", " ", value.strip().lower())


def wikilink_targets(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if value.startswith("[[") and value.endswith("]]"):
            inner = value[2:-2].split("#", 1)[0].strip()
            return [inner] if inner else []
        return [m.group(1).strip() for m in WIKILINK_RE.finditer(value)]
    if isinstance(value, list):
        targets: list[str] = []
        for item in value:
            targets.extend(wikilink_targets(item))
        return targets
    return [str(value).strip()] if str(value).strip() else []


def extract_links(meta: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for field, relation in RELATION_HINTS.items():
        if field not in meta:
            continue
        for target in wikilink_targets(meta[field]):
            key = (relation, _normalize_title(target))
            if key in seen:
                continue
            seen.add(key)
            links.append({"target": target, "relation": relation})
    return links


def build_title_index(records: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for doc in records:
        note_id = doc["id"]
        keys = {doc.get("title", ""), doc["id"].rsplit("/", 1)[-1].replace(".md", "")}
        for alias in doc.get("aliases") or []:
            keys.add(str(alias))
        for key in keys:
            normalized = _normalize_title(str(key))
            if normalized:
                index.setdefault(normalized, note_id)
    return index


def build_graph(records: list[dict[str, Any]]) -> dict[str, Any]:
    title_to_id = build_title_index(records)
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for doc in records:
        source_id = doc["id"]
        for link in doc.get("links") or []:
            target_id = title_to_id.get(_normalize_title(link["target"]))
            if not target_id or target_id == source_id:
                continue
            relation = link.get("relation") or "related"
            key = (source_id, target_id, relation)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append({"from": source_id, "to": target_id, "relation": relation})
    return {"edges": edges, "title_to_id": title_to_id}


def one_hop_neighbors(graph: dict[str, Any], node_id: str) -> list[dict[str, str]]:
    edges = graph.get("edges") or []
    out: list[dict[str, str]] = []
    for edge in edges:
        if edge["from"] == node_id:
            out.append({"id": edge["to"], "relation": edge["relation"], "direction": "out"})
        elif edge["to"] == node_id:
            out.append({"id": edge["from"], "relation": edge["relation"], "direction": "in"})
    return out


# Ontology chain relations preferred for world-model traversal.
CHAIN_RELATIONS = frozenset({"exhibits", "defines", "observed_by", "feeds", "participates_in"})


def n_hop_neighbors(
    graph: dict[str, Any],
    node_id: str,
    *,
    max_hops: int = 2,
    max_per_hop: int = 4,
) -> list[dict[str, Any]]:
    if max_hops < 1:
        return []

    seen: set[str] = {node_id}
    found: list[dict[str, Any]] = []
    frontier: list[tuple[str, int]] = [(node_id, 0)]

    while frontier:
        current_id, depth = frontier.pop(0)
        if depth >= max_hops:
            continue
        for neighbor in one_hop_neighbors(graph, current_id)[:max_per_hop]:
            neighbor_id = neighbor["id"]
            if neighbor_id in seen:
                continue
            seen.add(neighbor_id)
            hop = depth + 1
            found.append(
                {
                    "id": neighbor_id,
                    "relation": neighbor["relation"],
                    "direction": neighbor["direction"],
                    "hop": hop,
                    "chain_link": neighbor["relation"] in CHAIN_RELATIONS,
                    "from": current_id,
                }
            )
            if hop < max_hops:
                frontier.append((neighbor_id, hop))
    return found
