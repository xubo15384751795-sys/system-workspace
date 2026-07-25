"""Shared runtime I/O utilities for main chain scripts.

Avoids duplicating load_json/load_yaml/write_json in every script.
Only serves active pipeline scripts — not archive, experiments, or
Framework internals.

Public API:
    ROOT,
    load_json, load_jsonl, load_yaml, write_json, write_jsonl,
    entry_key, dedupe_entries, as_float,
    utc_now, ensure_dir
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from system_runtime.events import payload_of
from system_runtime.paths import WorkspacePaths

ROOT = WorkspacePaths.discover().root


def current_dir() -> Path:
    """Authority readout directory — candidate during daily run, published after gate."""
    override = os.environ.get("CURRENT_OUTPUT_DIR")
    if override:
        return Path(override)
    return ROOT / "Output" / "current"


def load_json(path: Path) -> dict[str, Any] | None:
    """Load a JSON file, returning None if missing or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file, returning empty list if missing."""
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                entries.append(payload_of(value))
        except json.JSONDecodeError:
            continue
    return entries


def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Atomically write JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=indent, ensure_ascii=False, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_jsonl(path: Path, entries: list[dict[str, Any]]) -> None:
    """Atomically write a list of dicts as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}


def utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def ensure_dir(path: Path) -> Path:
    """Create directory if it doesn't exist, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Trade ledger helpers
# ---------------------------------------------------------------------------

def entry_key(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Compute a deduplication key for a trade ledger entry."""
    thesis = entry.get("trade_thesis") or {}
    claim = ""
    if isinstance(thesis, dict):
        ladder = thesis.get("claim_ladder") or {}
        if isinstance(ladder, dict):
            claim = str(ladder.get("claim_statement", ""))
        claim = claim or str(thesis.get("hypothesis", ""))
    return (
        entry.get("date"),
        entry.get("decision"),
        entry.get("confidence"),
        entry.get("evidence_grade"),
        entry.get("time_horizon"),
        tuple(sorted(entry.get("asset_scope") or [])),
        entry.get("decision_fingerprint") or claim,
    )


def dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the latest record for each observable claim state."""
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for entry in entries:
        deduped[entry_key(entry)] = entry
    return list(deduped.values())


# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------

def as_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce a value to float, returning *default* on failure."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
