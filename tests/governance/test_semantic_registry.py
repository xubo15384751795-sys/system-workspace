from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.semantic import SemanticRegistry, build_sigma_vector


def test_semantic_registry_attaches_proxy_metadata() -> None:
    semantic = SemanticRegistry(ROOT / "governance" / "semantic_registry.json")

    row = semantic.attach_metadata({"proxy": "K_PROXY", "value": 0.72}, "K")

    assert row["target_concept"] == "K"
    assert row["proxy_status"] == "PROXY_REDUCED"
    assert row["semantic_distance"] == 3
    assert "claiming full event-space curvature" in row["not_valid_for"]


def test_not_implemented_concept_cannot_support_structural_claim() -> None:
    semantic = SemanticRegistry(ROOT / "governance" / "semantic_registry.json")

    with pytest.raises(ValueError, match="NOT_IMPLEMENTED"):
        semantic.require_safe_for_structural_claim("V")


def test_sigma_vector_preserves_channel_shape() -> None:
    semantic = SemanticRegistry(ROOT / "governance" / "semantic_registry.json")

    vector = build_sigma_vector(
        {"M": 0.2, "D": -0.4, "K": 0.88, "X_PRE": 0.7, "X_REALIZED": 0.1, "operator_penalty": 0.4},
        semantic,
    )

    assert vector["dominant_channel"] == "K"
    assert vector["cofire_count"] == 2
    assert any("X_PRE" in warning for warning in vector["semantic_warning"])

