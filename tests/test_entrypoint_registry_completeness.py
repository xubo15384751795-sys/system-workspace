"""Entrypoint Registry Completeness — every command script must be registered.

See: governance/entrypoint_registry.yaml
     governance/redundancy_budget.yaml
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "governance" / "entrypoint_registry.yaml"
SCRIPTS_DIR = ROOT / "scripts"
DAILY_RUN_PATH = ROOT / "verity" / "cli" / "daily_run.py"

VALID_STATUSES = {
    "active",
    "daily_active",
    "tool_active",
    "governance_active",
    "compatibility_wrapper",
    "shadow_active",
    "experimental",
    "archive_candidate",
    "archived",
    "deprecated",
    "blocked",
    "legacy_sealed",
    "archived_falsified",
}


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _registered_scripts(registry: dict) -> set[str]:
    scripts = set()
    for entry in registry.values():
        if isinstance(entry, dict) and "script" in entry:
            scripts.add(entry["script"])
    return scripts


def _command_scripts() -> set[str]:
    paths = [*SCRIPTS_DIR.glob("*.py"), *(SCRIPTS_DIR / "commands").rglob("*.py")]
    return {
        p.relative_to(ROOT).as_posix()
        for p in paths
        if p.is_file() and p.name != "__init__.py" and not p.name.startswith("_")
    }


def test_all_command_scripts_registered() -> None:
    """Every public scripts/**/*.py command must be explicitly registered."""
    registry = _load_registry()
    registered = _registered_scripts(registry)
    commands = _command_scripts()
    unregistered = commands - registered
    assert not unregistered, f"Unregistered scripts: {sorted(unregistered)}"


def test_registry_paths_exist() -> None:
    """Every active script path in registry must exist on disk."""
    registry = _load_registry()
    for name, entry in registry.items():
        if isinstance(entry, dict) and "script" in entry:
            # Archived entries may reference removed submodule files
            if entry.get("status") == "archived":
                continue
            path = ROOT / entry["script"]
            assert path.exists(), f"{name}: script not found: {entry['script']}"


def test_registry_statuses_valid() -> None:
    """Every registry entry must have a valid status."""
    registry = _load_registry()
    for name, entry in registry.items():
        if isinstance(entry, dict) and "status" in entry:
            assert entry["status"] in VALID_STATUSES, f"{name}: invalid status '{entry['status']}'"


def test_archive_candidates_not_in_daily_run() -> None:
    """archive_candidate scripts must not be called by daily_run.py."""
    registry = _load_registry()
    daily_run_text = DAILY_RUN_PATH.read_text(encoding="utf-8")

    archive_candidates = []
    for name, entry in registry.items():
        if isinstance(entry, dict) and entry.get("status") == "archive_candidate":
            script_name = Path(entry["script"]).stem
            archive_candidates.append((name, script_name))

    for name, script_name in archive_candidates:
        assert script_name not in daily_run_text, (
            f"{name} is archive_candidate but referenced in daily_run.py"
        )
