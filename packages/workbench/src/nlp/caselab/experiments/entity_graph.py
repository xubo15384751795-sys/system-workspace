"""Entity-mechanism bipartite graph — emergent role discovery.

READS: CaseLab vault (02_Entities, 01_Cases) via adapter
WRITES: Data/nlp/caselab_experiments/ only
DOES NOT modify System code, data, or outputs.

Discovers functional roles of entities based on which mechanisms
they connect to. Entities that connect to similar mechanisms
cluster into emergent functional groups.
"""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
from collections import Counter, defaultdict
from typing import Any

import numpy as np

OUTPUT_DIR = WorkspacePaths.discover().root / "Data" / "nlp" / "caselab_experiments"


def build_entity_mechanism_graph(
    entities: list[dict],
    cases: list[dict],
) -> dict[str, Any]:
    """Build bipartite graph: entity → mechanism connections.

    An entity is connected to a mechanism if:
    1. The entity's related_mechanisms includes it, OR
    2. The entity appears in a case that uses that mechanism
    """
    # Direct connections from entity metadata
    entity_mechs: dict[str, set[str]] = defaultdict(set)
    entity_types: dict[str, str] = {}

    for entity in entities:
        eid = entity.get("entity_id", "")
        entity_types[eid] = entity.get("entity_type", "unknown")
        for m in entity.get("related_mechanisms", []):
            entity_mechs[eid].add(m)

    # Indirect connections from case co-membership
    case_entity_mechs: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for case in cases:
        case_id = case.get("case_id", "")
        mechs = set(case.get("mechanisms", []))
        # Find entities in this case
        for entity_ref in case.get("related_entities", []):
            eid = entity_ref.lower().replace(" ", "_").replace("-", "_")
            case_entity_mechs[case_id][eid] = mechs

    # Merge indirect connections (entity appears in case → gets case's mechanisms)
    for case_id, entity_map in case_entity_mechs.items():
        for eid, mechs in entity_map.items():
            entity_mechs[eid].update(mechs)

    return {
        "entities": {eid: sorted(mechs) for eid, mechs in entity_mechs.items()},
        "entity_types": entity_types,
    }


def discover_entity_roles(
    graph: dict[str, Any],
    min_mechanisms: int = 2,
) -> list[dict]:
    """Cluster entities by mechanism overlap to discover emergent roles.

    Entities that share many mechanisms serve similar structural functions.
    """
    entities = graph["entities"]
    types = graph["entity_types"]

    # Filter entities with enough connections
    qualified = {
        eid: mechs for eid, mechs in entities.items()
        if len(mechs) >= min_mechanisms
    }

    if len(qualified) < 3:
        return []

    # Build similarity matrix (Jaccard on mechanism sets)
    eids = sorted(qualified.keys())
    n = len(eids)
    matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            set_i = set(qualified[eids[i]])
            set_j = set(qualified[eids[j]])
            if set_i or set_j:
                sim = len(set_i & set_j) / len(set_i | set_j)
            else:
                sim = 0.0
            matrix[i, j] = sim
            matrix[j, i] = sim

    # Simple clustering at threshold
    threshold = 0.3
    visited = set()
    clusters: list[dict[str, Any]] = []
    for i in range(n):
        if i in visited:
            continue
        queue = [i]
        component = []
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component.append(node)
            for j in range(n):
                if matrix[node, j] >= threshold and j not in visited:
                    queue.append(j)
        if len(component) >= 2:
            # Extract shared mechanisms
            shared_mechs = set(qualified[eids[component[0]]])
            for idx in component[1:]:
                shared_mechs &= set(qualified[eids[idx]])

            clusters.append({
                "entities": [eids[idx] for idx in component],
                "entity_types": [types.get(eids[idx], "unknown") for idx in component],
                "shared_mechanisms": sorted(shared_mechs),
                "size": len(component),
            })

    # Label clusters by their dominant mechanisms
    for cluster in clusters:
        # Count all mechanisms across cluster entities
        mech_counts: Counter[str] = Counter()
        for eid in cluster["entities"]:
            mech_counts.update(qualified.get(eid, []))
        cluster["dominant_mechanisms"] = [m for m, _ in mech_counts.most_common(5)]
        cluster["emergent_role"] = _infer_role(cluster["dominant_mechanisms"])

    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters


