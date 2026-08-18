"""Restore-manifest truthfulness and same-disk fail-closed tests."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.verify_restore_manifest import SCHEMA, validate_manifest


def _write_manifest(tmp_path: Path, *, pass_state: bool) -> Path:
    payload = {
        "schema_version": "system.restore_manifest.v1",
        "status": "PASS" if pass_state else "BLOCKED",
        "accepted_release_scope": "Data/harvester/exports",
        "bytes_owner": "object_storage" if pass_state else "UNCONFIGURED",
        "files": [] if not pass_state else [
            {
                "path": "Data/harvester/exports/release/data.parquet",
                "bytes_owner": "object_storage",
                "uri": "s3://private-bucket/releases/data.parquet",
                "content_hash": "0" * 64,
                "size_bytes": 1,
                "encryption_class": "managed",
                "access_class": "private",
            }
        ],
        "remote": {
            "type": "s3",
            "uri": "s3://private-bucket/releases",
            "same_disk_as_workspace": not pass_state,
            "complete_bytes_verified": pass_state,
            "content_hash_verified": pass_state,
        },
        "restore_drill": {
            "required": True,
            "status": "PASS" if pass_state else "NOT_RUN",
            "device_class": "compute_device",
            "last_verified_at": "2026-08-12T00:00:00Z" if pass_state else None,
        },
        "certification": {
            "recoverable": pass_state,
            "reason_codes": [] if pass_state else [
                "SAME_DISK_REMOTE",
                "COMPLETE_BYTES_NOT_VERIFIED",
                "RESTORE_DRILL_NOT_RUN",
                "CONTENT_HASH_NOT_VERIFIED",
                "BYTES_OWNER_UNCONFIGURED",
                "FILE_INVENTORY_EMPTY",
            ],
            "evidence_boundary": "test",
        },
    }
    path = tmp_path / "restore_manifest.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_current_restore_manifest_is_blocked_and_read_only() -> None:
    result = validate_manifest(
        Path(__file__).resolve().parents[1] / "governance/restore_manifest.yaml"
    )
    assert result["status"] == "BLOCKED"
    assert result["read_only"] is True
    assert "SAME_DISK_REMOTE" in result["reason_codes"]
    assert "REMOTE_PATH_NOT_FOUND" in result["reason_codes"]
    assert "FILE_INVENTORY_EMPTY" in result["reason_codes"]


def test_verified_off_device_manifest_can_pass(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, pass_state=True)

    result = validate_manifest(manifest, root=tmp_path)

    assert result["status"] == "PASS"
    assert result["recoverable"] is True


def test_schema_is_available() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8"))["$id"] == "system.restore_manifest.v1"
