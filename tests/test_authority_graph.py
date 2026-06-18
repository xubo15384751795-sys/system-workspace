from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_authority_graph_from_real_pipeline() -> None:
    module = _load_module("authority_graph", ROOT / "scripts" / "_authority_graph.py")
    graph = module.build_authority_graph(ROOT)

    assert graph["schema_version"] == "authority_graph.v1"
    assert graph["metrics"]["pipeline_step_count"] > 20
    assert graph["metrics"]["edge_count"] > 0
    assert "bridge" in graph["bridge_nodes"]
    core_steps = graph["metrics"]["core_capable_steps"]
    assert "bridge" in core_steps
    assert "quality_validation" in core_steps
    assert "judgment_layer" in core_steps
    assert graph["metrics"]["drift_count"] == 0


def test_bridge_is_only_sandbox_to_current_writer() -> None:
    module = _load_module("authority_graph", ROOT / "scripts" / "_authority_graph.py")
    graph = module.build_authority_graph(ROOT)
    nodes = {node["id"]: node for node in graph["nodes"]}

    sandbox_writes = []
    for edge in graph["edges"]:
        if edge.get("kind") != "produces":
            continue
        to_node = nodes.get(edge["to"], {})
        from_node = nodes.get(edge["from"], {})
        if to_node.get("zone") != "Z3":
            continue
        consumes_sandbox = any(
            nodes.get(f"artifact:{path}", {}).get("zone") == "Z_inf"
            for path in from_node.get("consumes", [])
            if str(path).startswith("Output/sandbox")
        )
        if consumes_sandbox:
            sandbox_writes.append(edge["from"])

    assert set(sandbox_writes) == {"bridge"}


def test_runtime_can_affect_core_requires_graph_and_gate() -> None:
    module = _load_module("authority_graph", ROOT / "scripts" / "_authority_graph.py")
    graph = module.build_authority_graph(ROOT)
    completed = set(graph["metrics"]["core_capable_steps"])

    blocked = module.runtime_can_affect_core_judgment(
        graph,
        promotion_gate_pass=False,
        trace_complete=True,
        completed_steps=completed,
    )
    assert blocked["allowed"] is False
    assert "promotion_gate_not_pass" in blocked["blocking_reasons"]

    allowed = module.runtime_can_affect_core_judgment(
        graph,
        promotion_gate_pass=True,
        trace_complete=True,
        completed_steps=completed,
    )
    assert allowed["allowed"] is True


def test_build_authority_graph_cli_writes_output(tmp_path: Path) -> None:
    module = _load_module("build_authority_graph", ROOT / "scripts" / "build_authority_graph.py")
    # Copy minimal policy + one pipeline step into temp root
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "authority_graph_policy.yaml").write_text(
        (ROOT / "governance" / "authority_graph_policy.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "governance" / "output_routing_policy.yaml").write_text(
        (ROOT / "governance" / "output_routing_policy.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "governance" / "daily_pipeline_registry.yaml").write_text(
        """
schema_version: daily_pipeline_registry.v2
steps:
  bridge:
    order: 1
    owner: Workbench
    consumes:
      - Output/sandbox/structural_replay_v2/
    produces:
      - Output/current/framework_output.json
    authority:
      affects_core_judgment: true
""",
        encoding="utf-8",
    )

    ag = _load_module("authority_graph_lib", ROOT / "scripts" / "_authority_graph.py")
    graph = ag.build_authority_graph(tmp_path)
    output = ag.write_authority_graph(graph, tmp_path)
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["metrics"]["pipeline_step_count"] == 1


def test_normalize_step_name_from_script_path() -> None:
    module = _load_module("authority_graph", ROOT / "scripts" / "_authority_graph.py")
    index = module.build_step_id_index(ROOT)
    assert module.normalize_step_name("scripts/governance_status.py", index) == "governance_status"
    assert module.normalize_step_name("governance_status", index) == "governance_status"


def test_generated_entrypoint_registry_covers_pipeline_scripts() -> None:
    module = _load_module("build_entrypoint_registry", ROOT / "scripts" / "build_entrypoint_registry.py")
    payload = module.build_generated_registry(ROOT)
    counts = payload["counts"]
    assert counts["merged_entries"] > 0
    assert "bridge_replay_to_current" in payload["entries"]
    assert payload["entries"]["bridge_replay_to_current"]["source"] == "daily_pipeline_registry"
