"""Step 1 architecture graph and dependency-direction gates."""
from __future__ import annotations

from pathlib import Path

from tools.audit.build_architecture_dependency_map import build_map

ROOT = Path(__file__).resolve().parents[1]


def test_import_graph_covers_declared_layers_and_gate() -> None:
    graph = build_map(ROOT, baseline_core_violations=0, baseline_registered_violations=22)

    assert graph["schema_version"] == "architecture.import_graph.v1"
    assert {
        "core",
        "application",
        "application_runtime",
        "orchestration",
        "domain",
        "compatibility",
        "tools",
        "archive",
        "tests",
    } <= set(graph["layers"])
    assert graph["node_count"] > 0
    assert graph["edge_count"] > 0
    assert graph["gate"]["status"] == "PASS"
    assert any(node["module"].startswith("benchmarks") for node in graph["nodes"])
    assert any(node["module"].startswith("ml") for node in graph["nodes"])
    assert any(node["module"].startswith("nlp") for node in graph["nodes"])
    assert any(node["module"].startswith("agents") for node in graph["nodes"])
    assert any(node["module"].startswith("paper_interface") for node in graph["nodes"])
    assert {
        "verity ↔ orchestration",
        "verity ↔ workbench",
        "workbench ↔ orchestration",
    } == {boundary["name"] for boundary in graph["focus_boundaries"]}


def test_live_packages_have_no_scripts_reverse_dependency() -> None:
    graph = build_map(ROOT, baseline_core_violations=0, baseline_registered_violations=22)

    assert graph["package_to_scripts_edges"] == []
    assert graph["gate"]["no_production_package_to_scripts"] is True


def test_existing_debt_is_owned_and_cycles_are_classified() -> None:
    graph = build_map(ROOT, baseline_core_violations=0, baseline_registered_violations=22)
    allowed_categories = {
        "shared_core_contract",
        "application_callback",
        "error_ownership",
        "temporary_compatibility",
    }

    assert graph["gate"]["all_existing_violations_have_owner"] is True
    assert graph["gate"]["registered_debt_not_expanded"] is True
    assert graph["gate"]["core_direction_not_increased"] is True
    assert all(cycle["category"] in allowed_categories for cycle in graph["cycles"])
    assert graph["gate"]["all_cycles_classified"] is True
    assert graph["gate"]["focus_boundaries_classified"] is True


def test_generated_architecture_artifacts_are_present() -> None:
    for relative in (
        "architecture/import_graph.json",
        "architecture/violations.json",
        "architecture/current_dependency_map.md",
    ):
        assert (ROOT / relative).exists(), relative