def _infer_role(mechanisms: list[str]) -> str:
    """Infer functional role label from dominant mechanisms."""
    mechs_lower = [m.lower() for m in mechanisms]

    if any("risk" in m or "transfer" in m for m in mechs_lower):
        return "risk_pricing_node"
    if any("liquidity" in m or "spiral" in m or "forced" in m for m in mechs_lower):
        return "liquidity_stress_node"
    if any("leverage" in m or "balance_sheet" in m or "repo" in m for m in mechs_lower):
        return "leverage_intermediary"
    if any("compute" in m or "capex" in m or "cuda" in m or "gpu" in m for m in mechs_lower):
        return "compute_infrastructure"
    if any("platform" in m or "lock" in m or "network" in m for m in mechs_lower):
        return "platform_monopoly"
    if any("ipo" in m or "listing" in m or "valuation" in m for m in mechs_lower):
        return "capital_market_node"
    if any("university" in m or "talent" in m or "startup" in m for m in mechs_lower):
        return "talent_pipeline"
    if any("clearing" in m or "settlement" in m or "counterparty" in m for m in mechs_lower):
        return "market_infrastructure"
    if any("dollar" in m or "policy" in m or "regulation" in m for m in mechs_lower):
        return "policy_regulator"
    if any("export" in m or "control" in m or "geopolitical" in m for m in mechs_lower):
        return "geopolitical_constraint"

    return "general_node"


def discover_entity_bridges(
    graph: dict[str, Any],
    clusters: list[dict],
) -> list[dict]:
    """Find entities that bridge multiple functional clusters.

    Bridge entities are systemically important — they connect
    different structural domains.
    """
    entities = graph["entities"]

    # Map entity to cluster(s)
    entity_to_clusters: dict[str, set[int]] = defaultdict(set)
    for ci, cluster in enumerate(clusters):
        for eid in cluster["entities"]:
            entity_to_clusters[eid].add(ci)

    bridges = []
    for eid, cluster_set in entity_to_clusters.items():
        if len(cluster_set) >= 2:
            mechs = entities.get(eid, [])
            bridges.append({
                "entity_id": eid,
                "entity_type": graph["entity_types"].get(eid, "unknown"),
                "bridges_clusters": len(cluster_set),
                "mechanism_count": len(mechs),
                "cluster_roles": [clusters[ci]["emergent_role"] for ci in cluster_set],
            })

    bridges.sort(key=lambda b: b["bridges_clusters"], reverse=True)
    return bridges


def run(entities: list[dict], cases: list[dict]) -> dict[str, Any]:
    """Full entity graph analysis pipeline."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Build bipartite graph
    graph = build_entity_mechanism_graph(entities, cases)

    # 2. Discover roles
    roles = discover_entity_roles(graph)

    # 3. Find bridges
    bridges = discover_entity_bridges(graph, roles)

    # 4. Package
    result = {
        "total_entities": len(graph["entities"]),
        "qualified_entities": sum(1 for e in graph["entities"].values() if len(e) >= 2),
        "emergent_roles": [
            {
                "role": r["emergent_role"],
                "entities": r["entities"][:10],
                "entity_types": r["entity_types"][:10],
                "shared_mechanisms": r["shared_mechanisms"][:5],
                "dominant_mechanisms": r["dominant_mechanisms"][:5],
                "size": r["size"],
            }
            for r in roles
        ],
        "bridge_entities": bridges[:15],
    }

    out_path = OUTPUT_DIR / "entity_graph.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return result
