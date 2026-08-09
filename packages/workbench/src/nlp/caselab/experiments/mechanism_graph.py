"""Mechanism co-occurrence graph — emergent structure discovery.

READS: CaseLab vault (01_Cases, 03_Mechanisms) via adapter
WRITES: Data/nlp/caselab_experiments/ only
DOES NOT modify System code, data, or outputs.

Discovers which mechanisms naturally cluster together based on
co-occurrence in case narratives. These clusters are emergent
structural dimensions — not pre-defined.
"""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

import numpy as np

OUTPUT_DIR = WorkspacePaths.discover().root / "Data" / "nlp" / "caselab_experiments"


def build_cooccurrence_matrix(cases: list[dict]) -> dict[str, Any]:
    """Build mechanism co-occurrence matrix from case data.

    Each case has a list of mechanisms. Mechanisms that appear together
    in the same case are "co-occurring". The frequency of co-occurrence
    reveals structural coupling.
    """
    # Count individual mechanism frequencies
    mechanism_freq: Counter[str] = Counter()
    # Count co-occurrence pairs
    cooccurrence: Counter[tuple[str, str]] = Counter()
    # Track which cases each mechanism appears in
    mechanism_cases: dict[str, set[str]] = defaultdict(set)

    for case in cases:
        mechs = case.get("mechanisms", [])
        case_id = case.get("case_id", "")

        for m in mechs:
            mechanism_freq[m] += 1
            mechanism_cases[m].add(case_id)

        # All pairs in this case
        for m1, m2 in combinations(sorted(set(mechs)), 2):
            cooccurrence[(m1, m2)] += 1

    # Build matrix
    mech_names = sorted(mechanism_freq.keys())
    n = len(mech_names)
    mech_idx = {m: i for i, m in enumerate(mech_names)}

    matrix = np.zeros((n, n))
    for (m1, m2), count in cooccurrence.items():
        i, j = mech_idx[m1], mech_idx[m2]
        # Normalize by min frequency (Jaccard-like)
        norm = min(mechanism_freq[m1], mechanism_freq[m2])
        score = count / norm if norm > 0 else 0
        matrix[i, j] = score
        matrix[j, i] = score

    # Set diagonal to 1
    np.fill_diagonal(matrix, 1.0)

    return {
        "mechanism_names": mech_names,
        "matrix": matrix.tolist(),
        "frequencies": {m: mechanism_freq[m] for m in mech_names},
        "cooccurrence_pairs": {
            f"{m1}||{m2}": count
            for (m1, m2), count in cooccurrence.most_common(50)
        },
        "mechanism_cases": {m: list(cases_set) for m, cases_set in mechanism_cases.items()},
    }


def discover_communities(cooc_data: dict, min_cluster_size: int = 2) -> list[dict]:
    """Discover mechanism clusters via simple agglomerative clustering.

    Uses the co-occurrence matrix as similarity. Clusters are
    emergent structural dimensions.
    """
    names = cooc_data["mechanism_names"]
    matrix = np.array(cooc_data["matrix"])
    n = len(names)

    if n < 3:
        return []

    # Simple hierarchical clustering via threshold
    # Find connected components at different thresholds
    thresholds = [0.6, 0.5, 0.4, 0.3, 0.2]
    best_clusters = []

    for threshold in thresholds:
        # Build adjacency at this threshold
        adj = matrix >= threshold
        np.fill_diagonal(adj, False)

        # Find connected components (BFS)
        visited = set()
        clusters = []
        for i in range(n):
            if i in visited:
                continue
            # BFS
            queue = [i]
            component = []
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                for j in range(n):
                    if adj[node, j] and j not in visited:
                        queue.append(j)
            if len(component) >= min_cluster_size:
                clusters.append({
                    "mechanisms": [names[idx] for idx in component],
                    "size": len(component),
                    "threshold": threshold,
                    "internal_density": _cluster_density(matrix, component),
                })

        if len(clusters) >= 3 and all(c["size"] <= 8 for c in clusters):
            best_clusters = clusters
            break

    if not best_clusters:
        # Fallback: lowest threshold, allow single-mechanism clusters
        threshold = 0.2
        visited = set()
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
                best_clusters.append({
                    "mechanisms": [names[idx] for idx in component],
                    "size": len(component),
                    "threshold": threshold,
                    "internal_density": _cluster_density(matrix, component),
                })

    # Rank by internal density
    best_clusters.sort(key=lambda c: c["internal_density"], reverse=True)

    return best_clusters


