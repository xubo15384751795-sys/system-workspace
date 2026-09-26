"""System index must project committed Output/current, never a publish candidate."""
from __future__ import annotations

import json
from pathlib import Path

from workbench.surfaces.build_system_index import (
    build_index,
    check_path,
    live_output_dir,
)


def test_live_output_dir_ignores_generation_env(monkeypatch, tmp_path: Path) -> None:
    from workbench.surfaces import build_system_index as bsi

    monkeypatch.setattr(bsi, "ROOT", tmp_path)
    monkeypatch.setenv("SYSTEM_GENERATION_MODE", "1")
    monkeypatch.setenv(
        "SYSTEM_GENERATION_DIR",
        str(tmp_path / "Output" / "runs" / "r1" / "publish_candidate"),
    )
    monkeypatch.setenv(
        "CURRENT_OUTPUT_DIR",
        str(tmp_path / "Output" / "runs" / "r1" / "publish_candidate" / "current"),
    )
    assert live_output_dir() == tmp_path / "Output"


def test_build_index_records_live_current_not_candidate(monkeypatch, tmp_path: Path) -> None:
    from workbench.surfaces import build_system_index as bsi

    monkeypatch.setattr(bsi, "ROOT", tmp_path)
    live_current = tmp_path / "Output" / "current"
    live_current.mkdir(parents=True)
    (live_current / "framework_output.json").write_text("{}\n", encoding="utf-8")
    (live_current / "00_READ_ME_FIRST.md").write_text("live\n", encoding="utf-8")
    candidate = tmp_path / "Output" / "runs" / "r1" / "publish_candidate" / "current"
    candidate.mkdir(parents=True)
    (candidate / "framework_output.json").write_text('{"candidate": true}\n', encoding="utf-8")
    monkeypatch.setenv("SYSTEM_GENERATION_MODE", "1")
    monkeypatch.setenv("SYSTEM_GENERATION_DIR", str(candidate.parent))
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(candidate))

    index = build_index()
    path = index["current_output"]["path"]
    assert index["current_output"]["exists"] is True
    assert index["readme_first"]["exists"] is True
    assert "publish_candidate" not in path
    assert path.endswith("Output/current/framework_output.json")
    assert json.loads(Path(path).read_text(encoding="utf-8")) == {}


def test_check_path_rejects_candidate_records(tmp_path: Path) -> None:
    candidate = tmp_path / "publish_candidate" / "current" / "framework_output.json"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("{}\n", encoding="utf-8")
    try:
        check_path(candidate)
    except RuntimeError as exc:
        assert "publish candidate" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for publish_candidate path")
