#!/usr/bin/env python3
"""Convert legacy live output directories to the generation pointer layout.

The command is deliberately dry-run by default.  Applying it moves the seven
compatibility surfaces that participate in the publish transaction into
an explicitly named baseline generation; the move is recoverable because the
entire baseline remains under ``Output/generations/``.

Usage:
    python3 scripts/migrate_output_to_generations.py --dry-run
    python3 scripts/migrate_output_to_generations.py --apply
    python3 scripts/migrate_output_to_generations.py --recover
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT

SURFACES = (
    "current",
    "position",
    "judgment",
    "trade_decision",
    "trade_ledger",
    "quality",
    "system_learning",
)
JOURNAL_NAME = ".legacy_generation_migration.json"
JOURNAL_SCHEMA = "system.legacy_generation_migration.v1"
METADATA_FILES = ("latest_run_id.txt", "manifest.json", "admission.json")


def _baseline_id() -> str:
    return "legacy_baseline_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _path_exists(path: Path) -> bool:
    """Return true for regular paths and dangling symlinks."""

    return path.exists() or path.is_symlink()


def _journal_path(root: Path) -> Path:
    return root / "Output" / JOURNAL_NAME


def _fsync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_journal(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist migration state before the next filesystem change."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _create_journal(path: Path, payload: dict[str, Any]) -> None:
    """Claim the migration journal without a preflight/replace race."""
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise RuntimeError(f"migration journal already exists: {path}") from exc
    except Exception:
        path.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _preflight(root: Path) -> dict[str, object]:
    """Describe whether the legacy surface is safe to migrate."""

    output = root / "Output"
    generations = output / "generations"
    journal = _journal_path(root)
    blockers: list[str] = []

    if not output.is_dir() or output.is_symlink():
        blockers.append(f"Output is not a regular directory: {output}")
    if journal.exists() or journal.is_symlink():
        blockers.append(f"incomplete migration journal exists: {journal}")
    if list(output.glob(f".{JOURNAL_NAME}.*.tmp")):
        blockers.append(f"temporary migration journal exists under: {output}")
    if _path_exists(output / "live"):
        blockers.append("Output/live already exists")
    if _path_exists(output / "ledgers"):
        blockers.append("Output/ledgers already exists")
    if generations.is_symlink():
        blockers.append("Output/generations must not be a symlink")
    elif generations.exists() and not generations.is_dir():
        blockers.append("Output/generations is not a directory")
    elif generations.is_dir() and any(generations.iterdir()):
        blockers.append("Output/generations is not empty")

    for name in SURFACES:
        path = output / name
        if path.is_symlink():
            blockers.append(f"compatibility surface is already a symlink: {path}")
        elif not path.is_dir():
            blockers.append(f"missing/non-directory compatibility surface: {path}")

    return {"ready": not blockers, "blockers": blockers}


def inspect(root: Path) -> dict[str, object]:
    output = root / "Output"
    generations = output / "generations"
    return {
        "root": str(root),
        "output": str(output),
        "surfaces": {
            name: {
                "path": str(output / name),
                "exists": (output / name).exists(),
                "is_symlink": (output / name).is_symlink(),
            }
            for name in SURFACES
        },
        "live_exists": (output / "live").exists(),
        "ledgers": {
            "path": str(output / "ledgers"),
            "exists": (output / "ledgers").exists(),
            "is_symlink": (output / "ledgers").is_symlink(),
        },
        "generations_exists": generations.exists(),
        "migration_journal": {
            "path": str(_journal_path(root)),
            "exists": _journal_path(root).exists() or _journal_path(root).is_symlink(),
        },
    }


def _link_specs(generation_id: str) -> list[dict[str, str]]:
    return [
        {"name": "live", "target": f"generations/{generation_id}"},
        *[
            {"name": name, "target": f"live/{name}"}
            for name in SURFACES
        ],
        {"name": "ledgers", "target": "live/trade_ledger"},
    ]


def _new_journal(root: Path, generation_id: str, generations_created: bool) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA,
        "root": str(root),
        "generation_id": generation_id,
        "phase": "PREPARED",
        "generations_created": generations_created,
        "moved_surfaces": [],
        "created_links": [],
        "links": _link_specs(generation_id),
    }


def _load_journal(root: Path) -> dict[str, Any]:
    path = _journal_path(root)
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"no migration journal found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"migration journal is unreadable: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != JOURNAL_SCHEMA:
        raise RuntimeError(f"unsupported migration journal: {path}")
    if payload.get("root") != str(root):
        raise RuntimeError("migration journal belongs to a different root")
    generation_id = payload.get("generation_id")
    if not isinstance(generation_id, str) or not generation_id or Path(generation_id).name != generation_id:
        raise RuntimeError("migration journal has an unsafe generation_id")
    return payload


def _expected_links(output: Path, payload: dict[str, Any]) -> list[tuple[Path, Path]]:
    links = payload.get("links")
    if not isinstance(links, list):
        raise RuntimeError("migration journal has no link plan")
    expected: list[tuple[Path, Path]] = []
    for item in links:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("target"), str):
            raise RuntimeError("migration journal has an invalid link plan")
        name = Path(item["name"])
        target = Path(item["target"])
        if name.name != item["name"] or target.is_absolute() or ".." in target.parts:
            raise RuntimeError("migration journal link plan escapes Output")
        expected.append((output / name, target))
    return expected


def _remove_expected_links(root: Path, payload: dict[str, Any]) -> None:
    output = root / "Output"
    for link, expected_target in reversed(_expected_links(output, payload)):
        if not link.is_symlink():
            if link.exists():
                # A compatibility surface is a regular legacy directory until
                # its move succeeds.  ``live`` and ``ledgers`` never have a
                # legitimate regular-directory state during recovery.
                if link.name not in SURFACES:
                    raise RuntimeError(f"unexpected non-symlink during migration recovery: {link}")
            continue
        if link.readlink() != expected_target:
            raise RuntimeError(f"unexpected symlink target during migration recovery: {link}")
        link.unlink()


def _rollback(root: Path, payload: dict[str, Any]) -> Path:
    """Roll back a prepared/interrupted migration, failing closed on ambiguity."""

    output = root / "Output"
    generations = output / "generations"
    generation_id = payload["generation_id"]
    target = generations / generation_id
    _remove_expected_links(root, payload)

    for name in reversed(SURFACES):
        source = target / name
        destination = output / name
        source_present = _path_exists(source)
        destination_present = _path_exists(destination)
        if source_present and destination_present:
            raise RuntimeError(f"ambiguous migration recovery state for {name}")
        if source_present:
            os.replace(source, destination)
        elif not destination_present:
            raise RuntimeError(f"missing both source and destination during recovery: {name}")

    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise RuntimeError(f"unsafe migration target during recovery: {target}")
        allowed = set(METADATA_FILES) | set(SURFACES)
        unexpected = [path for path in target.iterdir() if path.name not in allowed]
        if unexpected:
            raise RuntimeError("unexpected files remain in migration target: " + ", ".join(map(str, unexpected)))
        for name in METADATA_FILES:
            metadata = target / name
            if metadata.is_symlink() or metadata.is_dir():
                raise RuntimeError(f"unsafe migration metadata during recovery: {metadata}")
            if metadata.exists():
                metadata.unlink()
        target.rmdir()

    if payload.get("generations_created"):
        if generations.is_symlink() or (generations.exists() and not generations.is_dir()):
            raise RuntimeError(f"unsafe generations directory during recovery: {generations}")
        if generations.exists():
            generations.rmdir()

    journal = _journal_path(root)
    journal.unlink(missing_ok=True)
    for temporary in output.glob(f".{JOURNAL_NAME}.*.tmp"):
        temporary.unlink(missing_ok=True)
    return target


def _finalize_committed(root: Path, payload: dict[str, Any]) -> Path:
    """Remove a journal left after the committed layout is already complete."""

    output = root / "Output"
    target = output / "generations" / payload["generation_id"]
    if not target.is_dir() or target.is_symlink():
        raise RuntimeError(f"committed migration target is missing or unsafe: {target}")
    for name in SURFACES:
        if not (target / name).is_dir():
            raise RuntimeError(f"committed migration surface is missing: {target / name}")
    for link, expected_target in _expected_links(output, payload):
        if not link.is_symlink() or link.readlink() != expected_target:
            raise RuntimeError(f"committed migration link is missing or mismatched: {link}")
    _journal_path(root).unlink()
    for temporary in output.glob(f".{JOURNAL_NAME}.*.tmp"):
        temporary.unlink(missing_ok=True)
    return target


def recover(root: Path) -> Path:
    """Recover a migration interrupted by process termination."""

    payload = _load_journal(root)
    if payload.get("phase") == "COMMITTED":
        return _finalize_committed(root, payload)
    return _rollback(root, payload)


def _move_surface(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def apply(root: Path) -> Path:
    output = root / "Output"
    generations = output / "generations"
    live = output / "live"
    preflight = _preflight(root)
    if not preflight["ready"]:
        blockers = preflight["blockers"]
        raise RuntimeError("migration preflight blocked: " + "; ".join(blockers))

    generation_id = _baseline_id()
    target = generations / generation_id
    journal = _journal_path(root)
    payload = _new_journal(root, generation_id, not generations.exists())
    _create_journal(journal, payload)
    try:
        generations.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=False)
        payload["phase"] = "TARGET_CREATED"
        _write_journal(journal, payload)
        for name in SURFACES:
            _move_surface(output / name, target / name)
            payload["moved_surfaces"].append(name)
            _write_journal(journal, payload)
        (target / "latest_run_id.txt").write_text(generation_id + "\n", encoding="utf-8")
        (target / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "system.generation.v1",
                    "run_id": generation_id,
                    "status": "legacy_imported",
                    "authority": "DIAGNOSTIC_ONLY",
                    "source": "pre_generation_compatibility_surfaces",
                    "surfaces": list(SURFACES),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (target / "admission.json").write_text(
            json.dumps(
                {
                    "schema_version": "system.publish_admission.v1",
                    "run_id": generation_id,
                    "integrity_verdict": "PASS",
                    "publish_integrity_verdict": "PASS",
                    "diagnostic_verdict": "PASS",
                    "diagnostic_publish_verdict": "PASS",
                    "authority_verdict": "DIAGNOSTIC_ONLY",
                    "decision_authority_verdict": "DIAGNOSTIC_ONLY",
                    "generation_id": generation_id,
                    "reason_codes": ["LEGACY_BASELINE_IMPORTED"],
                    "source": "pre_generation_compatibility_surfaces",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        payload["phase"] = "LINKING"
        _write_journal(journal, payload)
        live.symlink_to(Path("generations") / generation_id, target_is_directory=True)
        payload["created_links"].append("live")
        _write_journal(journal, payload)
        for name in SURFACES:
            link = output / name
            link.symlink_to(Path("live") / name, target_is_directory=True)
            payload["created_links"].append(name)
            _write_journal(journal, payload)
        ledgers = output / "ledgers"
        if not ledgers.exists() and not ledgers.is_symlink():
            ledgers.symlink_to(Path("live") / "trade_ledger", target_is_directory=True)
            payload["created_links"].append("ledgers")
            _write_journal(journal, payload)
        payload["phase"] = "COMMITTED"
        _write_journal(journal, payload)
        journal.unlink()
        for temporary in output.glob(f".{JOURNAL_NAME}.*.tmp"):
            temporary.unlink(missing_ok=True)
    except Exception:
        try:
            _rollback(root, payload)
        except Exception as rollback_error:
            raise RuntimeError(
                "migration failed and automatic rollback failed; run --recover"
            ) from rollback_error
        raise
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true", help="inspect only (the default)")
    parser.add_argument("--apply", action="store_true", help="apply the recoverable baseline migration")
    parser.add_argument("--recover", action="store_true", help="roll back or finalize an interrupted migration journal")
    args = parser.parse_args(argv)
    if args.apply and args.recover:
        parser.error("--apply and --recover are mutually exclusive")
    root = args.root.expanduser().resolve()
    state = inspect(root)
    state["preflight"] = _preflight(root)
    print(json.dumps(state, indent=2, ensure_ascii=False))
    if args.recover:
        target = recover(root)
        print(f"Recovered migration state: {target}")
        return 0
    if not args.apply:
        print("DRY RUN — no output surface was changed")
        return 0
    target = apply(root)
    print(f"Applied recoverable baseline migration: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
