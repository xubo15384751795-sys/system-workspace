from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.semantic


ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_SRC = ROOT / "packages" / "workbench" / "src"
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


def test_sigma_vector_uses_canonical_four_channels() -> None:
    # Canonical four-channel contract: M / D / K / X_agg remain the framework
    # dimensions; the retired X_PRE / X_REALIZED splits are no longer part of
    # the Sigma vector.
    semantic = SemanticRegistry(ROOT / "governance" / "semantic_registry.json")

    vector = build_sigma_vector(
        {"M": 0.2, "D": -0.4, "K": 0.88, "X_agg": 0.7, "operator_penalty": 0.4},
        semantic,
    )

    assert vector["complete"] is True
    assert vector["dominant_channel"] == "K"
    assert vector["cofire_count"] == 2  # K=0.88 and X_agg=0.70 are ≥ 0.65
    assert "X_PRE" not in vector and "X_REALIZED" not in vector
    assert "X_agg" in vector
    assert vector["primary_readout"]["state"] == "FUNDING_PATH_NARROWING"
    assert vector["primary_readout"]["blocked_from_primary"] == ["K", "X_agg"]
    # K carries semantic_distance=3 in the registry -> distance warning surfaces.
    assert any("K:" in warning for warning in vector["semantic_warning"])


def test_sigma_vector_flags_partial_coverage_without_silent_collapse() -> None:
    # The real current state: only M and D are live; K and X_agg are absent.
    # They must NOT silently become 0.0 and let M/D pose as a complete reading.
    semantic = SemanticRegistry(ROOT / "governance" / "semantic_registry.json")

    vector = build_sigma_vector({"M": 0.2, "D": -0.4, "operator_penalty": 0.4}, semantic)

    assert vector["complete"] is False
    assert set(vector["channels_not_implemented"]) == {"K", "X_agg"}
    assert vector["K"] is None and vector["X_agg"] is None
    assert any("PARTIAL_CHANNEL_COVERAGE" in warning for warning in vector["semantic_warning"])


def test_measurement_eligibility_marks_md_primary_and_kx_limited() -> None:
    semantic = SemanticRegistry(ROOT / "governance" / "semantic_registry.json")

    vector = build_sigma_vector(
        {"M": 0.76, "D": -0.78, "K": 0.93, "X_agg": 0.91},
        semantic,
    )

    eligibility = vector["measurement_eligibility"]
    assert set(eligibility) == {"M", "D", "K", "X_agg"}
    assert eligibility["M"]["readout_role"] == "primary_readout"
    assert eligibility["D"]["readout_role"] == "primary_readout"
    assert eligibility["K"]["current_status"] == "THEORY_RETAINED_MEASUREMENT_INCOMPLETE"
    assert eligibility["X_agg"]["current_status"] == "BACKGROUND_ONLY_REBUILD_REQUIRED"
    assert vector["primary_readout"]["state"] == "MIXED_ANCHOR_PATH_STRESS"
