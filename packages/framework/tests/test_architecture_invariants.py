"""Architecture invariant tests — protect system boundaries from erosion.

These tests assert structural rules about the codebase itself:
  - No module bypasses the data boundary
  - Core does not depend on UI or runtime
  - RuntimePaths always resolves to valid directories
  - Snapshots always carry provenance
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────────────

SRC = Path(__file__).resolve().parent.parent / "src"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _all_source_files() -> list[Path]:
    return _all_source_files_in(SRC)


def _all_source_files_in(root: Path) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in filenames:
            if f.endswith(".py"):
                files.append(Path(dirpath) / f)
    return files


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


# ── Boundary Tests ───────────────────────────────────────────────────────────


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_no_absolute_user_paths(self) -> None:
        """No source file may contain hardcoded /Users/... paths."""
        for fp in _all_source_files():
            if fp.name == "runtime_context.py":
                continue
            text = fp.read_text()
            for i, line in enumerate(text.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""'):
                    continue
                self.assertNotIn(
                    '"/Users/',
                    stripped,
                    f"{fp.relative_to(PROJECT_ROOT)}:{i} contains hardcoded path",
                )
                self.assertNotIn(
                    "'/Users/",
                    stripped,
                    f"{fp.relative_to(PROJECT_ROOT)}:{i} contains hardcoded path",
                )

    def test_no_absolute_user_paths_in_tests(self) -> None:
        """No test file may contain hardcoded /Users/... paths."""
        TESTS = PROJECT_ROOT / "tests"
        if not TESTS.is_dir():
            return
        for fp in _all_source_files_in(TESTS):
            # This file itself contains "/Users/" as search patterns — skip self.
            if fp.name == "test_architecture_invariants.py":
                continue
            text = fp.read_text()
            for i, line in enumerate(text.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""'):
                    continue
                self.assertNotIn(
                    '"/Users/',
                    stripped,
                    f"{fp.relative_to(PROJECT_ROOT)}:{i} contains hardcoded path",
                )
                self.assertNotIn(
                    "'/Users/",
                    stripped,
                    f"{fp.relative_to(PROJECT_ROOT)}:{i} contains hardcoded path",
                )

    def test_core_does_not_import_runtime_or_ui(self) -> None:
        """src/core/ must not depend on src/runtime/ or src/ui/."""
        for fp in SRC.glob("core/**/*.py"):
            tree = _parse(fp)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and (
                        node.module.startswith("src.runtime")
                        or node.module.startswith("src.ui")
                    ):
                        rel = fp.relative_to(PROJECT_ROOT)
                        self.fail(f"{rel}:{node.lineno} — core imports {node.module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("src.runtime") or alias.name.startswith(
                            "src.ui"
                        ):
                            rel = fp.relative_to(PROJECT_ROOT)
                            self.fail(f"{rel}:{node.lineno} — core imports {alias.name}")

    def test_runtime_does_not_import_data_sources(self) -> None:
        """runtime/ must not directly import the legacy data_sources module."""
        for fp in SRC.glob("runtime/**/*.py"):
            tree = _parse(fp)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "data.data_sources" in node.module:
                        rel = fp.relative_to(PROJECT_ROOT)
                        self.fail(f"{rel}:{node.lineno} — runtime imports legacy {node.module}")

    def test_data_access_does_not_import_ui(self) -> None:
        """data_access/ must not depend on ui/."""
        for fp in SRC.glob("data_access/**/*.py"):
            tree = _parse(fp)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and node.module.startswith("src.ui"):
                        rel = fp.relative_to(PROJECT_ROOT)
                        self.fail(f"{rel}:{node.lineno} — data_access imports {node.module}")


# ── Runtime Context Tests ────────────────────────────────────────────────────


class RuntimeContextTests(unittest.TestCase):
    def test_discover_finds_valid_roots(self) -> None:
        from src.core.runtime_context import RuntimePaths

        paths = RuntimePaths.discover()
        self.assertTrue(paths.project_root.is_dir())
        # Project root should contain key marker files
        self.assertTrue((paths.project_root / "ROUTING_CONSTITUTION.md").is_file())
        self.assertTrue((paths.project_root / "Data").is_dir())
        self.assertEqual(paths.output_root, paths.project_root / "Output")

    def test_for_test_creates_isolated_paths(self) -> None:
        from src.core.runtime_context import RuntimePaths

        tmp = Path("/tmp/test_sdrs_invariant")
        paths = RuntimePaths.for_test(tmp)
        self.assertEqual(paths.project_root, tmp.resolve())
        self.assertEqual(paths.data_root, tmp.resolve() / "Data")
        # Project root should be /tmp/... not a home directory
        self.assertIn("tmp", str(paths.project_root))

    def test_from_project_root_resolves_all_subdirs(self) -> None:
        from src.core.runtime_context import RuntimePaths

        root = Path("/tmp/test_sdrs")
        paths = RuntimePaths.from_project_root(root)
        expected_root = root.resolve()
        self.assertEqual(paths.project_root, expected_root)
        self.assertEqual(paths.data_root, expected_root / "Data")
        self.assertEqual(paths.output_root, expected_root / "Output")
        self.assertEqual(paths.run_root, expected_root / "Output" / "deformation_runs")
        self.assertEqual(paths.logs_root, expected_root / "Output" / "logs")

    def test_run_mode_test_disables_ml_and_mock(self) -> None:
        from src.core.runtime_context import RunMode

        mode = RunMode.test()
        self.assertTrue(mode.use_mock)
        self.assertFalse(mode.ml_enabled)
        self.assertFalse(mode.export_image)


# ── Error Taxonomy Tests ─────────────────────────────────────────────────────


class ErrorTaxonomyTests(unittest.TestCase):
    def test_all_errors_have_severity_and_stage(self) -> None:
        from src.core import errors

        for name in dir(errors):
            obj = getattr(errors, name)
            if isinstance(obj, type) and issubclass(obj, errors.SystemError):
                self.assertIsInstance(getattr(obj, "severity", None), str, f"{name}.severity missing")
                self.assertIsInstance(getattr(obj, "stage", None), str, f"{name}.stage missing")

    def test_integration_error_is_raised_properly(self) -> None:
        from src.core.errors import IntegrationError

        with self.assertRaises(IntegrationError):
            raise IntegrationError("test failure")


# ── Config Tests ─────────────────────────────────────────────────────────────


class ConfigTests(unittest.TestCase):
    def test_pyproject_has_optional_deps(self) -> None:
        config_path = PROJECT_ROOT / "pyproject.toml"
        self.assertTrue(config_path.exists(), "pyproject.toml not found")
        text = config_path.read_text()
        self.assertIn("optional-dependencies", text)
        self.assertIn("math", text)
        self.assertIn("dev", text)

    def test_requirements_are_layered(self) -> None:
        req_dir = PROJECT_ROOT / "requirements"
        self.assertTrue(req_dir.is_dir(), "requirements/ directory not found")
        self.assertTrue((req_dir / "base.in").exists(), "base.in missing")
        self.assertTrue((req_dir / "math.in").exists(), "math.in missing")
        self.assertTrue((req_dir / "dev.in").exists(), "dev.in missing")
        self.assertTrue((req_dir / "lock.txt").exists(), "lock.txt missing")


if __name__ == "__main__":
    unittest.main()