def _cluster_density(matrix: np.ndarray, indices: list[int]) -> float:
    """Average pairwise similarity within a cluster."""
    if len(indices) < 2:
        return 0.0
    total = 0.0
    count = 0
    for i, j in combinations(indices, 2):
        total += matrix[i, j]
        count += 1
    return total / count if count > 0 else 0.0


def discover_bridge_mechanisms(cooc_data: dict, clusters: list[dict]) -> list[dict]:
    """Find mechanisms that bridge multiple clusters.

    Bridge mechanisms connect different structural domains —
    they're the most systemically important nodes.
    """
    names = cooc_data["mechanism_names"]
    matrix = np.array(cooc_data["matrix"])

    # Map each mechanism to its cluster(s)
    mech_to_clusters: dict[str, set[int]] = defaultdict(set)
    for ci, cluster in enumerate(clusters):
        for m in cluster["mechanisms"]:
            mech_to_clusters[m].add(ci)

    bridges = []
    for mech in names:
        clusters_connected = mech_to_clusters.get(mech, set())
        if len(clusters_connected) >= 2:
            # How many clusters does this mechanism bridge?
            bridge_score = len(clusters_connected)
            # Average similarity to mechanisms in each bridged cluster
            avg_sims = []
            for ci in clusters_connected:
                cluster_mechs = clusters[ci]["mechanisms"]
                sims = []
                for other in cluster_mechs:
                    if other != mech:
                        i = names.index(mech)
                        j = names.index(other)
                        sims.append(matrix[i, j])
                avg_sims.append(np.mean(sims) if sims else 0)

            bridges.append({
                "mechanism": mech,
                "bridges_clusters": len(clusters_connected),
                "avg_similarity": round(float(np.mean(avg_sims)), 3),
                "cluster_names": [clusters[ci]["mechanisms"][:3] for ci in clusters_connected],
            })

    bridges.sort(key=lambda b: (b["bridges_clusters"], b["avg_similarity"]), reverse=True)
    return bridges


def run(cases: list[dict]) -> dict[str, Any]:
    """Full mechanism graph analysis pipeline."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Co-occurrence matrix
    cooc = build_cooccurrence_matrix(cases)

    # 2. Community discovery
    clusters = discover_communities(cooc)

    # 3. Bridge mechanisms
    bridges = discover_bridge_mechanisms(cooc, clusters)

    # 4. Package results
    result = {
        "total_mechanisms": len(cooc["mechanism_names"]),
        "total_cases": len(cases),
        "top_cooccurrences": dict(list(cooc["cooccurrence_pairs"].items())[:20]),
        "clusters": [
            {
                "label": f"Cluster {i+1}",
                "mechanisms": c["mechanisms"],
                "size": c["size"],
                "density": round(c["internal_density"], 3),
                "threshold": c["threshold"],
            }
            for i, c in enumerate(clusters)
        ],
        "bridge_mechanisms": bridges[:10],
    }

    # Save
    out_path = OUTPUT_DIR / "mechanism_graph.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Save co-occurrence matrix as CSV for inspection
    csv_path = OUTPUT_DIR / "mechanism_cooccurrence.csv"
    names = cooc["mechanism_names"]
    matrix = np.array(cooc["matrix"])
    with open(csv_path, "w") as f:
        f.write("," + ",".join(names) + "\n")
        for i, name in enumerate(names):
            row = [name] + [f"{matrix[i,j]:.3f}" for j in range(len(names))]
            f.write(",".join(row) + "\n")

    return result
