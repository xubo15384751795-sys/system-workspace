"""Redundancy Budget — enforce entry/artifact/data governance rules.

See: governance/redundancy_budget.yaml
"""
from __future__ import annotations

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGET_PATH = ROOT / "governance" / "redundancy_budget.yaml"
REGISTRY_PATH = ROOT / "governance" / "entrypoint_registry.yaml"


def _load_budget() -> dict:
    return yaml.safe_load(BUDGET_PATH.read_text(encoding="utf-8"))


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_root_scripts_within_budget() -> None:
    """Root scripts count must not exceed max_visible."""
    budget = _load_budget()
    max_visible = budget["root_scripts"]["max_visible"]
    actual = len([p for p in (ROOT / "scripts").glob("*.py") if p.name != "__init__.py"])
    assert actual <= max_visible, (
        f"Root scripts ({actual}) exceeds budget ({max_visible}). "
        "Archive scripts or update governance/redundancy_budget.yaml"
    )


def test_all_scripts_have_valid_status() -> None:
    """Every registry entry must use an allowed status from redundancy_budget."""
    budget = _load_budget()
    allowed = set(budget["root_scripts"]["allowed_statuses"])
    # Also allow statuses from other categories
    allowed |= {"active", "deprecated", "blocked", "shadow_active"}

    registry = _load_registry()
    for name, entry in registry.items():
        if isinstance(entry, dict) and "status" in entry:
            assert entry["status"] in allowed, (
                f"{name}: status '{entry['status']}' not in allowed_statuses"
            )


def test_budget_file_exists() -> None:
    """redundancy_budget.yaml must exist and be valid YAML."""
    assert BUDGET_PATH.exists(), "governance/redundancy_budget.yaml missing"
    budget = _load_budget()
    assert "root_scripts" in budget
    assert "output" in budget
    assert "data" in budget
    assert "core_judgment" in budget
