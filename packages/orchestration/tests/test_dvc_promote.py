"""DVC promote helpers — pointers are fail-closed until remote verification."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import orchestration.dvc_promote as dvc_promote
from orchestration.dvc_promote import (
    record_canonical_panel_pointer,
    record_release_pointer,
    record_snapshot_pointer,
    verify_canonical_panel_pointer,
)


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
    assert not pointer.exists()
    assert payload["dvc_tracked"] is False
    assert payload["dvc_commit_status"] == "BLOCKED"
    assert payload["dvc_error"] == "DVC_DISABLED"
    assert payload["recoverability_status"] == "BLOCKED"
    assert payload["bytes_owner"] == "UNCONFIGURED"
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
    assert not meta.exists()
    assert payload["snapshot_id"] == "snap-1"
    assert payload["dvc_tracked"] is False
    assert payload["dvc_commit_status"] == "BLOCKED"


def test_record_canonical_panel_pointer_is_fail_closed_when_dvc_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SYSTEM_DISABLE_DVC", "1")
    database = tmp_path / "Data" / "canonical" / "panels.duckdb"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"duckdb-snapshot")

    payload = record_canonical_panel_pointer(database_path=database, root=tmp_path)

    assert payload["snapshot_id"]
    assert payload["database_path"] == str(database.resolve())
    assert payload["dvc_commit_status"] == "BLOCKED"
    assert payload["dvc_error"] == "DVC_DISABLED"
    assert not (tmp_path / "Data" / "canonical" / "panels.duckdb.dvc").exists()


def test_run_dvc_defaults_site_cache_to_repository_tmp(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("DVC_SITE_CACHE_DIR", raising=False)
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, "{}", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    dvc_promote._run_dvc(["status"], cwd=tmp_path)

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["DVC_SITE_CACHE_DIR"] == str(
        tmp_path / ".dvc" / "tmp" / "site-cache"
    )


def _fake_add(paths: list[Path], *, root: Path) -> dict:
    for path in paths:
        Path(f"{path}.dvc").write_text("outs:\n- md5: test\n", encoding="utf-8")
    return {
        "tracked": [str(path.resolve().relative_to(root.resolve())) for path in paths],
        "errors": [],
    }


def _fake_dvc_run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    if args[0] == "push":
        return subprocess.CompletedProcess(["dvc", *args], 0, "", "")
    if args[0] == "status":
        return subprocess.CompletedProcess(["dvc", *args], 0, "{}", "")
    return subprocess.CompletedProcess(["dvc", *args], 0, "", "")


def _make_release(tmp_path: Path) -> tuple[Path, str]:
    exports = tmp_path / "exports"
    release_id = "2026-08-10-r1"
    release_dir = exports / release_id
    release_dir.mkdir(parents=True)
    (release_dir / "catalog.json").write_text('{"ok": true}\n', encoding="utf-8")
    (release_dir / "release_digest.txt").write_text("deadbeef\n", encoding="utf-8")
    (release_dir / ".finalized").write_text("", encoding="utf-8")
    return exports, release_id


def test_pointer_is_retained_only_after_push_and_remote_digest_pass(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SYSTEM_DISABLE_DVC", raising=False)
    monkeypatch.setattr(dvc_promote, "ensure_local_remote", lambda root: root / "Data" / ".dvc_cache")
    monkeypatch.setattr(dvc_promote, "_dvc_add_paths", _fake_add)
    monkeypatch.setattr(dvc_promote, "_run_dvc", _fake_dvc_run)
    exports, release_id = _make_release(tmp_path)

    payload = record_release_pointer(exports_root=exports, release_id=release_id, root=tmp_path)

    pointer = exports / ".dvc_meta" / "latest_pointer.json"
    assert pointer.exists()
    pointer_body = json.loads(pointer.read_text(encoding="utf-8"))
    assert pointer_body["release_id"] == release_id
    assert "dvc_commit_status" not in pointer_body
    assert payload["dvc_tracked"] is True
    assert payload["dvc_push_verified"] is True
    assert payload["dvc_digest_verified"] is True
    assert payload["dvc_commit_status"] == "PASS"


def test_canonical_panel_pointer_tracks_only_the_duckdb_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SYSTEM_DISABLE_DVC", raising=False)
    monkeypatch.setattr(
        dvc_promote,
        "ensure_local_remote",
        lambda root: root / "Data" / ".dvc_cache",
    )
    monkeypatch.setattr(dvc_promote, "_dvc_add_paths", _fake_add)
    monkeypatch.setattr(dvc_promote, "_run_dvc", _fake_dvc_run)
    database = tmp_path / "Data" / "canonical" / "panels.duckdb"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"duckdb-snapshot")

    payload = record_canonical_panel_pointer(
        database_path=database,
        snapshot_id="panel-r1",
        root=tmp_path,
    )

    pointer = Path(f"{database}.dvc")
    metadata = database.parent / ".dvc_meta" / "latest_panel_pointer.json"
    assert pointer.exists()
    assert metadata.exists()
    assert json.loads(metadata.read_text(encoding="utf-8"))["snapshot_id"] == "panel-r1"
    assert payload["dvc_paths"] == [str(database.resolve().relative_to(tmp_path.resolve()))]
    assert payload["dvc_commit_status"] == "PASS"
    assert len(payload["dvc_pointer_digests"]) == 1


def test_failed_push_restores_previous_pointer_and_dvc_pointers(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("SYSTEM_DISABLE_DVC", raising=False)
    monkeypatch.setattr(dvc_promote, "ensure_local_remote", lambda root: root / "Data" / ".dvc_cache")
    monkeypatch.setattr(dvc_promote, "_dvc_add_paths", _fake_add)

    def failed_push(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        if args[0] == "push":
            return subprocess.CompletedProcess(["dvc", *args], 7, "", "failed")
        return subprocess.CompletedProcess(["dvc", *args], 0, "", "")

    monkeypatch.setattr(dvc_promote, "_run_dvc", failed_push)
    exports, release_id = _make_release(tmp_path)
    meta_dir = exports / ".dvc_meta"
    meta_dir.mkdir(parents=True)
    pointer = meta_dir / "latest_pointer.json"
    pointer.write_text('{"release_id":"previous"}\n', encoding="utf-8")

    payload = record_release_pointer(exports_root=exports, release_id=release_id, root=tmp_path)

    assert payload["dvc_tracked"] is False
    assert payload["dvc_error"] == "DVC_PUSH_FAILED_EXIT_7"
    assert json.loads(pointer.read_text(encoding="utf-8"))["release_id"] == "previous"
    assert not Path(f"{pointer}.dvc").exists()


def test_remote_digest_mismatch_does_not_leave_pointer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SYSTEM_DISABLE_DVC", raising=False)
    monkeypatch.setattr(dvc_promote, "ensure_local_remote", lambda root: root / "Data" / ".dvc_cache")
    monkeypatch.setattr(dvc_promote, "_dvc_add_paths", _fake_add)

    def mismatched_remote(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        if args[0] == "status":
            return subprocess.CompletedProcess(
                ["dvc", *args], 0, '{"not_in_remote": ["latest_pointer.json.dvc"]}', ""
            )
        return subprocess.CompletedProcess(["dvc", *args], 0, "", "")

    monkeypatch.setattr(dvc_promote, "_run_dvc", mismatched_remote)
    exports, release_id = _make_release(tmp_path)

    payload = record_release_pointer(exports_root=exports, release_id=release_id, root=tmp_path)

    assert payload["dvc_error"] == "DVC_REMOTE_DIGEST_MISMATCH"
    assert not (exports / ".dvc_meta" / "latest_pointer.json").exists()
    assert payload["recoverability_status"] == "BLOCKED"


def test_recoverability_metadata_uses_configured_remote_uri(tmp_path: Path) -> None:
    dvc_dir = tmp_path / ".dvc"
    dvc_dir.mkdir()
    (dvc_dir / "config").write_text(
        '[core]\n    remote = localcache\n'
        '[\'remote "localcache"\']\n    url = ../../Data/.dvc_cache\n',
        encoding="utf-8",
    )

    metadata = dvc_promote._recoverability_metadata(root=tmp_path)

    assert metadata["dvc_remote_uri"] == str((tmp_path / ".dvc" / "../../Data/.dvc_cache").resolve())


def test_verify_canonical_pointer_rejects_missing_remote_object(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "Data" / "canonical" / "panels.duckdb"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"duckdb-snapshot")
    pointer = Path(f"{database}.dvc")
    pointer.write_text(
        "outs:\n- md5: 5f0c6f07f5a4d1f6a0d4fbd9b6d4a4be\n  size: 15\n  hash: md5\n  path: panels.duckdb\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        dvc_promote,
        "_run_dvc",
        lambda _args, cwd: subprocess.CompletedProcess(
            ["dvc"], 0, '{"Data/canonical/panels.duckdb": "new"}', ""
        ),
    )

    result = verify_canonical_panel_pointer(database_path=database, root=tmp_path)

    assert result["status"] == "BLOCKED"
    assert result["remote_verified"] is False
    assert "DVC_REMOTE_DIGEST_MISMATCH" in result["reasons"]


def test_verify_canonical_pointer_passes_only_with_matching_clean_remote(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "Data" / "canonical" / "panels.duckdb"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"duckdb-snapshot")
    import hashlib

    digest = hashlib.md5(database.read_bytes(), usedforsecurity=False).hexdigest()
    pointer = Path(f"{database}.dvc")
    pointer.write_text(
        f"outs:\n- md5: {digest}\n  size: {database.stat().st_size}\n  hash: md5\n  path: panels.duckdb\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dvc_promote,
        "_run_dvc",
        lambda _args, cwd: subprocess.CompletedProcess(["dvc"], 0, "{}", ""),
    )

    result = verify_canonical_panel_pointer(database_path=database, root=tmp_path)

    assert result["status"] == "PASS"
    assert result["workspace_digest_match"] is True
    assert result["remote_verified"] is True
