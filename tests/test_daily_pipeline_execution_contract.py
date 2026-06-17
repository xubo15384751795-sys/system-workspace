"""Daily Pipeline Execution Contract — every step must have module-runner metadata.

See: governance/daily_pipeline_registry.yaml
     governance/architecture_cleanup_decisions.md D2
"""
from __future__ import annotations

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_all_steps_have_execution_contract() -> None:
    """Every pipeline step must have execution.mode, current_command, future_callable."""
    reg = _load_registry()
    missing = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        exec_ = step.get("execution", {})
        if not exec_.get("mode"):
            missing.append(f"{name}: missing execution.mode")
        if not exec_.get("current_command"):
            missing.append(f"{name}: missing execution.current_command")
        if not exec_.get("future_callable"):
            missing.append(f"{name}: missing execution.future_callable")
    assert not missing, "Steps missing execution contracts:\n" + "\n".join(missing)


def test_all_steps_have_contracts() -> None:
    """Every pipeline step must have contracts (inputs, outputs)."""
    reg = _load_registry()
    missing = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        contract = step.get("contracts", {})
        if "outputs" not in contract:
            missing.append(f"{name}: missing contracts.outputs")
    assert not missing, "Steps missing contracts:\n" + "\n".join(missing)


def test_all_steps_have_authority() -> None:
    """Every pipeline step must declare authority (owner, affects_core_judgment)."""
    reg = _load_registry()
    missing = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        auth = step.get("authority", {})
        if not auth.get("owner"):
            missing.append(f"{name}: missing authority.owner")
        if "affects_core_judgment" not in auth:
            missing.append(f"{name}: missing authority.affects_core_judgment")
    assert not missing, "Steps missing authority:\n" + "\n".join(missing)


def test_core_judgment_steps_not_experimental() -> None:
    """Steps that affect core judgment cannot be experimental."""
    reg = _load_registry()
    violations = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        auth = step.get("authority", {})
        if auth.get("affects_core_judgment") and step.get("status") == "experimental":
            violations.append(f"{name}: affects_core_judgment=true but status=experimental")
    assert not violations, "Core judgment violations:\n" + "\n".join(violations)
