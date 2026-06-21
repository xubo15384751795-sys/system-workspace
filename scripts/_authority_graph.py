"""Authority graph — topology-derived governance from pipeline structure.

Builds a typed directed graph from daily_pipeline_registry.yaml and
authority_graph_policy.yaml.  Graph-derived core judgment uses direct
production into the authorized runtime chain (from system_constitution.yaml).
"""
from __future__ import annotations

import fnmatch
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _runtime_io import ROOT, ensure_dir, load_yaml as _load_yaml  # noqa: E402

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "authority_graph.v1"
DEFAULT_OUTPUT = "Output/system_learning/latest/authority_graph.json"


def _normalize_path(path: str) -> str:
    return path.strip().rstrip("/")


def _artifact_id(path: str) -> str:
    return f"artifact:{_normalize_path(path)}"


def _path_matches(produced: str, consumed: str) -> bool:
    p = _normalize_path(produced)
    c = _normalize_path(consumed)
    if not p or not c:
        return False
    return c.startswith(p) or p.startswith(c)


def _core_chain_prefixes(root: Path, policy: dict[str, Any]) -> tuple[list[str], list[str]]:
    constitution = _load_yaml(root / "governance" / "system_constitution.yaml")
    hard_rule = constitution.get("hard_authority_rule", {}) or {}
    authorized = [
        _normalize_path(str(item))
        for item in hard_rule.get("authorized_runtime_chain", [])
        if str(item).endswith("/")
    ]
    canonical_data = [
        _normalize_path(str(item.get("prefix", "")))
        for item in policy.get("canonical_data_prefixes", [])
        if item.get("prefix")
    ]
    prohibited = [
        _normalize_path(str(item))
        for item in hard_rule.get("prohibited_from_core_judgment", [])
        if str(item).endswith("/")
    ]
    return authorized + canonical_data, prohibited


def _is_core_chain_path(path: str, core_prefixes: list[str], prohibited_prefixes: list[str]) -> bool:
    normalized = _normalize_path(path)
    if any(normalized.startswith(prefix) for prefix in prohibited_prefixes):
        return False
    return any(normalized.startswith(prefix) for prefix in core_prefixes)


def _is_surface_path(path: str, surface_prefixes: list[str]) -> bool:
    normalized = _normalize_path(path)
    return any(normalized.startswith(prefix) for prefix in surface_prefixes)


def _zone_for_artifact(path: str, policy: dict[str, Any], routing: dict[str, Any]) -> str:
    normalized = _normalize_path(path)
    for prefix_rule in policy.get("data_path_zones", []):
        prefix = _normalize_path(str(prefix_rule.get("prefix", "")))
        if prefix and normalized.startswith(prefix):
            return str(prefix_rule.get("zone", "Z1"))

    groups = routing.get("groups", {})
    group_zones = policy.get("routing_group_zones", {})
    best_len = -1
    best_zone = "Z1"
    for group_name, group in groups.items():
        group_path = _normalize_path(str(group.get("path", "")))
        if group_path and normalized.startswith(group_path) and len(group_path) > best_len:
            best_len = len(group_path)
            best_zone = str(group_zones.get(group_name, "Z1"))
    return best_zone


def _zone_for_step(step_id: str, policy: dict[str, Any]) -> tuple[str, str]:
    for rule in policy.get("step_zone_rules", []):
        pattern = str(rule.get("pattern", ""))
        if fnmatch.fnmatch(step_id, pattern):
            return str(rule.get("zone", "Z1")), str(rule.get("node_type", "pipeline_step"))
    return "Z1", "pipeline_step"


def _declared_affects_core(step: dict[str, Any]) -> bool:
    authority = step.get("authority", {}) or {}
    if "affects_core_judgment" in authority:
        return bool(authority["affects_core_judgment"])
    if "allowed_to_affect_core_judgment" in step:
        return bool(step["allowed_to_affect_core_judgment"])
    return False


def _collect_paths(step: dict[str, Any], key: str) -> list[str]:
    values: list[str] = []
    for field in (key, f"{key}s"):
        raw = step.get(field)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw)
    contracts = step.get("contracts", {}) or {}
    for contract_key in (key, f"{key}s"):
        contract_raw = contracts.get(contract_key)
        if isinstance(contract_raw, str):
            values.append(contract_raw)
        elif isinstance(contract_raw, list):
            values.extend(str(item) for item in contract_raw)
    artifact_path = step.get("artifact_path")
    if isinstance(artifact_path, str) and key in {"produces", "produce"}:
        values.append(artifact_path)
    return [_normalize_path(v) for v in values if v]


