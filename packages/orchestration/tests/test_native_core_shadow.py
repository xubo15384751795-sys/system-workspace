from __future__ import annotations

import pytest

from orchestration.operators import run_native_core_shadow as operator


def test_help_does_not_materialize_core_shadow(monkeypatch, capsys) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("--help must not run the core shadow job")

    monkeypatch.setattr(operator, "run_shadow", fail_if_called)

    with pytest.raises(SystemExit) as exc_info:
        operator.main(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--report" in help_text
    assert "--benchmark-panel" in help_text


def test_explicit_panel_builds_shadow_only_runner(monkeypatch, tmp_path) -> None:
    captured = {}

    class _Result:
        success = True
        all_events = ()

        def output_for_node(self, _node_name):
            return None

    def fake_build_assets(*, boundary_runner):
        captured["runner"] = boundary_runner
        return ()

    monkeypatch.setattr(operator, "build_native_core_assets", fake_build_assets)
    monkeypatch.setattr(operator, "build_native_core_checks", lambda _assets: ())
    monkeypatch.setattr(operator, "materialize", lambda *_args, **_kwargs: _Result())
    monkeypatch.setattr(
        operator,
        "execute_native_core_boundary",
        lambda step_id, **kwargs: {
            "step": step_id,
            "status": "success",
            "check_passed": True,
            "writes_active_generation": True,
            "current_output": str(kwargs["current_output"]),
            "benchmark_panel_path": str(kwargs["benchmark_panel_path"]),
        },
    )

    panel = tmp_path / "fresh-panel.parquet"
    panel.write_bytes(b"panel")
    root = tmp_path / "workspace"
    report = operator.run_shadow(root=root, benchmark_panel_path=panel)

    assert report["status"] == "PASS"
    assert report["materialization_mode"] == "explicit_panel_shadow"
    assert report["benchmark_panel_path"] == str(panel.resolve())
    assert report["workspace_current_unchanged"] is True

    result = captured["runner"]("neutral_pressure_measurement")
    assert result["benchmark_panel_path"] == str(panel.resolve())
    assert result["current_output"].endswith("Output/health/native_core_shadow")


def test_custom_root_default_panel_does_not_use_registered_global_job(monkeypatch, tmp_path) -> None:
    captured = {}

    def fail_if_registered_job_is_used(*_args, **_kwargs):
        raise AssertionError("custom root must not execute the global registered job")

    monkeypatch.setattr(operator.defs, "resolve_job_def", fail_if_registered_job_is_used)

    class _Result:
        success = True
        all_events = ()

        def output_for_node(self, _node_name):
            return None

    def fake_build_assets(*, boundary_runner):
        captured["runner"] = boundary_runner
        return ()

    monkeypatch.setattr(operator, "build_native_core_assets", fake_build_assets)
    monkeypatch.setattr(operator, "build_native_core_checks", lambda _assets: ())
    monkeypatch.setattr(operator, "materialize", lambda *_args, **_kwargs: _Result())
    monkeypatch.setattr(
        operator,
        "execute_native_core_boundary",
        lambda step_id, **kwargs: {
            "step": step_id,
            "status": "success",
            "check_passed": True,
            "writes_active_generation": True,
            "current_output": str(kwargs["current_output"]),
            "benchmark_panel_path": str(kwargs["benchmark_panel_path"]),
        },
    )

    root = tmp_path / "isolated-workspace"
    panel = root / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
    panel.parent.mkdir(parents=True)
    panel.write_bytes(b"panel")

    report = operator.run_shadow(root=root)

    assert report["status"] == "PASS"
    assert report["materialization_mode"] == "isolated_default_panel_shadow"
    assert report["benchmark_panel_path"] == str(panel.resolve())
    result = captured["runner"]("neutral_pressure_measurement")
    assert result["benchmark_panel_path"] == str(panel.resolve())
    assert result["current_output"].endswith("Output/health/native_core_shadow")
