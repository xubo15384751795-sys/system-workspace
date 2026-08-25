from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

from orchestration.operators.aggregate_daily_dual_track_window import evaluate_window
from orchestration.operators.run_daily_dual_track import (
    TrackSpec,
    _run_track,
    execute_dual_track,
    preflight_tracks,
)


def _workspace(root: Path) -> Path:
    (root / "governance").mkdir(parents=True)
    (root / "governance" / "daily_pipeline_registry.yaml").write_text("schema_version: test\n")
    (root / "scripts").mkdir()
    (root / "scripts" / "daily_run.py").write_text("# test workspace\n")
    return root


def _args(*, execute: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        execute=execute,
        tag="wave4_dual_track",
        execution_mode="subprocess",
        skip_harvester=False,
        skip_etf=False,
        use_horizon_sample=False,
        force_weekly=False,
        timeout_seconds=0,
    )


def test_preflight_requires_isolated_workspaces_and_outputs(tmp_path: Path) -> None:
    operator = tmp_path / "operator"
    legacy_root = _workspace(tmp_path / "legacy")
    native_root = _workspace(tmp_path / "native")
    legacy = TrackSpec("legacy", legacy_root, tmp_path / "legacy-output", False)
    native = TrackSpec("native", native_root, tmp_path / "native-output", True)

    report = preflight_tracks(legacy, native, operator_root=operator)

    assert report["status"] == "READY"
    assert report["writes_performed"] is False
    assert not (tmp_path / "legacy-output").exists()
    assert not (tmp_path / "native-output").exists()


def test_preflight_rejects_nested_output_or_cross_track_workspace_overlap(
    tmp_path: Path,
) -> None:
    operator = tmp_path / "operator"
    legacy_root = _workspace(tmp_path / "legacy")
    native_root = _workspace(tmp_path / "native")

    nested_output = TrackSpec(
        "legacy",
        legacy_root,
        legacy_root / "isolated-output",
        False,
    )
    cross_track_output = TrackSpec(
        "native",
        native_root,
        legacy_root / "native-output",
        True,
    )

    report = preflight_tracks(
        nested_output,
        cross_track_output,
        operator_root=operator,
    )

    assert report["status"] == "BLOCKED"
    assert any("legacy: output root must not overlap workspace root" in item for item in report["errors"])
    assert any("native output root must not overlap legacy workspace root" in item for item in report["errors"])


def test_dual_track_defaults_to_preflight_only(tmp_path: Path) -> None:
    operator = tmp_path / "operator"
    legacy_root = _workspace(tmp_path / "legacy")
    native_root = _workspace(tmp_path / "native")
    legacy = TrackSpec("legacy", legacy_root, tmp_path / "legacy-output", False)
    native = TrackSpec("native", native_root, tmp_path / "native-output", True)

    report = execute_dual_track(
        legacy,
        native,
        _args(execute=False),
        operator_root=operator,
    )

    assert report["status"] == "READY"
    assert report["reason"] == "preflight_only"
    assert report["promotion_allowed"] is False
    assert report["writes_performed"] is False


def test_execute_preflight_requires_matching_admitted_release_identity(tmp_path: Path) -> None:
    operator = tmp_path / "operator"
    legacy_root = _workspace(tmp_path / "legacy")
    native_root = _workspace(tmp_path / "native")
    for workspace, release_id in (
        (legacy_root, "2026-08-25-r1"),
        (native_root, "2026-08-24-r1"),
    ):
        latest = workspace / "Data" / "harvester" / "exports" / "latest"
        (latest / "manifests").mkdir(parents=True)
        (latest / "catalog.json").write_text(
            json.dumps({"release_id": release_id}),
            encoding="utf-8",
        )
        (latest / "manifests" / "benchmark_panel.manifest.json").write_text(
            json.dumps({"vintage_date": "2026-08-25", "as_of_date": "2026-08-25"}),
            encoding="utf-8",
        )
    legacy = TrackSpec("legacy", legacy_root, tmp_path / "legacy-output", False)
    native = TrackSpec("native", native_root, tmp_path / "native-output", True)

    def fail_if_started(*_args, **_kwargs):
        raise AssertionError("runner must not start after identity mismatch")

    report = execute_dual_track(
        legacy,
        native,
        _args(execute=True),
        operator_root=operator,
        runner=fail_if_started,
    )

    assert report["status"] == "INCOMPLETE"
    assert report["reason"] == "preflight_blocked"
    assert report["writes_performed"] is False
    assert any("release_id" in error for error in report["preflight"]["errors"])


