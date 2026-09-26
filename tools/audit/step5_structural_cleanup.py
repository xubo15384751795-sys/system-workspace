"""Read-only Step 5 structural-cleanup audit.

This audit inventories the current boundary and default execution path.  It
does not delete, move, regenerate, or restore production Data/Output
artifacts.  The restore preflight may copy one accepted generation into a
temporary isolated directory to prove structural fidelity; it never rewrites
production pointers or elevates authority.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOTS = (
    ROOT / "packages/harvester/src/harvester",
    ROOT / "packages/learning_hub/src/system_learning",
    ROOT / "packages/orchestration/orchestration",
    ROOT / "packages/workbench/src/workbench",
    ROOT / "packages/workbench/src/strategy_lab",
    ROOT / "packages/workbench/src/benchmarks",
    ROOT / "packages/workbench/src/ml",
    ROOT / "packages/workbench/src/nlp",
    ROOT / "caselab_context",
    ROOT / "caselab_runtime",
    ROOT / "verity/runtime",
    ROOT / "verity/cli",
    ROOT / "system_runtime",
    ROOT / "system_cli",
)
PACKAGE_ROOTS = tuple(
    root
    for root in PRODUCTION_ROOTS
    if root != ROOT / "system_cli" and root != ROOT / "verity/cli"
)
OPERATOR_PATH_RE = re.compile(r"/(?:Users|Applications|Volumes|private/var)/")
SCRIPT_CATEGORY_FILES = {
    "scripts/run_daily_scheduled.sh": "production_entrypoint",
    "scripts/run_dagster_daily.sh": "production_entrypoint",
    "scripts/orchestrate.sh": "production_entrypoint",
    "scripts/daily_run.py": "production_entrypoint",
}
MIGRATION_RE = re.compile(r"(?:migrat|repair|promot|sync|reconcile|backfill)", re.I)
GOD_MODULE_CLOSURES = {
    "daily_run": ROOT / "governance/step5a_daily_run_closure.yaml",
    "harvester_official": ROOT / "governance/step5b_harvester_official_closure.yaml",
}


def _iter_python(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            if "__pycache__" not in path.parts and path.is_file():
                yield path


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _imports(tree: ast.AST) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            yield (node.module or "", node.lineno)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    result: set[int] = set()
    for container in ast.walk(tree):
        body = getattr(container, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            result.add(id(first.value))
    return result


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _boundary_scan() -> dict[str, Any]:
    package_script_imports: list[dict[str, Any]] = []
    sys_path_mutations: list[dict[str, Any]] = []
    absolute_operator_paths: list[dict[str, Any]] = []
    for path in _iter_python(PACKAGE_ROOTS):
        relative = _relative(path)
        tree = _parse(path)
        if tree is None:
            continue
        for imported, line in _imports(tree):
            if imported == "scripts" or imported.startswith("scripts."):
                package_script_imports.append(
                    {"path": relative, "line": line, "module": imported}
                )
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                target = node.func
                value = target.value
                if (
                    isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "sys"
                    and value.attr == "path"
                    and target.attr in {"insert", "append", "extend"}
                ):
                    sys_path_mutations.append(
                        {"path": relative, "line": node.lineno, "operation": target.attr}
                    )
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and OPERATOR_PATH_RE.search(node.value)
            ):
                absolute_operator_paths.append(
                    {"path": relative, "line": node.lineno, "value": node.value}
                )
    return {
        "package_to_scripts": package_script_imports,
        "production_sys_path_mutations": sys_path_mutations,
        "production_absolute_operator_paths": absolute_operator_paths,
    }


def _classify_script(path: Path) -> str:
    relative = _relative(path)
    if relative in SCRIPT_CATEGORY_FILES:
        return SCRIPT_CATEGORY_FILES[relative]
    if relative.startswith("scripts/archive/"):
        return "archive"
    try:
        head = path.read_text(encoding="utf-8")[:1200]
    except (OSError, UnicodeDecodeError):
        head = ""
    if "Compatibility shim" in head or "Compatibility wrapper" in head:
        return "compatibility"
    if relative.startswith("scripts/launchd/"):
        return "operator"
    if MIGRATION_RE.search(path.name):
        return "migration"
    if relative.startswith("scripts/commands/") or relative.startswith("scripts/strategy_lab/"):
        return "developer_tooling"
    return "operator"


def _script_inventory() -> dict[str, Any]:
    files = [
        path
        for path in (ROOT / "scripts").rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix in {".py", ".sh"}
    ]
    categories = Counter(_classify_script(path) for path in files)
    examples: dict[str, list[str]] = {}
    for category in sorted(categories):
        examples[category] = sorted(
            _relative(path)
            for path in files
            if _classify_script(path) == category
        )[:12]
    return {
        "file_count": len(files),
        "count_is_not_a_kpi": True,
        "categories": dict(sorted(categories.items())),
        "examples": examples,
    }


def _active_registry_steps() -> list[dict[str, Any]]:
    document = yaml.safe_load(
        (ROOT / "governance/daily_pipeline_registry.yaml").read_text(encoding="utf-8")
    ) or {}
    result: list[dict[str, Any]] = []
    for step_id, step in (document.get("steps") or {}).items():
        if not isinstance(step, dict):
            continue
        if step.get("status", "active") in {"archived", "inactive"}:
            continue
        if str(step.get("schedule", "daily")) == "on_demand":
            continue
        execution = step.get("execution") or {}
        result.append(
            {
                "id": str(step_id),
                "mode": str(execution.get("mode") or "subprocess"),
                "callable": str(execution.get("future_callable") or ""),
                "command": str(step.get("command") or ""),
                "subprocess_justification": str(
                    (document.get("execution_policy") or {})
                    .get("subprocess_justifications", {})
                    .get(str(step_id), "")
                ),
            }
        )
    return result


def _execution_inventory() -> dict[str, Any]:
    steps = _active_registry_steps()
    script_callables = [
        step
        for step in steps
        if step["mode"] == "callable" and step["callable"].startswith("scripts.")
    ]
    subprocess_steps = [step for step in steps if step["mode"] == "subprocess"]
    script_subprocesses = [
        step
        for step in subprocess_steps
        if any(
            token == "scripts" or token.startswith("scripts/")
            for token in step["command"].split()
        )
    ]
    subprocess_metadata_shims = [
        step for step in subprocess_steps if step["callable"].startswith("scripts.")
    ]
    return {
        "active_step_count": len(steps),
        "callable_through_scripts": script_callables,
        "subprocess_steps": subprocess_steps,
        "subprocess_steps_through_scripts": script_subprocesses,
        "subprocess_metadata_shims": subprocess_metadata_shims,
        "default_execution_not_through_shims": not script_callables and not script_subprocesses,
    }


def _registry_authoring_report() -> dict[str, Any]:
    """Run the source-split audit as a separate read-only module process."""
    result = subprocess.run(
        [sys.executable, "-m", "tools.audit.registry_authoring_convergence"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "registry audit failed")
    return json.loads(result.stdout)


def _layout_contract_report() -> dict[str, Any]:
    """Run the non-destructive layout audit as a separate module process."""
    result = subprocess.run(
        [sys.executable, "-m", "tools.audit.layout_contract"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "layout audit failed")
    return json.loads(result.stdout)


def _restore_generation_report() -> dict[str, Any]:
    """Run structural and production restore preflight without touching production output."""
    result = subprocess.run(
        [sys.executable, "-m", "tools.audit.restore_generation_preflight"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or "restore preflight failed"
        )
    return json.loads(result.stdout)


def _god_module_inventory() -> dict[str, Any]:
    targets = {
        "daily_run": {
            "path": "verity/cli/daily_run.py",
            "split_targets": [
                "verity/cli/daily_application.py",
                "verity/cli/run_coordinator.py",
                "verity/cli/publication_coordinator.py",
                "verity/cli/post_run_sinks.py",
                "verity/cli/schedule_admission.py",
            ],
        },
        "harvester_official": {
            "path": "packages/harvester/src/harvester/official.py",
            "split_targets": [
                "packages/harvester/src/harvester/provider_catalog.py",
                "packages/harvester/src/harvester/provider_routing.py",
                "packages/harvester/src/harvester/acquisition.py",
                "packages/harvester/src/harvester/normalization.py",
                "packages/harvester/src/harvester/provenance.py",
                "packages/harvester/src/harvester/release.py",
                "packages/harvester/src/harvester/canonical.py",
            ],
        },
        "daily_pipeline_registry": {
            "path": "governance/daily_pipeline_registry.yaml",
            "split_targets": [
                "governance/pipeline/topology.yaml",
                "governance/pipeline/execution_profiles.yaml",
                "governance/pipeline/monitoring.yaml",
                "governance/pipeline/freshness.yaml",
                "governance/pipeline/ownership.yaml",
                "governance/pipeline/schedule_metadata.yaml",
            ],
        },
    }
    for name, item in targets.items():
        path = ROOT / item["path"]
        item["line_count"] = len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else None
        item["split_targets_present"] = [
            target for target in item["split_targets"] if (ROOT / target).exists()
        ]
        closure_status = "NOT_PROVEN"
        if name == "daily_pipeline_registry":
            try:
                closure_status = (
                    "PASS"
                    if _registry_authoring_report()["status"] == "PASS"
                    else "NOT_PROVEN"
                )
            except (OSError, RuntimeError, ValueError, KeyError):
                closure_status = "NOT_PROVEN"
        else:
            closure_path = GOD_MODULE_CLOSURES.get(name)
        if name != "daily_pipeline_registry" and closure_path is not None and closure_path.exists():
            try:
                closure = yaml.safe_load(closure_path.read_text(encoding="utf-8")) or {}
                gate_status = str((closure.get("gate") or {}).get("status") or "")
                closure_status = "PASS" if gate_status == "PASS" else "NOT_PROVEN"
            except (OSError, yaml.YAMLError):
                closure_status = "NOT_PROVEN"
        item["parity_status"] = closure_status
    return targets


def _layout_inventory() -> dict[str, Any]:
    audit = _layout_contract_report()
    symlinks: list[dict[str, str]] = []
    for path in ROOT.rglob("*"):
        if any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        if path.is_symlink():
            try:
                symlinks.append({"path": _relative(path), "target": str(path.readlink())})
            except OSError:
                pass
    return {
        "build_present": (ROOT / "build").exists(),
        "dist_present": (ROOT / "dist").exists(),
        "source_archive": "packages/framework_v1_archive",
        "symlink_count_outside_runtime_caches": len(symlinks),
        "symlinks_sample": symlinks[:20],
        "contract": "governance/layout_contract.yaml",
        "audit": "tools/audit/layout_contract.py",
        "audit_status": audit["status"],
        "classification_counts": audit["classification_counts"],
        "status": "CONTRACT_PASS_WITHOUT_CLEANUP"
        if audit["status"] == "PASS"
        else "AUDIT_FAILED",
    }


def build_report() -> dict[str, Any]:
    boundaries = _boundary_scan()
    execution = _execution_inventory()
    god_modules = _god_module_inventory()
    registry_authoring = _registry_authoring_report()
    layout = _layout_inventory()
    restore_generation = _restore_generation_report()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    structural_restore = restore_generation.get("structural_restore") or {}
    production_restore = restore_generation.get("production_restore") or {}
    structural_restore_status = str(structural_restore.get("status") or "NOT_PROVEN")
    production_restore_status = str(production_restore.get("status") or "NOT_PROVEN")
    gate = {
        "package_to_scripts": "PASS" if not boundaries["package_to_scripts"] else "FAIL",
        "production_sys_path_mutation": "PASS"
        if not boundaries["production_sys_path_mutations"]
        else "FAIL",
        "production_absolute_operator_path": "PASS"
        if not boundaries["production_absolute_operator_paths"]
        else "FAIL",
        "canonical_verity_entrypoint": "PASS"
        if project["scripts"].get("verity") == "verity.cli:main"
        else "FAIL",
        "legacy_cli_is_compatibility_alias": "PASS"
        if project["scripts"].get("system") == "system_cli.app:main"
        else "FAIL",
        "default_execution_not_through_shims": "PASS"
        if execution["default_execution_not_through_shims"]
        else "FAIL",
        "god_module_behavior_parity": (
            "PASS"
            if all(item["parity_status"] == "PASS" for item in god_modules.values())
            else "NOT_PROVEN"
        ),
        "layout_contract": layout["audit_status"],
        # Step 5 owns fidelity of an isolated structural restore.  Production
        # authority restore is deliberately reported separately and carried to
        # Step 6; it must not turn a structural PASS into a failure or vice
        # versa.
        "restore_generation": "PASS"
        if structural_restore_status == "PASS"
        else structural_restore_status,
        "production_authority_restore": (
            "DEFERRED_STEP6"
            if production_restore_status == "BLOCKED_NO_ELIGIBLE_PRODUCTION_TARGET"
            else production_restore_status
        ),
    }
    structural_gate_values = [
        value for key, value in gate.items() if key != "production_authority_restore"
    ]
    if all(value == "PASS" for value in structural_gate_values):
        overall = (
            "COMPLETE_WITH_PRODUCTION_RESTORE_DEFERRED"
            if production_restore_status == "BLOCKED_NO_ELIGIBLE_PRODUCTION_TARGET"
            else "COMPLETE"
        )
    else:
        overall = "IN_PROGRESS"
    return {
        "schema_version": "governance.step5_structural_cleanup.v2",
        "step": 5,
        "status": overall,
        "scope": "structural_cleanup_only",
        "data_output_cleanup": "DEFERRED_PENDING_EXACT_TARGET_AND_HUMAN_APPROVAL",
        "gate": gate,
        "boundaries": boundaries,
        "scripts": _script_inventory(),
        "execution": execution,
        "god_modules": god_modules,
        "registry_authoring": registry_authoring,
        "build_generated_layout": layout,
        "restore_generation_preflight": restore_generation,
        "production_authority_restore": {
            "status": production_restore_status,
            "owner": "Step 6 production recovery / target-environment proof",
            "not_proven": production_restore_status
            == "BLOCKED_NO_ELIGIBLE_PRODUCTION_TARGET",
            "authority_rule_unchanged": bool(
                production_restore.get("authority_rule_unchanged", True)
            ),
            "decision_consumers_required": bool(
                production_restore.get("decision_consumers_required", True)
            ),
        },
        "canonical_entrypoint": project["scripts"].get("verity"),
        "compatibility_entrypoint": project["scripts"].get("system"),
        "notes": [
            "The script count is an inventory signal, not a cleanup KPI.",
            "Provider admission, reliability qualification, and LaunchAgent reconciliation are outside this gate.",
            "No Data/Output deletion, clean, reset, stash, production restore, or production pointer rewrite was performed; the restore preflight only used an isolated temporary structural drill.",
            "Structural restore fidelity PASS does not imply production-authority restore PASS.",
        ],
    }


def main() -> int:
    print(json.dumps(build_report(), indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
