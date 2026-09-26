"""Harvester release retention reporting and --apply reclaim."""
from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile

import pytest

from scripts import apply_data_retention_policy as mod

POLICY = {
    "harvester_exports": {
        "keep_latest": True,
        "keep_last_n_daily": 7,
        "keep_monthly_checkpoints": True,
        "keep_lineage_generations": 14,
        "archive_debug_releases": True,
        "archive_tarball": "Data/archive/harvester_releases_2026H1.tar.zst",
        "current_debug_releases": ["test-debug", "test-debug2", "test-debug3"],
    }
}


def _write_release(exports_dir, name: str, *, jsonl: bool = False, parquet: bool = True) -> None:
    release = exports_dir / name
    data = release / "data"
    data.mkdir(parents=True)
    (release / "catalog.json").write_text('{"release_id": "%s"}' % name, encoding="utf-8")
    if parquet:
        (data / "benchmark_panel.parquet").write_bytes(b"PARQ" + b"x" * 32)
    if jsonl:
        (data / "observations.jsonl").write_text("{}\n", encoding="utf-8")
    (data / "notes.txt").write_text("keep-out-of-archive\n", encoding="utf-8")


@pytest.fixture
def exports(tmp_path, monkeypatch):
    """Ten July days, retries on days 3 and 7, plus a debug dir."""
    root = tmp_path
    exports_dir = root / "Data" / "harvester" / "exports"
    exports_dir.mkdir(parents=True)
    for day in range(1, 11):
        revisions = 3 if day in (3, 7) else 1
        for rev in range(1, revisions + 1):
            _write_release(
                exports_dir,
                f"2026-07-{day:02d}-r{rev}",
                jsonl=(day == 10 and rev == 1),
            )
    (exports_dir / ".failures").mkdir()
    (exports_dir / "20260426T074656Z").mkdir()
    (exports_dir / "test-debug2").mkdir()
    (exports_dir / "test-debug2" / "catalog.json").write_text("{}", encoding="utf-8")
    (exports_dir / "latest").symlink_to("2026-07-10-r1")
    monkeypatch.setattr(mod, "ROOT", root)
    return exports_dir


def _by_status(findings):
    return {f["status"]: f for f in findings}


class TestHarvesterReleaseRetention:
    def test_deletes_outside_window_but_keeps_monthly_first(self, exports):
        plan = mod.plan_harvester_export_actions(POLICY)
        # July 1 is monthly first; days 4-10 latest rN are the last 7 daily.
        assert "2026-07-01-r1" in plan["keep"]
        assert "2026-07-10-r1" in plan["keep"]
        assert "2026-07-07-r3" in plan["keep"]
        assert "2026-07-02-r1" in plan["delete"]
        assert "2026-07-03-r1" in plan["delete"]
        assert "2026-07-07-r1" in plan["delete"]
        assert "2026-07-07-r2" in plan["delete"]
        assert "test-debug2" in plan["debug_delete"]
        # Non-release dirs are neither kept nor deleted.
        assert "latest" not in plan["delete"]
        names = set(plan["delete"]) | set(plan["keep"]) | set(plan["debug_delete"])
        assert ".failures" not in names
        assert "20260426T074656Z" not in names

    def test_keep_reasons_include_latest_symlink_without_expanding_it(self, exports):
        plan = mod.plan_harvester_export_actions(POLICY)
        assert "latest_symlink" in plan["keep"]["2026-07-10-r1"]
        assert (exports / "latest").is_symlink()
        assert os.readlink(exports / "latest") == "2026-07-10-r1"

    def test_lineage_of_recent_generations_pins_old_release(self, tmp_path, monkeypatch, exports):
        gen = tmp_path / "Output" / "generations" / "daily_pipeline_20260710_000000_aaaaaa"
        current = gen / "current"
        current.mkdir(parents=True)
        (gen / "lineage.json").write_text(
            json.dumps({
                "schema_version": "system.generation_lineage.v1",
                "run_id": "daily_pipeline_20260710_000000_aaaaaa",
                "files": [{"path": "current/framework_output.json", "sha256": "ab"}],
            }),
            encoding="utf-8",
        )
        (current / "framework_output.json").write_text(
            json.dumps({"provenance": {"source_release_id": "2026-07-02-r1"}}),
            encoding="utf-8",
        )
        plan = mod.plan_harvester_export_actions(POLICY)
        assert "2026-07-02-r1" in plan["keep"]
        assert "2026-07-02-r1" not in plan["delete"]

    def test_ignores_non_release_directories(self, exports):
        plan = mod.plan_harvester_export_actions(POLICY)
        assert (exports / ".failures").is_dir()
        assert "latest" not in plan["delete"]

    def test_clean_when_within_budget(self, tmp_path, monkeypatch):
        exports_dir = tmp_path / "Data" / "harvester" / "exports"
        exports_dir.mkdir(parents=True)
        for day in (1, 2):
            _write_release(exports_dir, f"2026-07-{day:02d}-r1")
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        findings = mod._check_harvester_release_retention(
            {"harvester_exports": {"keep_last_n_daily": 7}}
        )
        assert findings == []

    def test_no_rule_declared_is_a_no_op(self, exports):
        assert mod._check_harvester_release_retention({"harvester_exports": {}}) == []

    def test_check_never_deletes(self, exports):
        before = sorted(p.name for p in exports.iterdir())
        mod._check_harvester_release_retention(POLICY)
        mod.plan_harvester_export_actions(POLICY)
        assert sorted(p.name for p in exports.iterdir()) == before

    def test_wired_into_the_check_run(self):
        import inspect

        source = inspect.getsource(mod.run_retention_check)
        assert "harvester_release_retention" in source
        assert "plan_harvester_export_actions" in source


