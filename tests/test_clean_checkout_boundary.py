"""The CI clean-checkout guard catches Data/Output materialization."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.commands.ci.clean_checkout_boundary import run_after, run_before


def test_clean_checkout_boundary_passes_when_surfaces_stay_absent(tmp_path: Path) -> None:
    state = tmp_path / "runner" / "boundary.json"

    assert run_before(tmp_path, state) == 0
    assert run_after(tmp_path, state) == 0

    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS"
    assert payload["before"] == {"Data": False, "Output": False}
    assert payload["after"] == {"Data": False, "Output": False}


def test_clean_checkout_boundary_fails_if_tests_materialize_a_surface(
    tmp_path: Path,
) -> None:
    state = tmp_path / "runner" / "boundary.json"

    assert run_before(tmp_path, state) == 0
    (tmp_path / "Output").mkdir()

    assert run_after(tmp_path, state) == 1
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["verdict"] == "FAIL"
    assert payload["after"]["Output"] is True


def test_clean_checkout_boundary_rejects_preexisting_broken_symlink(
    tmp_path: Path,
) -> None:
    state = tmp_path / "runner" / "boundary.json"
    (tmp_path / "Data").symlink_to(tmp_path / "missing-data-target")

    assert run_before(tmp_path, state) == 1
    assert run_after(tmp_path, state) == 1


def test_clean_checkout_boundary_allows_tracked_data_inputs(monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "runner" / "boundary.json"
    data = tmp_path / "Data"
    data.mkdir()
    (data / "panel.dvc").write_text("outs: []\n", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.commands.ci.clean_checkout_boundary._tracked_paths",
        lambda _root, name: {"Data/panel.dvc"} if name == "Data" else set(),
    )

    assert run_before(tmp_path, state) == 0
    assert run_after(tmp_path, state) == 0

    (data / "materialized.parquet").write_bytes(b"operator data")
    assert run_after(tmp_path, state) == 1
