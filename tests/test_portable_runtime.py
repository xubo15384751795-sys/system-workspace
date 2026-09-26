"""Step 3 portable-runtime gates for the installed default surface."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from system_runtime.context import (
    HostContext,
    RuntimeContext,
    SchedulerContext,
)
from system_runtime.run_outcome import RunOutcome
from system_runtime.secrets import EnvironmentSecretProvider
from verity.runtime.run_bundle import RunBundle

ROOT = Path(__file__).resolve().parents[1]


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("SYSTEM_TRIGGER_KIND", None)
    env.pop("SYSTEM_SCHEDULER_KIND", None)
    env.pop("SYSTEM_SCHEDULER_ID", None)
    env.pop("SYSTEM_SCHEDULE_ID", None)
    env.pop("SYSTEM_TRIGGER_ID", None)
    env.pop("SYSTEM_HOST_ID", None)
    return env


def test_runtime_context_resolves_all_portable_dependencies_once(tmp_path: Path) -> None:
    context = RuntimeContext.discover(
        ROOT,
        data_root=tmp_path / "Data",
        output_root=tmp_path / "Output",
        secrets=EnvironmentSecretProvider(),
        scheduler=SchedulerContext(
            trigger_kind="scheduled",
            scheduler_kind="systemd",
            scheduler_id="systemd:verity-daily",
            schedule_id="verity-daily",
            trigger_id="trigger-1",
        ),
        host=HostContext(host_id="fixture-host", platform="linux"),
        provider_config={"profile": "test"},
    )

    assert context.workspace == ROOT.resolve()
    assert context.data_root == (tmp_path / "Data").resolve()
    assert context.output_root == (tmp_path / "Output").resolve()
    assert context.scheduler.scheduler_kind == "systemd"
    assert context.host.host_id == "fixture-host"
    assert context.paths.data == context.data_root
    assert context.paths.output == context.output_root
    assert context.surface("current") == context.output_root / "current"


def test_clean_shell_installed_verity_runs_without_pythonpath(tmp_path: Path) -> None:
    env = _clean_env()
    result = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "verity"), "--workspace", str(ROOT), "pipeline", "validate"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True


def test_clean_shell_with_temporary_data_and_output_roots_runs(tmp_path: Path) -> None:
    env = _clean_env()
    env["SYSTEM_DATA_ROOT"] = str(tmp_path / "Data")
    env["SYSTEM_OUTPUT_ROOT"] = str(tmp_path / "Output")
    result = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "verity"), "--workspace", str(ROOT), "pipeline", "validate"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"] is True


def test_synthetic_systemd_changes_identity_not_business_result(monkeypatch) -> None:
    common = {
        "run_id": "daily_pipeline_fixture",
        "spec_status": "OK",
        "execution_status": "FAILED",
        "failed_steps": ["harvester"],
        "publish_status": "NOT_PUBLISHED",
    }
    monkeypatch.setenv("SYSTEM_TRIGGER_KIND", "scheduled")
    monkeypatch.setenv("SYSTEM_SCHEDULER_KIND", "launchd")
    monkeypatch.setenv("SYSTEM_SCHEDULER_ID", "com.system.daily-run")
    launchd = RunOutcome(**common)
    monkeypatch.setenv("SYSTEM_SCHEDULER_KIND", "systemd")
    monkeypatch.setenv("SYSTEM_SCHEDULER_ID", "systemd:verity-daily")
    systemd = RunOutcome(**common)

    assert launchd.exit_code == systemd.exit_code == 3
    assert launchd.execution_status == systemd.execution_status
    assert launchd.publish_status == systemd.publish_status
    assert launchd.scheduler_kind == "launchd"
    assert systemd.scheduler_kind == "systemd"


def test_run_bundle_persists_scheduler_neutral_identity(tmp_path: Path) -> None:
    context = RuntimeContext.discover(
        tmp_path,
        scheduler=SchedulerContext(
            trigger_kind="scheduled",
            scheduler_kind="systemd",
            scheduler_id="systemd:verity-daily",
            schedule_id="verity-daily",
            trigger_id="trigger-1",
        ),
        host=HostContext(host_id="fixture-host", platform="linux"),
    )
    bundle = RunBundle.start(
        mode="daily_pipeline",
        root=tmp_path,
        runtime_context=context,
        release_id="release-test",
        update_pointer=False,
    )
    manifest = json.loads((bundle.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_origin"] == "manual"
    assert manifest["execution_identity"] == {
        "trigger_kind": "scheduled",
        "scheduler_kind": "systemd",
        "scheduler_id": "systemd:verity-daily",
        "schedule_id": "verity-daily",
        "trigger_id": "trigger-1",
        "host_id": "fixture-host",
        "run_id": bundle.run_id,
        "release_id": "release-test",
    }


def test_active_production_surface_has_no_absolute_mac_paths() -> None:
    production_roots = [
        ROOT / "system_runtime",
        ROOT / "system_cli",
        ROOT / "verity",
        ROOT / "packages" / "harvester" / "src",
        ROOT / "packages" / "orchestration" / "orchestration",
        ROOT / "packages" / "learning_hub" / "src",
        ROOT / "packages" / "workbench" / "src",
    ]
    violations: list[str] = []
    for base in production_roots:
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "/Users/a1/" in text or re.search(r"/Users/[A-Za-z0-9_.-]+", text):
                violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_default_runtime_adapters_do_not_construct_pythonpath() -> None:
    paths = [
        ROOT / "system_cli" / "app.py",
        ROOT / "scripts" / "run_daily_scheduled.sh",
        ROOT / "scripts" / "run_dagster_daily.sh",
        ROOT / "scripts" / "orchestrate.sh",
        ROOT / "packages" / "harvester" / "scripts" / "daily_release.sh",
    ]
    assignment = re.compile(r"(?:export\s+)?PYTHONPATH\s*=")
    assert all(not assignment.search(path.read_text(encoding="utf-8")) for path in paths)
    sequence_executor = (
        ROOT / "packages" / "orchestration" / "orchestration" / "sequence_executor.py"
    ).read_text(encoding="utf-8")
    assert "PYTHONPATH" not in sequence_executor
