"""Operator-bound Workbench tool builds (refresh / live Output).

Kept out of merge-gate via STATEFUL_ROOT_TESTS.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_benchmark_evidence_dashboard_builds() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_benchmark_evidence_dashboard.py")],
        check=True,
        cwd=str(ROOT),
    )

    payload_path = (
        ROOT / "Output" / "workbench" / "benchmark_evidence" / "benchmark_evidence_dashboard.json"
    )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "workbench.evidence_panel.v1"
    statuses = {row["series_id"]: row["status"] for row in payload["series"]}
    assert statuses["NFCI"] == "available"
    assert statuses["VIXCLS"] == "available"
    assert "MOVE" in statuses


def test_artifact_navigator_builds_from_current() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True, cwd=str(ROOT))
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_benchmark_evidence_dashboard.py")],
        check=True,
        cwd=str(ROOT),
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_artifact_navigator.py")],
        check=True,
        cwd=str(ROOT),
    )

    payload_path = ROOT / "Output" / "workbench" / "artifacts" / "artifact_navigator.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "workbench.report_artifact.v1"
    names = {item["name"]: item for item in payload["artifacts"]}
    assert names["Current status card"]["exists"] is True
    assert names["Framework output"]["exists"] is True


def test_current_framework_output_matches_active_contract() -> None:
    subprocess.run([str(ROOT / "sys"), "refresh"], check=True, cwd=str(ROOT))
    payload = json.loads(
        (ROOT / "Output" / "current" / "framework_output.json").read_text(
            encoding="utf-8"
        )
    )
    # Deformation v1 is archived; the active Workbench contract is the
    # neutral macro-pressure measurement framework. The old test validated
    # Output/current/model_run.json, an artifact produced only by the retired
    # framework bridge and no longer emitted by the canonical refresh path.
    assert payload["schema_version"] == "workbench.framework_output.v3"
    assert payload["framework_id"] == "macro_pressure_measurement"
    assert payload["status"] in {
        "active_full",
        "active_partial",
        "degraded_partial",
        "degraded",
        "full",
        "partial",
        "missing",
        "stale",
    }
    assert isinstance(payload.get("basic"), dict)
    assert isinstance(payload.get("advanced"), dict)
