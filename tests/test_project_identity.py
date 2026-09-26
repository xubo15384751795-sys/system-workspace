"""Contract tests for the Verity root distribution identity."""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_distribution_is_verity_with_system_compatibility() -> None:
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]

    assert project["name"] == "verity"
    assert project["scripts"]["verity"] == "verity.cli:main"
    assert project["scripts"]["system"] == "system_cli.app:main"
    assert project["optional-dependencies"]["full"] == [
        "verity[ml,dev,orchestration]"
    ]


def test_system_cli_is_only_a_compatibility_forwarder() -> None:
    from system_cli import app as legacy
    from verity.cli import main as canonical

    assert canonical.__module__ == "verity.cli._application"
    assert legacy.main is canonical
