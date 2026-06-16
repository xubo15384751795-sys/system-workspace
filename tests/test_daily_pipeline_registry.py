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