def _drift_exempt(step_id: str, node: dict[str, Any], declared: bool, derived: bool, policy: dict[str, Any]) -> bool:
    if declared == derived:
        return True
    exempt = policy.get("drift_exempt", {}) or {}
    if not declared and derived:
        node_type = str(node.get("node_type", ""))
        if node_type in set(exempt.get("output_assembly_node_types", [])):
            return True
        for pattern in exempt.get("output_assembly_step_patterns", []):
            if fnmatch.fnmatch(step_id, pattern):
                return True
    return False


def build_step_id_index(root: Path) -> dict[str, str]:
    pipeline = _load_yaml(root / "docs" / "daily_pipeline_registry.yaml")
    index: dict[str, str] = {}
    for step_id, step in (pipeline.get("steps", {}) or {}).items():
        index[step_id] = step_id
        command = str(step.get("command", ""))
        if "scripts/" not in command:
            continue
        script = command.split("scripts/", 1)[1].split()[0]
        stem = Path(script).stem
        for key in (stem, f"scripts/{script}", script):
            current = index.get(key)
            if current is None or current.endswith("_refresh"):
                index[key] = step_id
    return index


WORK_CYCLE_STEP_ALIASES = {
    "build_change_analysis": "change_analysis",
    "run_supervisor_check": "supervisor_check",
    "daily_run": "daily_pipeline",
}


def normalize_step_name(raw: str, index: dict[str, str]) -> str:
    name = raw.strip()
    if name in index:
        return index[name]
    if name.startswith("scripts/"):
        stem = Path(name).stem
        if stem in WORK_CYCLE_STEP_ALIASES:
            return WORK_CYCLE_STEP_ALIASES[stem]
        return index.get(name, index.get(stem, name))
    stem = Path(name).stem if "/" in name else name
    if stem in WORK_CYCLE_STEP_ALIASES:
        return WORK_CYCLE_STEP_ALIASES[stem]
    return index.get(name, index.get(stem, name))


