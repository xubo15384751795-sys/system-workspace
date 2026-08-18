"""Tests for the DuckDB audit index layer.

Uses temporary release fixtures that exercise every path in index_release(),
rebuild_index(), query_index(), and diff_releases() without touching
any real finalized release directory.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


from harvester.audit.index import (
    build_index,
    diff_releases,
    query_index,
    rebuild_index,
)
from harvester.core.catalog import build_catalog, write_catalog
from harvester.core.manifest import build_manifest, write_manifest
from harvester.core.provenance import build_provenance, record_provenance


# ── fixture helpers ────────────────────────────────────────────────────────


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_data_file(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return _sha256_bytes(content.encode("utf-8"))


def _create_release_fixture(root: Path, release_id: str, dataset_ids: list[str]) -> Path:
    """Create a minimal but valid frozen release directory.

    Returns the release directory path.
    """
    release_dir = root / release_id
    (release_dir / "data").mkdir(parents=True, exist_ok=True)
    (release_dir / "manifests").mkdir(parents=True, exist_ok=True)
    (release_dir / "provenance").mkdir(parents=True, exist_ok=True)

    for ds_id in dataset_ids:
        # -- data file ---------------------------------------------------------
        content = f"date,value\n2026-01-01,{hash(ds_id) % 100}\n2026-01-02,{hash(ds_id) % 100 + 1}\n"
        data_path = release_dir / "data" / f"{ds_id}.csv"
        data_sha = _write_data_file(data_path, content)
        byte_size = data_path.stat().st_size

        # -- manifest ----------------------------------------------------------
        manifest = build_manifest(
            dataset_id=ds_id,
            release_id=release_id,
            as_of_date="2026-01-02",
            vintage_date="2026-01-03",
            source={
                "provider": f"test-{ds_id.split('_')[0]}",
                "kind": "public_api",
                "url_or_reference": "https://test.example/api",
                "retrieved_at": "2026-01-03T00:00:00Z",
            },
            data_file={
                "path": f"data/{ds_id}.csv",
                "format": "csv",
                "sha256": data_sha,
                "byte_size": byte_size,
                "row_count": 2,
            },
            columns=[
                {"name": "date", "dtype": "date", "nullable": False,
                 "description": "Observation date.", "semantic_role": "time_index"},
                {"name": "value", "dtype": "float64", "nullable": False,
                 "description": "Observed value.", "semantic_role": "measure"},
            ],
            time_coverage={
                "start": "2026-01-01", "end": "2026-01-02",
                "frequency": "daily", "time_column": "date",
            },
            provenance_path=f"provenance/{ds_id}.provenance.json",
        )
        write_manifest(manifest, release_dir / "manifests" / f"{ds_id}.manifest.json")

        # -- provenance --------------------------------------------------------
        provenance = build_provenance(
            dataset_id=ds_id,
            release_id=release_id,
            acquisition={
                "method": "api_client",
                "source_identifier": f"test-provider-{ds_id.split('_')[0]}",
                "started_at": "2026-01-03T00:00:00Z",
                "completed_at": "2026-01-03T00:00:01Z",
                "operator": "harvester.test",
            },
            checksums={"raw_sha256": data_sha, "final_sha256": data_sha},
            notes="test provenance",
        )
        record_provenance(
            release_dir / "provenance" / f"{ds_id}.provenance.json",
            provenance,
            append=False,
        )

    # -- catalog ---------------------------------------------------------------
    catalog = build_catalog(
        release_dir,
        release_id=release_id,
        finalized_at="2026-01-03T00:00:00Z",
    )
    write_catalog(catalog, release_dir / "catalog.json")
    return release_dir


# ── tests ──────────────────────────────────────────────────────────────────


class TestAuditIndexBuild:
    def test_index_release_populates_tables(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        release_dir = _create_release_fixture(
            exports, "2026-01-03-r1",
            ["official_panel", "stress_indicator"],
        )
        db_path = str(tmp_path / "audit.duckdb")

        result = build_index(release_dir, db_path=db_path)
        assert result.skipped is False
        assert result.release_id == "2026-01-03-r1"
        assert result.datasets_indexed == 2
        assert result.provider_runs_indexed >= 1

    def test_index_release_skips_already_indexed(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        release_dir = _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])
        db_path = str(tmp_path / "audit.duckdb")

        first = build_index(release_dir, db_path=db_path)
        assert first.skipped is False

        second = build_index(release_dir, db_path=db_path)
        assert second.skipped is True

    def test_releases_table_row(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])
        db_path = str(tmp_path / "audit.duckdb")

        build_index(exports / "2026-01-03-r1", db_path=db_path)
        rows = query_index(
            "SELECT release_id, dataset_count, total_bytes FROM releases",
            db_path=db_path,
        )
        assert len(rows) == 1
        assert rows[0][0] == "2026-01-03-r1"
        assert rows[0][1] == 1
        assert rows[0][2] > 0  # total_bytes

    def test_datasets_table_row(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel", "stress_indicator"])
        db_path = str(tmp_path / "audit.duckdb")

        build_index(exports / "2026-01-03-r1", db_path=db_path)
        rows = query_index(
            "SELECT dataset_id, release_id, format, row_count, as_of_date FROM datasets ORDER BY dataset_id",
            db_path=db_path,
        )
        assert len(rows) == 2
        assert rows[0][0] == "official_panel"
        assert rows[0][1] == "2026-01-03-r1"
        assert rows[0][2] == "csv"
        assert rows[0][3] == 2

    def test_provider_runs_table(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel", "stress_indicator"])
        db_path = str(tmp_path / "audit.duckdb")

        build_index(exports / "2026-01-03-r1", db_path=db_path)
        rows = query_index(
            "SELECT release_id, provider_name, series_fetched FROM provider_runs",
            db_path=db_path,
        )
        assert len(rows) >= 1


class TestAuditIndexRebuild:
    def test_rebuild_rescans_all_releases(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])
        _create_release_fixture(exports, "2026-01-04-r1", ["official_panel", "stress_indicator"])
        db_path = str(tmp_path / "audit.duckdb")

        count = rebuild_index(exports, db_path=db_path)
        assert count == 2

        releases = query_index(
            "SELECT release_id FROM releases ORDER BY release_id", db_path=db_path
        )
        assert [r[0] for r in releases] == ["2026-01-03-r1", "2026-01-04-r1"]

    def test_rebuild_is_idempotent(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])
        db_path = str(tmp_path / "audit.duckdb")

        assert rebuild_index(exports, db_path=db_path) == 1
        assert rebuild_index(exports, db_path=db_path) == 1

        releases = query_index(
            "SELECT release_id FROM releases", db_path=db_path
        )
        assert len(releases) == 1

    def test_rebuild_skips_legacy_catalogs(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])
        legacy = exports / "20260101T000000Z"
        legacy.mkdir(parents=True)
        (legacy / "catalog.json").write_text(
            json.dumps({"bundle_id": "20260101T000000Z", "files": []}),
            encoding="utf-8",
        )
        db_path = str(tmp_path / "audit.duckdb")

        assert rebuild_index(exports, db_path=db_path) == 1

        releases = query_index(
            "SELECT release_id FROM releases", db_path=db_path
        )
        assert [r[0] for r in releases] == ["2026-01-03-r1"]


class TestAuditDiff:
    def test_diff_detects_added_datasets(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])
        _create_release_fixture(exports, "2026-01-04-r1", ["official_panel", "stress_indicator"])
        db_path = str(tmp_path / "audit.duckdb")

        rebuild_index(exports, db_path=db_path)
        changes = diff_releases("2026-01-03-r1", "2026-01-04-r1", db_path=db_path)

        added = [c for c in changes if c["change_type"] == "added"]
        removed = [c for c in changes if c["change_type"] == "removed"]
        unchanged = [c for c in changes if c["change_type"] == "unchanged"]

        assert len(added) == 1
        assert added[0]["dataset_id"] == "stress_indicator"
        assert len(removed) == 0
        assert len(unchanged) == 1
        assert unchanged[0]["dataset_id"] == "official_panel"

    def test_diff_detects_removed_datasets(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel", "stress_indicator"])
        _create_release_fixture(exports, "2026-01-04-r1", ["official_panel"])
        db_path = str(tmp_path / "audit.duckdb")

        rebuild_index(exports, db_path=db_path)
        changes = diff_releases("2026-01-03-r1", "2026-01-04-r1", db_path=db_path)

        removed = [c for c in changes if c["change_type"] == "removed"]
        assert len(removed) == 1
        assert removed[0]["dataset_id"] == "stress_indicator"

    def test_diff_detects_sha256_change(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])

        # Create release with same dataset_id but different content
        release_b = exports / "2026-01-04-r1"
        (release_b / "data").mkdir(parents=True, exist_ok=True)
        (release_b / "manifests").mkdir(parents=True, exist_ok=True)
        (release_b / "provenance").mkdir(parents=True, exist_ok=True)

        data_b = release_b / "data" / "official_panel.csv"
        content_b = "date,value\n2026-01-01,99\n2026-01-02,98\n"
        data_sha_b = _sha256_bytes(content_b.encode("utf-8"))
        data_b.write_text(content_b, encoding="utf-8")
        byte_size_b = data_b.stat().st_size

        manifest_b = build_manifest(
            dataset_id="official_panel", release_id="2026-01-04-r1",
            as_of_date="2026-01-02", vintage_date="2026-01-04",
            source={"provider": "test", "kind": "public_api", "retrieved_at": "2026-01-04T00:00:00Z"},
            data_file={"path": "data/official_panel.csv", "format": "csv", "sha256": data_sha_b, "byte_size": byte_size_b, "row_count": 2},
            columns=[{"name": "date", "dtype": "date", "nullable": False, "semantic_role": "time_index"},
                     {"name": "value", "dtype": "float64", "nullable": False, "semantic_role": "measure"}],
            time_coverage={"start": "2026-01-01", "end": "2026-01-02", "frequency": "daily", "time_column": "date"},
            provenance_path="provenance/official_panel.provenance.json",
        )
        write_manifest(manifest_b, release_b / "manifests" / "official_panel.manifest.json")

        prov_b = build_provenance(
            dataset_id="official_panel", release_id="2026-01-04-r1",
            acquisition={"method": "api_client", "source_identifier": "test", "started_at": "2026-01-04T00:00:00Z",
                         "completed_at": "2026-01-04T00:00:01Z", "operator": "test"},
            checksums={"raw_sha256": data_sha_b, "final_sha256": data_sha_b},
        )
        record_provenance(release_b / "provenance" / "official_panel.provenance.json", prov_b, append=False)

        catalog_b = build_catalog(release_b, release_id="2026-01-04-r1", finalized_at="2026-01-04T00:00:00Z")
        write_catalog(catalog_b, release_b / "catalog.json")

        db_path = str(tmp_path / "audit.duckdb")
        rebuild_index(exports, db_path=db_path)
        changes = diff_releases("2026-01-03-r1", "2026-01-04-r1", db_path=db_path)

        sha_changes = [c for c in changes if c["change_type"] in ("sha256_change", "row_growth", "row_shrink")]
        assert len(sha_changes) == 1
        assert sha_changes[0]["dataset_id"] == "official_panel"


class TestRebuildability:
    """Verify that the index is fully rebuildable from frozen releases alone."""

    def test_delete_db_and_rebuild_yields_same_data(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel", "stress_indicator"])
        db_path = str(tmp_path / "audit.duckdb")

        # First build
        build_index(exports / "2026-01-03-r1", db_path=db_path)
        first_releases = query_index("SELECT release_id, dataset_count FROM releases", db_path=db_path)
        first_datasets = query_index("SELECT dataset_id, row_count FROM datasets ORDER BY dataset_id", db_path=db_path)

        # Delete the DB
        Path(db_path).unlink()
        assert not Path(db_path).exists()

        # Rebuild
        rebuild_index(exports, db_path=db_path)
        second_releases = query_index("SELECT release_id, dataset_count FROM releases", db_path=db_path)
        second_datasets = query_index("SELECT dataset_id, row_count FROM datasets ORDER BY dataset_id", db_path=db_path)

        assert first_releases == second_releases
        assert first_datasets == second_datasets


class TestNoImmutableArtifactChanges:
    """The audit index must not write to or modify any release directory."""

    def test_indexing_does_not_modify_release_files(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        release_dir = _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])
        db_path = str(tmp_path / "audit.duckdb")

        # Snapshot the release directory before indexing
        before = {}
        for p in sorted(release_dir.rglob("*")):
            if p.is_file():
                before[str(p)] = (p.stat().st_mtime, p.stat().st_size, _sha256_bytes(p.read_bytes()))

        build_index(release_dir, db_path=db_path)

        # Verify nothing changed
        for filepath, (mtime_before, size_before, sha_before) in before.items():
            p = Path(filepath)
            mtime_after = p.stat().st_mtime
            size_after = p.stat().st_size
            sha_after = _sha256_bytes(p.read_bytes())
            assert mtime_after == mtime_before, f"{filepath} mtime changed"
            assert size_after == size_before, f"{filepath} size changed"
            assert sha_after == sha_before, f"{filepath} content changed"

    def test_duckdb_not_written_inside_exports(self, tmp_path: Path) -> None:
        exports = tmp_path / "exports"
        _create_release_fixture(exports, "2026-01-03-r1", ["official_panel"])
        db_path = str(tmp_path / "audit.duckdb")

        build_index(exports / "2026-01-03-r1", db_path=db_path)

        # No .duckdb file inside exports/
        db_files_in_exports = list(exports.rglob("*.duckdb"))
        assert len(db_files_in_exports) == 0, f"DuckDB file leaked into exports: {db_files_in_exports}"


class TestNoProviderWritesToDuckDB:
    """Providers never write to DuckDB; only the audit layer does."""

    def test_provider_code_has_no_duckdb_imports(self, tmp_path: Path) -> None:
        providers_dir = (
            Path(__file__).resolve().parents[1] / "src" / "harvester" / "providers"
        )
        duckdb_refs: list[str] = []
        for py_file in sorted(providers_dir.glob("*.py")):
            content = py_file.read_text()
            if "duckdb" in content and py_file.name != "__init__.py":
                # __init__.py is the provider registry, not a data provider
                duckdb_refs.append(str(py_file.relative_to(providers_dir.parent.parent.parent)))
        assert len(duckdb_refs) == 0, (
            f"Provider files must not reference DuckDB: {duckdb_refs}"
        )
