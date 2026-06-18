"""Daily pipeline registry consistency tests.

Verifies that every step in daily_run.py is registered, and that
registry rules (core judgment, failure behavior) are consistent.
See: governance/daily_pipeline_registry.yaml
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_registry() -> dict:
    try:
        import yaml
        path = ROOT / "governance" / "daily_pipeline_registry.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8")).get("steps", {})
    except Exception:
        return {}


def _load_constitution() -> dict:
    try:
        import yaml
        path = ROOT / "governance" / "system_constitution.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_daily_run_steps() -> set[str]:
    """Extract step names from daily_run.py run_step() calls."""
    daily_run = ROOT / "scripts" / "daily_run.py"
    source = daily_run.read_text(encoding="utf-8")
    return set(re.findall(r'run_step\("([^"]+)"', source))


def test_all_daily_run_steps_registered() -> None:
    """Every step invoked in daily_run.py must have a registry entry."""
    registry = _load_registry()
    steps = _get_daily_run_steps()
    missing = steps - set(registry.keys())
    assert not missing, (
        f"Daily run steps missing from registry: {missing}"
    )


def test_core_judgment_steps_have_blocking_failure() -> None:
    """Steps with allowed_to_affect_core_judgment: true must have blocking or degrading failure_behavior."""
    registry = _load_registry()
    blocking_behaviors = {
        "block_core_judgment", "block_current_readout", "block_promotion",
        "hold_flat", "lower_claim_ceiling",
    }
    violations = []
    for name, spec in registry.items():
        if spec.get("allowed_to_affect_core_judgment") is True:
            behavior = spec.get("failure_behavior", "")
            if behavior not in blocking_behaviors:
                violations.append(
                    f"{name}: allowed_to_affect_core_judgment=true but "
                    f"failure_behavior={behavior!r} (expected blocking)"
                )
    assert not violations, "Core judgment steps without blocking failure:\n" + "\n".join(violations)


def test_blocked_steps_cannot_affect_judgment() -> None:
    """Blocked steps must have allowed_to_affect_core_judgment: false."""
    registry = _load_registry()
    violations = []
    for name, spec in registry.items():
        if spec.get("status") == "blocked" and spec.get("allowed_to_affect_core_judgment") is True:
            violations.append(f"{name}: blocked but allowed_to_affect_core_judgment=true")
    assert not violations, "Blocked steps affecting judgment:\n" + "\n".join(violations)


def test_experimental_steps_cannot_affect_judgment() -> None:
    """Experimental steps must have allowed_to_affect_core_judgment: false."""
    registry = _load_registry()
    violations = []
    for name, spec in registry.items():
        if spec.get("status") == "experimental" and spec.get("allowed_to_affect_core_judgment") is True:
            violations.append(f"{name}: experimental but allowed_to_affect_core_judgment=true")
    assert not violations, "Experimental steps affecting judgment:\n" + "\n".join(violations)


def test_all_active_steps_have_owner() -> None:
    """All active steps must have an owner defined."""
    registry = _load_registry()
    violations = []
    for name, spec in registry.items():
        if spec.get("status") == "active" and not spec.get("owner"):
            violations.append(f"{name}: active but no owner")
    assert not violations, "Active steps without owner:\n" + "\n".join(violations)


def test_all_steps_have_failure_behavior() -> None:
    """All steps must define failure_behavior."""
    registry = _load_registry()
    violations = []
    for name, spec in registry.items():
        if not spec.get("failure_behavior"):
            violations.append(f"{name}: no failure_behavior defined")
    assert not violations, "Steps without failure_behavior:\n" + "\n".join(violations)


def test_registry_schema_version() -> None:
    """Registry must use v2 schema with enriched fields."""
    import yaml
    path = ROOT / "governance" / "daily_pipeline_registry.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data.get("schema_version") == "daily_pipeline_registry.v2", (
        f"Expected schema_version v2, got {data.get('schema_version')}"
    )


# ── Authority Convergence Invariants ────────────────────────────────────────


def test_sandbox_steps_cannot_affect_core_judgment() -> None:
    """Steps that produce to Output/sandbox/ must NOT affect core judgment.

    This is the hard authority rule: sandbox outputs are staging artifacts,
    not authority sources. They must go through bridge/gate to reach core.
    """
    registry = _load_registry()
    violations = []
    for name, spec in registry.items():
        produces = spec.get("produces", [])
        artifact_path = spec.get("artifact_path", "")

        # Check if any output is under Output/sandbox/
        produces_sandbox = any(
            str(p).startswith("Output/sandbox/") for p in produces
        )
        artifact_in_sandbox = artifact_path.startswith("Output/sandbox/")

        if produces_sandbox or artifact_in_sandbox:
            if spec.get("allowed_to_affect_core_judgment") is True:
                violations.append(
                    f"{name}: produces to Output/sandbox/ but "
                    f"allowed_to_affect_core_judgment=true — sandbox cannot affect core"
                )
    assert not violations, (
        "Sandbox steps affecting core judgment:\n" + "\n".join(violations)
    )


def test_core_affecting_outputs_must_be_current_or_runs() -> None:
    """Steps with allowed_to_affect_core_judgment: true must NOT produce to
    prohibited paths (sandbox, research, archive, system_learning).

    This enforces the hard authority rule from system_constitution.yaml.
    Prohibited paths are read from constitution — single source of truth.
    """
    registry = _load_registry()
    constitution = _load_constitution()
    prohibited_prefixes = tuple(
        constitution.get("hard_authority_rule", {}).get("prohibited_from_core_judgment", [
            "Output/sandbox/", "Output/research/", "Output/archive/", "Output/system_learning/",
        ])
    )
    violations = []
    for name, spec in registry.items():
        if spec.get("allowed_to_affect_core_judgment") is not True:
            continue

        produces = spec.get("produces", [])
        artifact_path = spec.get("artifact_path", "")

        # Check if any output is in a prohibited path
        for output in produces:
            if any(str(output).startswith(p) for p in prohibited_prefixes):
                violations.append(
                    f"{name}: allowed_to_affect_core_judgment=true but produces to "
                    f"{output} (prohibited path)"
                )
        if any(artifact_path.startswith(p) for p in prohibited_prefixes):
            violations.append(
                f"{name}: allowed_to_affect_core_judgment=true but artifact_path "
                f"is {artifact_path} (prohibited path)"
            )

    assert not violations, (
        "Core-affecting steps in prohibited paths:\n" + "\n".join(violations)
    )


def test_sandbox_chain_must_go_through_bridge() -> None:
    """If a step produces to sandbox and a downstream step bridges to current,
    only the bridge step can affect core judgment.

    Validates: sandbox replay → bridge validation → current framework_output
    """
    registry = _load_registry()
    violations = []

    for name, spec in registry.items():
        produces = spec.get("produces", [])
        produces_sandbox = any(
            str(p).startswith("Output/sandbox/") for p in produces
        )

        if not produces_sandbox:
            continue

        # This step produces to sandbox. Check if it claims core authority.
        if spec.get("allowed_to_affect_core_judgment") is True:
            violations.append(
                f"{name}: produces to sandbox but claims "
                f"allowed_to_affect_core_judgment=true — must go through bridge"
            )

    assert not violations, (
        "Sandbox producers claiming core authority:\n" + "\n".join(violations)
    )


# ── Authority Field Drift Invariants ─────────────────────────────────────


def test_authority_field_drift() -> None:
    """authority.affects_core_judgment must match top-level allowed_to_affect_core_judgment.

    These two fields express the same fact. If they diverge, the system has
    two conflicting authorities for the same question. This test prevents drift.
    """
    registry = _load_registry()
    violations = []
    for name, spec in registry.items():
        top_level = spec.get("allowed_to_affect_core_judgment")
        nested = spec.get("authority", {}).get("affects_core_judgment")
        if top_level is not None and nested is not None:
            if bool(top_level) != bool(nested):
                violations.append(
                    f"{name}: allowed_to_affect_core_judgment={top_level} "
                    f"but authority.affects_core_judgment={nested} — drift"
                )
    assert not violations, (
        "Authority field drift (top-level vs nested):\n" + "\n".join(violations)
    )


def test_failure_behavior_field_drift() -> None:
    """authority.failure_behavior must match top-level failure_behavior.

    Same rationale as authority field drift — one fact, one source.
    """
    registry = _load_registry()
    violations = []
    for name, spec in registry.items():
        top_level = spec.get("failure_behavior")
        nested = spec.get("authority", {}).get("failure_behavior")
        if top_level and nested and top_level != nested:
            violations.append(
                f"{name}: failure_behavior={top_level!r} "
                f"but authority.failure_behavior={nested!r} — drift"
            )
    assert not violations, (
        "Failure behavior field drift:\n" + "\n".join(violations)
    )


def test_audit_reports_not_treated_as_current_authority() -> None:
    """Steps that produce audit/report output to system_learning must NOT
    claim allowed_to_affect_core_judgment: true.

    Audit reports are historical snapshots, not runtime authority.
    """
    registry = _load_registry()
    violations = []
    for name, spec in registry.items():
        if spec.get("allowed_to_affect_core_judgment") is not True:
            continue
        produces = spec.get("produces", [])
        artifact = spec.get("artifact_path", "")
        all_outputs = [str(p) for p in produces] + [artifact]
        if any("system_learning" in p for p in all_outputs):
            violations.append(
                f"{name}: allowed_to_affect_core_judgment=true but "
                f"produces to system_learning — audit reports are not current authority"
            )
    assert not violations, (
        "Audit reports treated as current authority:\n" + "\n".join(violations)
    )
