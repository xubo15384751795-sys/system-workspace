"""Run Bundle tests — verify atomic run record creation and contents.

Each run produces Output/runs/{run_id}/ with:
  manifest.json, input_snapshot.json, steps.jsonl,
  decision_trace.json, signal_trace.json, artifact_index.json

Output/current/latest_run_id.txt points to the most recent bundle.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add scripts to path for import
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_bundle import RunBundle, latest_run_dir


@pytest.fixture
def tmp_output(tmp_path):
    """Create a temp output directory with Output/current/ structure."""
    output = tmp_path / "Output"
    (output / "current").mkdir(parents=True)
    # Create a fake input artifact
    (output / "current" / "framework_output.json").write_text(
        json.dumps({"status": "ACTIVE_FULL", "basic": {"overall": "ACTIVE_FULL"}}),
        encoding="utf-8",
    )
    (output / "current" / "status.json").write_text(
        json.dumps({"promotion_gate": {"status": "PASS"}}),
        encoding="utf-8",
    )
    return tmp_path


class TestRunBundleCreation:
    """Test bundle creation and directory structure."""

    def test_start_creates_directory(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        assert bundle.run_dir.exists()
        assert bundle.run_dir.is_dir()
        assert "test_" in bundle.run_id

    def test_start_writes_manifest(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output, origin="launchd")
        manifest_path = bundle.run_dir / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["run_id"] == bundle.run_id
        assert manifest["mode"] == "test"
        assert manifest["status"] == "running"
        assert manifest["started_at"] is not None
        assert manifest["run_origin"] == "launchd"

    def test_start_writes_input_snapshot(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        snapshot_path = bundle.run_dir / "input_snapshot.json"
        assert snapshot_path.exists()
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        # Should have fingerprinted existing artifacts
        assert "Output/current/framework_output.json" in snapshot
        fw_entry = snapshot["Output/current/framework_output.json"]
        # Fingerprinted entries have sha256, not status
        assert "sha256" in fw_entry
        assert fw_entry["size_bytes"] > 0

    def test_start_creates_latest_pointer(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        pointer = tmp_output / "Output" / "current" / "latest_run_id.txt"
        assert pointer.exists()
        assert pointer.read_text(encoding="utf-8").strip() == bundle.run_id

    def test_run_id_format(self, tmp_output):
        bundle = RunBundle.start(mode="daily_pipeline", root=tmp_output)
        parts = bundle.run_id.split("_")
        # Should be: mode_YYYYMMDD_HHMMSS_entropy
        assert parts[0] == "daily"
        assert parts[1] == "pipeline"
        assert len(parts[2]) == 8  # YYYYMMDD
        assert len(parts[3]) == 6  # HHMMSS
        assert len(parts[4]) == 6  # hex entropy


class TestStepRecording:
    """Test step recording into bundles."""

    def test_record_step_appends_to_steps_jsonl(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_step("harvester", status="success", duration_s=12.3)
        bundle.record_step("bridge", status="failed", duration_s=5.1, returncode=1)

        steps_file = bundle.run_dir / "steps.jsonl"
        assert steps_file.exists()
        lines = steps_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        step1 = json.loads(lines[0])
        assert step1["step"] == "harvester"
        assert step1["status"] == "success"
        assert step1["duration_s"] == 12.3

        step2 = json.loads(lines[1])
        assert step2["step"] == "bridge"
        assert step2["status"] == "failed"
        assert step2["returncode"] == 1

    def test_record_step_tracks_count(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_step("step1", status="success")
        bundle.record_step("step2", status="failed")
        bundle.record_step("step3", status="success")
        bundle.finish(status="success")

        manifest = json.loads(
            (bundle.run_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["steps_count"] == 3

    def test_record_step_with_detail(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_step("step1", status="success", detail="some detail text")

        lines = (bundle.run_dir / "steps.jsonl").read_text(encoding="utf-8").strip().split("\n")
        step = json.loads(lines[0])
        assert step["detail"] == "some detail text"

    def test_record_step_preserves_additive_canonical_lineage(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        canonical_ids = {
            "observation_id": "obs_fixture",
            "measurement_id": "mea_fixture",
            "evidence_id": "evd_fixture",
            "claim_id": "clm_fixture",
        }
        bundle.record_step(
            "neutral_pressure_measurement",
            status="success",
            canonical_ids=canonical_ids,
            canonical_chain={"schema_version": "system.canonical_chain.v1"},
            canonical_source_path="/tmp/current/neutral_pressure_snapshot.json",
        )

        entry = json.loads(
            (bundle.run_dir / "steps.jsonl").read_text(encoding="utf-8").strip()
        )
        assert entry["canonical_ids"] == canonical_ids
        assert entry["canonical_chain"]["schema_version"] == "system.canonical_chain.v1"
        assert entry["canonical_source_path"].endswith("neutral_pressure_snapshot.json")

    def test_record_step_blocked_upstream_records_blocked_by(self, tmp_output):
        """A blocked_upstream step records its blocked_by lineage structurally."""
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_step("structural_replay", status="failed", returncode=1)
        bundle.record_step(
            "bridge",
            status="blocked_upstream",
            duration_s=0,
            blocked_by=["structural_replay"],
        )
        bundle.finish(status="partial_failure")

        lines = (bundle.run_dir / "steps.jsonl").read_text(encoding="utf-8").strip().split("\n")
        bridge = json.loads(lines[1])
        assert bridge["step"] == "bridge"
        assert bridge["status"] == "blocked_upstream"
        assert bridge["blocked_by"] == ["structural_replay"]

        manifest = json.loads(
            (bundle.run_dir / "manifest.json").read_text(encoding="utf-8")
        )
        # Phase 1.3 rollup semantics: steps_failed counts only REAL failures
        # (not blocked_upstream collateral), steps_blocked counts the collateral,
        # root_failures names the root-cause step(s).
        assert manifest["steps_succeeded"] == 0
        assert manifest["steps_failed"] == 1  # structural_replay only
        assert manifest["steps_blocked"] == 1  # bridge
        assert manifest["root_failures"] == ["structural_replay"]

    def test_record_step_captures_stderr_tail_and_log(self, tmp_output):
        """Phase 0.1: failed step's stderr_tail lands in steps.jsonl and full
        stderr lands in step_logs/<step>.stderr.log."""
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_step(
            "harvester",
            status="failed",
            returncode=1,
            stderr_tail="Traceback: Yahoo rate limit",
            full_stderr="ERROR: 429 Too Many Requests\nTraceback: Yahoo rate limit\n",
        )
        bundle.finish(status="partial_failure")

        lines = (bundle.run_dir / "steps.jsonl").read_text(encoding="utf-8").strip().split("\n")
        step = json.loads(lines[0])
        assert step["stderr_tail"] == "Traceback: Yahoo rate limit"

        log = bundle.run_dir / "step_logs" / "harvester.stderr.log"
        assert log.exists(), "failed step full stderr must be persisted"
        assert "429 Too Many Requests" in log.read_text(encoding="utf-8")

    def test_record_step_success_discards_full_stderr(self, tmp_output):
        """Success steps do not write a step_logs file (no noise)."""
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_step("harvester", status="success", returncode=0,
                           stderr_tail="", full_stderr="some warning")
        bundle.finish(status="success")
        assert not (bundle.run_dir / "step_logs" / "harvester.stderr.log").exists()


class TestTraceCapture:
    """Test decision and signal trace capture."""

    def test_capture_decision_trace(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.capture_decision_trace({
            "decision": "WATCH",
            "confidence": {"level": "low"},
        })
        bundle.finish(status="success")

        trace_path = bundle.run_dir / "decision_trace.json"
        assert trace_path.exists()
        traces = json.loads(trace_path.read_text(encoding="utf-8"))
        assert len(traces) == 1
        assert traces[0]["data"]["decision"] == "WATCH"

    def test_capture_signal_trace(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.capture_signal_trace({
            "framework_status": "active_full",
            "sigma_vector": {"M": 0.5, "D": 0.3},
        })
        bundle.finish(status="success")

        trace_path = bundle.run_dir / "signal_trace.json"
        assert trace_path.exists()
        traces = json.loads(trace_path.read_text(encoding="utf-8"))
        assert len(traces) == 1
        assert traces[0]["data"]["sigma_vector"]["M"] == 0.5

    def test_multiple_traces_accumulate(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.capture_decision_trace({"decision": "WATCH"})
        bundle.capture_decision_trace({"decision": "HEDGE"})
        bundle.capture_signal_trace({"status": "partial"})
        bundle.capture_signal_trace({"status": "full"})
        bundle.finish(status="success")

        decisions = json.loads(
            (bundle.run_dir / "decision_trace.json").read_text(encoding="utf-8")
        )
        signals = json.loads(
            (bundle.run_dir / "signal_trace.json").read_text(encoding="utf-8")
        )
        assert len(decisions) == 2
        assert len(signals) == 2

    def test_finalize_evidence_is_idempotent_and_closes_trace_capture(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.capture_decision_trace({"decision": "WATCH"})

        bundle.finalize_evidence()
        trace_path = bundle.run_dir / "decision_trace.json"
        before = trace_path.read_bytes()

        with pytest.raises(RuntimeError, match="evidence is already finalized"):
            bundle.capture_decision_trace({"decision": "BUY"})
        bundle.finalize_evidence()
        bundle.finish(status="success")

        assert trace_path.read_bytes() == before


class TestArtifactIndex:
    """Test artifact recording."""

    def test_record_artifact(self, tmp_output):
        # Create a real artifact
        artifact = tmp_output / "Output" / "current" / "test_artifact.json"
        artifact.write_text(json.dumps({"test": True}), encoding="utf-8")

        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_artifact(artifact)

        index_path = bundle.run_dir / "artifact_index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(index) == 1
        assert index[0]["path"] == "Output/current/test_artifact.json"
        assert "sha256" in index[0]

    def test_record_multiple_artifacts(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_artifact(tmp_output / "Output" / "current" / "framework_output.json")
        bundle.record_artifact(tmp_output / "Output" / "current" / "status.json")

        index = json.loads(
            (bundle.run_dir / "artifact_index.json").read_text(encoding="utf-8")
        )
        assert len(index) == 2

    def test_record_nonexistent_artifact_is_noop(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_artifact(tmp_output / "nonexistent.json")

        index_path = bundle.run_dir / "artifact_index.json"
        # Should not exist since nothing was recorded
        assert not index_path.exists()


class TestBundleFinish:
    """Test bundle finalization."""

    def test_finish_updates_manifest(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_step("step1", status="success")
        bundle.finish(status="success")

        manifest = json.loads(
            (bundle.run_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["status"] == "success"
        assert manifest["finished_at"] is not None
        assert manifest["duration_s"] is not None
        assert manifest["duration_s"] >= 0

    def test_finish_creates_empty_artifact_index(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.finish(status="success")

        index_path = bundle.run_dir / "artifact_index.json"
        assert index_path.exists()
        assert json.loads(index_path.read_text(encoding="utf-8")) == []

    def test_finish_returns_run_dir(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        result = bundle.finish(status="success")
        assert result == bundle.run_dir
        assert result.exists()

    def test_finish_counts_steps(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.record_step("step1", status="success")
        bundle.record_step("step2", status="failed")
        bundle.record_step("step3", status="success")
        bundle.finish(status="partial_failure")

        manifest = json.loads(
            (bundle.run_dir / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["steps_count"] == 3
        assert manifest["steps_succeeded"] == 2
        assert manifest["steps_failed"] == 1


class TestLatestRunDir:
    """Test latest run pointer lookup."""

    def test_latest_run_dir_returns_bundle(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        result = latest_run_dir(root=tmp_output)
        assert result == bundle.run_dir

    def test_latest_run_dir_returns_none_when_missing(self, tmp_path):
        result = latest_run_dir(root=tmp_path)
        assert result is None

    def test_latest_run_dir_returns_none_for_stale_pointer(self, tmp_output):
        pointer = tmp_output / "Output" / "current" / "latest_run_id.txt"
        pointer.write_text("nonexistent_run_id\n", encoding="utf-8")
        result = latest_run_dir(root=tmp_output)
        assert result is None


class TestLargeValueScrubbing:
    """Test that large values are trimmed in traces."""

    def test_large_value_is_trimmed(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        large_data = {"big_field": "x" * 100_000}
        bundle.capture_decision_trace(large_data)
        bundle.finish(status="success")

        traces = json.loads(
            (bundle.run_dir / "decision_trace.json").read_text(encoding="utf-8")
        )
        assert "[trimmed:" in traces[0]["data"]["big_field"]

    def test_normal_value_is_kept(self, tmp_output):
        bundle = RunBundle.start(mode="test", root=tmp_output)
        bundle.capture_decision_trace({"small_field": "normal_value"})
        bundle.finish(status="success")

        traces = json.loads(
            (bundle.run_dir / "decision_trace.json").read_text(encoding="utf-8")
        )
        assert traces[0]["data"]["small_field"] == "normal_value"
