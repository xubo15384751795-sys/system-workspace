"""Text emergence — discover structural dimensions from case narratives.

READS: CaseLab vault (01_Cases) via adapter
WRITES: Data/nlp/caselab_experiments/ only
DOES NOT modify System code, data, or outputs.

Extracts keyword co-occurrence patterns from case narratives
to discover structural dimensions that emerge from the corpus
rather than being pre-defined (like S-A-L-V-P-tau).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parents[5] / "Data" / "nlp" / "caselab_experiments"

# Structural concept seeds — used to anchor emergence, not constrain it.
# These are broad enough to let patterns emerge within and across them.
CONCEPT_SEEDS: dict[str, list[str]] = {
    # Financial structure
    "leverage": ["杠杆", "leverage", "borrowing", "负债", "debt", "margin"],
    "liquidity": ["流动性", "liquidity", "funding", "融资", "repo", "回购"],
    "credit": ["信用", "credit", "spread", "利差", "default", "违约"],
    "volatility": ["波动", "volatility", "vol", "波动率", "variance"],
    "correlation": ["相关", "correlation", "相关性", "联动"],
    "positioning": ["仓位", "positioning", "crowded", "集中", "持仓"],

    # Risk dynamics
    "forced_selling": ["被迫", "forced", "抛售", "selling", "liquidat", "margin call"],
    "spiral": ["螺旋", "spiral", "反馈", "自我强化", "self-reinforcing", "cascade"],
    "contagion": ["传染", "contagion", "蔓延", "spillover", "溢出"],
    "cascade": ["级联", "cascade", "连锁", "chain reaction"],
    "run": ["挤兑", "run", "deposit", "存款", "bank run", "redemption"],

    # Market structure
    "clearing": ["清算", "clearing", "settlement", "结算", "CCP"],
    "counterparty": ["交易对手", "counterparty", "bilateral"],
    "intermediary": ["中介", "intermediary", "broker", "dealer", "做市"],
    "market_microstructure": ["微结构", "microstructure", "order book", "做市"],

    # Technology / platform
    "compute": ["算力", "compute", "GPU", "芯片", "semiconductor", "数据中心"],
    "platform": ["平台", "platform", "ecosystem", "生态", "network effect"],
    "lock_in": ["锁定", "lock-in", "绑定", "switching cost", "转换成本"],
    "scaling": ["规模化", "scaling", "规模", "规模经济", "economies of scale"],

    # Capital / valuation
    "valuation": ["估值", "valuation", "定价", "pricing", "bubble", "泡沫"],
    "ipo": ["上市", "IPO", "listing", "公开募股", "public offering"],
    "capex": ["资本开支", "capex", "capital expenditure", "投资"],
    "revenue": ["收入", "revenue", "营收", "growth", "增长"],

    # Institutional
    "governance": ["治理", "governance", "partnership", "合伙", "corporate"],
    "regulation": ["监管", "regulation", "政策", "policy", "regulator"],
    "intervention": ["干预", "intervention", "bailout", "救助", "backstop"],
    "tax": ["税", "tax", "fiscal", "财政"],

    # Geographic / systemic
    "dollar_system": ["美元", "dollar", "USD", "储备货币", "reserve currency"],
    "capital_flow": ["资本流动", "capital flow", "资金流", "热钱", "hot money"],
    "supply_chain": ["供应链", "supply chain", "供应", "上游", "下游"],
    "talent": ["人才", "talent", "brain drain", "移民", "immigration"],
}


def extract_concept_vectors(cases: list[dict]) -> dict[str, Any]:
    """Extract concept frequency vectors from case narratives.

    Each case becomes a vector in concept-space. Cases with similar
    concept profiles are structurally similar, even if their
    surface narratives differ.
    """
    case_vectors: dict[str, dict[str, float]] = {}
    concept_freq: Counter[str] = Counter()

    for case in cases:
        case_id = case.get("case_id", "")
        # Combine all text
        text = " ".join([
            case.get("narrative_summary", ""),
            case.get("risk_migration", ""),
            case.get("feedback_loop", ""),
        ]).lower()

        if not text.strip():
            continue

        # Count concept occurrences
        vector: dict[str, float] = {}
        for concept, keywords in CONCEPT_SEEDS.items():
            count = sum(len(re.findall(re.escape(kw.lower()), text)) for kw in keywords)
            if count > 0:
                vector[concept] = float(count)
                concept_freq[concept] += count

        case_vectors[case_id] = vector

    return {
        "case_vectors": case_vectors,
        "concept_frequencies": dict(concept_freq.most_common()),
    }


def discover_concept_clusters(concept_data: dict) -> list[dict]:
    """Cluster concepts by co-occurrence across cases.

    Concepts that frequently appear together in the same cases
    form emergent structural dimensions.
    """
    case_vectors = concept_data["case_vectors"]
    if not case_vectors:
        return []

    # Get all concepts that appear in at least 3 cases
    concept_case_count: Counter[str] = Counter()
    for vec in case_vectors.values():
        for c in vec:
            concept_case_count[c] += 1

    active_concepts = [c for c, n in concept_case_count.items() if n >= 3]
    if len(active_concepts) < 3:
        return []

    # Build concept co-occurrence matrix
    n = len(active_concepts)
    cooc = np.zeros((n, n))
    concept_idx = {c: i for i, c in enumerate(active_concepts)}

    for case_id, vec in case_vectors.items():
        concepts_in_case = [c for c in vec if c in concept_idx]
        for c1, c2 in combinations(concepts_in_case, 2):
            i, j = concept_idx[c1], concept_idx[c2]
            cooc[i, j] += 1
            cooc[j, i] += 1

    # Normalize by co-occurrence frequency
    for i in range(n):
        for j in range(n):
            if i != j:
                denom = min(concept_case_count[active_concepts[i]], concept_case_count[active_concepts[j]])
                if denom > 0:
                    cooc[i, j] /= denom

    # Cluster at threshold
    threshold = 0.4
    visited = set()
    clusters = []
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
                if cooc[node, j] >= threshold and j not in visited:
                    queue.append(j)
        if len(component) >= 2:
            cluster_concepts = [active_concepts[idx] for idx in component]
            # Internal density
            density = 0.0
            count = 0
            for a, b in combinations(component, 2):
                density += cooc[a, b]
                count += 1
            density = density / count if count else 0

            clusters.append({
                "concepts": cluster_concepts,
                "size": len(cluster_concepts),
                "density": round(float(density), 3),
                "case_count": sum(
                    1 for vec in case_vectors.values()
                    if all(c in vec for c in cluster_concepts)
                ),
            })

    clusters.sort(key=lambda c: c["density"] * c["size"], reverse=True)
    return clusters


def discover_emergent_dimensions(
    concept_data: dict,
    clusters: list[dict],
) -> list[dict]:
    """Name emergent structural dimensions from concept clusters.

    Each cluster represents a latent dimension that the corpus
    naturally organizes around. These can replace or augment
    the pre-defined S-A-L-V-P-tau.
    """
    dimensions = []
    for i, cluster in enumerate(clusters):
        concepts = cluster["concepts"]

        # Generate dimension name from concepts
        dim_name = _name_dimension(concepts)

        # Find cases that score highest on this dimension
        case_vectors = concept_data["case_vectors"]
        case_scores = []
        for case_id, vec in case_vectors.items():
            score = sum(vec.get(c, 0) for c in concepts)
            if score > 0:
                case_scores.append((case_id, score))

        case_scores.sort(key=lambda x: x[1], reverse=True)

        dimensions.append({
            "dimension_id": f"D{i+1}",
            "name": dim_name,
            "concepts": concepts,
            "density": cluster["density"],
            "case_count": cluster["case_count"],
            "top_cases": [
                {"case_id": cid, "score": round(score, 1)}
                for cid, score in case_scores[:5]
            ],
        })

    return dimensions


def _name_dimension(concepts: list[str]) -> str:
    """Generate a human-readable dimension name from concept list."""
    concept_names = {
        "leverage": "杠杆",
        "liquidity": "流动性",
        "credit": "信用",
        "volatility": "波动率",
        "correlation": "相关性",
        "positioning": "仓位",
        "forced_selling": "被迫卖出",
        "spiral": "螺旋反馈",
        "contagion": "传染",
        "cascade": "级联",
        "run": "挤兑",
        "clearing": "清算",
        "counterparty": "交易对手",
        "intermediary": "中介",
        "market_microstructure": "微结构",
        "compute": "算力",
        "platform": "平台",
        "lock_in": "锁定",
        "scaling": "规模化",
        "valuation": "估值",
        "ipo": "上市",
        "capex": "资本开支",
        "revenue": "收入",
        "governance": "治理",
        "regulation": "监管",
        "intervention": "干预",
        "tax": "税",
        "dollar_system": "美元体系",
        "capital_flow": "资本流动",
        "supply_chain": "供应链",
        "talent": "人才",
    }
    names = [concept_names.get(c, c) for c in concepts[:4]]
    return "+".join(names)


def run(cases: list[dict]) -> dict[str, Any]:
    """Full text emergence pipeline."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Extract concept vectors
    concept_data = extract_concept_vectors(cases)

    # 2. Discover concept clusters
    clusters = discover_concept_clusters(concept_data)

    # 3. Name emergent dimensions
    dimensions = discover_emergent_dimensions(concept_data, clusters)

    # 4. Package
    result = {
        "total_cases": len(concept_data["case_vectors"]),
        "total_concepts": len(concept_data["concept_frequencies"]),
        "concept_frequencies": concept_data["concept_frequencies"],
        "emergent_clusters": clusters,
        "emergent_dimensions": dimensions,
    }

    out_path = OUTPUT_DIR / "text_emergence.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return result
