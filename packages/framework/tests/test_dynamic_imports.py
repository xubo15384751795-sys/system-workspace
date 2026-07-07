"""DYN-1.1 / boundary: dynamic package imports; core must not depend on it."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

import src.dynamic as dynamic_pkg
from src.dynamic import EventPhase, TemporalFrame, get_temporal_frame, list_temporal_frames


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports_dynamic_module(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "src.dynamic" or mod.startswith("src.dynamic."):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "src.dynamic" or alias.name.startswith("src.dynamic."):
                    return True
    return False


class TestDynamicImports(unittest.TestCase):
    def test_package_imports(self) -> None:
        assert dynamic_pkg.__doc__
        self.assertIs(EventPhase, dynamic_pkg.EventPhase)
        self.assertIs(TemporalFrame, dynamic_pkg.TemporalFrame)
        self.assertIs(get_temporal_frame, dynamic_pkg.get_temporal_frame)
        self.assertIs(list_temporal_frames, dynamic_pkg.list_temporal_frames)

    def test_core_pipeline_does_not_import_dynamic(self) -> None:
        """Core scoring layer must not depend on src.dynamic (non-invasive spine)."""
        core_dir = SRC / "core"
        self.assertTrue(core_dir.is_dir(), "expected src/core/")
        offenders: list[str] = []
        for fp in sorted(core_dir.rglob("*.py")):
            if fp.name.startswith("__"):
                continue
            tree = _parse(fp)
            if _imports_dynamic_module(tree):
                offenders.append(str(fp.relative_to(PROJECT_ROOT)))
        self.assertEqual(
            offenders,
            [],
            "src/core must not import src.dynamic:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
