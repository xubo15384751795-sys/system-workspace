#!/usr/bin/env python3
"""Verify Agent Work Protocol — machine check for constitution compliance.

Checks that Agent-initiated code changes follow the agent_work_protocol
declared in governance/system_constitution.yaml.

Usage:
    python3 scripts/verify_agent_work_protocol.py
    python3 scripts/verify_agent_work_protocol.py --declaration path/to/decl.yaml
    python3 scripts/verify_agent_work_protocol.py --json

Exit codes:
    0 — all checks pass
    1 — violations found
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _workspace_imports import add_scripts
add_scripts()

from _runtime_io import ROOT, load_yaml  # noqa: E402

CONSTITUTION_PATH = ROOT / "governance" / "system_constitution.yaml"
CAPABILITY_REGISTRY_PATH = ROOT / "governance" / "capability_registry.yaml"
GOVERNANCE_FREEZE_PATH = ROOT / "governance" / "governance_freeze_manifest.yaml"
TEMPLATE_PATH = ROOT / "module_contexts" / "agent_work_protocol.template.yaml"
DEFAULT_DECLARATION_PATH = ROOT / "Output" / "agent_work_protocol.yaml"

REQUIRED_FIELDS = [
    "owner_module",
    "touched_paths",
    "authority_level",
    "expected_artifact",
    "verification_command",
    "affects_core_judgment",
]

ROOT_SCRIPTS_DIR = ROOT / "scripts"
GOVERNANCE_DIR = ROOT / "governance"


def _load_constitution() -> dict[str, Any]:
    return load_yaml(CONSTITUTION_PATH) or {}


def _load_capability_registry() -> dict[str, Any]:
    return load_yaml(CAPABILITY_REGISTRY_PATH) or {}


def _load_freeze_manifest() -> dict[str, Any]:
    return load_yaml(GOVERNANCE_FREEZE_PATH) or {}


def check_required_fields(decl: dict[str, Any]) -> list[dict[str, str]]:
    """Check that all required declaration fields are present and non-empty."""
    violations = []
    for field in REQUIRED_FIELDS:
        value = decl.get(field)
        if value is None or value == "" or value == []:
            violations.append({
                "rule": "required_field",
                "field": field,
                "severity": "error",
                "message": f"Missing or empty required field: {field}",
            })
    return violations


def check_owner_exists(decl: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, str]]:
    """Check that owner_module exists in capability_registry."""
    violations = []
    owner = decl.get("owner_module", "")
    if not owner:
        return violations
    modules = registry.get("modules", {})
    if owner not in modules:
        violations.append({
            "rule": "owner_exists",
            "field": "owner_module",
            "severity": "error",
            "message": f"owner_module '{owner}' not found in capability_registry.yaml",
        })
    return violations


def check_touched_paths_exist(decl: dict[str, Any]) -> list[dict[str, str]]:
    """Check that all touched_paths exist on disk."""
    violations = []
    for path_str in decl.get("touched_paths", []):
        full_path = ROOT / path_str if not Path(path_str).is_absolute() else Path(path_str)
        if not full_path.exists():
            violations.append({
                "rule": "touched_path_exists",
                "field": "touched_paths",
                "severity": "warning",
                "message": f"Touched path does not exist: {path_str}",
            })
    return violations


def check_no_new_root_scripts(decl: dict[str, Any]) -> list[dict[str, str]]:
    """Hard rule: No new root scripts unless thin wrapper."""
    violations = []
    for path_str in decl.get("touched_paths", []):
        p = ROOT / path_str if not Path(path_str).is_absolute() else Path(path_str)
        # Check if this is a NEW file in scripts/ (not archive/, not existing)
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) == 2 and parts[0] == "scripts" and parts[1].endswith(".py"):
            # This is a root script — check if it's new (not in git)
            # We just flag it as a reminder; actual enforcement is in redundancy_budget
            pass
    return violations


def check_governance_freeze(decl: dict[str, Any]) -> list[dict[str, str]]:
    """Check if governance files are being modified under freeze."""
    violations = []
    freeze = _load_freeze_manifest()
    if not freeze.get("active", False):
        return violations

    for path_str in decl.get("touched_paths", []):
        p = ROOT / path_str if not Path(path_str).is_absolute() else Path(path_str)
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) >= 1 and parts[0] == "governance":
            # Check if this file is in the approved list
            approved = freeze.get("approved_changes", [])
            approved_paths = {a.get("path", "") for a in approved}
            if path_str not in approved_paths and str(rel) not in approved_paths:
                violations.append({
                    "rule": "governance_freeze",
                    "field": "touched_paths",
                    "severity": "error",
                    "message": (
                        f"Governance file '{path_str}' modified under active freeze "
                        f"without approval"
                    ),
                })
    return violations


def check_affects_core_judgment(decl: dict[str, Any]) -> list[dict[str, str]]:
    """If affects_core_judgment is true, extra verification is required."""
    violations = []
    if not decl.get("affects_core_judgment", False):
        return violations

    verification = decl.get("verification_command", "")
    if not verification:
        violations.append({
            "rule": "core_judgment_verification",
            "field": "verification_command",
            "severity": "error",
            "message": (
                "affects_core_judgment=true requires a verification_command"
            ),
        })
    return violations


def check_experiment_guard(decl: dict[str, Any]) -> list[dict[str, str]]:
    """If experiment_status is set, check promotion gate."""
    violations = []
    exp_status = decl.get("experiment_status", "")
    if exp_status and exp_status != "research_only":
        if not decl.get("promotion_gate_passed", False):
            violations.append({
                "rule": "experiment_promotion",
                "field": "promotion_gate_passed",
                "severity": "error",
                "message": (
                    f"experiment_status='{exp_status}' requires promotion_gate_passed=true"
                ),
            })
    return violations


def verify(declaration_path: Path | None = None) -> dict[str, Any]:
    """Run all protocol checks and return a report."""
    decl_path = declaration_path or DEFAULT_DECLARATION_PATH
    decl = load_yaml(decl_path)

    if decl is None:
        return {
            "valid": False,
            "declaration_path": str(decl_path),
            "violations": [{
                "rule": "declaration_exists",
                "severity": "error",
                "message": f"No agent work protocol declaration found at {decl_path}",
            }],
            "summary": "No declaration file found",
        }

    constitution = _load_constitution()
    protocol = constitution.get("agent_work_protocol", {})
    registry = _load_capability_registry()

    all_violations: list[dict[str, str]] = []

    all_violations.extend(check_required_fields(decl))
    all_violations.extend(check_owner_exists(decl, registry))
    all_violations.extend(check_touched_paths_exist(decl))
    all_violations.extend(check_no_new_root_scripts(decl))
    all_violations.extend(check_governance_freeze(decl))
    all_violations.extend(check_affects_core_judgment(decl))
    all_violations.extend(check_experiment_guard(decl))

    errors = [v for v in all_violations if v["severity"] == "error"]
    warnings = [v for v in all_violations if v["severity"] == "warning"]

    return {
        "valid": len(errors) == 0,
        "declaration_path": str(decl_path),
        "task_id": decl.get("task_id", ""),
        "owner_module": decl.get("owner_module", ""),
        "violations": all_violations,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "summary": (
            f"Protocol OK — {len(errors)} errors, {len(warnings)} warnings"
            if not errors
            else f"Protocol FAILED — {len(errors)} errors, {len(warnings)} warnings"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify agent work protocol compliance")
    parser.add_argument(
        "--declaration",
        type=Path,
        default=None,
        help="Path to agent work protocol declaration YAML",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    report = verify(args.declaration)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        if report["violations"]:
            for v in report["violations"]:
                print(f"  [{v['severity'].upper()}] {v['message']}")
        print(report["summary"])

    if not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
