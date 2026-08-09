"""DVC promote helpers — pointer JSON always; dvc add best-effort."""
from __future__ import annotations

import json
from pathlib import Path

from orchestration.dvc_promote import record_release_pointer, record_snapshot_pointer


def test_record_release_pointer_writes_meta(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SYSTEM_DISABLE_DVC", "1")
    exports = tmp_path / "exports"
    release_id = "2026-08-10-r1"
    release_dir = exports / release_id
    release_dir.mkdir(parents=True)
    (release_dir / "catalog.json").write_text('{"ok": true}\n', encoding="utf-8")
    (release_dir / "release_digest.txt").write_text("deadbeef\n", encoding="utf-8")
    (release_dir / ".finalized").write_text("", encoding="utf-8")

    payload = record_release_pointer(exports_root=exports, release_id=release_id, root=tmp_path)
    pointer = exports / ".dvc_meta" / "latest_pointer.json"
    assert pointer.exists()
    body = json.loads(pointer.read_text(encoding="utf-8"))
    assert body["release_id"] == release_id
    assert payload["dvc_tracked"] is False
    staged = exports / ".dvc_meta" / "releases" / release_id / "catalog.json"
    assert staged.exists()


def test_record_snapshot_pointer_writes_meta(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SYSTEM_DISABLE_DVC", "1")
    snap_root = tmp_path / "Data" / "deformation" / "snapshots"
    snap_root.mkdir(parents=True)
    snap = snap_root / "snap-1.json"
    snap.write_text('{"id": "snap-1"}\n', encoding="utf-8")
    index = snap_root / "index.json"
    index.write_text('{"latest": "snap-1"}\n', encoding="utf-8")
    payload = record_snapshot_pointer(
        snapshot_path=snap,
        snapshot_id="snap-1",
        index_path=index,
        root=tmp_path,
    )
    meta = snap_root / ".dvc_meta" / "latest_snapshot_pointer.json"
    assert meta.exists()
    assert payload["snapshot_id"] == "snap-1"
    assert payload["dvc_tracked"] is False
