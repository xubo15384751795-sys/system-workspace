from __future__ import annotations

from pathlib import Path

import pandas as pd

# Derived materialized views (rebuilt each run; not append-only source of truth).
DERIVED_LEDGER_FILES = {
    "system_event_ledger": "system_event_ledger.parquet",
    "violation_ledger": "violation_ledger.parquet",
    "event_edges": "event_edges.parquet",
    "improvement_queue": "improvement_queue.parquet",
    "subsystem_health": "subsystem_health.parquet",
}

LEDGER_FILES = DERIVED_LEDGER_FILES


def read_existing_improvement_queue(ledger_dir: Path) -> pd.DataFrame | None:
    path = ledger_dir / DERIVED_LEDGER_FILES["improvement_queue"]
    if not path.exists():
        return None
    return pd.read_parquet(path)


def stamp_ledger_frame(frame: pd.DataFrame, run_id: str) -> pd.DataFrame:
    stamped = frame.copy()
    stamped["generated_by_run"] = run_id
    return stamped


def write_derived_ledgers(
    ledger_dir: Path,
    ledgers: dict[str, pd.DataFrame],
    run_id: str | None = None,
) -> dict[str, Path]:
    ledger_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, filename in DERIVED_LEDGER_FILES.items():
        if name not in ledgers:
            continue
        path = ledger_dir / filename
        frame = stamp_ledger_frame(ledgers[name], run_id) if run_id else ledgers[name]
        frame.to_parquet(path, index=False)
        paths[name] = path
    return paths


def write_ledgers(
    ledger_dir: Path,
    ledgers: dict[str, pd.DataFrame],
    run_id: str | None = None,
) -> dict[str, Path]:
    """Backward-compatible alias for derived ledger writes."""
    return write_derived_ledgers(ledger_dir, ledgers, run_id)
