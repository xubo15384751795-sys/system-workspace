from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from system_learning.schema import normalize_event

_write_lock = threading.Lock()


def runtime_log_dir(system_root: Path) -> Path:
    return system_root / "Output" / "system_learning" / "runtime"


def runtime_log_path(system_root: Path, *, day: str | None = None) -> Path:
    day = day or datetime.now(UTC).strftime("%Y-%m-%d")
    return runtime_log_dir(system_root) / f"records_{day}.jsonl"


def append_runtime_record(
    system_root: Path,
    record: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> Path:
    """Append one normalized runtime record — sole write API for peer observations."""
    path = runtime_log_path(system_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = dict(record)
    payload.setdefault("event_id", f"runtime-{uuid.uuid4().hex}")
    payload.setdefault("timestamp", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    normalized = normalize_event(payload, source_path or path)

    line = json.dumps(normalized, ensure_ascii=False, default=str)
    with _write_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return path


def read_runtime_records(
    system_root: Path,
    *,
    limit: int | None = None,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Read recent runtime records (newest files first)."""
    log_dir = runtime_log_dir(system_root)
    if not log_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    paths = sorted(log_dir.glob("records_*.jsonl"), reverse=True)[: max(days, 1)]
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if limit is not None and len(records) >= limit:
                return list(reversed(records))
    return list(reversed(records))
