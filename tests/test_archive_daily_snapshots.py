"""Tests for daily snapshot archiving."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "archive"))

import archive_daily_snapshots as ads


def test_archive_daily_snapshots_copies_once(tmp_path: Path, monkeypatch) -> None:
    current = tmp_path / "Output" / "current"
    caselab = tmp_path / "Output" / "caselab"
    archive = tmp_path / "Output" / "archive"
    current.mkdir(parents=True)
    caselab.mkdir(parents=True)

    fw = current / "framework_output.json"
    fw.write_text(json.dumps({"as_of": "2026-06-18"}), encoding="utf-8")
    (caselab / "2026-06-18.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    monkeypatch.setattr(ads, "ROOT", tmp_path)
    monkeypatch.setattr(ads, "FRAMEWORK_SRC", fw)
    monkeypatch.setattr(ads, "CASELAB_DIR", caselab)
    monkeypatch.setattr(ads, "ARCHIVE_ROOT", archive)
    monkeypatch.setattr(ads, "MANIFEST_PATH", archive / "snapshot_manifest.json")

    first = ads.archive_daily_snapshots("2026-06-18")
    second = ads.archive_daily_snapshots("2026-06-18")

    assert len(first["archived"]) == 2
    assert "framework_output" in first["skipped"] or "caselab" in second["skipped"]
    assert (archive / "framework_output" / "2026-06-18.json").exists()
