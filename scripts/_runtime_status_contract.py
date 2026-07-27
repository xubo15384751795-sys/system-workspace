#!/usr/bin/env python3
"""Load governance/runtime_status_contract.yaml — shared enum authority for tests."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "governance" / "runtime_status_contract.yaml"


@lru_cache(maxsize=1)
def load_runtime_status_contract() -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid runtime status contract: {CONTRACT_PATH}")
    return data


def framework_output_status_values(*, include_legacy: bool = True) -> frozenset[str]:
    contract = load_runtime_status_contract()
    block = contract["framework_output_status"]
    values = set(block["canonical"])
    if include_legacy:
        values.update(block.get("legacy_aliases", []))
    return frozenset(values)


def judgment_decision_values(*, include_legacy: bool = True) -> frozenset[str]:
    contract = load_runtime_status_contract()
    block = contract["judgment_decision"]
    values = set(block["producer"])
    if include_legacy:
        values.update(block.get("legacy_reader", []))
    return frozenset(values)


def judgment_confidence_values() -> frozenset[str]:
    contract = load_runtime_status_contract()
    return frozenset(contract["judgment_confidence"])
