"""Tests for build_learning_hub_feedback.py — pipeline alert feedback loop."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "build_learning_hub_feedback",
        ROOT / "scripts" / "build_learning_hub_feedback.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPipelineAlertFeedback:
    """Test build_pipeline_alert_feedback reads alerts correctly."""

    def test_no_alerts(self, tmp_path):
        mod = _load_module()
        # Patch ALERT_PATH to non-existent file
        original = mod.ALERT_PATH
        mod.ALERT_PATH = tmp_path / "no_alert.json"
        try:
            result = mod.build_pipeline_alert_feedback()
            assert result["status"] == "no_alerts"
            assert result["failed_steps"] == []
        finally:
            mod.ALERT_PATH = original

    def test_with_failed_steps(self, tmp_path):
        mod = _load_module()
        alert_dir = tmp_path / "alerts"
        alert_dir.mkdir()
        alert = {
            "timestamp": "2026-06-20T00:00:00Z",
            "severity": "HIGH",
            "warnings": ["QUALITY: FULL_PROXY_REDUCED"],
            "failed_steps": [
                {"step": "harvester", "error": "timeout after 115s", "duration_s": 115.0},
                {"step": "structural_replay", "error": "ModuleNotFoundError", "duration_s": 0.3},
            ],
            "summary": "2 steps failed, 1 warnings",
        }
        (alert_dir / "latest_alert.json").write_text(json.dumps(alert))
        original = mod.ALERT_PATH
        mod.ALERT_PATH = alert_dir / "latest_alert.json"
        try:
            result = mod.build_pipeline_alert_feedback()
            assert result["status"] == "ok"
            assert result["severity"] == "HIGH"
            assert result["total_failed"] == 2
            assert result["failed_steps"][0]["step"] == "harvester"
            assert "timeout" in result["failed_steps"][0]["error"]
            assert result["warnings"] == ["QUALITY: FULL_PROXY_REDUCED"]
        finally:
            mod.ALERT_PATH = original

    def test_with_string_failed_steps(self, tmp_path):
        """Backward compat: old alert format has string failed_steps."""
        mod = _load_module()
        alert_dir = tmp_path / "alerts"
        alert_dir.mkdir()
        alert = {
            "severity": "HIGH",
            "failed_steps": ["harvester", "structural_replay"],
            "warnings": [],
        }
        (alert_dir / "latest_alert.json").write_text(json.dumps(alert))
        original = mod.ALERT_PATH
        mod.ALERT_PATH = alert_dir / "latest_alert.json"
        try:
            result = mod.build_pipeline_alert_feedback()
            assert result["total_failed"] == 2
            assert result["failed_steps"][0]["step"] == "harvester"
            assert result["failed_steps"][0]["error"] == ""
        finally:
            mod.ALERT_PATH = original