def test_apply_packs_parquet_without_jsonl_then_deletes(exports, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    action = mod.apply_harvester_export_retention(POLICY)

    assert action["status"] == "harvester_exports_applied"
    assert "2026-07-02-r1" in action["deleted"]
    assert "test-debug2" in action["deleted"]
    assert (exports / "2026-07-10-r1").is_dir()
    assert (exports / "2026-07-01-r1").is_dir()
    assert not (exports / "2026-07-02-r1").exists()
    assert not (exports / "test-debug2").exists()
    assert (exports / "latest").is_symlink()
    assert os.readlink(exports / "latest") == "2026-07-10-r1"
    assert not (exports / "2026-07-10-r1" / "data" / "observations.jsonl").exists()
    assert (exports / "2026-07-10-r1" / "data" / "benchmark_panel.parquet").is_file()

    archive = tmp_path / "Data" / "archive" / "harvester_releases_2026H1.tar.zst"
    assert archive.is_file()
    raw = subprocess.check_output(["zstd", "-dc", str(archive)])
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
        names = tar.getnames()
    assert "2026-07-02-r1/catalog.json" in names
    assert "2026-07-02-r1/data/benchmark_panel.parquet" in names
    assert all(".jsonl" not in name for name in names)
    assert all("notes.txt" not in name for name in names)
    assert "latest" not in names
    assert "latest/catalog.json" not in names


def test_output_runs_recent_n_reports_without_mutating(tmp_path, monkeypatch):
    runs_dir = tmp_path / "Output" / "runs"
    runs_dir.mkdir(parents=True)
    for index in range(4):
        run = runs_dir / f"run-{index}"
        run.mkdir()
        (run / "manifest.json").write_text("{}", encoding="utf-8")
        os.utime(run, (1_000_000 + index, 1_000_000 + index))
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    findings = mod._check_output_runs_retention(
        {
            "output_runs": {
                "path": "Output/runs",
                "keep_last_n": 2,
                "retention_days": None,
                "archive_path": "Output/archive/runs",
            }
        }
    )

    assert findings[0]["count"] == "2"
    assert sorted(path.name for path in runs_dir.iterdir()) == [
        "run-0",
        "run-1",
        "run-2",
        "run-3",
    ]


def test_output_runs_apply_moves_to_recoverable_archive(tmp_path, monkeypatch):
    runs_dir = tmp_path / "Output" / "runs"
    runs_dir.mkdir(parents=True)
    for index in range(3):
        (runs_dir / f"run-{index}").mkdir()
        os.utime(runs_dir / f"run-{index}", (1_000_000 + index, 1_000_000 + index))
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    policy = {
        "output_runs": {
            "path": "Output/runs",
            "keep_last_n": 1,
            "retention_days": None,
            "archive_path": "Output/archive/runs",
        }
    }

    action = mod._apply_output_runs_retention(policy)

    assert action["status"] == "output_runs_archived"
    assert action["count"] == "2"
    assert (runs_dir / "run-2").is_dir()
    assert (tmp_path / "Output" / "archive" / "runs" / "run-0").is_dir()
    assert (tmp_path / "Output" / "archive" / "runs" / "run-1").is_dir()
