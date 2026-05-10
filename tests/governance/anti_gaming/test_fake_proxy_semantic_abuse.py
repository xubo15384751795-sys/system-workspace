from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.semantic import SemanticRegistry, validate_proxy_row_semantics


def test_semantic_distance_4_cannot_support_strong_claim(tmp_path) -> None:
    registry = tmp_path / "semantic_registry.json"
    registry.write_text(
        """
{
  "K": {
    "implemented_status": "PARTIAL",
    "semantic_distance": 4,
    "proxy_status": "PROXY_REDUCED",
    "operational_proxy": "vol proxy",
    "reduction_errors": ["Only vol proxy"],
    "valid_for": ["warning"],
    "not_valid_for": ["full curvature claim"]
  }
}
""",
        encoding="utf-8",
    )

    semantic = SemanticRegistry(registry)
    with pytest.raises(ValueError):
        semantic.require_safe_for_structural_claim("K")


def test_fake_semantic_registry_missing_reduction_errors_is_rejected(tmp_path) -> None:
    registry = tmp_path / "semantic_registry.json"
    registry.write_text(
        """
{
  "K": {
    "implemented_status": "PARTIAL",
    "semantic_distance": 3,
    "proxy_status": "PROXY_REDUCED",
    "operational_proxy": "K basket",
    "reduction_errors": [],
    "valid_for": ["warning"],
    "not_valid_for": ["full curvature claim"]
  }
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reduction_errors"):
        SemanticRegistry(registry)


def test_fake_proxy_row_with_bare_semantic_fields_is_rejected() -> None:
    row = {
        "target_concept": "X_PRE",
        "proxy_status": "DATA_TRUNCATED_PROXY",
        "semantic_distance": 4,
        "reduction_errors": [],
        "not_valid_for": [],
    }

    with pytest.raises(ValueError, match="reduction_errors"):
        validate_proxy_row_semantics(row)
