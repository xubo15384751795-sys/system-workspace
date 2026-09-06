from __future__ import annotations

import json
from pathlib import Path

from harvester.core.acquisition_timing import (
    append_local_step,
    local_step_record,
    ranked_items,
    source_record,
    utc_now,
)
from harvester.core.exporter import finalize_release, sha256_file
from harvester.core.manifest import write_manifest
from harvester.core.provenance import (
    build_provenance,
    record_provenance,
    validate_provenance,
)

from tests.test_export_immutability import restore_permissions
from tests.test_manifest_schema import sample_manifest


def test_source_and_local_step_records_are_rankable() -> None:
    t0 = 0.0
    sources = [
        source_record(
            source_id="FAST",
            started_at="2026-08-01T00:00:00Z",
            t0=t0,
            attempts=1,
            outcome="success",
        ),
    ]
    sources[0]["elapsed_s"] = 0.2
    steps = [
        local_step_record(
            step_id="jsonl_observations",
            started_at="2026-08-01T00:00:01Z",
            t0=t0,
            outcome="success",
        )
    ]
    steps[0]["elapsed_s"] = 4.5
    ranked = ranked_items({"sources": sources, "local_steps": steps})
    assert [item["name"] for item in ranked[:2]] == ["jsonl_observations", "FAST"]
    assert ranked[0]["kind"] == "local_step"


def test_provenance_schema_accepts_acquisition_sources() -> None:
    provenance = build_provenance(
        dataset_id="benchmark_panel",
        release_id="2026-08-01-r1",
        acquisition={
            "method": "api_client",
            "source_identifier": "tests",
            "started_at": "2026-08-01T00:00:00Z",
            "completed_at": "2026-08-01T00:00:02Z",
            "operator": "pytest",
            "sources": [
                {
                    "source_id": "DGS10",
                    "series_id": "DGS10",
                    "provider": "fred",
                    "started_at": "2026-08-01T00:00:00Z",
                    "completed_at": "2026-08-01T00:00:01Z",
                    "elapsed_s": 1.0,
                    "attempts": 2,
                    "outcome": "success",
                }
            ],
            "local_steps": [
                {
                    "step_id": "jsonl_observations",
                    "started_at": "2026-08-01T00:00:01Z",
                    "completed_at": "2026-08-01T00:00:02Z",
                    "elapsed_s": 0.4,
                    "attempts": 1,
                    "outcome": "success",
                }
            ],
        },
        checksums={"final_sha256": "0" * 64},
    )
    validate_provenance(provenance)


def _create_benchmark_release(exports_root: Path) -> Path:
    release_dir = exports_root / "2026-04-26-r1"
    (release_dir / "data").mkdir(parents=True)
    (release_dir / "manifests").mkdir()
    (release_dir / "provenance").mkdir()
    (release_dir / "quality_reports").mkdir()

    data_path = release_dir / "data" / "benchmark_panel.csv"
    data_path.write_text("date,value\n2026-04-25,1.0\n", encoding="utf-8")
    actual_sha = sha256_file(data_path)
    manifest = sample_manifest(actual_sha, data_path.stat().st_size)
    manifest["dataset_id"] = "benchmark_panel"
    manifest["data_file"]["path"] = "data/benchmark_panel.csv"
    manifest["lineage"]["provenance_path"] = "provenance/benchmark_panel.provenance.json"
    manifest["quality_report_path"] = "quality_reports/benchmark_panel.quality.json"
    write_manifest(manifest, release_dir / "manifests" / "benchmark_panel.manifest.json")

    provenance = build_provenance(
        dataset_id="benchmark_panel",
        release_id="2026-04-26-r1",
        acquisition={
            "method": "api_client",
            "source_identifier": "tests",
            "started_at": "2026-04-26T00:00:00Z",
            "completed_at": "2026-04-26T00:00:01Z",
            "operator": "pytest",
            "sources": [
                {
                    "source_id": "DGS10",
                    "started_at": "2026-04-26T00:00:00Z",
                    "completed_at": "2026-04-26T00:00:01Z",
                    "elapsed_s": 0.5,
                    "attempts": 1,
                    "outcome": "success",
                }
            ],
            "local_steps": [
                {
                    "step_id": "jsonl_observations",
                    "started_at": "2026-04-26T00:00:00Z",
                    "completed_at": "2026-04-26T00:00:01Z",
                    "elapsed_s": 0.1,
                    "attempts": 1,
                    "outcome": "success",
                }
            ],
        },
        checksums={"raw_sha256": actual_sha, "final_sha256": actual_sha},
        observation_start="2026-04-25",
        observation_end="2026-04-25",
    )
    record_provenance(release_dir / "provenance" / "benchmark_panel.provenance.json", provenance)
    (release_dir / "quality_reports" / "benchmark_panel.quality.json").write_text(
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


def test_finalize_records_validation_elapsed(tmp_path: Path) -> None:
    exports_root = tmp_path / "exports"
    release_dir = _create_benchmark_release(exports_root)
    try:
        finalize_release("2026-04-26-r1", exports_root=exports_root, dry_run=False)
        provenance = json.loads(
            (release_dir / "provenance" / "benchmark_panel.provenance.json").read_text()
        )
        steps = {item["step_id"]: item for item in provenance["acquisition"]["local_steps"]}
        assert "finalize_validation" in steps
        assert steps["finalize_validation"]["outcome"] == "success"
        assert steps["finalize_validation"]["elapsed_s"] >= 0
        assert steps["jsonl_observations"]["elapsed_s"] == 0.1
    finally:
        restore_permissions(release_dir)


def test_append_local_step_is_noop_when_missing(tmp_path: Path) -> None:
    append_local_step(
        tmp_path / "missing.json",
        local_step_record(step_id="finalize_validation", started_at=utc_now(), t0=0.0),
    )
    assert not (tmp_path / "missing.json").exists()
