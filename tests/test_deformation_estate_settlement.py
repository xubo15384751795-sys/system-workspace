from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_v1_is_archived_falsified_and_has_no_active_framework_authority() -> None:
    capabilities = yaml.safe_load((ROOT / "governance" / "capability_registry.yaml").read_text())
    assert capabilities["deformation_framework"]["status"] == "ARCHIVED_FALSIFIED"
    assert "write_current_output" in capabilities["deformation_framework"]["forbidden_claims"]

    registry = json.loads(
        (ROOT / "packages" / "workbench" / "contracts" / "workbench" / "framework_registry.json").read_text()
    )
    by_id = {entry["framework_id"]: entry for entry in registry["frameworks"]}
    assert by_id["structural_deformation"]["active"] is False
    assert by_id["structural_deformation"]["executable"] == "denied"
    assert by_id["structural_deformation"]["contract_path"].endswith(
        "structural_deformation.archive.yaml"
    )
    assert by_id["macro_pressure_measurement"]["active"] is True


def test_default_pipeline_uses_neutral_measurement_and_archives_v1() -> None:
    registry = yaml.safe_load((ROOT / "governance" / "daily_pipeline_registry.yaml").read_text())["steps"]
    assert registry["neutral_pressure_measurement"]["status"] == "active"
    assert registry["structural_replay"]["status"] == "archived"
    assert registry["bridge"]["status"] == "archived"
    assert registry["k_measurement_gate"]["schedule"] == "on_demand"
    assert registry["x_measurement_gate"]["schedule"] == "on_demand"
    assert registry["judgment_layer"]["contracts"]["inputs"][0] == "Output/current/neutral_pressure_snapshot.json"


def test_no_active_framework_owned_pipeline_steps() -> None:
    """Estate settlement: Deformation Framework / Framework must not own an active step."""
    registry = yaml.safe_load((ROOT / "governance" / "daily_pipeline_registry.yaml").read_text())["steps"]
    forbidden_owners = {"Deformation Framework", "Framework"}
    still_active: list[str] = []
    for step_id, step in registry.items():
        if not isinstance(step, dict) or step.get("status") != "active":
            continue
        owners = {str(step.get("owner") or "")}
        authority = step.get("authority") or {}
        if isinstance(authority, dict):
            owners.add(str(authority.get("owner") or ""))
        owners.discard("")
        if owners & forbidden_owners:
            still_active.append(step_id)
    assert still_active == [], (
        "owner in {Deformation Framework, Framework} must not be active: "
        + ", ".join(still_active)
    )


def test_archive_guard_denies_unapproved_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from verity.runtime._deformation_archive_guard import require_archived_reproduction

    monkeypatch.delenv("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", raising=False)
    with pytest.raises(SystemExit, match="ARCHIVED_FALSIFIED"):
        require_archived_reproduction()


def test_direct_v1_entrypoint_fails_before_legacy_imports() -> None:
    env = os.environ.copy()
    env.pop("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", None)
    env.pop("ZCODE_BUNDLE_RUN_ID", None)
    result = subprocess.run(
        [sys.executable, "scripts/structural_replay_v2.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "ARCHIVED_FALSIFIED" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_archive_bridge_cannot_write_authoritative_current(monkeypatch: pytest.MonkeyPatch) -> None:
    from verity.runtime._deformation_archive_guard import require_archived_reproduction

    monkeypatch.setenv("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", "1")
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(ROOT / "Output" / "current"))
    monkeypatch.delenv("ZCODE_BUNDLE_RUN_ID", raising=False)
    with pytest.raises(SystemExit, match="cannot write authoritative"):
        require_archived_reproduction(current_writer=True)


def test_neutral_producer_does_not_import_framework_source() -> None:
    source = (ROOT / "packages" / "workbench" / "src" / "workbench" / "measurement" / "neutral_pressure_measurement.py").read_text()
    assert "packages.framework" not in source
    assert "src.proxies" not in source
    assert "_replay_registry" not in source


def test_v2_has_no_operational_permission() -> None:
    capabilities = yaml.safe_load((ROOT / "governance" / "capability_registry.yaml").read_text())
    v2 = capabilities["funding_endogenous_boundary_v2"]
    assert v2["status"] == "REAL_EXPERIMENTAL"
    assert "current_output_generation" in v2["forbidden_claims"]
    assert "inherited_v1_permission" in v2["forbidden_claims"]


def test_v1_promotion_path_is_permanently_blocked() -> None:
    source = (
        ROOT
        / "packages"
        / "workbench"
        / "src"
        / "workbench"
        / "workspace"
        / "promote_snapshot.py"
    ).read_text()
    assert "ARCHIVED_FALSIFIED: canonical promotion is permanently denied" in source
