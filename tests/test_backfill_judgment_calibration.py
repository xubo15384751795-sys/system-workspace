"""Tests for judgment backfill from archives and run bundles."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import workbench.judgment.backfill_judgment_calibration as bjc


def test_discover_dates_from_archive_and_caselab(tmp_path: Path, monkeypatch) -> None:
    archive_fw = tmp_path / "archive" / "framework_output"
    archive_cl = tmp_path / "archive" / "caselab"
    caselab = tmp_path / "caselab"
    archive_fw.mkdir(parents=True)
    archive_cl.mkdir(parents=True)
    caselab.mkdir(parents=True)

    (archive_fw / "2026-06-16.json").write_text(json.dumps({"as_of": "2026-06-16"}), encoding="utf-8")
    (caselab / "2026-06-17.json").write_text(json.dumps({"match_quality": {"top_score": 0.4}}), encoding="utf-8")

    monkeypatch.setattr(bjc, "ARCHIVE_FW", archive_fw)
    monkeypatch.setattr(bjc, "ARCHIVE_CASELAB", archive_cl)
    monkeypatch.setattr(bjc, "CASELAB_DIR", caselab)
    monkeypatch.setattr(bjc, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(bjc, "discover_signal_trace_frameworks", lambda: {})

    dates = bjc.discover_dates()
    assert dates == ["2026-06-16", "2026-06-17"]


def test_backfill_skips_existing_without_force(tmp_path: Path, monkeypatch) -> None:
    judgment_dir = tmp_path / "judgment"
    judgment_dir.mkdir(parents=True)
    (judgment_dir / "2026-06-16.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(bjc, "discover_dates", lambda: ["2026-06-16"])
    monkeypatch.setattr(bjc, "discover_signal_trace_frameworks", lambda: {})
    monkeypatch.setattr(
        bjc,
        "_load_framework",
        lambda date_str, signal_fw: {"as_of": f"{date_str}T00:00:00+00:00", "advanced": {"sigma_vector": {}}},
    )
    monkeypatch.setattr(bjc, "_load_caselab_for_date", lambda date_str: None)
    monkeypatch.setattr(bjc, "JUDGMENT_DIR", judgment_dir)

    report = bjc.backfill_judgment_calibration(dry_run=True, refresh_calibration=False)
    assert report["created_count"] == 0
    assert report["skipped"][0]["reason"] == "judgment_exists"


def test_framework_from_signal_trace_shape() -> None:
    fw = bjc._framework_from_signal_trace(
        {
            "framework_status": "active_full",
            "overall": "ACTIVE_FULL",
            "quality_status": "FULL_PROXY_REDUCED",
            "sigma_vector": {"M": -1.0, "D": -0.5},
            "primary_readout": {"state": "MIXED_ANCHOR_PATH_STRESS"},
        },
        "2026-06-17",
    )
    assert fw["as_of"].startswith("2026-06-17")
    assert fw["advanced"]["sigma_vector"]["M"] == -1.0
    assert fw["basic"]["primary_market_space"] == "MIXED_ANCHOR_PATH_STRESS"


def test_framework_from_caselab_minimal() -> None:
    fw = bjc.framework_from_caselab(
        {"system_state": {"M": 1.0, "D": -0.5, "K": 0.2, "X": 0.1, "pattern": "STABLE_LOCAL"}},
        "2026-06-15",
    )
    assert fw is not None
    assert fw["advanced"]["sigma_vector"]["M"] == 1.0
    assert fw["provenance"]["source"] == "caselab_system_state"
