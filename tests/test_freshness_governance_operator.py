"""Operator-bound freshness probes against live Harvester releases."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.operator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "workbench" / "src"))

from workbench.freshness import build_release_freshness_manifest


def test_current_release_marks_tedrate_retired_and_move_missing() -> None:
    manifest = build_release_freshness_manifest(
        ROOT / "Data" / "harvester" / "exports" / "20260426T074656Z"
    )
    by_series = {item["series_id"]: item for item in manifest["indicators"]}

    assert by_series["TEDRATE"]["freshness_status"] == "retired_or_unavailable"
    assert by_series["TEDRATE"]["current_diagnostics_allowed"] is False
    assert "January 2022" in by_series["TEDRATE"]["retired_reason"]

    assert by_series["MOVE"]["freshness_status"] == "missing"
    assert by_series["MOVE"]["required"] is True
    assert by_series["MOVE"]["missing_reason"] == (
        "Not present in the admitted Harvester evidence release."
    )
    assert manifest["model_input_validity"] == "incomplete"
    assert "MOVE is required but missing" in manifest["gate_result"]["warnings"]