def build_authority_graph(root: Path) -> dict[str, Any]:
    pipeline = _load_yaml(root / "docs" / "daily_pipeline_registry.yaml")
    policy = _load_yaml(root / "governance" / "authority_graph_policy.yaml")
    routing = _load_yaml(root / "governance" / "output_routing_policy.yaml")

    bridge_nodes = list(policy.get("bridge_nodes", ["bridge"]))
    surface_prefixes = [_normalize_path(p) for p in policy.get("surface_path_prefixes", ["Output/current/"])]
    core_prefixes, prohibited_prefixes = _core_chain_prefixes(root, policy)

    steps: dict[str, dict[str, Any]] = pipeline.get("steps", {}) or {}
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    step_produces: dict[str, list[str]] = {}
    step_consumes: dict[str, list[str]] = {}

    for step_id, step in steps.items():
        zone, node_type = _zone_for_step(step_id, policy)
        produces = _collect_paths(step, "produces")
        consumes = _collect_paths(step, "consumes")
        step_produces[step_id] = produces
        step_consumes[step_id] = consumes

        nodes[step_id] = {
            "id": step_id,
            "kind": "pipeline_step",
            "zone": zone,
            "node_type": node_type,
            "owner": str((step.get("authority") or {}).get("owner") or step.get("owner") or ""),
            "order": int(step.get("order") or 0),
            "declared_affects_core": _declared_affects_core(step),
            "bridge_node": step_id in bridge_nodes,
            "produces": produces,
            "consumes": consumes,
        }

        for path in produces:
            artifact = _artifact_id(path)
            if artifact not in nodes:
                nodes[artifact] = {
                    "id": artifact,
                    "kind": "artifact",
                    "zone": _zone_for_artifact(path, policy, routing),
                    "path": path,
                    "in_core_chain": _is_core_chain_path(path, core_prefixes, prohibited_prefixes),
                    "in_surface": _is_surface_path(path, surface_prefixes),
                }
            edges.append({"from": step_id, "to": artifact, "kind": "produces"})
            if step_id in bridge_nodes and nodes[artifact]["zone"] == "Z3":
                edges[-1]["bridge"] = True

    for step_id, consumes in step_consumes.items():
        for consumed in consumes:
            artifact = _artifact_id(consumed)
            if artifact not in nodes:
                nodes[artifact] = {
                    "id": artifact,
                    "kind": "artifact",
                    "zone": _zone_for_artifact(consumed, policy, routing),
                    "path": consumed,
                    "in_core_chain": _is_core_chain_path(consumed, core_prefixes, prohibited_prefixes),
                    "in_surface": _is_surface_path(consumed, surface_prefixes),
                }
            edges.append({"from": artifact, "to": step_id, "kind": "consumes"})

    for producer_id, produces in step_produces.items():
        for consumer_id, consumes in step_consumes.items():
            if producer_id == consumer_id:
                continue
            if any(_path_matches(p, c) for p in produces for c in consumes):
                edges.append({"from": producer_id, "to": consumer_id, "kind": "data_flow"})

    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    for edge in edges:
        out_degree[edge["from"]] += 1
        in_degree[edge["to"]] += 1

    drift: list[dict[str, Any]] = []
    exempt_drift: list[dict[str, Any]] = []
    core_capable_steps: list[str] = []

    for step_id, node in nodes.items():
        if node.get("kind") != "pipeline_step":
            continue
        produces = node.get("produces", [])
        derived_core = any(
            _is_core_chain_path(path, core_prefixes, prohibited_prefixes) for path in produces
        )
        reaches_surface = any(_is_surface_path(path, surface_prefixes) for path in produces)

        node["graph_derived_affects_core"] = derived_core
        node["graph_reaches_current_surface"] = reaches_surface
        node["in_degree"] = in_degree.get(step_id, 0)
        node["out_degree"] = out_degree.get(step_id, 0)
        if derived_core:
            core_capable_steps.append(step_id)

        declared = bool(node.get("declared_affects_core"))
        if declared != derived_core:
            item = {
                "step_id": step_id,
                "declared_affects_core": declared,
                "graph_derived_affects_core": derived_core,
                "graph_reaches_current_surface": reaches_surface,
            }
            if _drift_exempt(step_id, node, declared, derived_core, policy):
                exempt_drift.append(item)
            else:
                drift.append(item)

    violations: list[dict[str, Any]] = []
    for edge in edges:
        if edge.get("kind") != "produces":
            continue
        from_node = nodes.get(edge["from"], {})
        to_node = nodes.get(edge["to"], {})
        if from_node.get("kind") != "pipeline_step" or to_node.get("kind") != "artifact":
            continue
        if to_node.get("zone") != "Z3":
            continue
        consumes_sandbox = any(
            str(path).startswith("Output/sandbox")
            for path in from_node.get("consumes", [])
        )
        if consumes_sandbox and not from_node.get("bridge_node"):
            violations.append(
                {
                    "id": "bridge_singleton",
                    "severity": "high",
                    "message": (
                        f"Step '{edge['from']}' writes to Z3 surface but is not a declared bridge node"
                    ),
                }
            )
        if from_node.get("zone") == "Z_inf" and not from_node.get("bridge_node"):
            violations.append(
                {
                    "id": "sandbox_requires_bridge",
                    "severity": "high",
                    "message": (
                        f"Experimental-zone step '{edge['from']}' writes directly to Z3 surface"
                    ),
                }
            )

    for item in drift:
        violations.append(
            {
                "id": "declared_derived_alignment",
                "severity": "medium",
                "message": (
                    f"Step '{item['step_id']}' declared_affects_core="
                    f"{item['declared_affects_core']} but graph_derived="
                    f"{item['graph_derived_affects_core']}"
                ),
            }
        )

    high_severity = [v for v in violations if v.get("severity") == "high"]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": [
            "docs/daily_pipeline_registry.yaml",
            "governance/authority_graph_policy.yaml",
            "governance/output_routing_policy.yaml",
            "governance/system_constitution.yaml",
        ],
        "core_chain_prefixes": core_prefixes,
        "zones": policy.get("zones", {}),
        "bridge_nodes": bridge_nodes,
        "surface_path_prefixes": surface_prefixes,
        "nodes": list(nodes.values()),
        "edges": edges,
        "invariants": {
            "valid": len(high_severity) == 0,
            "violations": violations,
        },
        "drift": {
            "declared_derived_mismatches": drift,
            "exempt_mismatches": exempt_drift,
        },
        "metrics": {
            "pipeline_step_count": sum(1 for n in nodes.values() if n.get("kind") == "pipeline_step"),
            "artifact_node_count": sum(1 for n in nodes.values() if n.get("kind") == "artifact"),
            "edge_count": len(edges),
            "core_capable_step_count": len(core_capable_steps),
            "core_capable_steps": sorted(core_capable_steps),
            "drift_count": len(drift),
            "exempt_drift_count": len(exempt_drift),
        },
    }


