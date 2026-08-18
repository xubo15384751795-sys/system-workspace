#!/usr/bin/env python3
"""Classify legacy feedback records without granting calibration eligibility.

The default mode is a read-only report. ``--apply`` creates a timestamped
backup beside the manifest and atomically replaces it with explicit
``candidate/ineligible`` fields for records that predate the lifecycle
contract. No record is promoted, marked golden, or allowed to affect core
judgment.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT
from system_runtime.feedback_lifecycle import make_transition_event

MANIFEST = ROOT / "Data" / "feedback_samples" / "sample_manifest.jsonl"


def _legacy_fields(*, sample_id: str, occurred_at: str) -> dict[str, Any]:
    return {
        "lifecycle_state": "candidate",
        "eligibility": "ineligible",
        "eligibility_reason_codes": [
            "LEGACY_RECORD_CLASSIFIED",
            "HUMAN_REVIEW_REQUIRED",
            "AUTHORITY_NOT_VERIFIED",
        ],
        "allowed_to_affect_core_judgment": False,
        "calibration_set": False,
        "golden": False,
        "lifecycle_events": [
            make_transition_event(
                sample_id=sample_id,
                from_state=None,
                to_state="candidate",
                owner="feedback_eligibility_migration",
                occurred_at=occurred_at,
                evidence=["legacy_manifest_record", "human_review_required"],
            )
        ],
    }


def migrate_manifest(
    manifest: Path = MANIFEST,
    *,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not manifest.is_file():
        return {
            "status": "MISSING",
            "manifest": str(manifest),
            "records": 0,
            "records_to_classify": 0,
            "applied": False,
        }
    records: list[dict[str, Any]] = []
    malformed = 0
    to_classify = 0
    occurred_at = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(value, dict):
            malformed += 1
            continue
        record = dict(value)
        missing = any(
            key not in record
            for key in (
                "lifecycle_state",
                "eligibility",
                "eligibility_reason_codes",
                "allowed_to_affect_core_judgment",
                "calibration_set",
                "golden",
                "lifecycle_events",
            )
        )
        if missing:
            sample_id = str(record.get("sample_id") or f"legacy-line-{line_number}")
            record.setdefault("sample_id", sample_id)
            record.update(_legacy_fields(sample_id=sample_id, occurred_at=occurred_at))
            notes = record.get("migration_notes")
            if not isinstance(notes, list):
                notes = []
                record["migration_notes"] = notes
            notes.append(
                "classified legacy record as candidate/ineligible; human review required"
            )
            to_classify += 1
        records.append(record)
    if malformed:
        return {
            "status": "BLOCKED",
            "manifest": str(manifest),
            "records": len(records),
            "records_to_classify": to_classify,
            "malformed_records": malformed,
            "applied": False,
            "reason_code": "MALFORMED_RECORDS",
        }
    result: dict[str, Any] = {
        "status": "PASS" if to_classify == 0 else "READY_TO_APPLY",
        "manifest": str(manifest),
        "records": len(records),
        "records_to_classify": to_classify,
        "malformed_records": 0,
        "applied": False,
        "would_grant_calibration": False,
        "would_allow_core_judgment": False,
    }
    if not apply or to_classify == 0:
        return result
    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    backup = manifest.with_name(f"{manifest.name}.pre-eligibility-{timestamp}.bak")
    temporary = manifest.with_name(f".{manifest.name}.eligibility.tmp")
    shutil.copy2(manifest, backup)
    temporary.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest)
    result.update({"status": "APPLIED", "applied": True, "backup": str(backup)})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = migrate_manifest(args.manifest.resolve(), apply=args.apply)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(
            f"{result['status']}: records={result['records']} "
            f"to_classify={result['records_to_classify']} applied={result['applied']}"
        )
    return 1 if result["status"] in {"BLOCKED", "MISSING"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
