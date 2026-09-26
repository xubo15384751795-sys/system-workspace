"""Tests for the recoverable legacy-to-generation surface migration."""
from __future__ import annotations

from pathlib import Path

import pytest

from system_runtime.publish_transaction import PublishTransaction
from verity.cli import migrate_output_to_generations as migration


def _seed_legacy_output(root: Path) -> Path:
    output = root / "Output"
    for name in migration.SURFACES:
        surface = output / name
        surface.mkdir(parents=True)
        (surface / "sentinel.txt").write_text(f"{name}\n", encoding="utf-8")
    return output


def test_apply_creates_recoverable_legacy_baseline(tmp_path: Path) -> None:
    output = _seed_legacy_output(tmp_path)

    target = migration.apply(tmp_path)

    assert target.parent == output / "generations"
    assert (output / "live").is_symlink()
    assert (output / "live").resolve() == target
    for name in migration.SURFACES:
        link = output / name
        assert link.is_symlink()
        assert link.resolve() == target / name
        assert (target / name / "sentinel.txt").read_text(encoding="utf-8") == f"{name}\n"
    assert (output / "ledgers").is_symlink()
    assert (output / "ledgers").resolve() == target / "trade_ledger"
    assert PublishTransaction.reconcile(tmp_path)["status"] == "complete_legacy_baseline"
    with pytest.raises(RuntimeError, match="migration preflight blocked"):
        migration.apply(tmp_path)


def test_apply_rejects_existing_ledgers_surface(tmp_path: Path) -> None:
    output = _seed_legacy_output(tmp_path)
    (output / "ledgers").mkdir()

    with pytest.raises(RuntimeError, match="Output/ledgers"):
        migration.apply(tmp_path)

    assert not (output / "live").exists()
    assert not (output / "generations").exists()


def test_apply_rolls_back_regular_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _seed_legacy_output(tmp_path)
    original_move = migration._move_surface

    def fail_on_judgment(source: Path, destination: Path) -> None:
        if source.name == "judgment":
            raise OSError("injected migration failure")
        original_move(source, destination)

    monkeypatch.setattr(migration, "_move_surface", fail_on_judgment)
    with pytest.raises(OSError, match="injected migration failure"):
        migration.apply(tmp_path)

    assert not (output / migration.JOURNAL_NAME).exists()
    assert not (output / "generations").exists()
    assert not (output / "live").exists()
    for name in migration.SURFACES:
        assert (output / name).is_dir()
        assert not (output / name).is_symlink()


def test_recover_rolls_back_process_interruption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _seed_legacy_output(tmp_path)
    original_move = migration._move_surface

    def interrupt_on_judgment(source: Path, destination: Path) -> None:
        if source.name == "judgment":
            raise KeyboardInterrupt
        original_move(source, destination)

    monkeypatch.setattr(migration, "_move_surface", interrupt_on_judgment)
    with pytest.raises(KeyboardInterrupt):
        migration.apply(tmp_path)

    journal = output / migration.JOURNAL_NAME
    assert journal.is_file()
    assert migration.inspect(tmp_path)["migration_journal"]["exists"] is True

    target = migration.recover(tmp_path)

    assert target == output / "generations" / target.name
    assert not journal.exists()
    assert not (output / "generations").exists()
    assert not (output / "live").exists()
    for name in migration.SURFACES:
        assert (output / name / "sentinel.txt").read_text(encoding="utf-8") == f"{name}\n"


def test_dry_run_reports_ready_without_changing_surfaces(tmp_path: Path) -> None:
    output = _seed_legacy_output(tmp_path)
    before = {name: (output / name).stat().st_mtime_ns for name in migration.SURFACES}

    state = migration.inspect(tmp_path)
    state["preflight"] = migration._preflight(tmp_path)

    assert state["preflight"] == {"ready": True, "blockers": []}
    assert not (output / migration.JOURNAL_NAME).exists()
    assert before == {name: (output / name).stat().st_mtime_ns for name in migration.SURFACES}


def test_initial_journal_claim_is_exclusive(tmp_path: Path) -> None:
    output = _seed_legacy_output(tmp_path)
    journal = output / migration.JOURNAL_NAME
    payload = migration._new_journal(tmp_path, "legacy_baseline_fixture", True)

    migration._create_journal(journal, payload)
    with pytest.raises(RuntimeError, match="migration journal already exists"):
        migration._create_journal(journal, payload)

    assert migration._load_journal(tmp_path)["generation_id"] == "legacy_baseline_fixture"
