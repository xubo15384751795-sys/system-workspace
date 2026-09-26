from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

from tests._harness_tools import harness_tools_owner

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return sys.modules[name]


def test_every_root_governance_file_has_an_attention_shape() -> None:
    module = _load("governance_drag", ROOT / "tools" / "audit" / "build_governance_drag_report.py")
    metrics = module.build_report(ROOT)["metrics"]
    assert metrics["unclassified_governance_files"] == []
    assert metrics["stale_inventory_entries"] == []
    assert sum(metrics["shape_counts"].values()) == metrics["governance_root_file_count"]


def test_machine_shapes_have_real_consumers() -> None:
    module = _load("governance_drag_consumers", ROOT / "tools" / "audit" / "build_governance_drag_report.py")
    metrics = module.build_report(ROOT)["metrics"]
    assert metrics["unbacked_machine_files"] == []
    for name, consumers in metrics["machine_consumer_evidence"].items():
        assert consumers, f"{name} is labelled machine-enforced but has no consumer"


def test_attention_surface_respects_budget() -> None:
    module = _load("governance_drag_budget", ROOT / "tools" / "audit" / "build_governance_drag_report.py")
    metrics = module.build_report(ROOT)["metrics"]
    budget = metrics["attention_budget"]
    assert metrics["procedural_rule_file_count"] <= budget["max_procedural_rule_files"]
    assert metrics["always_read_file_count"] <= budget["max_always_read_files"]
    assert metrics["always_read_rule_lines"] <= budget["max_always_read_rule_lines"]


def test_drag_score_does_not_treat_governance_file_count_as_weight() -> None:
    module = _load("governance_drag_shape", ROOT / "tools" / "audit" / "build_governance_drag_report.py")
    report = module.build_report(ROOT)
    components = report["drag_assessment"]["component_scores"]
    assert report["schema"] == "governance_drag_report.v2"
    assert "governance_attention_drag" in components
    assert "governance_file_drag" not in components
    assert "governance_yaml_count_inventory_only" in report["metrics"]


def test_router_returns_only_task_local_reading_surface() -> None:
    with harness_tools_owner():
        from tools.task_router import route_task

        decision = route_task("audit governance attention and feedback loops")
    assert decision["read_first"] == [decision["context_file"]]
    assert "MODULES.md" not in decision["read_first"]
    assert "ROUTING_CONSTITUTION.md" not in decision["read_first"]


def test_sunset_queue_names_a_property_and_disposition() -> None:
    module = _load("governance_drag_sunset", ROOT / "tools" / "audit" / "build_governance_drag_report.py")
    queue = module.build_report(ROOT)["metrics"]["sunset_queue"]
    assert queue
    for name, item in queue.items():
        assert item.get("property"), f"{name} has no maintained property"
        assert item.get("disposition"), f"{name} has no sunset disposition"


def test_machine_constitution_cannot_regrow_procedural_sections() -> None:
    constitution = yaml.safe_load(
        (ROOT / "governance" / "system_constitution.yaml").read_text(encoding="utf-8")
    )
    assert set(constitution) == {
        "schema_version",
        "updated_at",
        "hard_authority_rule",
        "module_roles",
        "governance_freeze",
        "freshness_rules",
    }


def test_human_entrypoints_do_not_require_global_governance_reading() -> None:
    readme_head = "\n".join((ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:35])
    modules_head = "\n".join((ROOT / "MODULES.md").read_text(encoding="utf-8").splitlines()[:25])
    assert "architecture_cleanup_decisions.md" not in readme_head
    assert "first stop" not in modules_head.lower()
    assert "not required reading" in modules_head


def test_task_plan_activates_only_local_context_as_reading_surface() -> None:
    with harness_tools_owner():
        from tools.task_planner import create_task_plan

        plan = create_task_plan("audit governance attention")
    route_step = plan["steps"][0]
    assert route_step["artifacts"] == [plan["route"]["context_file"]]
