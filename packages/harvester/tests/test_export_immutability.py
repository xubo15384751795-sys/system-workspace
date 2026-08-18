from __future__ import annotations

import json
from pathlib import Path

import pytest

from harvester.core.exporter import ExportValidationError, FinalizedReleaseError, finalize_release, sha256_file
from harvester.core.manifest import write_manifest
from harvester.core.provenance import build_provenance, record_provenance
from tests.test_manifest_schema import sample_manifest


def create_release(exports_root: Path, *, bad_hash: bool = False) -> Path:
    release_dir = exports_root / "2026-04-26-r1"
    (release_dir / "data").mkdir(parents=True)
    (release_dir / "manifests").mkdir()
    (release_dir / "provenance").mkdir()
    (release_dir / "quality_reports").mkdir()

    data_path = release_dir / "data" / "sample_panel.csv"
    data_path.write_text("date,value\n2026-04-25,1.0\n", encoding="utf-8")
    actual_sha = sha256_file(data_path)
    manifest_sha = "f" * 64 if bad_hash else actual_sha
    manifest = sample_manifest(manifest_sha, data_path.stat().st_size)
    write_manifest(manifest, release_dir / "manifests" / "sample_panel.manifest.json")

    provenance = build_provenance(
        dataset_id="sample_panel",
        release_id="2026-04-26-r1",
        acquisition={
            "method": "manual_upload",
            "source_identifier": "tests",
            "started_at": "2026-04-26T00:00:00Z",
            "completed_at": "2026-04-26T00:00:01Z",
            "operator": "pytest",
        },
        checksums={"raw_sha256": actual_sha, "final_sha256": manifest_sha},
        observation_start="2026-04-25",
        observation_end="2026-04-25",
    )
    record_provenance(release_dir / "provenance" / "sample_panel.provenance.json", provenance)
    (release_dir / "quality_reports" / "sample_panel.quality.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "observation_coverage": {
                    "start": "2026-04-25",
                    "end": "2026-04-25",
                    "time_column": "date",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return release_dir


def restore_permissions(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_dir():
            child.chmod(0o755)
        else:
            child.chmod(0o644)
    if path.exists():
        path.chmod(0o755)


def test_finalize_release_dry_run_does_not_write(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    create_release(exports_root)

    result = finalize_release("2026-04-26-r1", exports_root=exports_root)

    assert result.dry_run is True
    assert result.verified_datasets == 1
    assert not (exports_root / "2026-04-26-r1" / "catalog.json").exists()
    assert not (exports_root / "latest").exists()


def test_finalize_release_writes_catalog_latest_and_seals(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = create_release(exports_root)
    try:
        result = finalize_release("2026-04-26-r1", exports_root=exports_root, dry_run=False)

        assert result.dry_run is False
        assert (release_dir / "catalog.json").exists()
        assert (release_dir / ".finalized").exists()
        assert (release_dir / "release_digest.txt").exists()
        assert (exports_root / "latest").is_symlink()
        assert (exports_root / "latest").readlink() == Path("2026-04-26-r1")
        with pytest.raises(FinalizedReleaseError):
            finalize_release("2026-04-26-r1", exports_root=exports_root, dry_run=False)
    finally:
        restore_permissions(release_dir)


def test_finalize_release_rejects_hash_mismatch(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    create_release(exports_root, bad_hash=True)

    with pytest.raises(ExportValidationError, match="sha256 mismatch"):
        finalize_release("2026-04-26-r1", exports_root=exports_root)


def test_finalize_release_rejects_undeclared_data_files(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = create_release(exports_root)
    (release_dir / "data" / "scratch.csv").write_text("debug\n1\n", encoding="utf-8")

    with pytest.raises(ExportValidationError, match="undeclared data files"):
        finalize_release("2026-04-26-r1", exports_root=exports_root)


def test_finalize_release_rejects_failed_quality_report(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = create_release(exports_root)
    (release_dir / "quality_reports" / "sample_panel.quality.json").write_text(
        '{"status": "failed", "blockers": ["bad data"]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ExportValidationError, match="quality report failed"):
        finalize_release("2026-04-26-r1", exports_root=exports_root)


def test_finalize_release_rejects_manifest_observation_end_mismatch(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = create_release(exports_root)
    manifest_path = release_dir / "manifests" / "sample_panel.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["time_coverage"]["end"] = "2026-04-24"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(ExportValidationError, match="manifest observation coverage mismatch.*end"):
        finalize_release("2026-04-26-r1", exports_root=exports_root)


def test_finalize_release_rejects_quality_observation_end_mismatch(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = create_release(exports_root)
    quality_path = release_dir / "quality_reports" / "sample_panel.quality.json"
    quality_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "observation_coverage": {
                    "start": "2026-04-25",
                    "end": "2026-04-24",
                    "time_column": "date",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ExportValidationError, match="quality observation coverage mismatch.*end"):
        finalize_release("2026-04-26-r1", exports_root=exports_root)


def test_finalize_release_rejects_provenance_observation_end_mismatch(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = create_release(exports_root)
    provenance_path = release_dir / "provenance" / "sample_panel.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["observation_coverage"]["end"] = "2026-04-24"
    provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")

    with pytest.raises(ExportValidationError, match="provenance observation coverage mismatch.*end"):
        finalize_release("2026-04-26-r1", exports_root=exports_root)


def test_finalize_release_rejects_invalid_canonical_chain_sidecar(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = create_release(exports_root)
    provenance_path = release_dir / "provenance" / "sample_panel.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["canonical_chain_path"] = "provenance/sample_panel.canonical_chains.jsonl"
    provenance["canonical_chain_count"] = 1
    provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")
    (release_dir / "provenance" / "sample_panel.canonical_chains.jsonl").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(ExportValidationError, match="canonical chain sidecar invalid"):
        finalize_release("2026-04-26-r1", exports_root=exports_root)


def test_finalize_release_rejects_invalid_measurement_spec(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = create_release(exports_root)
    provenance_path = release_dir / "provenance" / "sample_panel.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["measurement_spec_path"] = "provenance/sample_panel.measurement_spec.json"
    provenance["measurement_spec_version"] = "system.measurement_spec.v1"
    provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")
    (release_dir / "provenance" / "sample_panel.measurement_spec.json").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(ExportValidationError, match="measurement spec invalid"):
        finalize_release("2026-04-26-r1", exports_root=exports_root)
