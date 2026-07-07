"""Framework registry — discovers and loads framework capability contracts.

The registry reads ``contracts/workbench/framework_registry.json`` to find
active frameworks, then loads each framework's ``framework.yaml`` to understand
its capabilities, rendering rules, and evidence requirements.

Usage::

    from workbench.framework_registry import load_registry, active_frameworks
    registry = load_registry()
    for fw in active_frameworks(registry):
        print(fw["display_name"])
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from workbench.paths import workbench_root, workspace_root


_WB_ROOT = workbench_root()
_WS_ROOT = workspace_root()
REGISTRY_PATH = _WB_ROOT / "contracts" / "workbench" / "framework_registry.json"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load the framework registry and hydrate each framework's contract.

    Returns a dict with keys: ``schema_version``, ``frameworks``.
    Each framework entry gains a ``contract`` key containing the parsed
    ``framework.yaml`` content, resolved against the workspace root.
    """
    registry_path = (path or REGISTRY_PATH).resolve()
    registry = read_json(registry_path)

    for entry in registry.get("frameworks", []):
        contract_rel = entry.get("contract_path", "")
        contract_abs = (_WS_ROOT / contract_rel).resolve()
        if contract_abs.exists():
            with contract_abs.open("r", encoding="utf-8") as handle:
                entry["contract"] = yaml.safe_load(handle) or {}
            entry["contract_resolved_path"] = str(contract_abs)
        else:
            entry["contract"] = {}
            entry["contract_resolved_path"] = None

    return registry


def active_frameworks(registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return all active (registered + enabled) framework entries."""
    if registry is None:
        registry = load_registry()
    return [fw for fw in registry.get("frameworks", []) if fw.get("active")]


def get_framework(registry: dict[str, Any], framework_id: str) -> dict[str, Any] | None:
    """Find a framework entry by framework_id."""
    for fw in registry.get("frameworks", []):
        if fw.get("framework_id") == framework_id:
            return fw
    return None


def register_framework(
    framework_id: str,
    contract_path: str,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Add a framework to the registry.

    Returns the updated registry dict. Does NOT write to disk —
    callers must persist the registry after validation.
    """
    reg_path = (registry_path or REGISTRY_PATH).resolve()
    registry = read_json(reg_path)

    existing = get_framework(registry, framework_id)
    if existing:
        existing["contract_path"] = contract_path
        existing["active"] = True
    else:
        registry.setdefault("frameworks", []).append({
            "framework_id": framework_id,
            "contract_path": contract_path,
            "active": True,
        })

    return registry


def unregister_framework(
    framework_id: str,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Mark a framework as inactive or remove it from the registry."""
    reg_path = (registry_path or REGISTRY_PATH).resolve()
    registry = read_json(reg_path)
    registry["frameworks"] = [
        fw for fw in registry.get("frameworks", [])
        if fw.get("framework_id") != framework_id
    ]
    return registry


def list_frameworks(registry: dict[str, Any] | None = None) -> str:
    """Return a human-readable list of registered frameworks."""
    if registry is None:
        registry = load_registry()
    lines = []
    for fw in registry.get("frameworks", []):
        status = "active" if fw.get("active") else "inactive"
        contract = fw.get("contract", {})
        name = contract.get("display_name", fw.get("framework_id", "unknown"))
        version = contract.get("version", "?")
        lines.append(f"  [{status}] {fw.get('framework_id')} — {name} v{version}")
    return "\n".join(lines) if lines else "  (no frameworks registered)"


def framework_evidence_requirements(
    registry: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Collect required evidence from all active frameworks.

    Returns ``{series_id: [requirement_entries, ...]}`` where each entry
    carries ``framework_id``, ``optional``, ``fallback``, ``label``, ``area``.
    """
    if registry is None:
        registry = load_registry()
    required: dict[str, list[dict[str, Any]]] = {}
    for fw in active_frameworks(registry):
        contract = fw.get("contract", {})
        for item in contract.get("required_evidence", []):
            sid = item["series_id"]
            required.setdefault(sid, []).append({
                "framework_id": fw["framework_id"],
                "optional": item.get("optional", False),
                "fallback": item.get("fallback"),
                "label": item.get("label", sid),
                "area": item.get("area", "Unknown"),
            })
    return required


def framework_for_output(framework_id: str, registry: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Convenience: get the hydrated framework entry for a given framework_id."""
    if registry is None:
        registry = load_registry()
    return get_framework(registry, framework_id)


def resolve_value(data: dict[str, Any], dot_path: str, default: Any = None) -> Any:
    """Resolve a dot-separated path against a nested dict.

    Example: ``resolve_value(fw_output, 'advanced.sigma')`` looks up
    ``fw_output['advanced']['sigma']``.
    """
    node: Any = data
    for part in dot_path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node
