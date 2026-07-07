"""DuckDB audit index — a rebuildable projection over finalized releases.

Source of truth:  exports/<release_id>/catalog.json
                  exports/<release_id>/manifests/*.manifest.json
                  exports/<release_id>/provenance/*.provenance.json
                  exports/<release_id>/quality_reports/*.quality.json

DuckDB is NOT the source of truth.  Every row in these tables can be
reconstructed by re-reading the frozen release directories.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from harvester.core.catalog import CatalogValidationError, load_catalog

# ── DDL ──────────────────────────────────────────────────────────────────────

DDL_RELEASES = """
CREATE TABLE IF NOT EXISTS releases (
    release_id          TEXT PRIMARY KEY,
    finalized_at        TIMESTAMP,
    harvester_version   TEXT,
    dataset_count       INTEGER NOT NULL DEFAULT 0,
    total_bytes         BIGINT  NOT NULL DEFAULT 0,
    catalog_sha256      TEXT,
    indexed_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    release_path        TEXT,
    notes               TEXT
)
"""

DDL_DATASETS = """
CREATE TABLE IF NOT EXISTS datasets (
    dataset_id          TEXT NOT NULL,
    release_id          TEXT NOT NULL,
    dataset_revision    INTEGER NOT NULL DEFAULT 1,
    format              TEXT,
    row_count           BIGINT,
    byte_size           BIGINT,
    data_sha256         TEXT,
    as_of_date          DATE,
    vintage_date        DATE,
    source_provider     TEXT,
    source_kind         TEXT,
    time_start          DATE,
    time_end            DATE,
    time_frequency      TEXT,
    manifest_path       TEXT,
    provenance_path     TEXT,
    quality_report_path TEXT,
    notes               TEXT,
    PRIMARY KEY (dataset_id, release_id)
)
"""

DDL_PROVIDER_RUNS = """
CREATE TABLE IF NOT EXISTS provider_runs (
    run_id              TEXT PRIMARY KEY,
    release_id          TEXT NOT NULL,
    provider_name       TEXT NOT NULL,
    series_fetched      INTEGER NOT NULL DEFAULT 0,
    series_succeeded    INTEGER NOT NULL DEFAULT 0,
    series_failed       INTEGER NOT NULL DEFAULT 0,
    run_started_at      TIMESTAMP,
    run_completed_at    TIMESTAMP,
    fetch_errors        TEXT,
    provenance_data     TEXT,
    indexed_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_DATASET_CHANGES = """
CREATE TABLE IF NOT EXISTS dataset_changes (
    change_id           TEXT PRIMARY KEY,
    dataset_id          TEXT NOT NULL,
    release_a           TEXT NOT NULL,
    release_b           TEXT NOT NULL,
    change_type         TEXT NOT NULL,
    detail              TEXT,
    compared_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

ALL_DDL = [DDL_RELEASES, DDL_DATASETS, DDL_PROVIDER_RUNS, DDL_DATASET_CHANGES]


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _sha256_file(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── AuditIndex class ────────────────────────────────────────────────────────

@dataclass
class IndexReleaseResult:
    release_id: str
    datasets_indexed: int
    provider_runs_indexed: int
    skipped: bool


class AuditIndex:
    """Manages a DuckDB audit index over finalized Harvester releases."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._con: duckdb.DuckDBPyConnection | None = None

    # -- connection management -------------------------------------------------

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            self._con = duckdb.connect(str(self._db_path))
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def _ensure_tables(self) -> None:
        for ddl in ALL_DDL:
            self.con.execute(ddl)

    # -- rebuild ---------------------------------------------------------------

    def rebuild(self, exports_root: str | Path) -> int:
        """Drop all tables, re-create, and re-index every finalized release.

        Returns the number of releases indexed.
        """
        root = Path(exports_root)
        if not root.exists():
            return 0

        # Drop and recreate
        for tbl in ("dataset_changes", "provider_runs", "datasets", "releases"):
            self.con.execute(f"DROP TABLE IF EXISTS {tbl}")
        self._ensure_tables()

        releases = sorted(
            d for d in root.iterdir()
            if d.is_dir() and d.name != "latest" and not d.name.startswith(".")
            and (d / "catalog.json").exists()
        )
        count = 0
        for release_dir in releases:
            try:
                result = self.index_release(release_dir)
            except (CatalogValidationError, KeyError, ValueError):
                continue
            if not result.skipped:
                count += 1
        return count

    # -- index one release -----------------------------------------------------

    def index_release(self, release_path: str | Path) -> IndexReleaseResult:
        """Index a single finalized release into DuckDB.

        Reads catalog.json, every manifest, every provenance record,
        and every quality report from the frozen release directory.
        """
        rpath = Path(release_path)
        catalog_path = rpath / "catalog.json"
        if not catalog_path.exists():
            raise FileNotFoundError(f"catalog.json not found in {rpath}")

        catalog = load_catalog(rpath)
        release_id = catalog["release_id"]
        if rpath.name != release_id:
            raise ValueError(
                f"Release directory name {rpath.name!r} does not match "
                f"catalog.release_id {release_id!r}"
            )

        self._ensure_tables()

        # Skip if already indexed
        existing = self.con.execute(
            "SELECT 1 FROM releases WHERE release_id = ?", [release_id]
        ).fetchone()
        if existing:
            return IndexReleaseResult(
                release_id=release_id, datasets_indexed=0,
                provider_runs_indexed=0, skipped=True,
            )

        catalog_sha = _sha256_file(catalog_path)
        now = _timestamp()

        # -- releases table ----------------------------------------------------
        datasets_list = catalog.get("datasets", [])
        total_bytes = 0
        for ds in datasets_list:
            data_path = rpath / ds["data_path"]
            if data_path.exists():
                total_bytes += data_path.stat().st_size

        self.con.execute(
            """INSERT INTO releases
               (release_id, finalized_at, harvester_version, dataset_count,
                total_bytes, catalog_sha256, indexed_at, release_path, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                release_id,
                catalog.get("finalized_at", ""),
                catalog.get("harvester_version", ""),
                len(datasets_list),
                total_bytes,
                catalog_sha,
                now,
                str(rpath.resolve()),
                catalog.get("notes", ""),
            ],
        )

        # -- datasets table ----------------------------------------------------
        datasets_count = 0
        for ds_entry in datasets_list:
            manifest_path = rpath / ds_entry["manifest_path"]
            prov_path = rpath / ds_entry["provenance_path"]
            qr_path_raw = ds_entry.get("quality_report_path", "")
            qr_path = rpath / qr_path_raw if qr_path_raw else None
            qr_exists = qr_path is not None and qr_path.exists()

            manifest = _read_json(manifest_path) if manifest_path.exists() else {}
            provenance = _read_json(prov_path) if prov_path.exists() else {}
            data_file = manifest.get("data_file", {})
            source = manifest.get("source", {})
            time_cov = manifest.get("time_coverage", {})

            self.con.execute(
                """INSERT INTO datasets
                   (dataset_id, release_id, dataset_revision, format,
                    row_count, byte_size, data_sha256,
                    as_of_date, vintage_date,
                    source_provider, source_kind,
                    time_start, time_end, time_frequency,
                    manifest_path, provenance_path, quality_report_path, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    ds_entry["dataset_id"],
                    release_id,
                    ds_entry.get("dataset_revision", 1),
                    data_file.get("format", ""),
                    data_file.get("row_count"),
                    data_file.get("byte_size"),
                    data_file.get("sha256", ""),
                    manifest.get("as_of_date", ""),
                    manifest.get("vintage_date", ""),
                    source.get("provider", ""),
                    source.get("kind", ""),
                    time_cov.get("start", ""),
                    time_cov.get("end", ""),
                    time_cov.get("frequency", ""),
                    ds_entry["manifest_path"],
                    ds_entry["provenance_path"],
                    qr_path_raw if qr_exists else "",
                    manifest.get("notes", ""),
                ],
            )
            datasets_count += 1

        # -- provider_runs table -----------------------------------------------
        # One row per unique source.provider found in manifests
        # (aggregated from provenance acquisition records)
        providers_seen: dict[str, dict[str, Any]] = {}
        prov_dir = rpath / "provenance"
        if prov_dir.exists():
            for prov_file in sorted(prov_dir.glob("*.provenance.json")):
                prov = _read_json(prov_file)
                acq = prov.get("acquisition", {})
                source_id = acq.get("source_identifier", "unknown")
                key = source_id

                if key not in providers_seen:
                    providers_seen[key] = {
                        "attempts": [],
                        "started_at": acq.get("started_at", ""),
                        "completed_at": acq.get("completed_at", ""),
                        "dataset_ids": [],
                    }
                providers_seen[key]["dataset_ids"].append(prov["dataset_id"])

        provider_count = 0
        for source_id, info in providers_seen.items():
            run_id = f"{release_id}_{source_id.replace('/', '_').replace(':', '_')[:48]}"
            self.con.execute(
                """INSERT INTO provider_runs
                   (run_id, release_id, provider_name, series_fetched,
                    series_succeeded, series_failed,
                    run_started_at, run_completed_at,
                    fetch_errors, provenance_data, indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    run_id,
                    release_id,
                    source_id,
                    len(info["dataset_ids"]),   # series_fetched
                    len(info["dataset_ids"]),   # series_succeeded (best-effort)
                    0,                           # series_failed
                    info.get("started_at") or now,
                    info.get("completed_at") or now,
                    "[]",
                    json.dumps(info, default=str),
                    now,
                ],
            )
            provider_count += 1

        return IndexReleaseResult(
            release_id=release_id,
            datasets_indexed=datasets_count,
            provider_runs_indexed=provider_count,
            skipped=False,
        )

    # -- query -----------------------------------------------------------------

    def query(self, sql: str, params: list[Any] | None = None) -> duckdb.DuckDBPyRelation:
        """Run a read-only SQL query against the index tables."""
        return self.con.execute(sql, params or [])

    # -- diff two releases -----------------------------------------------------

    def diff_releases(
        self, release_a: str, release_b: str
    ) -> list[dict[str, Any]]:
        """Compare two indexed releases at the dataset level.

        Returns a list of change records, each with:
          dataset_id, change_type, detail (JSON)
        """
        self.con.execute("DELETE FROM dataset_changes WHERE release_a = ? AND release_b = ?",
                         [release_a, release_b])

        changes: list[dict[str, Any]] = []
        now = _timestamp()

        # Datasets only in A (removed in B)
        only_a = self.con.execute(
            """SELECT d.dataset_id FROM datasets d
               WHERE d.release_id = ?
                 AND d.dataset_id NOT IN (
                   SELECT dataset_id FROM datasets WHERE release_id = ?
               )""",
            [release_a, release_b],
        ).fetchall()

        for (ds_id,) in only_a:
            detail = json.dumps({"side": "a_only", "summary": "dataset absent from release_b"})
            change_id = str(uuid.uuid4())[:12]
            self.con.execute(
                """INSERT INTO dataset_changes
                   (change_id, dataset_id, release_a, release_b, change_type, detail, compared_at)
                   VALUES (?, ?, ?, ?, 'removed', ?, ?)""",
                [change_id, ds_id, release_a, release_b, detail, now],
            )
            changes.append({"dataset_id": ds_id, "change_type": "removed", "detail": detail})

        # Datasets only in B (added in B)
        only_b = self.con.execute(
            """SELECT d.dataset_id FROM datasets d
               WHERE d.release_id = ?
                 AND d.dataset_id NOT IN (
                   SELECT dataset_id FROM datasets WHERE release_id = ?
               )""",
            [release_b, release_a],
        ).fetchall()

        for (ds_id,) in only_b:
            detail = json.dumps({"side": "b_only", "summary": "dataset new in release_b"})
            change_id = str(uuid.uuid4())[:12]
            self.con.execute(
                """INSERT INTO dataset_changes
                   (change_id, dataset_id, release_a, release_b, change_type, detail, compared_at)
                   VALUES (?, ?, ?, ?, 'added', ?, ?)""",
                [change_id, ds_id, release_a, release_b, detail, now],
            )
            changes.append({"dataset_id": ds_id, "change_type": "added", "detail": detail})

        # Datasets in both — compare
        common = self.con.execute(
            """SELECT a.dataset_id, a.data_sha256 AS sha_a, b.data_sha256 AS sha_b,
                      a.row_count AS rc_a, b.row_count AS rc_b,
                      a.time_end AS end_a, b.time_end AS end_b
               FROM datasets a
               JOIN datasets b ON a.dataset_id = b.dataset_id
               WHERE a.release_id = ? AND b.release_id = ?""",
            [release_a, release_b],
        ).fetchall()

        for (ds_id, sha_a, sha_b, rc_a, rc_b, end_a, end_b) in common:
            if sha_a != sha_b:
                detail = json.dumps({
                    "sha256_before": sha_a, "sha256_after": sha_b,
                    "row_count_before": rc_a, "row_count_after": rc_b,
                    "time_end_before": str(end_a), "time_end_after": str(end_b),
                })
                if rc_b is not None and rc_a is not None and rc_b > rc_a:
                    ct = "row_growth"
                elif rc_b is not None and rc_a is not None and rc_b < rc_a:
                    ct = "row_shrink"
                else:
                    ct = "sha256_change"
            else:
                ct = "unchanged"
                detail = json.dumps({"row_count": rc_a})

            change_id = str(uuid.uuid4())[:12]
            self.con.execute(
                """INSERT INTO dataset_changes
                   (change_id, dataset_id, release_a, release_b, change_type, detail, compared_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [change_id, ds_id, release_a, release_b, ct, detail, now],
            )
            changes.append({"dataset_id": ds_id, "change_type": ct, "detail": detail})

        return changes

    def list_indexed_releases(self) -> list[str]:
        rows = self.con.execute(
            "SELECT release_id FROM releases ORDER BY finalized_at DESC"
        ).fetchall()
        return [r[0] for r in rows]


# ── module-level convenience functions ──────────────────────────────────────

def _default_db_path() -> Path:
    """Default DuckDB path: Data/harvester/audit/index.duckdb"""
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "data" / "audit" / "index.duckdb"


def build_index(
    release_path: str | Path,
    db_path: str | Path | None = None,
) -> IndexReleaseResult:
    """Index a single finalized release.  Convenience function."""
    db = db_path or str(_default_db_path())
    idx = AuditIndex(db)
    try:
        return idx.index_release(release_path)
    finally:
        idx.close()


def rebuild_index(
    exports_root: str | Path | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Rebuild the entire index from scratch by re-reading all finalized
    releases under *exports_root*.  Returns the number of releases indexed."""
    db = db_path or str(_default_db_path())
    root = exports_root or str(_default_db_path().parent.parent / "exports")
    idx = AuditIndex(db)
    try:
        return idx.rebuild(root)
    finally:
        idx.close()


def query_index(
    sql: str,
    db_path: str | Path | None = None,
    params: list[Any] | None = None,
) -> list[tuple[Any, ...]]:
    """Run a read-only SQL query and return results as list of tuples."""
    db = db_path or str(_default_db_path())
    idx = AuditIndex(db)
    try:
        rel = idx.query(sql, params)
        return rel.fetchall()
    finally:
        idx.close()


def diff_releases(
    release_a: str,
    release_b: str,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Compare two indexed releases and return dataset-level changes."""
    db = db_path or str(_default_db_path())
    idx = AuditIndex(db)
    try:
        return idx.diff_releases(release_a, release_b)
    finally:
        idx.close()
