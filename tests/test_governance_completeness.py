"""Governance Completeness — all governance files must exist and be valid.

Checks the full governance file set established in Batch 1-6.
"""
from __future__ import annotations

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "governance"

REQUIRED_FILES = [
    "architecture_cleanup_decisions.md",
    "deferred_work_register.yaml",
    "data_request_registry.yaml",
    "authority_registry.yaml",
    "output_routing_policy.yaml",
    "entrypoint_registry.yaml",
    "capability_registry.yaml",
    "redundancy_budget.yaml",
    "data_retention_policy.yaml",
    "system_constitution.yaml",
]


def test_all_governance_files_exist() -> None:
    """All required governance files must exist."""
    missing = []
    for name in REQUIRED_FILES:
        path = GOV / name
        if not path.exists():
            missing.append(name)
    assert not missing, f"Missing governance files: {missing}"


def test_governance_yaml_files_parse() -> None:
    """All YAML governance files must parse without errors."""
    failures = []
    for name in REQUIRED_FILES:
        path = GOV / name
        if path.exists() and path.suffix == ".yaml":
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as e:
                failures.append(f"{name}: {e}")
    assert not failures, f"YAML parse failures:\n" + "\n".join(failures)


def test_deferred_register_has_deadlines() -> None:
    """Every deferred item must have a hard_deadline."""
    reg = yaml.safe_load((GOV / "deferred_work_register.yaml").read_text(encoding="utf-8"))
    missing = []
    for item in reg.get("items", []):
        if not item.get("hard_deadline"):
            missing.append(item.get("id", "unknown"))
    assert not missing, f"Deferred items missing hard_deadline: {missing}"


def test_data_authority_entries_have_forbidden_use() -> None:
    """Every data authority entry must declare forbidden_use."""
    reg = yaml.safe_load((GOV / "authority_registry.yaml").read_text(encoding="utf-8"))
    missing = []
    for entry in reg.get("data_sources", []):
        if "forbidden_use" not in entry:
            missing.append(entry.get("path", "unknown"))
    assert not missing, f"Entries missing forbidden_use: {missing}"
