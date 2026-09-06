from __future__ import annotations

import json
from pathlib import Path

from harvester.core.canonical_lineage import (
    SCHEMA_VERSION,
    merkle_from_records,
    rebuild_observations,
    select_delta,
    upsert_key,
    verify_rebuild_matches_digest,
    write_canonical_lineage,
)
from harvester.core.exporter import finalize_release, sha256_file
from harvester.core.manifest import write_manifest
from harvester.core.provenance import (
    build_provenance,
    record_provenance,
    validate_provenance,
)
from jsonschema import Draft202012Validator

from system_runtime.canonical_ids import build_observation, validate_observation
from tests.test_export_immutability import restore_permissions
from tests.test_manifest_schema import sample_manifest

ROOT = Path(__file__).resolve().parents[3]


def _obs(series: str, day: str, value: float) -> dict:
    return build_observation(
        canonical_series_id=series,
        observed_at=day,
        vintage_at="2026-09-06",
        value=value,
        unit="index",
        source_id="test",
        source_snapshot_sha256="a" * 64,
        provenance={"captured_at": "2026-09-06T00:00:00Z", "producer": "test"},
    )


def test_v1_reader_accepts_records_stored_in_v2_delta() -> None:
    record = _obs("FRED:NFCI", "2026-09-01", 0.2)
    validate_observation(record)
    assert record["observation_id"].startswith("obs_")


