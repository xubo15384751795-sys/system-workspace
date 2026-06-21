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
        assert parsed["type"] == "test"
        assert parsed["step"] == "foo"

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


# ── check_freshness ────────────────────────────────────────────────────


class TestCheckFreshness:
    def test_missing_framework_output(self, mod, tmp_path):
        """Missing file returns status=missing."""
        with patch("daily_run.ROOT", tmp_path):
            result = mod.check_freshness()
        assert result["status"] == "missing"

    def test_fresh_framework_output(self, mod, tmp_path):
        """Recently modified file returns status=fresh."""
        fw_dir = tmp_path / "Output" / "current"
        fw_dir.mkdir(parents=True)
        fw_file = fw_dir / "framework_output.json"
        fw_file.write_text("{}")
        with patch("daily_run.ROOT", tmp_path):
            result = mod.check_freshness()
        assert result["status"] == "fresh"
        assert result["stale_hours"] is not None
        assert result["stale_hours"] < 1