def load_authority_graph(root: Path, *, build_if_missing: bool = True) -> dict[str, Any] | None:
    path = root / DEFAULT_OUTPUT
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Failed to load authority graph from %s", path, exc_info=True)
    if not build_if_missing:
        return None
    graph = build_authority_graph(root)
    write_authority_graph(graph, root)
    return graph


def write_authority_graph(graph: dict[str, Any], root: Path) -> Path:
    output_path = root / DEFAULT_OUTPUT
    ensure_dir(output_path.parent)
    output_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output_path


def _index_nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in graph.get("nodes", []) if node.get("id")}


def step_graph_derived_affects_core(graph: dict[str, Any], step_id: str) -> bool:
    node = _index_nodes(graph).get(step_id, {})
    return bool(node.get("graph_derived_affects_core"))


def graph_credit_metrics(graph: dict[str, Any], completed_steps: set[str]) -> dict[str, Any]:
    nodes = _index_nodes(graph)
    active = [nodes[s] for s in completed_steps if s in nodes and nodes[s].get("kind") == "pipeline_step"]
    if not active:
        return {
            "completed_pipeline_steps": 0,
            "core_capable_completed": 0,
            "total_in_degree": 0,
        }
    return {
        "completed_pipeline_steps": len(active),
        "core_capable_completed": sum(1 for n in active if n.get("graph_derived_affects_core")),
        "total_in_degree": sum(int(n.get("in_degree", 0)) for n in active),
    }


def runtime_can_affect_core_judgment(
    graph: dict[str, Any],
    *,
    promotion_gate_pass: bool,
    trace_complete: bool,
    completed_steps: set[str] | None = None,
) -> dict[str, Any]:
    """Runtime authority: graph topology + gate state + trace completeness."""
    core_steps = set(graph.get("metrics", {}).get("core_capable_steps", []))
    if completed_steps is None:
        core_completed = core_steps
    else:
        core_completed = core_steps & completed_steps

    graph_allows = bool(core_completed) and graph.get("invariants", {}).get("valid", False)
    allowed = promotion_gate_pass and trace_complete and graph_allows

    return {
        "allowed": allowed,
        "promotion_gate_pass": promotion_gate_pass,
        "trace_complete": trace_complete,
        "graph_invariants_valid": graph.get("invariants", {}).get("valid", False),
        "core_capable_steps_completed": sorted(core_completed),
        "blocking_reasons": _runtime_blocking_reasons(
            promotion_gate_pass=promotion_gate_pass,
            trace_complete=trace_complete,
            graph=graph,
            core_completed=core_completed,
        ),
    }


def _runtime_blocking_reasons(
    *,
    promotion_gate_pass: bool,
    trace_complete: bool,
    graph: dict[str, Any],
    core_completed: set[str],
) -> list[str]:
    reasons: list[str] = []
    if not promotion_gate_pass:
        reasons.append("promotion_gate_not_pass")
    if not trace_complete:
        reasons.append("run_trace_incomplete")
    if not graph.get("invariants", {}).get("valid", True):
        reasons.append("authority_graph_invariants_failed")
    if not core_completed:
        reasons.append("no_core_capable_pipeline_steps_completed")
    return reasons


def completed_steps_from_run(root: Path) -> set[str]:
    pointer = root / "Output" / "current" / "latest_run_id.txt"
    if not pointer.exists():
        return set()
    run_id = pointer.read_text(encoding="utf-8").strip()
    if not run_id:
        return set()
    steps_path = root / "Output" / "runs" / run_id / "steps.jsonl"
    if not steps_path.exists():
        return set()

    index = build_step_id_index(root)
    completed: set[str] = set()
    for line in steps_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("status") != "success":
            continue
        raw_step = payload.get("step") or payload.get("name") or payload.get("script")
        if raw_step:
            completed.add(normalize_step_name(str(raw_step), index))
    return completed
