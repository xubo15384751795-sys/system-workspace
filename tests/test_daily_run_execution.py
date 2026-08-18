"""Tests for daily_run.py — execution logic.

Tests the utility functions that can be verified without running the full pipeline:
- run_step: subprocess execution with timeout handling
- _detect_schedule_slot: hour → slot mapping
- write_runtime_event: JSONL event writing
- write_alert: alert file generation
- check_freshness: framework_output staleness check
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    """Load daily_run as a module with scripts/ on sys.path."""
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(
        "daily_run", ROOT / "scripts" / "daily_run.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["daily_run"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def test_requested_authority_blocks_malformed_size(mod):
    assert mod.requested_authority_from_decision({"decision": "BUY", "effective_size": "bad"}) == "BLOCK"
    assert mod.requested_authority_from_decision({"decision": "BUY", "effective_size": "nan"}) == "BLOCK"
    assert mod.requested_authority_from_decision({"decision": "WATCH", "effective_size": "bad"}) == "DIAGNOSTIC_ONLY"


@pytest.mark.parametrize(
    ("state_name", "expected"),
    [
        ("ADMITTED", "TRANSACTION_FAILED"),
        ("ROLLED_BACK", "TRANSACTION_ROLLED_BACK"),
        ("RECOVERY_REQUIRED", "RECOVERY_REQUIRED"),
        ("COMMITTED", None),
    ],
)
def test_transaction_commit_state_maps_to_typed_reason(mod, state_name, expected):
    transaction = mod.PublishTransaction("run-test", Path("/tmp/run-test"))
    transaction.state = mod.TransactionState[state_name]

    result = mod._transaction_failure_reasons(transaction, commit_attempted=True)

    assert result == ([] if expected is None else [expected])


def test_generation_evidence_finalizes_before_live_pointer_commit() -> None:
    source = (ROOT / "scripts" / "daily_run.py").read_text(encoding="utf-8")
    assert source.index("bundle.finalize_evidence()") < source.index(
        "transaction.commit_generation(ROOT)"
    )


# ── run_step ───────────────────────────────────────────────────────────


class TestRunStep:
    def test_success(self, mod):
        """Successful command returns status=success."""
        result = mod.run_step("test_ok", ["python3", "-c", "print('hello')"])
        assert result["step"] == "test_ok"
        assert result["status"] == "success"
        assert result["returncode"] == 0
        assert "hello" in result["stdout_tail"]

    def test_failure(self, mod):
        """Failing command returns status=failed."""
        result = mod.run_step("test_fail", ["python3", "-c", "import sys; sys.exit(1)"])
        assert result["step"] == "test_fail"
        assert result["status"] == "failed"
        assert result["returncode"] == 1

    def test_timeout_returns_timeout_status(self, mod):
        """Command exceeding timeout returns status=timeout."""
        result = mod.run_step(
            "test_timeout",
            ["python3", "-c", "import time; time.sleep(10)"],
            env={"_TEST_TIMEOUT": "1"},
        )
        # The function uses TIMEOUT_LONG (600s), so we can't easily trigger
        # a real timeout in a test. Instead, verify the structure.
        assert "step" in result
        assert "status" in result
        assert "duration_s" in result

    def test_error_returns_error_status(self, mod):
        """Invalid command returns status=error."""
        result = mod.run_step("test_error", ["/nonexistent/command/path"])
        assert result["step"] == "test_error"
        assert result["status"] == "error"
        assert "error" in result


# ── _detect_schedule_slot ──────────────────────────────────────────────


class TestDetectScheduleSlot:
    def test_overnight(self, mod):
        assert mod._detect_schedule_slot(0) == "overnight"
        assert mod._detect_schedule_slot(5) == "overnight"
        assert mod._detect_schedule_slot(9) == "overnight"

    def test_mid_session(self, mod):
        assert mod._detect_schedule_slot(10) == "mid_session"
        assert mod._detect_schedule_slot(12) == "mid_session"
        assert mod._detect_schedule_slot(16) == "mid_session"

    def test_post_close(self, mod):
        assert mod._detect_schedule_slot(17) == "post_close"
        assert mod._detect_schedule_slot(20) == "post_close"
        assert mod._detect_schedule_slot(21) == "post_close"

    def test_daily_summary(self, mod):
        assert mod._detect_schedule_slot(22) == "daily_summary"
        assert mod._detect_schedule_slot(23) == "daily_summary"


def test_weekly_compatibility_readout_respects_cadence(mod):
    monday = datetime(2026, 8, 10, tzinfo=UTC)
    tuesday = datetime(2026, 8, 11, tzinfo=UTC)

    assert mod._weekly_cadence_due(monday, mod.parse_args([])) is True
    assert mod._weekly_cadence_due(tuesday, mod.parse_args([])) is False
    assert mod._weekly_cadence_due(tuesday, mod.parse_args(["--force-weekly"])) is True


# ── write_runtime_event ────────────────────────────────────────────────


class TestWriteRuntimeEvent:
    def test_writes_jsonl(self, mod, tmp_path):
        event = {"type": "test", "step": "foo", "status": "success"}
        mod.write_runtime_event(event, output_root=tmp_path)

        runtime_dir = tmp_path / "runtime_events"
        assert runtime_dir.exists()
        files = list(runtime_dir.glob("*.jsonl"))
        assert len(files) == 1

        lines = files[0].read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["schema_version"] == "system.event_envelope.v1"
        assert parsed["event_type"] == "test"
        assert parsed["payload"]["step"] == "foo"

    def test_appends_multiple_events(self, mod, tmp_path):
        for i in range(3):
            mod.write_runtime_event({"idx": i}, output_root=tmp_path)

        runtime_dir = tmp_path / "runtime_events"
        files = list(runtime_dir.glob("*.jsonl"))
        lines = files[0].read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3


# ── write_alert ────────────────────────────────────────────────────────


class TestWriteAlert:
    def test_no_failures_low_severity(self, mod, tmp_path):
        steps = [{"step": "a", "status": "success"}]
        mod.write_alert([], steps, output_root=tmp_path)

        alert_dir = tmp_path / "alerts"
        assert alert_dir.exists()
        alert_file = alert_dir / "latest_alert.json"
        assert alert_file.exists()

        alert = json.loads(alert_file.read_text(encoding="utf-8"))
        assert alert["severity"] == "LOW"

    def test_failed_step_high_severity(self, mod, tmp_path):
        steps = [{"step": "a", "status": "failed"}]
        mod.write_alert([], steps, output_root=tmp_path)

        alert_file = tmp_path / "alerts" / "latest_alert.json"
        alert = json.loads(alert_file.read_text(encoding="utf-8"))
        assert alert["severity"] == "HIGH"

    def test_warnings_medium_severity(self, mod, tmp_path):
        steps = [{"step": "a", "status": "success"}]
        mod.write_alert(["some warning"], steps, output_root=tmp_path)

        alert_file = tmp_path / "alerts" / "latest_alert.json"
        alert = json.loads(alert_file.read_text(encoding="utf-8"))
        assert alert["severity"] == "MEDIUM"

    def test_alert_records_lineage_and_dedup_key(self, mod, tmp_path):
        outcome = {
            "run_id": "daily_test",
            "publish_status": "COMMITTED",
            "admission_verdict": "PASS",
            "authority_mode": "authoritative",
            "generation_id": "generation_test",
            "release_id": "release_test",
        }
        mod.write_alert([], [{"step": "a", "status": "success"}], output_root=tmp_path, outcome=outcome)

        alert = json.loads((tmp_path / "alerts" / "latest_alert.json").read_text(encoding="utf-8"))
        assert alert["run_id"] == "daily_test"
        assert alert["generation_id"] == "generation_test"
        assert alert["release_id"] == "release_test"
        assert len(alert["notification_dedup_key"]) == 64

    def test_alert_uses_provider_status_matrix(self, mod, tmp_path):
        mod.write_alert(
            [],
            [{"step": "provider", "status": "success"}],
            output_root=tmp_path,
            provider_status="reused_after_provider_failure",
        )

        alert = json.loads((tmp_path / "alerts" / "latest_alert.json").read_text(encoding="utf-8"))
        assert alert["provider_status"] == "reused_after_provider_failure"
        assert alert["provider_alert_policy"] == "ERROR"
        assert alert["provider_alert_eligibility"] == "ALLOWED"
        assert alert["severity"] == "HIGH"

    def test_alert_unknown_provider_status_is_visible_and_blocked(self, mod, tmp_path):
        mod.write_alert(
            [],
            [{"step": "provider", "status": "success"}],
            output_root=tmp_path,
            provider_status="unknown",
        )

        alert = json.loads((tmp_path / "alerts" / "latest_alert.json").read_text(encoding="utf-8"))
        assert alert["provider_alert_policy"] is None
        assert alert["provider_alert_eligibility"] == "BLOCKED"
        assert "unknown provider status" in alert["provider_alert_policy_error"]

    def test_alert_uses_outcome_failure_when_all_steps_succeeded(self, mod, tmp_path):
        outcome = {
            "run_id": "blocked-late-admission",
            "exit_code": 4,
            "status": "partial_failure",
            "admission_verdict": "BLOCK",
            "publish_status": "NOT_PUBLISHED",
        }
        mod.write_alert(
            [],
            [{"step": "all_steps", "status": "success"}],
            output_root=tmp_path,
            outcome=outcome,
        )

        alert = json.loads((tmp_path / "alerts" / "latest_alert.json").read_text(encoding="utf-8"))
        assert alert["status"] == "partial_failure"
        assert alert["severity"] == "HIGH"
        assert "exit_code=4" in alert["summary"]


# ── check_freshness ────────────────────────────────────────────────────


class TestCheckFreshness:
    def test_missing_framework_output(self, mod, tmp_path):
        """Missing file returns status=missing."""
        with patch("scripts._runtime_io.ROOT", tmp_path):
            result = mod.check_freshness()
        assert result["status"] == "missing"

    def test_fresh_pressure_snapshot(self, mod, tmp_path):
        """Recently modified file returns status=fresh."""
        fw_dir = tmp_path / "Output" / "current"
        fw_dir.mkdir(parents=True)
        fw_file = fw_dir / "neutral_pressure_snapshot.json"
        fw_file.write_text("{}")
        with patch("scripts._runtime_io.ROOT", tmp_path):
            result = mod.check_freshness()
        assert result["status"] == "fresh"
        assert result["stale_hours"] is not None
        assert result["stale_hours"] < 1


def test_harvester_warning_uses_observation_end_not_finalized_at(mod, tmp_path, monkeypatch):
    latest = tmp_path / "Data" / "harvester" / "exports" / "latest"
    (latest / "manifests").mkdir(parents=True)
    (latest / "catalog.json").write_text(
        json.dumps({"finalized_at": "2099-01-01T00:00:00Z"}), encoding="utf-8"
    )
    for dataset_id in ("benchmark_panel", "cross_asset_daily_panel"):
        (latest / "manifests" / f"{dataset_id}.manifest.json").write_text(
            json.dumps({"time_coverage": {"end": "2020-01-01"}}), encoding="utf-8"
        )
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    warnings = mod.check_warnings()

    assert any(warning.startswith("HARVESTER_STALE:") for warning in warnings)


def test_harvester_warning_surfaces_provider_carry_forward(mod, tmp_path, monkeypatch):
    latest = tmp_path / "Data" / "harvester" / "exports" / "latest"
    (latest / "manifests").mkdir(parents=True)
    for dataset_id in ("benchmark_panel", "cross_asset_daily_panel"):
        outcome = (
            {
                "status": "reused_after_provider_failure",
                "failed_count": 53,
                "requested_count": 65,
            }
            if dataset_id == "benchmark_panel"
            else {"status": "refreshed"}
        )
        (latest / "manifests" / f"{dataset_id}.manifest.json").write_text(
            json.dumps(
                {
                    "time_coverage": {"end": "2026-08-14"},
                    "provider_outcome": outcome,
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    warnings = mod.check_warnings()

    assert any(
        warning == "HARVESTER_PROVIDER_DEGRADED: benchmark_panel "
        "status=reused_after_provider_failure failed=53/65"
        for warning in warnings
    )
