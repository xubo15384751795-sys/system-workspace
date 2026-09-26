"""Work-cycle modes must not become a second live publisher."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def test_full_work_cycle_is_scheduler_owned_by_default() -> None:
    env = os.environ.copy()
    env.pop("SYSTEM_USE_LEGACY_WORK_CYCLE", None)
    env.pop("SYSTEM_GENERATION_MODE", None)
    env.pop("SYSTEM_GENERATION_DIR", None)
    env["SYSTEM_ROOT"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "scripts/run_work_cycle.py", "--mode", "full", "--json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 78
    assert "scheduled Dagster path" in result.stderr


def test_quick_and_standard_work_cycle_are_candidate_owned() -> None:
    source = (ROOT / "verity" / "cli" / "run_work_cycle.py").read_text(encoding="utf-8")

    assert "PublishTransaction" in source
    assert "transaction.prepare()" in source
    assert "transaction.activate()" in source
    assert "transaction.write_lineage()" in source
    assert "RunBundle.start(mode=f\"work_cycle_{args.mode}\", update_pointer=False)" in source
    assert "SYSTEM_USE_LEGACY_WORK_CYCLE" in source
    assert "if not _legacy_work_cycle_enabled()" in source
    assert "raise SystemExit(1)" in source


def test_candidate_work_cycle_does_not_advance_global_pointer(monkeypatch, tmp_path: Path) -> None:
    from verity.cli import run_work_cycle

    run_work_cycle.RUNS = tmp_path / "Output" / "runs"
    bundle = SimpleNamespace(run_dir=tmp_path / "Output" / "runs" / "candidate_run")
    bundle.run_dir.mkdir(parents=True)

    monkeypatch.delenv("SYSTEM_USE_LEGACY_WORK_CYCLE", raising=False)
    run_work_cycle._update_latest_work_cycle_pointer(bundle)
    assert not (run_work_cycle.RUNS / "latest_work_cycle.txt").exists()

    monkeypatch.setenv("SYSTEM_USE_LEGACY_WORK_CYCLE", "1")
    run_work_cycle._update_latest_work_cycle_pointer(bundle)
    assert (run_work_cycle.RUNS / "latest_work_cycle.txt").read_text() == str(bundle.run_dir)
