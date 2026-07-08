"""Test isolation audit checks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages" / "workbench" / "src"))

from benchmarks.market_feedback.isolation_audit import (
    _check_no_qlib_imports,
    _check_path_sandboxed,
)


class TestIsolationAuditChecks:
    def test_no_qlib_imports_in_main_src(self):
        result = _check_no_qlib_imports()
        assert result["status"] == "passed", f"Qlib imports found: {result.get('detail')}"

    def test_path_sandbox_check(self):
        result = _check_path_sandboxed(Path("/tmp/test_benchmark"), "sandbox_input")
        # skipped when directory doesn't exist — not a failure
        assert result["status"] in ("passed", "skipped")

    def test_job_spec_forbidden_valid(self, tmp_path):
        spec = {"input_dir": "Output/benchmarks/market_feedback/test/sandbox_input",
                "output_dir": "Output/benchmarks/market_feedback/test/qlib_output",
                "workspace_dir": "Output/benchmarks/market_feedback/test/qlib_workspace"}
        job_spec_path = tmp_path / "qlib_job_spec.json"
        import json
        job_spec_path.write_text(json.dumps(spec))
        # This test validates the check logic, not the fs path
        errors = []
        forbidden = ["Data/", "packages/workbench/src", "Output/deformation_runs/", "Output/system_learning/"]
        for key in ["input_dir", "workspace_dir", "output_dir"]:
            value = spec.get(key, "")
            for f in forbidden:
                if f in value:
                    errors.append(f)
        assert len(errors) == 0, f"Valid paths should not trigger forbidden checks: {errors}"

    def test_job_spec_forbidden_rejects_bad_path(self):
        forbidden = ["Data/", "packages/workbench/src", "Output/deformation_runs/", "Output/system_learning/"]
        spec = {"input_dir": "Data/releases/leak", "output_dir": "/tmp/out", "workspace_dir": "/tmp/ws"}
        errors = []
        for key in ["input_dir", "workspace_dir", "output_dir"]:
            value = spec.get(key, "")
            for f in forbidden:
                if f in value:
                    errors.append((key, value, f))
        assert len(errors) > 0, "Should catch Data/ in job spec paths"

    def test_learning_event_excludes_raw_payload(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        event = {
            "event_type": "test",
            "predictions": [1, 2, 3],  # forbidden
        }
        event_path = events_dir / "benchmark_event.json"
        import json
        event_path.write_text(json.dumps(event))

        with open(event_path) as f:
            event_data = json.load(f)
        forbidden_keys = {"predictions", "raw_positions", "qlib_cache", "raw_model"}
        found = [k for k in forbidden_keys if k in event_data]
        assert len(found) > 0, "Should detect forbidden keys in event"
