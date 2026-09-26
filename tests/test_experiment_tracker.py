"""Portable experiment-run tracking contract tests."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from verity.runtime._experiment_tracker import (
    ExperimentTracker,
    ExperimentTrackingError,
)
from verity.runtime.run_bundle import RunBundle


def test_tracker_records_params_metric_history_tags_and_artifacts(tmp_path: Path) -> None:
    path = tmp_path / "experiment.json"
    tracker = ExperimentTracker(
        path,
        run_id="run-1",
        experiment_name="qlib_shadow",
        started_at=datetime(2026, 8, 24, tzinfo=UTC),
        params={"learning_rate": 0.1},
        tags={"route": "shadow"},
    )
    tracker.log_metric("rank_ic", 0.25, step=1)
    tracker.log_metric("rank_ic", 0.31, step=2)
    tracker.set_inputs({"panel": {"sha256": "abc"}})
    tracker.log_artifact({"path": "Output/metrics.json", "sha256": "def"})
    tracker.finish(
        status="success",
        finished_at=datetime(2026, 8, 24, 1, tzinfo=UTC),
        duration_s=12.5,
        metrics={"rows": 100},
        tags={"verdict": "inconclusive"},
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "system.experiment_run.v1"
    assert payload["run_id"] == "run-1"
    assert payload["status"] == "success"
    assert payload["params"]["learning_rate"] == 0.1
    assert payload["metrics"]["rank_ic"] == 0.31
    assert payload["metrics"]["rows"] == 100.0
    assert [row["step"] for row in payload["metric_history"] if row["metric"] == "rank_ic"] == [1, 2]
    assert payload["inputs"]["panel"]["sha256"] == "abc"
    assert payload["artifacts"][0]["path"] == "Output/metrics.json"
    assert payload["tags"]["verdict"] == "inconclusive"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "0.1", True])
def test_tracker_rejects_non_finite_or_non_numeric_metrics(tmp_path: Path, value) -> None:
    tracker = ExperimentTracker(
        tmp_path / "experiment.json",
        run_id="run-1",
        experiment_name="test",
    )
    with pytest.raises(ExperimentTrackingError):
        tracker.log_metric("bad", value)


def test_run_bundle_emits_experiment_record_without_removing_operational_files(tmp_path: Path) -> None:
    bundle = RunBundle.start(
        mode="experiment_test",
        root=tmp_path,
        update_pointer=False,
    )
    bundle.log_param("dataset", "fixture")
    bundle.record_step("fit", duration_s=0.5)
    artifact = tmp_path / "Output" / "current" / "metric.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{"score": 0.2}\n', encoding="utf-8")
    bundle.record_artifact(artifact)
    bundle.finish(status="success")

    experiment = json.loads((bundle.run_dir / "experiment.json").read_text(encoding="utf-8"))
    manifest = json.loads((bundle.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert experiment["run_id"] == bundle.run_id
    assert experiment["params"]["dataset"] == "fixture"
    assert experiment["metrics"]["step.fit.duration_s"] == 0.5
    assert experiment["metrics"]["steps.succeeded"] == 1.0
    assert experiment["artifacts"][0]["path"] == "Output/current/metric.json"
    assert manifest["experiment_record"] == "experiment.json"
    assert (bundle.run_dir / "steps.jsonl").is_file()
    assert (bundle.run_dir / "artifact_index.json").is_file()
