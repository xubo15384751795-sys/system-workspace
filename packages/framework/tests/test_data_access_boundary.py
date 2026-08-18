from __future__ import annotations

import ast
import hashlib
import json
from typing import cast

import pytest

pytestmark = pytest.mark.data_boundary
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import warnings

import pandas as pd

from src.data_access import (
    EvidenceBoundaryError,
    DataBackend,
    DataSourceRouter,
    HarvesterAdapter,
    HarvesterBundle,
    HarvesterCatalogMissingError,
    HarvesterIntegrityError,
    HarvesterSchemaError,
    LegacyDataAdapter,
)
from src.core.runtime_context import RuntimePaths
from src.data.paths import resolve_data_root, resolve_fred_cache_dir, resolve_lab_root, resolve_snapshot_store_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HARVESTER_CONTRACTS = PROJECT_ROOT.parent / "harvester" / "contracts"


class DataAccessBoundaryTests(unittest.TestCase):
    def test_legacy_backend_still_loads_current_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            proxy_dir = root / "processed" / "proxies"
            proxy_dir.mkdir(parents=True)
            _write_parquet(
                pd.DataFrame(
                    {
                        "run_date": ["2026-04-26"],
                        "M": [0.1],
                        "D": [0.2],
                        "K": [0.3],
                        "X": [0.4],
                    }
                ),
                proxy_dir / "proxy_readings.parquet",
            )

            adapter = LegacyDataAdapter({"data": {"root": str(root)}})
            frame = adapter.load_table("proxy_readings")
            inventory = adapter.inventory()

            self.assertEqual(adapter.backend, "legacy")
            self.assertEqual(float(frame.loc[0, "M"]), 0.1)
            self.assertIn("source_role", frame.columns)
            self.assertEqual(frame.loc[0, "source_role"], "proxy_candidate")
            self.assertTrue(any(entry.path.endswith("proxy_readings.parquet") for entry in inventory))

    def test_legacy_backend_uses_lab_root_and_rejects_harvester_internal_roots(self) -> None:
        with TemporaryDirectory() as tmp:
            system_root = Path(tmp)
            lab_root = system_root / "structural_lab"
            (lab_root / "processed").mkdir(parents=True)
            config = {
                "data": {
                    "system_root": str(system_root),
                    "lab_root": str(lab_root),
                }
            }

            adapter = LegacyDataAdapter(config)

            self.assertEqual(adapter.data_root, lab_root)
            with self.assertRaises(ValueError):
                LegacyDataAdapter(data_root=str(RuntimePaths.discover().harvester_root / "raw"))

    def test_runtime_paths_default_under_lab_root(self) -> None:
        with TemporaryDirectory() as tmp:
            system_root = Path(tmp)
            config = {"data": {"system_root": str(system_root)}}

            self.assertEqual(resolve_data_root(config), system_root / "structural_lab")
            self.assertEqual(
                resolve_snapshot_store_path(config),
                system_root / "structural_lab" / "runtime" / "system.duckdb",
            )

    def test_default_paths_never_fall_back_to_old_system_root_locations(self) -> None:
        with TemporaryDirectory() as tmp:
            system_root = Path(tmp)
            config = {"data": {"system_root": str(system_root)}}

            self.assertEqual(resolve_lab_root(config), system_root / "structural_lab")
            self.assertNotEqual(resolve_snapshot_store_path(config), system_root / "system.duckdb")
            self.assertEqual(
                resolve_snapshot_store_path(config),
                system_root / "structural_lab" / "runtime" / "system.duckdb",
            )
            self.assertEqual(
                resolve_fred_cache_dir(config),
                system_root / "structural_lab" / "runtime" / "fred_cache",
            )
            self.assertNotEqual(resolve_fred_cache_dir(config), system_root / "raw" / "fred")
            self.assertNotEqual(resolve_fred_cache_dir(config), system_root / "harvester" / "raw" / "fred")

    def test_project_config_declares_path_boundary(self) -> None:
        import yaml

        config = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"))

        # Validate that config declares required boundary keys (not exact machine paths).
        self.assertIn("data", config)
        self.assertIn("system_root", config["data"])
        self.assertIn("lab_root", config["data"])
        self.assertIn("backend", config["data"])
        self.assertIsInstance(config["data"]["system_root"], str)
        self.assertTrue(len(config["data"]["system_root"]) > 0, "data.system_root must be a non-empty string")
        self.assertIsInstance(config["data"]["lab_root"], str)
        self.assertTrue(len(config["data"]["lab_root"]) > 0, "data.lab_root must be a non-empty string")

        self.assertIn("runtime", config)
        self.assertIsInstance(config["runtime"]["duckdb_path"], str)
        self.assertTrue(len(config["runtime"]["duckdb_path"]) > 0)
        self.assertIsInstance(config["runtime"]["calibration_dir"], str)
        self.assertTrue(len(config["runtime"]["calibration_dir"]) > 0)

        self.assertIn("harvester", config)
        self.assertIsInstance(config["harvester"]["exports_root"], str)
        self.assertTrue(len(config["harvester"]["exports_root"]) > 0)
        self.assertIs(config["harvester"]["require_finalized"], True)
        self.assertIs(config["harvester"]["validate_hashes"], True)
        self.assertIs(config["harvester"]["validate_schema"], True)
        self.assertIs(config["harvester"]["allow_legacy_fallback_when_harvester_selected"], False)

        self.assertIn("legacy", config)
        self.assertIsInstance(config["legacy"]["root"], str)
        self.assertTrue(len(config["legacy"]["root"]) > 0)
        self.assertIs(config["legacy"]["allow_direct_fetch"], False)
        self.assertIs(config["allow_legacy_fallback"], False)

        self.assertIn("data_sources", config)
        self.assertIsNone(config["data_sources"]["fred_cache_dir"])

    def test_legacy_acquisition_path_emits_authority_warning(self) -> None:
        from src.runtime.assembly import build_system

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "data_backend": "legacy",
                "data": {
                    "system_root": str(root),
                    "lab_root": str(root / "lab"),
                    "backend": "legacy",
                },
                "runtime": {"duckdb_path": str(root / "lab" / "runtime" / "system.duckdb")},
            }
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                build_system(config, use_mock=True)

            assert any("AUTHORITY CONFIG WARNING" in str(item.message) for item in caught)

    def test_router_chooses_legacy_backend_with_deprecation_warning(self) -> None:
        self.assertEqual(DataSourceRouter({"data_backend": "legacy"}).backend, DataBackend.LEGACY)
        with self.assertRaises(EvidenceBoundaryError):
            DataSourceRouter({"data_backend": "legacy"}).create_adapter()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            adapter = DataSourceRouter({"data_backend": "legacy"}, allow_legacy=True).create_adapter()

        self.assertIsInstance(adapter, LegacyDataAdapter)
        self.assertTrue(any(item.category is DeprecationWarning for item in caught))

    def test_router_defaults_to_harvester_backend(self) -> None:
        self.assertEqual(DataSourceRouter({}).backend, DataBackend.HARVESTER)

    def test_router_harvester_backend_requires_loadable_catalog(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "exports").mkdir()
            router = DataSourceRouter(
                {
                    "data_backend": "harvester",
                    "harvester": {
                        "exports_root": str(root / "exports"),
                        "root": str(root),
                        "require_finalized": True,
                    },
                }
            )

            with self.assertRaises(HarvesterCatalogMissingError):
                router.create_adapter()

    def test_harvester_adapter_raises_when_catalog_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "exports").mkdir()

            with self.assertRaises(HarvesterCatalogMissingError):
                HarvesterAdapter(root, contract_root=HARVESTER_CONTRACTS)

    def test_harvester_adapter_raises_when_catalog_schema_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            root, release_dir = _make_release_root(Path(tmp))
            (release_dir / "catalog.json").write_text(json.dumps({"datasets": []}), encoding="utf-8")
            (release_dir / ".finalized").write_text("{}\n", encoding="utf-8")

            with self.assertRaises(HarvesterSchemaError):
                HarvesterAdapter(root, contract_root=HARVESTER_CONTRACTS)

    def test_harvester_adapter_raises_when_sha256_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            root, release_dir = _write_harvester_bundle(Path(tmp))
            data_path = release_dir / "data" / "sample_panel.csv"
            data_path.write_text("date,value\n2026-04-25,99.0\n", encoding="utf-8")

            adapter = HarvesterAdapter(root, contract_root=HARVESTER_CONTRACTS)
            with self.assertRaises(HarvesterIntegrityError):
                adapter.load_dataset("sample_panel")

    def test_harvester_adapter_loads_catalog_manifest_and_data(self) -> None:
        with TemporaryDirectory() as tmp:
            root, _release_dir = _write_harvester_bundle(Path(tmp))

            adapter = HarvesterAdapter(root, contract_root=HARVESTER_CONTRACTS)
            self.assertEqual(adapter.list_datasets(), ["sample_panel"])
            manifest = adapter.get_manifest("sample_panel")
            frame = adapter.load_dataset("sample_panel", as_of="2026-04-25", vintage="2026-04-26")

            self.assertEqual(manifest["dataset_id"], "sample_panel")
            self.assertEqual(float(frame.loc[0, "value"]), 1.0)

    def test_harvester_adapter_accepts_explicit_exports_root_release_and_catalog(self) -> None:
        with TemporaryDirectory() as tmp:
            root, _release_dir = _write_harvester_bundle(Path(tmp))

            adapter = HarvesterAdapter(
                exports_root=root / "exports",
                release="latest",
                catalog_file="catalog.json",
                require_finalized=True,
                validate_hashes=True,
                validate_schema=True,
                contract_root=HARVESTER_CONTRACTS,
            )

            self.assertEqual(adapter.list_datasets(), ["sample_panel"])

    def test_harvester_bundle_catalog_rejects_unfinalized_status(self) -> None:
        with TemporaryDirectory() as tmp:
            root, release_dir = _write_bundle_release(Path(tmp), status="draft")

            with self.assertRaises(HarvesterIntegrityError):
                HarvesterAdapter(
                    exports_root=root / "exports",
                    release=release_dir.name,
                    contract_root=HARVESTER_CONTRACTS,
                )

    def test_harvester_bundle_catalog_rejects_missing_declared_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root, release_dir = _write_bundle_release(Path(tmp))
            (release_dir / "data" / "corpus_index.parquet").unlink()

            with self.assertRaises(HarvesterIntegrityError):
                HarvesterAdapter(
                    exports_root=root / "exports",
                    release=release_dir.name,
                    contract_root=HARVESTER_CONTRACTS,
                )

    def test_harvester_bundle_catalog_rejects_hash_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            root, release_dir = _write_bundle_release(Path(tmp))
            _write_parquet(
                pd.DataFrame(
                    {
                        "candidate_id": ["changed"],
                        "as_of_date": ["2026-04-26"],
                        "mechanism_channel": ["M"],
                        "proxy_name": ["changed"],
                        "source_id": ["unit"],
                        "source_series_id": ["changed"],
                        "value": [2.0],
                        "unit": ["index"],
                        "frequency": ["daily"],
                        "status": ["observed"],
                        "notes": [""],
                    }
                ),
                release_dir / "data" / "proxy_candidate_panel.parquet",
            )

            with self.assertRaises(HarvesterIntegrityError):
                HarvesterAdapter(
                    exports_root=root / "exports",
                    release=release_dir.name,
                    contract_root=HARVESTER_CONTRACTS,
                )

    def test_harvester_bundle_catalog_loads_minimal_bundle(self) -> None:
        with TemporaryDirectory() as tmp:
            root, release_dir = _write_bundle_release(Path(tmp))
            adapter = HarvesterAdapter(
                exports_root=root / "exports",
                release=release_dir.name,
                contract_root=HARVESTER_CONTRACTS,
            )

            bundle = adapter.load_bundle()

            self.assertIsInstance(bundle, HarvesterBundle)
            self.assertEqual(bundle.bundle_id, release_dir.name)
            self.assertEqual(adapter.list_datasets(), ["benchmark_panel", "corpus_index", "proxy_candidate_panel"])
            self.assertEqual(float(bundle.benchmark_panel.loc[0, "value"]), 1.0)
            self.assertEqual(bundle.source_registry["status"], "finalized")
            self.assertTrue(bundle.validation_report["checked_files"])

    def test_proxy_modules_do_not_import_direct_connectors(self) -> None:
        forbidden_prefixes = (
            "src.data.gateway",
            "src.data.adapters",
            "src.data.data_sources",
            "src.data.external_downloads",
            "src.research_corpus.providers",
        )
        offenders: list[str] = []
        for path in (PROJECT_ROOT / "src" / "proxies").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for module in _imported_modules(tree):
                if module.startswith(forbidden_prefixes):
                    offenders.append(f"{path.name}: {module}")

        self.assertEqual(offenders, [])


