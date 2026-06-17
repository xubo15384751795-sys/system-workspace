"""Daily Pipeline IO Contract — verify step inputs/outputs form a valid chain.

Checks that the pipeline registry is internally consistent:
- Every step has required metadata
- Consumes can be traced to upstream produces
- Core judgment steps have declared outputs
- Blocked/experimental steps cannot affect core judgment

See: governance/daily_pipeline_registry.yaml
     governance/architecture_cleanup_decisions.md D2
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _all_produced_paths(reg: dict) -> set[str]:
    """Collect all paths declared as produced by any step."""
    paths = set()
    for step in reg.get("steps", {}).values():
        if not isinstance(step, dict):
            continue
        for p in step.get("contracts", {}).get("outputs", []):
            paths.add(str(p))
        if step.get("artifact_path"):
            paths.add(str(step["artifact_path"]))
        for p in step.get("produces", []):
            paths.add(str(p))
    return paths


def _external_inputs(reg: dict) -> set[str]:
    """Paths declared as external inputs (Harvester, CaseLab, manual)."""
    return {str(p) for p in reg.get("external_inputs", [])}


def _consumed_paths_for_step(step: dict) -> set[str]:
    """Deduplicated set of paths consumed by a step.

    The registry uses YAML anchors so ``input`` and ``contracts.inputs``
    often point to the same underlying list.  We union all sources but
    deduplicate by value.
    """
    paths: set[str] = set()
    for source in ("input", "consumes"):
        for p in step.get(source, []):
            paths.add(str(p))
    for p in step.get("contracts", {}).get("inputs", []):
        paths.add(str(p))
    return paths


def _harvester_release_paths() -> set[str]:
    """Paths from the latest Harvester release."""
    exports = ROOT / "Data" / "harvester" / "exports" / "latest"
    if not exports.exists():
        return set()
    return {str(p.relative_to(ROOT)) for p in exports.rglob("*") if p.is_file()}


def _system_paths() -> set[str]:
    """Well-known system paths that steps can consume."""
    return {
        "Data/harvester/exports/latest/data/benchmark_panel.parquet",
        "Data/system_index/latest.json",
        "Output/current/framework_output.json",
        "Output/current/status.json",
        "Output/judgment/latest.json",
        "Output/trade_decisions/latest.json",
    }


def test_all_steps_have_required_metadata() -> None:
    """Every step must have owner, status, execution, authority."""
    reg = _load_registry()
    missing = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        issues = []
        if not step.get("authority", {}).get("owner"):
            issues.append("owner")
        if not step.get("status"):
            issues.append("status")
        if not step.get("execution", {}).get("mode"):
            issues.append("execution.mode")
        if "affects_core_judgment" not in step.get("authority", {}):
            issues.append("authority.affects_core_judgment")
        if not step.get("failure_behavior"):
            issues.append("failure_behavior")
        if issues:
            missing.append(f"{name}: missing {', '.join(issues)}")
    assert not missing, "Steps missing required metadata:\n" + "\n".join(missing)


def test_core_judgment_steps_have_outputs() -> None:
    """Steps that affect core judgment must declare outputs or artifact_path."""
    reg = _load_registry()
    missing = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        auth = step.get("authority", {})
        if not auth.get("affects_core_judgment"):
            continue
        contracts = step.get("contracts", {})
        has_outputs = bool(contracts.get("outputs")) or bool(step.get("artifact_path")) or bool(step.get("produces"))
        if not has_outputs:
            missing.append(name)
    assert not missing, f"Core judgment steps without declared outputs: {missing}"


def _path_resolves(consumed: str, produced: set[str], externals: set[str]) -> bool:
    """Check whether *consumed* is covered by a produced path or external input.

    Handles directory prefixes: consuming
    ``Data/harvester/exports/latest/data/benchmark_panel.parquet`` is satisfied
    by a producer that declares ``Data/harvester/exports/latest/``.
    """
    for p in produced:
        if consumed == p or consumed.startswith(p) or p.startswith(consumed):
            return True
    for ext in externals:
        if consumed == ext or consumed.startswith(ext) or ext.startswith(consumed):
            return True
    return False


def test_consumes_traceable_to_upstream() -> None:
    """Every consumed path must be produced by a prior step, Harvester, or system."""
    reg = _load_registry()
    all_produced = _all_produced_paths(reg)
    all_produced |= _harvester_release_paths()
    all_produced |= _system_paths()
    externals = _external_inputs(reg)

    untraceable = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        for path_str in _consumed_paths_for_step(step):
            if not _path_resolves(path_str, all_produced, externals):
                untraceable.append(f"{name} consumes '{path_str}' — no upstream producer found")
    assert not untraceable, (
        f"{len(untraceable)} untraceable consumes:\n" + "\n".join(untraceable)
    )


def test_blocked_experimental_cannot_affect_core_judgment() -> None:
    """blocked/experimental steps must not affect core judgment."""
    reg = _load_registry()
    violations = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        status = step.get("status", "")
        auth = step.get("authority", {})
        if status in ("blocked", "experimental") and auth.get("affects_core_judgment"):
            violations.append(f"{name}: status={status} but affects_core_judgment=true")
    assert not violations, "Core judgment violations:\n" + "\n".join(violations)


def test_registry_paths_have_no_typos() -> None:
    """Registry command paths should not have obvious typos."""
    reg = _load_registry()
    typos = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        cmd = step.get("command", step.get("execution", {}).get("current_command", ""))
        if "horvester" in cmd.lower():
            typos.append(f"{name}: 'horvester' typo in command")
        if "scrpts" in cmd.lower():
            typos.append(f"{name}: 'scrpts' typo in command")
    assert not typos, "Registry typos:\n" + "\n".join(typos)


def test_failure_behavior_declared() -> None:
    """Every step must have a failure_behavior."""
    reg = _load_registry()
    missing = []
    for name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        fb = step.get("failure_behavior") or step.get("authority", {}).get("failure_behavior")
        if not fb:
            missing.append(name)
    assert not missing, f"Steps missing failure_behavior: {missing}"