def test_delta_omits_unchanged_rows_and_rebuild_matches_digest(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    first = exports / "2026-09-04-r1"
    second = exports / "2026-09-06-r1"
    observations_v1 = [
        _obs("FRED:NFCI", "2026-09-01", 0.1),
        _obs("FRED:NFCI", "2026-09-02", 0.2),
    ]
    write_canonical_lineage(
        release_dir=first,
        dataset_id="benchmark_panel",
        release_id="2026-09-04-r1",
        observations=observations_v1,
        chains=[],
        exports_root=exports,
        measurement_definition="Benchmark panel value recorded for the release",
        predicate="benchmark_value_recorded_on",
    )
    observations_v2 = [
        *observations_v1,
        _obs("FRED:NFCI", "2026-09-03", 0.3),
    ]
    # revision of 09-02
    observations_v2[1] = _obs("FRED:NFCI", "2026-09-02", 0.25)
    result = write_canonical_lineage(
        release_dir=second,
        dataset_id="benchmark_panel",
        release_id="2026-09-06-r1",
        observations=observations_v2,
        chains=[],
        exports_root=exports,
        measurement_definition="Benchmark panel value recorded for the release",
        predicate="benchmark_value_recorded_on",
    )
    delta_path = second / result.observation_relpath
    delta_rows = [json.loads(line) for line in delta_path.read_text().splitlines() if line.strip()]
    assert result.lineage["storage_mode"] == "delta"
    assert result.lineage["previous_release_id"] == "2026-09-04-r1"
    assert {upsert_key(row) for row in delta_rows} == {
        ("FRED:NFCI", "2026-09-02"),
        ("FRED:NFCI", "2026-09-03"),
    }
    rebuilt = rebuild_observations(second, "benchmark_panel")
    assert len(rebuilt) == 3
    assert merkle_from_records(rebuilt) == result.lineage["observations"]["merkle_root"]
    report = verify_rebuild_matches_digest(second, "benchmark_panel")
    assert report["observation_digest_match"] is True
    schema = json.loads((ROOT / "protocols" / "canonical_chain_v2.schema.json").read_text())
    Draft202012Validator(schema).validate(result.lineage)


def test_tombstones_drop_keys_missing_from_current_release(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    first = exports / "2026-09-04-r1"
    second = exports / "2026-09-06-r1"
    write_canonical_lineage(
        release_dir=first,
        dataset_id="benchmark_panel",
        release_id="2026-09-04-r1",
        observations=[
            _obs("FRED:NFCI", "2026-09-01", 0.1),
            _obs("FRED:DROP", "2026-09-01", 1.0),
        ],
        chains=[],
        exports_root=exports,
    )
    result = write_canonical_lineage(
        release_dir=second,
        dataset_id="benchmark_panel",
        release_id="2026-09-06-r1",
        observations=[
            _obs("FRED:NFCI", "2026-09-01", 0.1),
            _obs("FRED:NFCI", "2026-09-02", 0.2),
        ],
        chains=[],
        exports_root=exports,
    )
    assert result.lineage["tombstones"] == [
        {"canonical_series_id": "FRED:DROP", "observed_at": "2026-09-01"}
    ]
    rebuilt = rebuild_observations(second, "benchmark_panel")
    assert {upsert_key(row) for row in rebuilt} == {
        ("FRED:NFCI", "2026-09-01"),
        ("FRED:NFCI", "2026-09-02"),
    }
    assert merkle_from_records(rebuilt) == result.lineage["observations"]["merkle_root"]


def test_select_delta_treats_same_value_as_persistent() -> None:
    from harvester.core.canonical_lineage import observation_leaf_hash

    first = _obs("FRED:NFCI", "2026-09-01", 0.1)
    second = _obs("FRED:NFCI", "2026-09-01", 0.1)
    second["source"]["snapshot_sha256"] = "b" * 64
    delta = select_delta([second], {upsert_key(first): observation_leaf_hash(first)})
    assert delta == []


def _write_panel_release(release_dir: Path, observations: list[dict], release_id: str) -> None:
    from harvester.core.canonical_lineage import write_canonical_lineage

    (release_dir / "data").mkdir(parents=True)
    (release_dir / "manifests").mkdir()
    (release_dir / "quality_reports").mkdir()
    data_path = release_dir / "data" / "benchmark_panel.csv"
    data_path.write_text("date,value\n2026-04-25,1.0\n", encoding="utf-8")
    actual_sha = sha256_file(data_path)
    lineage = write_canonical_lineage(
        release_dir=release_dir,
        dataset_id="benchmark_panel",
        release_id=release_id,
        observations=observations,
        chains=[],
        exports_root=release_dir.parent,
    )
    manifest = sample_manifest(actual_sha, data_path.stat().st_size)
    manifest["dataset_id"] = "benchmark_panel"
    manifest["release_id"] = release_id
    manifest["data_file"]["path"] = "data/benchmark_panel.csv"
    manifest["lineage"]["provenance_path"] = "provenance/benchmark_panel.provenance.json"
    manifest["quality_report_path"] = "quality_reports/benchmark_panel.quality.json"
    write_manifest(manifest, release_dir / "manifests" / "benchmark_panel.manifest.json")
    provenance = build_provenance(
        dataset_id="benchmark_panel",
        release_id=release_id,
        acquisition={
            "method": "api_client",
            "source_identifier": "tests",
            "started_at": "2026-04-26T00:00:00Z",
            "completed_at": "2026-04-26T00:00:01Z",
            "operator": "pytest",
        },
        checksums={"raw_sha256": actual_sha, "final_sha256": actual_sha},
        observation_start="2026-04-25",
        observation_end="2026-04-25",
        **{key: value for key, value in lineage.provenance_fields.items() if value is not None},
    )
    validate_provenance(provenance)
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


def test_finalize_validates_digest_not_full_count_as_jsonl_lines(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    first = exports / "2026-09-04-r1"
    second = exports / "2026-09-06-r1"
    v1 = [_obs("FRED:NFCI", "2026-09-01", 0.1), _obs("FRED:NFCI", "2026-09-02", 0.2)]
    _write_panel_release(first, v1, "2026-09-04-r1")
    v2 = [*v1, _obs("FRED:NFCI", "2026-09-03", 0.3)]
    _write_panel_release(second, v2, "2026-09-06-r1")
    try:
        result = finalize_release("2026-09-06-r1", exports_root=exports, dry_run=False)
        assert result.verified_datasets == 1
        provenance = json.loads(
            (second / "provenance" / "benchmark_panel.provenance.json").read_text()
        )
        assert provenance["canonical_schema_version"] == SCHEMA_VERSION
        assert provenance["canonical_observation_count"] == 3
        assert provenance["canonical_observation_delta_count"] == 1
        jsonl_lines = [
            line
            for line in (second / "provenance" / "benchmark_panel.canonical_observations.jsonl")
            .read_text()
            .splitlines()
            if line.strip()
        ]
        assert len(jsonl_lines) == 1
    finally:
        restore_permissions(second)
        restore_permissions(first)
