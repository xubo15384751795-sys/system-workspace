"""The lock must cover what the project declares.

requirements.lock.txt was built by `pip freeze | grep` over eight hand-written
names. It missed omegaconf, mcp and mypy — all declared directly in
requirements-dev.txt — and every transitive dependency, so eight pins stood in
for a 461-package interpreter. P0-2's clean-checkout reproduction evidence
needs the environment to actually be reproducible.

These tests assert coverage of the *declared* surface rather than byte
equality with a regenerated file: CI runs Linux and the operator runs macOS,
so the resolved closures legitimately differ. Byte equality would be flaky and
would teach people to ignore the check.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.commands.ci import generate_dependency_lock as gen

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock.txt"


def _lock_pins() -> dict[str, str]:
    pins = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, version = line.partition("==")
        pins[canonicalize_name(name)] = version
    return pins


@pytest.fixture(scope="module")
def pins() -> dict[str, str]:
    return _lock_pins()


class TestLockCoversDeclaredDependencies:
    def test_lock_exists_and_is_not_token(self, pins):
        """Eight pins was the bug, not the baseline."""
        assert len(pins) > 20, f"only {len(pins)} pins — closure is not resolved"

    def test_every_dev_requirement_is_pinned(self, pins):
        """The historical miss: omegaconf, mcp and mypy are declared here and
        were absent from the lock."""
        text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            name = canonicalize_name(Requirement(line).name)
            assert name in pins, f"{name} declared in requirements-dev.txt but not locked"

    def test_every_package_core_dependency_is_pinned(self, pins):
        project_names = set()
        declared: set[str] = set()
        for pyproject in gen.PYPROJECTS:
            if not pyproject.exists():
                continue
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project", {})
            project_names.add(canonicalize_name(project.get("name", "")))
            for spec in project.get("dependencies", []) or []:
                declared.add(canonicalize_name(Requirement(spec).name))
        for name in declared - project_names:
            assert name in pins, f"{name} is a declared dependency but not locked"

    def test_uninstalled_optional_extras_are_not_pinned(self, pins):
        """torch, jax and openbb are optional and CI does not install them.
        Pinning them would imply the project requires them."""
        for name in ("torch", "jax", "openbb", "streamlit", "sentence-transformers"):
            assert canonicalize_name(name) not in pins, (
                f"{name} is an uninstalled optional extra and must not be locked"
            )

    def test_all_pins_are_exact(self, pins):
        for name, version in pins.items():
            assert version, f"{name} has no pinned version"


class TestGenerator:
    def test_declared_roots_include_every_package(self):
        roots = gen._declared_roots()
        # One representative direct dependency from each pyproject.
        for name in ("pandas", "requests", "pyarrow", "pydantic", "jsonschema"):
            assert canonicalize_name(name) in roots

    def test_generator_is_idempotent(self, pins):
        """Running the generator twice must not churn the file."""
        resolved, missing = gen.resolve_closure(gen._declared_roots())
        assert not missing, f"declared but not installed: {missing}"
        again, _ = gen.resolve_closure(gen._declared_roots())
        assert resolved == again

    def test_check_mode_does_not_write(self):
        before = LOCK.read_bytes()
        gen.main([])
        assert LOCK.read_bytes() == before
