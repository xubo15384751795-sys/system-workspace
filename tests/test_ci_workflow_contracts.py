"""Regression contracts for CI environment and dependency boundaries."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_generation_inventory_step_exports_scripts_pythonpath() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    marker = "      - name: Generation writer inventory"
    section = workflow.split(marker, 1)[1].split("      - name:", 1)[0]

    assert 'PYTHONPATH: ".:scripts"' in section
    assert "python scripts/check_generation_writer_inventory.py --json" in section


def test_nightly_framework_suite_installs_its_viz_extra() -> None:
    workflow = (ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8")
    framework = (ROOT / "packages/framework/pyproject.toml").read_text(encoding="utf-8")
    deformation = workflow.split("  deformation:", 1)[1].split("  harvester:", 1)[0]

    assert "uv sync --locked --all-packages --extra viz" in deformation
    assert 'viz = ["plotly>=5", "streamlit>=1.30"' in framework
