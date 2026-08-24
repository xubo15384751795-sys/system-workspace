"""Regression contracts for CI environment and dependency boundaries."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from verify_experiment_core_judgment import AUDIT_MD_PATH, _audit_report_paths

from scripts.commands.weekly.architecture_reality_audit import (
    OUTPUT_DIR,
    _report_output_dir,
)

ROOT = Path(__file__).resolve().parents[1]


def test_generation_inventory_step_exports_scripts_pythonpath() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    marker = "      - name: Generation writer inventory"
    section = workflow.split(marker, 1)[1].split("      - name:", 1)[0]

    assert 'PYTHONPATH: ".:scripts"' in section
    assert "uv run --locked python scripts/check_generation_writer_inventory.py --json" in section
    assert "pip install" not in section


def test_lint_pipeline_docs_use_locked_workspace_interpreter() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "uv run --locked python -m system_cli pipeline docs --check" in workflow
    lint = workflow.split("  lint:", 1)[1].split("  lock-integrity:", 1)[0]
    assert "python -m pip install \"pyyaml" not in lint


def test_nightly_framework_suite_installs_its_viz_extra() -> None:
    workflow = (ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8")
    framework = (ROOT / "packages/framework/pyproject.toml").read_text(encoding="utf-8")
    deformation = workflow.split("  deformation:", 1)[1].split("  harvester:", 1)[0]

    assert "uv sync --locked --all-packages --extra viz" in deformation
    assert 'viz = ["plotly>=5", "streamlit>=1.30"' in framework


@pytest.mark.governance_loop
def test_audit_report_writers_bypass_workspace_on_github_runners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CI runner report writes must stay outside the checkout (boundary contract).

    The integration job's clean-checkout boundary check fails if any step
    materializes untracked ``Output/`` content after the root tests ran.
    """
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    isolated = [
        (_report_output_dir() / "architecture_reality_audit.json", None),
        _audit_report_paths(),
    ]
    try:
        for path, _ in isolated:
            assert not path.is_relative_to(ROOT / "Output")
            assert Path(tempfile.gettempdir()) in path.resolve().parents or path.parent == Path(
                tempfile.gettempdir()
            ) or str(path).startswith(str(Path(tempfile.gettempdir())))
    finally:
        for path, _ in isolated:
            shutil.rmtree(path.parent, ignore_errors=True)


@pytest.mark.governance_loop
def test_audit_report_writers_default_to_workspace_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without CI-runner detection, operator behavior is unchanged."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert _report_output_dir() == OUTPUT_DIR == ROOT / "Output" / "system_learning" / "latest"
    md_path, json_path = _audit_report_paths()
    assert (
        md_path
        == json_path.with_suffix(".md")
        == AUDIT_MD_PATH
        == ROOT / "Output" / "system_learning" / "latest" / "experiment_core_judgment_audit.md"
    )
