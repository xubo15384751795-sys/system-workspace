from __future__ import annotations

import ast
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_UI_IMPORTS = (
    "src.data.gateway",
    "src.proxies",
    "src.diagnostics",
    "src.derivation",
    "src.benchmarks",
    "harvester",
)


class UIContractTests(unittest.TestCase):
    def test_run_viewer_does_not_import_computation_modules(self) -> None:
        path = PROJECT_ROOT / "src" / "ui" / "run_viewer.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders = [
            module
            for module in _imported_modules(tree)
            if module == "harvester" or module.startswith(FORBIDDEN_UI_IMPORTS)
        ]

        self.assertEqual(offenders, [])

    def test_legacy_ui_is_marked_compatibility_only(self) -> None:
        text = (PROJECT_ROOT / "src" / "ui" / "app.py").read_text(encoding="utf-8")

        self.assertIn("Legacy interactive UI retained for compatibility", text)
        self.assertIn("No new features should be added here", text)

def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


if __name__ == "__main__":
    unittest.main()
