"""The resolver lock must cover the workspace's declared dependency surface.

``uv.lock`` is the current authority.  ``requirements.lock.txt`` and its
installed-environment generator remain only as a historical compatibility
input and are intentionally not used by CI.  These tests validate the
resolver output without requiring a local virtual environment or network
access.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
UV_LOCK = ROOT / "uv.lock"
PYPROJECTS = [ROOT / "pyproject.toml", *sorted((ROOT / "packages").glob("*/pyproject.toml"))]


def _lock_payload() -> dict:
    return tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))


def _lock_packages() -> dict[str, dict]:
    return {
        canonicalize_name(str(package["name"])): package
        for package in _lock_payload().get("package", [])
        if package.get("name") and package.get("version")
    }


def _project_data() -> list[dict]:
    return [
        tomllib.loads(path.read_text(encoding="utf-8"))
        for path in PYPROJECTS
        if path.exists()
    ]


def _workspace_names() -> set[str]:
    return {
        canonicalize_name(str(data.get("project", {}).get("name", "")))
        for data in _project_data()
    }


def _declared_requirement_names() -> set[str]:
    names: set[str] = set()
    for data in _project_data():
        project = data.get("project", {})
        for spec in project.get("dependencies", []) or []:
            names.add(canonicalize_name(Requirement(spec).name))
        for specs in (project.get("optional-dependencies", {}) or {}).values():
            for spec in specs or []:
                names.add(canonicalize_name(Requirement(spec).name))
        for specs in (data.get("dependency-groups", {}) or {}).values():
            for spec in specs or []:
                names.add(canonicalize_name(Requirement(spec).name))
    requirements_dev = ROOT / "requirements-dev.txt"
    for line in requirements_dev.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(canonicalize_name(Requirement(line).name))
    return names


class TestUvLock:
    def test_lock_exists_and_is_resolved(self) -> None:
        assert UV_LOCK.exists()
        payload = _lock_payload()
        assert payload.get("version") == 1
        assert len(_lock_packages()) > 100

    def test_manifest_contains_every_workspace_member(self) -> None:
        manifest = {
            canonicalize_name(str(name))
            for name in _lock_payload().get("manifest", {}).get("members", [])
        }
        assert manifest == _workspace_names()

    def test_every_declared_dependency_is_present_in_resolver_lock(self) -> None:
        packages = _lock_packages()
        missing = sorted(_declared_requirement_names() - set(packages))
        assert not missing, f"declared dependencies missing from uv.lock: {missing}"

    def test_every_package_core_dependency_is_pinned(self) -> None:
        packages = _lock_packages()
        workspace_names = _workspace_names()
        declared: set[str] = set()
        for data in _project_data():
            for spec in data.get("project", {}).get("dependencies", []) or []:
                declared.add(canonicalize_name(Requirement(spec).name))
        missing = sorted(declared - workspace_names - set(packages))
        assert not missing, f"core dependencies missing from uv.lock: {missing}"

    def test_default_workspace_sync_does_not_activate_optional_extras(self) -> None:
        """Resolution may list extras; the default sync must not install them."""
        default_names: set[str] = set()
        optional_names: set[str] = set()
        for package in _lock_payload().get("package", []):
            source = package.get("source", {})
            if "editable" not in source:
                continue
            default_names.update(
                canonicalize_name(str(dep["name"]))
                for dep in package.get("dependencies", [])
                if dep.get("name")
            )
            for dep_group in package.get("dev-dependencies", {}).values():
                default_names.update(
                    canonicalize_name(str(dep["name"]))
                    for dep in dep_group
                    if dep.get("name")
                )
            for dep_group in package.get("optional-dependencies", {}).values():
                optional_names.update(
                    canonicalize_name(str(dep["name"]))
                    for dep in dep_group
                    if dep.get("name")
                )
        assert {"torch", "jax", "openbb", "streamlit", "sentence-transformers"} <= optional_names
        assert not (
            {"torch", "jax", "openbb", "streamlit", "sentence-transformers"} & default_names
        )

    def test_all_resolved_packages_have_exact_versions(self) -> None:
        for name, package in _lock_packages().items():
            assert package.get("version"), f"{name} has no exact version"

    def test_legacy_lock_writer_requires_explicit_compatibility_flag(self) -> None:
        legacy_lock = ROOT / "requirements.lock.txt"
        before = legacy_lock.read_bytes()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.commands.ci.generate_dependency_lock",
                "--write",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "--allow-legacy-compatibility-write" in result.stderr
        assert legacy_lock.read_bytes() == before

    def test_historical_requirement_files_do_not_advertise_install_authority(self) -> None:
        historical_files = (
            ROOT / "requirements.lock.txt",
            ROOT / "requirements-dev.txt",
            ROOT / "packages" / "framework_v1_archive" / "requirements.txt",
            ROOT / "packages" / "framework_v1_archive" / "requirements" / "lock.txt",
        )
        for path in historical_files:
            header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8]).lower()
            assert "historical" in header
            assert "uv.lock" in header
            assert "not" in header and "author" in header

        generator = (
            ROOT / "scripts" / "commands" / "ci" / "generate_dependency_lock.py"
        ).read_text(encoding="utf-8")
        assert "must not be installed directly" in generator
        assert "Usage: pip install -r requirements.lock.txt" not in generator

    def test_ci_does_not_free_resolve_workspace_dependencies(self) -> None:
        """CI project installs must stay on the locked uv workspace path."""
        workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        workflows.extend(sorted((ROOT / ".github" / "workflows").glob("*.yaml")))
        assert workflows

        for workflow in workflows:
            text = workflow.read_text(encoding="utf-8")
            assert "pip install -r" not in text
            assert "pip install --requirement" not in text

            for line in text.splitlines():
                if "python -m pip install" in line:
                    # These are bootstrap tools, not project dependencies, and
                    # their top-level versions must remain exact.
                    assert "uv==" in line or "semgrep==" in line, (workflow, line)
                if "uv sync" in line or "uv run" in line or "uv export" in line:
                    assert "--locked" in line, (workflow, line)

            release_install = "uv pip install --python" in text
            if release_install:
                assert "--no-deps" in text

    def test_framework_dependencies_are_declared_in_project_metadata(self) -> None:
        """The Framework build surface must not consume legacy lock inputs."""
        project = (ROOT / "packages" / "framework_v1_archive" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        assert "[project]" in project
        assert "dependencies = [" in project
        assert "dynamic = [\"dependencies\"]" not in project
        assert "requirements/lock.txt" not in project

    def test_workspace_build_requirements_are_exact_and_hash_constrained(self) -> None:
        """PEP 517 build tools must not be freely re-resolved by CI."""
        expected = {"setuptools==84.0.0", "wheel==0.46.2"}
        projects = [ROOT / "pyproject.toml", *sorted((ROOT / "packages").glob("*/pyproject.toml"))]
        assert len(projects) == 6
        for path in projects:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            assert set(data["build-system"]["requires"]) == expected, path

        constraints = (ROOT / "constraints" / "build-constraints.txt").read_text(encoding="utf-8")
        assert "setuptools==84.0.0" in constraints
        assert "wheel==0.46.2" in constraints
        assert "packaging==26.3" in constraints
        assert constraints.count("--hash=sha256:") == 6

        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert ci.count("--build-constraints constraints/build-constraints.txt") == 2
        assert ci.count("--require-hashes") >= 2