def _make_release_root(root: Path) -> tuple[Path, Path]:
    release_dir = root / "exports" / "2026-04-26-r1"
    release_dir.mkdir(parents=True)
    latest = root / "exports" / "latest"
    latest.symlink_to("2026-04-26-r1")
    return root, release_dir


def _write_harvester_bundle(root: Path) -> tuple[Path, Path]:
    root, release_dir = _make_release_root(root)
    (release_dir / "data").mkdir()
    (release_dir / "manifests").mkdir()
    (release_dir / "provenance").mkdir()

    data_path = release_dir / "data" / "sample_panel.csv"
    data_path.write_text("date,value\n2026-04-25,1.0\n", encoding="utf-8")
    sha = _sha256(data_path)
    byte_size = data_path.stat().st_size

    manifest = {
        "schema_version": "1.0",
        "dataset_id": "sample_panel",
        "dataset_revision": 1,
        "release_id": "2026-04-26-r1",
        "as_of_date": "2026-04-25",
        "vintage_date": "2026-04-26",
        "source": {
            "provider": "unit-test",
            "kind": "manual_curation",
            "url_or_reference": "tests",
            "retrieved_at": "2026-04-26T00:00:00Z",
        },
        "data_file": {
            "path": "data/sample_panel.csv",
            "format": "csv",
            "sha256": sha,
            "byte_size": byte_size,
            "row_count": 1,
        },
        "columns": [
            {"name": "date", "dtype": "date", "nullable": False, "description": "Observation date."},
            {"name": "value", "dtype": "float64", "nullable": False, "description": "Observed value."},
        ],
        "time_coverage": {"start": "2026-04-25", "end": "2026-04-25", "frequency": "daily", "time_column": "date"},
        "lineage": {"provenance_path": "provenance/sample_panel.provenance.json"},
    }
    _write_json(release_dir / "manifests" / "sample_panel.manifest.json", manifest)

    provenance = {
        "schema_version": "1.0",
        "dataset_id": "sample_panel",
        "dataset_revision": 1,
        "release_id": "2026-04-26-r1",
        "acquisition": {
            "method": "manual_upload",
            "source_identifier": "tests",
            "started_at": "2026-04-26T00:00:00Z",
            "completed_at": "2026-04-26T00:00:01Z",
            "operator": "unittest",
        },
        "transformations": [],
        "checksums": {"raw_sha256": sha, "final_sha256": sha},
    }
    _write_json(release_dir / "provenance" / "sample_panel.provenance.json", provenance)

    catalog = {
        "schema_version": "1.0",
        "harvester_version": "0.1.0",
        "release_id": "2026-04-26-r1",
        "finalized_at": "2026-04-26T00:00:02Z",
        "datasets": [
            {
                "dataset_id": "sample_panel",
                "dataset_revision": 1,
                "manifest_path": "manifests/sample_panel.manifest.json",
                "data_path": "data/sample_panel.csv",
                "provenance_path": "provenance/sample_panel.provenance.json",
            }
        ],
    }
    _write_json(release_dir / "catalog.json", catalog)
    (release_dir / ".finalized").write_text("{}\n", encoding="utf-8")
    return root, release_dir


