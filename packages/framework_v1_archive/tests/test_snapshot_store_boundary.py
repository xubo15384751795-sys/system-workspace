"""Boundary test: production paths must not directly construct DuckDBSnapshotStore.

After the 2026-07-07-duckdb-snapshot-store-migration SEAL phase, the legacy
DuckDBSnapshotStore is sealed read-only. Production code must obtain snapshot
stores through the backend selector (assembly._build_snapshot_store) rather
than constructing DuckDBSnapshotStore directly, so the backend can be swapped
to HarvesterSnapshotStore via config.

Exempt files (legitimate direct references):
  - src/runtime/assembly.py — the backend selector itself
  - src/data/snapshot_store.py — the class definition
  - src/data/dual_write_snapshot_store.py — wraps both backends
  - src/data/snapshot_store_freeze.py — freeze guard
  - scripts/backfill_runtime_snapshots.py — batch migration tool (transitional)

Mirrors tests/test_data_boundary_extended.py::test_production_paths_do_not_import_legacy.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


class SnapshotStoreBoundaryTests(unittest.TestCase):
    def test_production_paths_do_not_directly_construct_duckdb_store(self) -> None:
        """Production src/ must not call DuckDBSnapshotStore(...) directly.

        The backend selector (assembly._build_snapshot_store) is the only
        legitimate construction site. Direct construction bypasses the
        config-driven backend choice and would prevent Harvester cutover.
        """
        root = Path(__file__).resolve().parents[1]
        framework_src = root / "src"

        # Production directories to scan
        production_dirs = [
            framework_src / "runtime",
            framework_src / "core",
            framework_src / "output",
            framework_src / "ml",
            framework_src / "ui",
            framework_src / "data_access",
            framework_src / "derivation",
            framework_src / "dynamics",
            framework_src / "diagnostics",
            framework_src / "operators",
            framework_src / "mechanisms",
            framework_src / "nlp",
            framework_src / "validation",
            framework_src / "proxies",
        ]

        # Exemptions: files legitimately allowed to reference DuckDBSnapshotStore
        exempt_files = {
            framework_src / "runtime" / "assembly.py",  # backend selector
            framework_src / "data" / "snapshot_store.py",  # class definition
            framework_src / "data" / "dual_write_snapshot_store.py",  # wraps both
            framework_src / "data" / "snapshot_store_freeze.py",  # freeze guard
        }

        violations: list[str] = []

        for prod_dir in production_dirs:
            if not prod_dir.exists():
                continue
            py_files = (
                [prod_dir] if prod_dir.is_file() else list(prod_dir.rglob("*.py"))
            )
            for py_file in py_files:
                if "__pycache__" in str(py_file):
                    continue
                if py_file in exempt_files:
                    continue
                try:
                    source = py_file.read_text(encoding="utf-8")
                    tree = ast.parse(source, filename=str(py_file))
                except (SyntaxError, UnicodeDecodeError):
                    continue

                for node in ast.walk(tree):
                    # Detect DuckDBSnapshotStore(...) constructor calls
                    if isinstance(node, ast.Call):
                        func = node.func
                        name = None
                        if isinstance(func, ast.Name):
                            name = func.id
                        elif isinstance(func, ast.Attribute):
                            name = func.attr
                        if name == "DuckDBSnapshotStore":
                            violations.append(
                                f"{py_file.relative_to(root)}:{node.lineno} "
                                f"directly constructs DuckDBSnapshotStore — use "
                                f"assembly._build_snapshot_store(config) instead"
                            )

        self.assertEqual(
            violations,
            [],
            "Production paths must not directly construct DuckDBSnapshotStore. "
            "Use assembly._build_snapshot_store(config) which selects the backend "
            "via config['snapshot_store']['backend']. Violations:\n"
            + "\n".join(violations),
        )

    def test_duckdb_snapshot_store_has_retire_after_marker(self) -> None:
        """DuckDBSnapshotStore must carry a retire_after marker in its docstring."""
        from src.data.snapshot_store import DuckDBSnapshotStore

        doc = DuckDBSnapshotStore.__doc__ or ""
        self.assertIn("retire_after", doc, "DuckDBSnapshotStore docstring must declare retire_after")
        self.assertIn("2026-10-15", doc, "DuckDBSnapshotStore retire_after must be 2026-10-15")

    def test_duckdb_write_methods_are_guarded(self) -> None:
        """DuckDBSnapshotStore write methods must be decorated with the freeze guard."""
        import inspect

        from src.data.snapshot_store import DuckDBSnapshotStore

        write_methods = [
            "save",
            "save_fast_signal",
            "save_cross_validation",
            "upsert_raw_series",
            "upsert_event_log",
        ]
        for method_name in write_methods:
            method = getattr(DuckDBSnapshotStore, method_name, None)
            self.assertIsNotNone(method, f"{method_name} must exist on DuckDBSnapshotStore")
            assert method is not None
            # The @guard_method decorator wraps the method; the source should
            # show the @_guard_write decorator applied.
            source = inspect.getsource(method)
            self.assertIn(
                "_guard_write",
                source,
                f"{method_name} must be decorated with @_guard_write (freeze guard)",
            )


if __name__ == "__main__":
    unittest.main()
