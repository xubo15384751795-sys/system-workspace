"""The repository's declared Python support matches its local and CI targets."""
from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SPEC = ">=3.13,<3.14"


def _active_project_paths() -> list[Path]:
    return [
        ROOT / "pyproject.toml",
        *sorted((ROOT / "packages").glob("*/pyproject.toml")),
        ROOT / "paper-empirical-interface" / "pyproject.toml",
    ]


def test_active_projects_bound_to_python_313() -> None:
    for path in _active_project_paths():
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        assert project["requires-python"] == PYTHON_SPEC, path


def test_local_runtime_target_is_python_313() -> None:
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13"


def test_ci_uses_only_python_313() -> None:
    versions: set[str] = set()
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert 'python-version: "3.12"' not in text, workflow
        document = yaml.safe_load(text) or {}
        for job in (document.get("jobs") or {}).values():
            for step in (job.get("steps") or []):
                configured = ((step.get("with") or {}).get("python-version"))
                if isinstance(configured, str) and not configured.startswith("${{"):
                    versions.add(configured)
            matrix = ((job.get("strategy") or {}).get("matrix") or {}).get(
                "python-version", []
            )
            if isinstance(matrix, list):
                versions.update(str(version) for version in matrix)
    assert versions == {"3.13"}


def test_runtime_entrypoints_use_the_313_resolver() -> None:
    entrypoints = [
        ROOT / "sys",
        ROOT / "scripts" / "orchestrate.sh",
        ROOT / "scripts" / "run_dagster_daily.sh",
        ROOT / "scripts" / "run_daily_scheduled.sh",
        ROOT / "scripts" / "install_daily_run_launchd.sh",
    ]
    for path in entrypoints:
        text = path.read_text(encoding="utf-8")
        assert "3.14" not in text, path
        if path.name == "run_daily_scheduled.sh":
            assert "run_dagster_daily.sh" in text, path
        else:
            assert "resolve_system_python.sh" in text, path

    daily_plist = (ROOT / "scripts" / "launchd" / "com.system.daily-run.plist").read_text(
        encoding="utf-8"
    )
    assert "__SYSTEM_PYTHON__" in daily_plist
    assert 'requires-python = "==3.13.*"' in (ROOT / "uv.lock").read_text(encoding="utf-8")


def test_resolver_prefers_synced_workspace_environment() -> None:
    """The scheduled interpreter must see the packages installed by uv sync."""
    workspace_python = ROOT / ".venv" / "bin" / "python"
    if not workspace_python.is_file():
        # A clean source checkout may be inspected before its first sync; the
        # resolver's managed-Python fallback is covered by the support contract.
        return
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "resolve_system_python.sh")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(workspace_python)


def test_dagster_wrapper_validates_explicit_python_override(tmp_path: Path) -> None:
    """A stale launchd PYTHON must fail before entering the daily executor."""
    fake = tmp_path / "python-314"
    fake.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-c\" ]; then exit 1; fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    env = os.environ.copy()
    env.update({"SYSTEM_ROOT": str(ROOT), "PYTHON": str(fake)})
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "run_dagster_daily.sh"), "--dry-run"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 78
    assert "not Python 3.13" in result.stderr