def _write_bundle_release(root: Path, status: str = "finalized") -> tuple[Path, Path]:
    release_dir = root / "exports" / "2026-04-26-r1"
    data_dir = release_dir / "data"
    data_dir.mkdir(parents=True)
    (root / "exports" / "latest").symlink_to("2026-04-26-r1")

    frames = {
        "benchmark_panel": pd.DataFrame(
            {
                "date": ["2026-04-26"],
                "series_id": ["TEST"],
                "source_id": ["unit"],
                "source_series_id": ["TEST"],
                "value": [1.0],
                "unit": ["index"],
                "frequency": ["daily"],
                "vintage_date": ["2026-04-26"],
                "quality_flag": ["observed"],
            }
        ),
        "proxy_candidate_panel": pd.DataFrame(
            {
                "candidate_id": ["candidate_1"],
                "as_of_date": ["2026-04-26"],
                "mechanism_channel": ["M"],
                "proxy_name": ["test_proxy"],
                "source_id": ["unit"],
                "source_series_id": ["TEST"],
                "value": [1.0],
                "unit": ["index"],
                "frequency": ["daily"],
                "status": ["observed"],
                "notes": [""],
            }
        ),
        "corpus_index": pd.DataFrame(
            {
                "document_id": ["doc_1"],
                "source_id": ["unit"],
                "title": ["Test document"],
                "publisher": ["Unit"],
                "published_date": ["2026-04-26"],
                "retrieved_at": ["2026-04-26T00:00:00Z"],
                "url_or_reference": ["tests"],
                "document_type": ["note"],
                "status": ["indexed"],
                "sha256": ["0" * 64],
            }
        ),
    }

    files: list[dict] = []
    for role, frame in frames.items():
        path = data_dir / f"{role}.parquet"
        _write_parquet(frame, path)
        files.append(_catalog_file_entry(release_dir, path, role, "parquet", frame.columns))

    manifest_path = release_dir / "manifest.jsonl"
    manifest_rows = [
        {
            "bundle_id": release_dir.name,
            "path": entry["path"],
            "role": entry["role"],
            "format": entry["format"],
            "sha256": entry["sha256"],
            "status": status,
        }
        for entry in files
    ]
    manifest_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in manifest_rows) + "\n",
        encoding="utf-8",
    )
    files.append(_catalog_file_entry(release_dir, manifest_path, "manifest", "jsonl", ()))

    provenance_path = release_dir / "provenance.jsonl"
    provenance_path.write_text(
        json.dumps(
            {
                "bundle_id": release_dir.name,
                "path": "data/benchmark_panel.parquet",
                "role": "benchmark_panel",
                "sha256": files[0]["sha256"],
                "status": status,
                "transformations": ["unit test fixture"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    files.append(_catalog_file_entry(release_dir, provenance_path, "provenance", "jsonl", ()))

    source_registry_path = release_dir / "source_registry.json"
    _write_json(
        source_registry_path,
        {"bundle_id": release_dir.name, "sources": [], "status": status},
    )
    files.append(_catalog_file_entry(release_dir, source_registry_path, "source_registry", "json", ()))

    export_report_path = release_dir / "export_report.md"
    export_report_path.write_text("# Export Report\n", encoding="utf-8")
    files.append(_catalog_file_entry(release_dir, export_report_path, "export_report", "markdown", ()))

    _write_json(
        release_dir / "catalog.json",
        {
            "bundle_id": release_dir.name,
            "created_at": "2026-04-26T00:00:00Z",
            "files": files,
            "producer": {"host": "unit", "operator": "unit"},
            "status": status,
        },
    )
    return root, release_dir


def _catalog_file_entry(release_dir: Path, path: Path, role: str, file_format: str, columns: object) -> dict:
    rel = path.relative_to(release_dir).as_posix()
    entry = {
        "byte_size": path.stat().st_size,
        "format": file_format,
        "path": rel,
        "role": role,
        "sha256": _sha256(path),
    }
    if file_format == "parquet":
        entry["schema"] = {
            "format": "parquet",
            "columns": [
                {"name": str(name), "nullable": True, "type": "string"}
                for name in cast(list[object], columns)
            ],
        }
    return entry


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_parquet(path, index=False)
    except Exception:
        import polars as pl

        pl.DataFrame(frame.to_dict(orient="list")).write_parquet(path)


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
