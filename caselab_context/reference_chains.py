"""Reference chain registry for retrieval boosting."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from caselab_context.paper_paths import paper_root

CHAINS_PATH = paper_root() / "90_Admin/Context Rules/reference_chains.yml"


@lru_cache(maxsize=1)
def load_reference_chains() -> list[dict[str, Any]]:
    if not CHAINS_PATH.exists():
        return []
    data = yaml.safe_load(CHAINS_PATH.read_text(encoding="utf-8")) or {}
    chains = data.get("chains")
    return chains if isinstance(chains, list) else []


def reference_node_titles() -> set[str]:
    titles: set[str] = set()
    for chain in load_reference_chains():
        for node in chain.get("nodes") or []:
            titles.add(str(node).strip().lower())
    return titles


def reference_chain_boost(title: str) -> float:
    normalized = title.strip().lower()
    if normalized in reference_node_titles():
        return 0.06
    return 0.0


def chains_for_anchor(anchor_case: str) -> list[dict[str, Any]]:
    target = anchor_case.strip().lower()
    return [
        chain
        for chain in load_reference_chains()
        if str(chain.get("anchor_case", "")).strip().lower() == target
    ]