def test_native_track_enables_both_native_asset_and_file_boundary_flags(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path / "native")
    output = tmp_path / "native-output"
    seen: dict[str, object] = {}

    def fake_runner(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return CompletedProcess(command, 0, stdout="", stderr="")

    result = _run_track(
        TrackSpec("native", workspace, output, True),
        _args(execute=True),
        runner=fake_runner,
    )

    assert result["exit_code"] == 0
    assert seen["env"]["SYSTEM_USE_NATIVE_DAILY_ASSETS"] == "1"
    assert seen["env"]["SYSTEM_USE_NATIVE_FILE_BOUNDARIES"] == "1"


def _window_payload(observation_date: str, *, status: str = "MATCH") -> dict:
    dimensions = {
        "inputs": "MATCH",
        "identity": "MATCH",
        "steps": "MATCH",
        "canonical_lineage": "MATCH",
        "publication": "MATCH",
        "generation_surfaces": "MATCH",
    }
    return {
        "schema_version": "system.orchestration_dual_track_execution.v1",
        "authority": "shadow_only",
        "promotion_allowed": False,
        "observed_at": f"{observation_date}T08:00:00+00:00",
        "observation_date": observation_date,
        "execution_requested": True,
        "writes_performed": True,
        "status": status,
        "parity": {
            "status": status,
            "dimensions": dimensions,
            "identity_parity": {
                "plan_digest": {"left": "plan-1", "right": "plan-1"},
                "release_ids": {"left": ["release-1"], "right": ["release-1"]},
                "vintage_clocks": {"left": ["2026-08-25"], "right": ["2026-08-25"]},
            },
        },
    }


def _write_window_reports(tmp_path: Path, count: int, *, mismatch_at: int | None = None) -> list[Path]:
    start = date(2026, 8, 19)
    paths: list[Path] = []
    for index in range(count):
        day = (start + timedelta(days=index)).isoformat()
        status = "MISMATCH" if mismatch_at == index else "MATCH"
        path = tmp_path / f"dual-{day}.json"
        path.write_text(json.dumps(_window_payload(day, status=status)), encoding="utf-8")
        paths.append(path)
    return paths


def test_dual_track_window_requires_seven_consecutive_real_matches(tmp_path: Path) -> None:
    report = evaluate_window(_write_window_reports(tmp_path, 7))

    assert report["status"] == "MATCH"
    assert report["observation_count"] == 7
    assert report["window_start"] == "2026-08-19"
    assert report["window_end"] == "2026-08-25"
    assert report["promotion_allowed"] is False


def test_dual_track_window_stays_incomplete_until_minimum_window(tmp_path: Path) -> None:
    report = evaluate_window(_write_window_reports(tmp_path, 6))

    assert report["status"] == "INCOMPLETE"
    assert report["reason"] == "observation_window_short"


def test_dual_track_window_surfaces_any_parity_mismatch(tmp_path: Path) -> None:
    report = evaluate_window(_write_window_reports(tmp_path, 7, mismatch_at=3))

    assert report["status"] == "MISMATCH"
    assert report["reason"] == "parity_mismatch_or_identity_drift"


def test_dual_track_window_rejects_wrong_schema_version(tmp_path: Path) -> None:
    paths = _write_window_reports(tmp_path, 7)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["schema_version"] = "old.execution.v0"
    paths[0].write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_window(paths)

    assert report["status"] == "INCOMPLETE"
    assert paths[0].as_posix() in report["unsafe_entries"]


def test_dual_track_window_rejects_observation_timestamp_drift(tmp_path: Path) -> None:
    paths = _write_window_reports(tmp_path, 7)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["observed_at"] = "2026-08-26T08:00:00+00:00"
    paths[0].write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_window(paths)

    assert report["status"] == "INCOMPLETE"
    assert paths[0].as_posix() in report["unsafe_entries"]
