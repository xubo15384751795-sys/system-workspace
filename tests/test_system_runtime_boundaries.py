from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from system_runtime.artifacts import ArtifactBoundaryError, ArtifactStore
from system_runtime.events import EventEnvelope, JsonlEventStore, payload_of
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import load_pipeline, render_sequence_yaml


def test_pipeline_registry_is_the_runtime_single_source() -> None:
    paths = WorkspacePaths.discover()
    pipeline = load_pipeline(paths)
    # The manual cross-asset recovery command is registered but excluded from
    # the scheduled sequence; canonical daily acquisition belongs to Harvester.
    assert pipeline.sequence(), "compiled scheduled sequence is empty"
    assert render_sequence_yaml(pipeline) == (
        paths.governance / "daily_run_sequence.yaml"
    ).read_text(encoding="utf-8")


def test_event_envelope_validates_and_legacy_payload_adapts() -> None:
    paths = WorkspacePaths.discover()
    schema = json.loads((paths.root / "protocols/event_envelope.schema.json").read_text())
    event = EventEnvelope.create(
        event_type="test",
        payload_schema="test.v1",
        payload={"value": 1},
        producer="pytest",
        run_id="run-1",
    )
    jsonschema.validate(event.as_dict(), schema)
    assert payload_of(event.as_dict()) == {"value": 1}
    assert payload_of({"legacy": True}) == {"legacy": True}


def test_event_store_migrates_legacy_rows_on_upsert(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"schema_version":"thing.v1","id":"a","value":1}\n')
    store = JsonlEventStore(path)
    event = EventEnvelope.create(
        event_type="thing",
        payload_schema="thing.v2",
        payload={"schema_version": "thing.v2", "id": "a", "value": 2},
        producer="pytest",
    )
    assert store.upsert(event, identity_fields=("id",)) == "updated"
    raw = json.loads(path.read_text().splitlines()[0])
    assert raw["schema_version"] == "system.event_envelope.v1"
    assert store.read_payloads()[0]["value"] == 2


def test_artifact_store_is_atomic_and_cannot_escape_output(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    (root / "governance").mkdir(parents=True)
    (root / "governance/daily_pipeline_registry.yaml").write_text("steps: {}\n")
    store = ArtifactStore(WorkspacePaths(root))
    target = store.write_json("validation/example.json", {"ok": True})
    assert json.loads(target.read_text()) == {"ok": True}
    try:
        store.write_json("../escape.json", {"bad": True})
    except ArtifactBoundaryError:
        pass
    else:
        raise AssertionError("ArtifactStore allowed path escape")
