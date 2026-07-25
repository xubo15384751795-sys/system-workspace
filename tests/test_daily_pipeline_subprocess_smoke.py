"""Subprocess smoke E2E — verify the main pipeline chain is runnable.

These tests verify the minimum viable pipeline chain can be invoked:

  structural_replay → bridge → quality_validation → judgment_layer →
  judgment_promotion_gate → trade_decision → risk_gate →
  freshness_validator → architecture_reality_audit →
  build_system_index → build_readme_first

Strategy:
  - Scripts that support argparse get ``--help`` (exit 0, no side effects).
  - Scripts without argparse are checked for a ``main()`` entry point.
  - Registry artifact paths are cross-checked against script output declarations.

This does NOT run the full pipeline — it verifies the chain is structurally
complete and each script is invocable.

See: governance/daily_pipeline_registry.yaml
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"

# Main chain steps (the critical path)
MAIN_CHAIN = [
    "structural_replay",
    "bridge",
    "quality_validation",
    "judgment_layer",
    "judgment_promotion_gate",
    "trade_decision",
    "risk_gate",
    "freshness_validator",
    "architecture_reality_audit",
    "system_index",
    "readme_first",
]

# Scripts that support --help (have argparse)
ARGPARSE_SCRIPTS = {
    "quality_validation": "scripts/quality_field_validator.py",
    "judgment_layer": "scripts/judgment_layer.py",
    "judgment_promotion_gate": "scripts/judgment_promotion_gate.py",
    "trade_decision": "scripts/trade_decision_layer.py",
    "risk_gate": "scripts/trade_risk_gate.py",
    "system_index": "scripts/build_system_index.py",
    "readme_first": "scripts/commands/weekly/build_readme_first.py",
    "freshness_validator": "scripts/freshness_validator.py",
    "architecture_reality_audit": "scripts/commands/weekly/architecture_reality_audit.py",
}

# Scripts without argparse — just check existence + main()
NO_ARGPARSE_SCRIPTS = {
    "structural_replay": "scripts/structural_replay_v2.py",
    "bridge": "scripts/bridge_replay_to_current.py",
}


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Script existence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step_name", MAIN_CHAIN, ids=lambda s: s)
def test_script_exists(step_name: str) -> None:
    """Every main chain step must have a script file on disk."""
    reg = _load_registry()
    step = reg.get("steps", {}).get(step_name)
    assert step is not None, f"{step_name} not in registry"

    cmd = step.get("command", step.get("execution", {}).get("current_command", ""))
    # Extract script path from command
    script = None
    for part in cmd.split():
        if part.endswith(".py"):
            script = ROOT / part
            break
    if script is None:
        pytest.skip(f"No .py script in command: {cmd}")
    assert script.exists(), f"Script not found: {script}"


# ---------------------------------------------------------------------------
# 2. --help smoke (no side effects)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("step_name", "script_path"),
    list(ARGPARSE_SCRIPTS.items()),
    ids=lambda s: s if isinstance(s, str) else "",
)
def test_script_help_exits_cleanly(step_name: str, script_path: str) -> None:
    """Scripts with argparse must exit 0 on --help."""
    full = ROOT / script_path
    if not full.exists():
        pytest.skip(f"Script not found: {full}")
    result = subprocess.run(
        [sys.executable, str(full), "--help"],
        capture_output=True, text=True, timeout=15, cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"{script_path} --help exited {result.returncode}:\n"
        f"stderr: {result.stderr[-300:]}"
    )


# ---------------------------------------------------------------------------
# 3. main() entry point check (no-argparse scripts)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("step_name", "script_path"),
    list(NO_ARGPARSE_SCRIPTS.items()),
    ids=lambda s: s if isinstance(s, str) else "",
)
def test_script_has_main_function(step_name: str, script_path: str) -> None:
    """Scripts without argparse must define a main() for future callable use."""
    full = ROOT / script_path
    if not full.exists():
        pytest.skip(f"Script not found: {full}")
    source = full.read_text(encoding="utf-8")
    assert "def main(" in source, (
        f"{script_path} has no main() function — needed for future callable"
    )


# ---------------------------------------------------------------------------
# 4. Registry artifact path consistency
# ---------------------------------------------------------------------------

def test_main_chain_steps_have_artifact_paths() -> None:
    """Every main chain step must declare an artifact_path."""
    reg = _load_registry()
    missing = []
    for name in MAIN_CHAIN:
        step = reg.get("steps", {}).get(name, {})
        if not step.get("artifact_path"):
            missing.append(name)
    assert not missing, f"Main chain steps missing artifact_path: {missing}"


def test_main_chain_artifacts_are_output_paths() -> None:
    """Main chain artifact paths should be under Output/ or Data/."""
    reg = _load_registry()
    bad = []
    for name in MAIN_CHAIN:
        step = reg.get("steps", {}).get(name, {})
        ap = step.get("artifact_path", "")
        if ap and not (ap.startswith("Output/") or ap.startswith("Data/")):
            bad.append(f"{name}: {ap}")
    assert not bad, (
        "Artifact paths outside Output/ or Data/:\n" + "\n".join(bad)
    )


# ---------------------------------------------------------------------------
# 5. Step ordering is monotonic
# ---------------------------------------------------------------------------

def test_main_chain_ordering_is_monotonic() -> None:
    """Main chain steps must have non-decreasing order values."""
    reg = _load_registry()
    prev_order = -1
    violations = []
    for name in MAIN_CHAIN:
        step = reg.get("steps", {}).get(name, {})
        order = step.get("order")
        if order is None:
            continue
        if order < prev_order:
            violations.append(f"{name}: order={order} < previous={prev_order}")
        prev_order = order
    assert not violations, (
        "Main chain ordering violations:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 6. Each step declares failure_behavior
# ---------------------------------------------------------------------------

def test_main_chain_has_failure_behavior() -> None:
    """Every main chain step must have failure_behavior."""
    reg = _load_registry()
    missing = []
    for name in MAIN_CHAIN:
        step = reg.get("steps", {}).get(name, {})
        fb = step.get("failure_behavior")
        if not fb:
            missing.append(name)
    assert not missing, f"Main chain steps missing failure_behavior: {missing}"
