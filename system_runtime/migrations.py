"""Recoverable migrations for legacy JSONL state stores."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .events import JsonlEventStore, envelope_of, is_envelope
from .paths import WorkspacePaths


@dataclass(frozen=True)
class MigrationResult:
    files_scanned: int
    files_changed: int
    records_scanned: int
    legacy_records: int
    backup_root: Path | None


def _known_event_files(paths: WorkspacePaths) -> Iterable[tuple[Path, str, str, str]]:
    yield (
        paths.output / "trade_ledger/decisions.jsonl",
        "trade_decision_recorded",
        "trade_ledger_entry.v2",
        "record_trade_decision",
    )
    patterns = (
        ("runtime_events/*.jsonl", "daily_run_event", "run_event.v1", "daily_run"),
        ("system_learning/events/run_events_*.jsonl", "pipeline_run", "run_event.v1", "record_daily_run_event"),
        (
            "system_learning/events/judgment_calibration_*.jsonl",
            "judgment_calibration",
            "system.judgment_calibration_event.v2",
            "learning_hub_judgment_calibration",
        ),
        (
            "system_learning/events/trade_decision_calibration_*.jsonl",
            "trade_decision_calibration",
            "trade_decision_calibration_event.v1",
            "learning_hub_trade_calibration",
        ),
    )
    for pattern, event_type, schema, producer in patterns:
        for path in sorted(paths.output.glob(pattern)):
            yield path, event_type, schema, producer


def migrate_known_event_stores(
    paths: WorkspacePaths | None = None,
    *,
    apply: bool = False,
) -> MigrationResult:
    paths = paths or WorkspacePaths.discover()
    candidates = [entry for entry in _known_event_files(paths) if entry[0].exists()]
    records_scanned = 0
    legacy_records = 0
    changed: list[tuple[Path, str, str, str, list[dict]]] = []
    for path, event_type, schema, producer in candidates:
        records = list(JsonlEventStore(path).iter_records())
        records_scanned += len(records)
        legacy = sum(1 for record in records if not is_envelope(record))
        legacy_records += legacy
        if legacy:
            changed.append((path, event_type, schema, producer, records))

    backup_root: Path | None = None
    if apply and changed:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_root = paths.output / "archive/schema_migrations" / stamp
        for path, event_type, schema, producer, records in changed:
            relative = path.relative_to(paths.output)
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            events = [
                envelope_of(
                    record,
                    event_type=event_type,
                    payload_schema=schema,
                    producer=producer,
                )
                for record in records
            ]
            JsonlEventStore(path).replace(events)

    return MigrationResult(
        files_scanned=len(candidates),
        files_changed=len(changed),
        records_scanned=records_scanned,
        legacy_records=legacy_records,
        backup_root=backup_root,
    )
