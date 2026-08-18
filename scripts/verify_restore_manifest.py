#!/usr/bin/env python3
"""Read-only validator for accepted-release recovery evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "governance" / "restore_manifest.yaml"
SCHEMA = ROOT / "protocols" / "restore_manifest.schema.json"


def validate_manifest(path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
    reasons: list[str] = []
    remote = payload["remote"]
    files = payload["files"]
    drill = payload["restore_drill"]
    certification = payload["certification"]
    remote_uri = str(remote["uri"])
    if remote["same_disk_as_workspace"]:
        reasons.append("SAME_DISK_REMOTE")
    if not remote["complete_bytes_verified"]:
        reasons.append("COMPLETE_BYTES_NOT_VERIFIED")
    if not remote["content_hash_verified"]:
        reasons.append("CONTENT_HASH_NOT_VERIFIED")
    if drill["status"] != "PASS":
        reasons.append(
            "RESTORE_DRILL_NOT_RUN"
            if drill["status"] == "NOT_RUN"
            else "RESTORE_DRILL_FAILED"
        )
    if payload["bytes_owner"] == "UNCONFIGURED":
        reasons.append("BYTES_OWNER_UNCONFIGURED")
    if not files:
        reasons.append("FILE_INVENTORY_EMPTY")
    for index, file_record in enumerate(files):
        if file_record["bytes_owner"] == "UNCONFIGURED":
            reasons.append(f"FILE_{index}_BYTES_OWNER_UNCONFIGURED")
        if file_record["bytes_owner"] != payload["bytes_owner"]:
            reasons.append(f"FILE_{index}_BYTES_OWNER_MISMATCH")
    if "://" not in remote_uri:
        try:
            resolved_remote = (root / remote_uri).resolve()
            workspace = root.resolve()
            if not resolved_remote.exists():
                reasons.append("REMOTE_PATH_NOT_FOUND")
            if resolved_remote == workspace or workspace in resolved_remote.parents:
                reasons.append("REMOTE_WITHIN_WORKSPACE")
        except (OSError, RuntimeError):
            reasons.append("REMOTE_URI_UNRESOLVABLE")
    declared_reasons = set(certification["reason_codes"])
    missing_declared = sorted(set(reasons) - declared_reasons)
    if missing_declared:
        reasons.append("DECLARED_REASON_CODES_INCOMPLETE")
    calculated_recoverable = not reasons
    if bool(certification["recoverable"]) != calculated_recoverable:
        reasons.append("RECOVERABILITY_VERDICT_MISMATCH")
    if calculated_recoverable and payload["status"] != "PASS":
        reasons.append("STATUS_VERDICT_MISMATCH")
    if not calculated_recoverable and payload["status"] == "PASS":
        reasons.append("STATUS_CLAIMS_PASS_WITH_INCOMPLETE_EVIDENCE")
    return {
        "schema_version": "system.restore_manifest.v1",
        "manifest": str(path.resolve()),
        "status": "PASS" if not reasons else "BLOCKED",
        "declared_status": payload["status"],
        "bytes_owner": payload["bytes_owner"],
        "remote_uri": remote_uri,
        "remote_path_exists": (
            (root / remote_uri).resolve().exists()
            if "://" not in remote_uri
            else None
        ),
        "recoverable": calculated_recoverable,
        "reason_codes": sorted(set(reasons)),
        "restore_drill_status": drill["status"],
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = validate_manifest(args.manifest.resolve(), root=args.root.resolve())
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        print(f"restore manifest: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
