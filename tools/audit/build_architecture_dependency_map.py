"""Build the machine-readable Step 1 architecture dependency map.

The map is deliberately independent of import-time behavior. It parses every
Python source file in the declared workspace surfaces, resolves workspace
imports where possible, and records unresolved imports as external edges. The
result is an observation artifact; it does not import application modules or
run the daily pipeline.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SourceSurface:
    root: Path
    module_prefix: str
    layer: str
    kind: str


@dataclass(frozen=True)
class ModuleInfo:
    module: str
    path: str
    layer: str
    kind: str


@dataclass(frozen=True)
class ImportRef:
    imported: str
    line: int
    resolved: str | None


SURFACES = (
    SourceSurface(Path("system_runtime"), "system_runtime", "core", "production"),
    SourceSurface(Path("system_cli"), "system_cli", "application", "production"),
    SourceSurface(Path("verity/cli"), "verity.cli", "application", "production"),
    SourceSurface(Path("verity/runtime"), "verity.runtime", "application_runtime", "production"),
    SourceSurface(Path("packages/orchestration/orchestration"), "orchestration", "orchestration", "production"),
    SourceSurface(Path("packages/harvester/src/harvester"), "harvester", "domain", "production"),
    SourceSurface(Path("packages/learning_hub/src/system_learning"), "system_learning", "domain", "production"),
    SourceSurface(Path("packages/workbench/src/workbench"), "workbench", "domain", "production"),
    SourceSurface(Path("packages/workbench/src/strategy_lab"), "strategy_lab", "domain", "production"),
    SourceSurface(Path("packages/workbench/src/benchmarks"), "benchmarks", "domain", "production"),
    SourceSurface(Path("packages/workbench/src/ml"), "ml", "domain", "production"),
    SourceSurface(Path("packages/workbench/src/nlp"), "nlp", "domain", "production"),
    SourceSurface(
        Path("paper-empirical-interface/src/paper_interface"),
        "paper_interface",
        "domain",
        "production",
    ),
    SourceSurface(Path("caselab_context"), "caselab_context", "domain", "production"),
    SourceSurface(Path("caselab_runtime"), "caselab_runtime", "domain", "production"),
    SourceSurface(Path("packages/workbench/agents"), "agents", "tools", "tools"),
    SourceSurface(Path("packages/learning_hub/run_hub.py"), "learning_hub.run_hub", "compatibility", "compatibility"),
    SourceSurface(Path("packages/learning_hub/scripts"), "learning_hub_scripts", "compatibility", "compatibility"),
    SourceSurface(Path("scripts"), "scripts", "compatibility", "compatibility"),
    SourceSurface(Path("tools"), "tools", "tools", "tools"),
    SourceSurface(Path("ExternalTools/qlib_benchmark_runner"), "qlib_benchmark_runner", "tools", "tools"),
    SourceSurface(Path("packages/framework_v1_archive/src"), "archive", "archive", "archive"),
    SourceSurface(Path("packages/framework_v1_archive/scripts"), "archive_scripts", "archive", "archive"),
    SourceSurface(Path("governance/archive"), "governance_archive", "archive", "archive"),
    SourceSurface(Path("tests"), "tests", "tests", "tests"),
    SourceSurface(Path("paper-empirical-interface/tests"), "tests.paper_interface", "tests", "tests"),
    SourceSurface(
        Path("ExternalTools/qlib_benchmark_runner/tests"),
        "tests.qlib_benchmark_runner",
        "tests",
        "tests",
    ),
    SourceSurface(
        Path("packages/framework_v1_archive/tests"),
        "tests.framework_archive",
        "tests",
        "tests",
    ),
    SourceSurface(Path("packages/harvester/tests"), "tests.harvester", "tests", "tests"),
    SourceSurface(Path("packages/learning_hub/tests"), "tests.learning_hub", "tests", "tests"),
    SourceSurface(Path("packages/orchestration/tests"), "tests.orchestration", "tests", "tests"),
    SourceSurface(Path("packages/workbench/tests"), "tests.workbench", "tests", "tests"),
)

FOCUS_BOUNDARIES = (
    {
        "name": "verity ↔ orchestration",
        "left_prefixes": ("verity",),
        "right_prefixes": ("orchestration",),
        "category": "application_callback",
        "owner": "Orchestration",
        "rationale": "The application adapter triggers orchestration and must receive results through an explicit callback or protocol.",
    },
    {
        "name": "verity ↔ workbench",
        "left_prefixes": ("verity",),
        "right_prefixes": ("workbench", "strategy_lab"),
        "category": "shared_core_contract",
        "owner": "System runtime",
        "rationale": "Shared runtime/path and admission contracts must move down to system_runtime; an adapter import must not become domain ownership.",
    },
    {
        "name": "workbench ↔ orchestration",
        "left_prefixes": ("workbench", "strategy_lab"),
        "right_prefixes": ("orchestration",),
        "category": "temporary_compatibility",
        "owner": "Orchestration",
        "rationale": "Current reverse edges are registered ARCH-004 migration debt and must reduce as orchestration contracts replace implementation imports.",
    },
)


def _source_files(surface: SourceSurface, root: Path) -> Iterable[tuple[Path, str]]:
    base = root / surface.root
    if not base.exists():
        return
    if base.is_file():
        yield base, surface.module_prefix
        return
    ignored_directories = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "site-packages",
        "venv",
    }
    for path in sorted(base.rglob("*.py")):
        if any(part in ignored_directories or part.endswith(".egg-info") for part in path.relative_to(base).parts):
            continue
        relative = path.relative_to(base)
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts.pop()
        else:
            parts[-1] = path.stem
        suffix = ".".join(parts)
        module = surface.module_prefix + (f".{suffix}" if suffix else "")
        yield path, module


def collect_modules(root: Path = ROOT) -> dict[str, ModuleInfo]:
    modules: dict[str, ModuleInfo] = {}
    for surface in SURFACES:
        for path, module in _source_files(surface, root):
            relative = path.relative_to(root).as_posix()
            modules.setdefault(module, ModuleInfo(module, relative, surface.layer, surface.kind))
    return modules


def _resolve_relative(module: str, imported: str, level: int) -> str:
    package = module if module.endswith(".__init__") else module.rsplit(".", 1)[0]
    relative = "." * level + imported
    return importlib.util.resolve_name(relative, package)


def _raw_imports(tree: ast.AST, module: str) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                try:
                    base = _resolve_relative(module, base, node.level)
                except (ImportError, ValueError):
                    base = f"<relative:{node.level}>.{base}".rstrip(".")
            yield base, node.lineno


def resolve_module(imported: str, modules: dict[str, ModuleInfo]) -> str | None:
    if not imported or imported.startswith("<relative:"):
        return None
    if imported in modules:
        return imported
    candidate = imported
    while "." in candidate:
        candidate = candidate.rsplit(".", 1)[0]
        if candidate in modules:
            return candidate
    return None


def _matches_prefix(module: str, prefixes: Iterable[str]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def _parse_imports(path: Path, module: str, modules: dict[str, ModuleInfo]) -> tuple[list[ImportRef], str | None]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    refs = [ImportRef(imported, line, resolve_module(imported, modules)) for imported, line in _raw_imports(tree, module)]
    return refs, None


def _tarjan(adjacency: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency.get(node, ())):
            if target not in indices:
                strongconnect(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for node in sorted(adjacency):
        if node not in indices:
            strongconnect(node)
    return sorted(components, key=lambda item: item[0])


def _cycle_classification(nodes: list[str], modules: dict[str, ModuleInfo]) -> dict[str, Any]:
    layers = sorted({modules[node].layer for node in nodes})
    if "compatibility" in layers or "archive" in layers:
        category = "temporary_compatibility"
        owner = "Architecture migration"
        rationale = "The cycle crosses a retained compatibility or archive boundary and is removable after parity evidence."
    elif layers == ["core"]:
        category = "shared_core_contract"
        owner = "System runtime"
        rationale = "The cycle is internal to core; extract a stable contract rather than hiding it with a lazy import."
    elif "application" in layers and ("domain" in layers or "orchestration" in layers):
        category = "application_callback"
        owner = "Orchestration"
        rationale = "The application side of the cycle must expose a callback or protocol owned by a lower layer."
    else:
        category = "error_ownership"
        owner = "Architecture migration"
        rationale = "The cycle crosses ownership boundaries without an approved callback or shared core contract."
    return {
        "nodes": nodes,
        "layers": layers,
        "category": category,
        "owner": owner,
        "rationale": rationale,
    }


def _focus_boundary_report(
    edges: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reports = []
    for boundary in FOCUS_BOUNDARIES:
        left = tuple(boundary["left_prefixes"])
        right = tuple(boundary["right_prefixes"])
        forward = [
            edge
            for edge in edges
            if _matches_prefix(edge["source"], left) and _matches_prefix(edge["target"], right)
        ]
        reverse = [
            edge
            for edge in edges
            if _matches_prefix(edge["source"], right) and _matches_prefix(edge["target"], left)
        ]
        cross_boundary_cycles = [
            cycle["nodes"]
            for cycle in cycles
            if any(_matches_prefix(node, left) for node in cycle["nodes"])
            and any(_matches_prefix(node, right) for node in cycle["nodes"])
        ]
        reports.append(
            {
                "name": boundary["name"],
                "left_prefixes": list(left),
                "right_prefixes": list(right),
                "forward_edge_count": len(forward),
                "reverse_edge_count": len(reverse),
                "has_bidirectional_dependency": bool(forward and reverse),
                "strongly_connected_components": cross_boundary_cycles,
                "category": boundary["category"],
                "owner": boundary["owner"],
                "rationale": boundary["rationale"],
            }
        )
    return reports


def _contract_report(root: Path) -> dict[str, Any]:
    scanner_path = root / "tools" / "audit" / "architecture_invariants.py"
    spec = importlib.util.spec_from_file_location("_verity_architecture_invariants", scanner_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load architecture scanner: {scanner_path}")
    scanner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = scanner
    spec.loader.exec_module(scanner)
    report = scanner.scan_architecture(root)
    contract = yaml.safe_load((root / "governance/architecture_contract.yaml").read_text(encoding="utf-8")) or {}
    debt_by_id = {str(entry["id"]): entry for entry in (contract.get("temporary_debt", {}).get("entries", []) or [])}
    violations = []
    for item in report.violations:
        payload = item.as_dict()
        debt = debt_by_id.get(str(item.debt_id)) if item.debt_id else None
        payload["registered"] = bool(debt)
        payload["owner"] = debt.get("owner") if debt else None
        payload["migration_target"] = debt.get("migration_target") if debt else None
        violations.append(payload)
    return {
        "status": report.status,
        "registered_debt_count": len(report.violations) - len(report.unregistered),
        "unregistered_violation_count": len(report.unregistered),
        "all_existing_violations_have_owner": all(item["owner"] for item in violations),
        "violations": violations,
    }


def build_map(root: Path = ROOT, *, baseline_core_violations: int = 0, baseline_registered_violations: int = 22) -> dict[str, Any]:
    modules = collect_modules(root)
    refs_by_module: dict[str, list[ImportRef]] = {}
    syntax_failures: list[dict[str, str]] = []
    edge_occurrences: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    external_counts: Counter[str] = Counter()
    adjacency: dict[str, set[str]] = {module: set() for module in modules}

    for module, info in sorted(modules.items()):
        refs, error = _parse_imports(root / info.path, module, modules)
        refs_by_module[module] = refs
        if error:
            syntax_failures.append({"module": module, "path": info.path, "error": error})
        for ref in refs:
            if ref.resolved is None:
                external_counts[ref.imported] += 1
                continue
            adjacency[module].add(ref.resolved)
            edge_occurrences[(module, ref.resolved)].append({"line": ref.line, "imported": ref.imported})

    edges = []
    for (source, target), occurrences in sorted(edge_occurrences.items()):
        edges.append({
            "source": source,
            "target": target,
            "source_layer": modules[source].layer,
            "target_layer": modules[target].layer,
            "occurrences": sorted(occurrences, key=lambda item: (item["line"], item["imported"])),
        })

    production_layers = {"core", "application", "application_runtime", "orchestration", "domain", "tools"}
    package_to_scripts = [
        edge for edge in edges
        if edge["source_layer"] in production_layers
        and edge["target_layer"] == "compatibility"
        and edge["target"].startswith("scripts")
    ]
    layer_counts = Counter(info.layer for info in modules.values())
    layer_edges = Counter((edge["source_layer"], edge["target_layer"]) for edge in edges)
    cycles = [_cycle_classification(nodes, modules) for nodes in _tarjan(adjacency)]
    focus_boundaries = _focus_boundary_report(edges, cycles)
    violations = _contract_report(root)
    current_core = sum(
        1 for item in violations["violations"] if item["rule_id"] in {"ARCH-002", "ARCH-003"}
    )
    current_registered = int(violations["registered_debt_count"])
    gate = {
        "architecture_dag_written_to_test": (root / "tests/test_architecture_dependency_map.py").exists(),
        "all_existing_violations_have_owner": bool(violations["all_existing_violations_have_owner"]),
        "production_package_to_scripts_count": len(package_to_scripts),
        "no_production_package_to_scripts": not package_to_scripts,
        "baseline_core_to_orchestration_domain_count": baseline_core_violations,
        "current_core_to_orchestration_domain_count": current_core,
        "core_direction_not_increased": current_core <= baseline_core_violations,
        "baseline_registered_violation_count": baseline_registered_violations,
        "current_registered_violation_count": current_registered,
        "registered_debt_not_expanded": current_registered <= baseline_registered_violations,
        "all_cycles_classified": all(cycle["category"] for cycle in cycles),
        "focus_boundaries_classified": all(
            boundary["category"] and boundary["owner"] for boundary in focus_boundaries
        ),
    }
    boolean_gate_values = [value for value in gate.values() if isinstance(value, bool)]
    gate["status"] = "PASS" if all(boolean_gate_values) else "BLOCKED"

    nodes_payload = [
        {
            "module": info.module,
            "path": info.path,
            "layer": info.layer,
            "kind": info.kind,
            "imports": [
                {"module": ref.imported, "line": ref.line, "resolved": ref.resolved}
                for ref in refs_by_module[module]
            ],
        }
        for module, info in sorted(modules.items())
    ]
    return {
        "schema_version": "architecture.import_graph.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "layers": ["core", "application", "application_runtime", "orchestration", "domain", "compatibility", "tools", "archive", "tests"],
        "source_surfaces": [
            {
                "root": surface.root.as_posix(),
                "module_prefix": surface.module_prefix,
                "layer": surface.layer,
                "kind": surface.kind,
            }
            for surface in SURFACES
        ],
        "node_count": len(nodes_payload),
        "edge_count": len(edges),
        "layer_node_counts": dict(sorted(layer_counts.items())),
        "nodes": nodes_payload,
        "edges": edges,
        "layer_edges": [
            {"source_layer": source, "target_layer": target, "edge_count": count}
            for (source, target), count in sorted(layer_edges.items())
        ],
        "external_import_counts": dict(external_counts.most_common()),
        "syntax_failures": syntax_failures,
        "cycles": cycles,
        "focus_boundaries": focus_boundaries,
        "package_to_scripts_edges": package_to_scripts,
        "gate": gate,
    }


def _violations_payload(graph: dict[str, Any], root: Path) -> dict[str, Any]:
    contract = _contract_report(root)
    rule_counts = Counter(item["rule_id"] for item in contract["violations"])
    owner_counts = Counter(str(item["owner"]) for item in contract["violations"] if item["owner"])
    return {
        "schema_version": "architecture.violations.v1",
        "generated_at": graph["generated_at"],
        "scanner": "tools/audit/architecture_invariants.py",
        "contract_report": contract,
        "rule_counts": dict(sorted(rule_counts.items())),
        "owner_counts": dict(sorted(owner_counts.items())),
        "package_to_scripts_edges": graph["package_to_scripts_edges"],
        "cycles": graph["cycles"],
        "focus_boundaries": graph["focus_boundaries"],
        "gate": graph["gate"],
    }


def _markdown(graph: dict[str, Any], violations: dict[str, Any]) -> str:
    lines = [
        "# Current Architecture Dependency Map",
        "",
        f"- Generated at: {graph['generated_at']}",
        f"- Nodes: {graph['node_count']}; internal edges: {graph['edge_count']}",
        f"- Gate: **{graph['gate']['status']}**",
        "",
        "## Layer inventory",
        "",
        "| Layer | Python modules |",
        "|---|---:|",
    ]
    for layer, count in graph["layer_node_counts"].items():
        lines.append(f"| {layer} | {count} |")
    lines += ["", "## Cross-layer edges", "", "| Source | Target | Edges |", "|---|---|---:|"]
    for item in graph["layer_edges"]:
        if item["source_layer"] != item["target_layer"]:
            lines.append(f"| {item['source_layer']} | {item['target_layer']} | {item['edge_count']} |")
    lines += [
        "",
        "## Architecture violations",
        "",
        f"- Registered violations: {violations['contract_report']['registered_debt_count']}",
        f"- Unregistered violations: {violations['contract_report']['unregistered_violation_count']}",
        f"- All current violations have an owner: {violations['contract_report']['all_existing_violations_have_owner']}",
        "",
        "| Rule | Count |",
        "|---|---:|",
    ]
    for rule, count in violations["rule_counts"].items():
        lines.append(f"| {rule} | {count} |")
    lines += [
        "",
        "## Package to scripts",
        "",
        f"Production package to scripts edges: **{len(graph['package_to_scripts_edges'])}**",
    ]
    if graph["package_to_scripts_edges"]:
        lines += ["", "| Source | Target |", "|---|---|"]
        lines.extend(f"| {edge['source']} | {edge['target']} |" for edge in graph["package_to_scripts_edges"])
    lines += ["", "## Cycles", "", f"Detected strongly connected components: {len(graph['cycles'])}", ""]
    if graph["cycles"]:
        lines += ["| Category | Owner | Nodes |", "|---|---|---:|"]
        for cycle in graph["cycles"]:
            lines.append(f"| {cycle['category']} | {cycle['owner']} | {len(cycle['nodes'])} |")
    else:
        lines.append("No multi-module import cycles were detected.")
    lines += [
        "",
        "## Focused ownership boundaries",
        "",
        "| Boundary | Direct forward edges | Direct reverse edges | SCCs | Category | Owner |",
        "|---|---:|---:|---:|---|---|",
    ]
    for boundary in graph["focus_boundaries"]:
        lines.append(
            f"| {boundary['name']} | {boundary['forward_edge_count']} | "
            f"{boundary['reverse_edge_count']} | {len(boundary['strongly_connected_components'])} | "
            f"{boundary['category']} | {boundary['owner']} |"
        )
    lines += [
        "",
        "## Step 1 gate",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for key, value in graph["gate"].items():
        if key == "status":
            continue
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "This map is structural evidence. It does not promote provider, freshness, publication, or decision authority.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(graph: dict[str, Any], root: Path = ROOT) -> None:
    output = root / "architecture"
    output.mkdir(parents=True, exist_ok=True)
    (output / "import_graph.json").write_text(
        json.dumps(graph, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    violations = _violations_payload(graph, root)
    (output / "violations.json").write_text(
        json.dumps(violations, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "current_dependency_map.md").write_text(_markdown(graph, violations), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-core-violations", type=int, default=0)
    parser.add_argument("--baseline-registered-violations", type=int, default=22)
    args = parser.parse_args(argv)
    graph = build_map(
        ROOT,
        baseline_core_violations=args.baseline_core_violations,
        baseline_registered_violations=args.baseline_registered_violations,
    )
    write_outputs(graph)
    print(json.dumps({
        "status": graph["gate"]["status"],
        "node_count": graph["node_count"],
        "edge_count": graph["edge_count"],
        "cycles": len(graph["cycles"]),
        "package_to_scripts": len(graph["package_to_scripts_edges"]),
    }, sort_keys=True))
    return 0 if graph["gate"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
