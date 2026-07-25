"""Dual-write snapshot store — evidence-window bridge.

Wraps a primary (Harvester) and secondary (legacy DuckDB) snapshot store.
Writes fan out to both backends; reads prefer the Harvester store and fall
back to DuckDB when the Harvester store has no row for the key.

Used during the 2026-07-07-duckdb-snapshot-store-migration evidence window
to verify parity before sealing the DuckDB store read-only.
"""

from __future__ import annotations

from typing import Iterator

import pandas as pd

from src.core.interfaces import SnapshotStoreInterface
from src.core.models import CrossValidation, FastSignal, Snapshot


class DualWriteSnapshotStore(SnapshotStoreInterface):
    """Write-through bridge: harvester (primary) + duckdb (secondary).

    Reads prefer ``primary``; if it returns None for a keyed lookup, the
    ``secondary`` is tried. Range reads merge + de-duplicate by run_date,
    preferring primary rows.
    """

    def __init__(self, primary: SnapshotStoreInterface, secondary: SnapshotStoreInterface) -> None:
        self.primary = primary
        self.secondary = secondary

    # ------------------------------------------------------------------
    # Snapshot writes / reads
    # ------------------------------------------------------------------

    def save(self, snapshot: Snapshot) -> None:
        self.primary.save(snapshot)
        self.secondary.save(snapshot)

    def load(self, run_date: str) -> Snapshot | None:
        result = self.primary.load(run_date)
        if result is not None:
            return result
        return self.secondary.load(run_date)

    def load_range(self, start: str, end: str) -> list[Snapshot]:
        return list(self.iter_range(start, end))

    def iter_range(self, start: str, end: str, batch_size: int = 500) -> Iterator[Snapshot]:
        primary = list(self.primary.iter_range(start, end, batch_size=batch_size))
        primary_dates = {snap.run_date for snap in primary}
        for snap in primary:
            yield snap
        # Yield secondary rows whose run_date is not already covered by primary.
        for snap in self.secondary.iter_range(start, end, batch_size=batch_size):
            if snap.run_date not in primary_dates:
                yield snap

    def load_latest_before(self, run_date: str) -> Snapshot | None:
        result = self.primary.load_latest_before(run_date)
        if result is not None:
            return result
        return self.secondary.load_latest_before(run_date)

    def load_latest_snapshot(
        self,
        run_date: str,
        run_type: str | None = None,
        inclusive: bool = True,
    ) -> Snapshot | None:
        result = self.primary.load_latest_snapshot(run_date, run_type=run_type, inclusive=inclusive)
        if result is not None:
            return result
        return self.secondary.load_latest_snapshot(run_date, run_type=run_type, inclusive=inclusive)

    # ------------------------------------------------------------------
    # FastSignal / CrossValidation
    # ------------------------------------------------------------------

    def save_fast_signal(self, signal: FastSignal) -> None:
        self.primary.save_fast_signal(signal)
        self.secondary.save_fast_signal(signal)

    def load_fast_signal(self, date: str) -> FastSignal | None:
        result = self.primary.load_fast_signal(date)
        if result is not None:
            return result
        return self.secondary.load_fast_signal(date)

    def load_latest_fast_signal_before(self, date: str, inclusive: bool = True) -> FastSignal | None:
        result = self.primary.load_latest_fast_signal_before(date, inclusive=inclusive)
        if result is not None:
            return result
        return self.secondary.load_latest_fast_signal_before(date, inclusive=inclusive)

    def save_cross_validation(self, validation: CrossValidation) -> None:
        self.primary.save_cross_validation(validation)
        self.secondary.save_cross_validation(validation)

    def load_cross_validation(self, date: str) -> CrossValidation | None:
        result = self.primary.load_cross_validation(date)
        if result is not None:
            return result
        return self.secondary.load_cross_validation(date)

    # ------------------------------------------------------------------
    # Raw series / event log
    # ------------------------------------------------------------------

    def upsert_raw_series(self, frame: pd.DataFrame, source: str, pulled_at: str) -> None:
        self.primary.upsert_raw_series(frame, source, pulled_at)
        self.secondary.upsert_raw_series(frame, source, pulled_at)

    def upsert_event_log(self, frame: pd.DataFrame) -> None:
        self.primary.upsert_event_log(frame)
        self.secondary.upsert_event_log(frame)
