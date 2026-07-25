"""Harvester-backed snapshot store — Parquet system-of-record.

Replaces the legacy DuckDBSnapshotStore with a Parquet-native store laid out
under a Harvester-governed directory (default Data/harvester/snapshots/).
The ``payload_json`` column in snapshots.parquet is the real system of record
(mirrors the DuckDB design); normalized tables (proxy_readings,
structural_state, fast_signals, cross_validations, raw_series, event_log) are
maintained as separate Parquet files for downstream ML/analytics consumers.

Writes are idempotent via read-merge-write UPSERT semantics on primary keys.
All 13 methods of the duck-typed SnapshotStoreInterface contract are implemented.

Migration: 2026-07-07-duckdb-snapshot-store-migration (FREEZE→MOVE→SEAL).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from src.core.interfaces import SnapshotStoreInterface
from src.core.models import (
    CrossValidation,
    FastSignal,
    MeanFieldGapState,
    NarrativeReading,
    ProxyReading,
    ShadowMassState,
    Snapshot,
    StructuralBeliefState,
    StructuralDiagnosticState,
    StructuralPrimitiveState,
    StructuralState,
)
from src.data.paths import resolve_data_root


def _resolve_harvester_snapshots_root(
    path: str | None = None,
    data_root: str | None = None,
) -> Path:
    """Resolve the Harvester-governed snapshots directory.

    Priority: explicit ``path`` arg > ``data_root/snapshots`` > discovered
    ``Data/harvester/snapshots``.
    """
    if path is not None:
        return Path(path).expanduser()
    if data_root is not None:
        return Path(data_root).expanduser() / "snapshots"
    # Default: Data/harvester/snapshots (Harvester-governed)
    discovered = resolve_data_root()
    # resolve_data_root returns the structural_lab root; climb to Data/ then harvester/
    return discovered.parent / "harvester" / "snapshots"


class HarvesterSnapshotStore(SnapshotStoreInterface):
    """Parquet-backed snapshot store under Harvester governance.

    Layout (all Parquet, idempotent UPSERT on PK):
        <root>/snapshots.parquet          # run_date(PK), run_type, payload_json, created_at, updated_at
        <root>/proxy_readings.parquet     # run_date, proxy_name(PK), value, zscore, direction, components, available
        <root>/structural_state.parquet   # run_date(PK), sigma_t, ...
        <root>/fast_signals.parquet       # date(PK), run_type, payload_json, ...
        <root>/cross_validations.parquet  # date(PK), canonical_date, fast_date, verdict, payload_json, ...
        <root>/raw_series.parquet         # series_id, date(PK), source, value, pulled_at
        <root>/event_log.parquet          # event_id(PK), event_date, actor, ...

    Reads decode Snapshot objects from snapshots.payload_json (same round-trip
    contract as DuckDBSnapshotStore).
    """

    def __init__(self, path: str | None = None, data_root: str | None = None) -> None:
        self.root = _resolve_harvester_snapshots_root(path=path, data_root=data_root)
        self.data_root = Path(data_root) if data_root is not None else resolve_data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_dirs()

    # ------------------------------------------------------------------
    # Snapshot writes / reads (the real system of record)
    # ------------------------------------------------------------------

    def save(self, snapshot: Snapshot) -> None:
        payload = self._snapshot_to_payload(snapshot)
        payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        now = pd.Timestamp.utcnow()

        # snapshots.parquet — UPSERT on run_date
        snapshots_df = self._read_parquet("snapshots")
        new_row = pd.DataFrame(
            [{"run_date": snapshot.run_date, "run_type": snapshot.run_type,
              "payload_json": payload_json, "created_at": now, "updated_at": now}]
        )
        snapshots_df = self._upsert_rows(snapshots_df, new_row, keys=["run_date"])
        self._write_parquet("snapshots", snapshots_df)

        # proxy_readings.parquet — UPSERT on (run_date, proxy_name)
        proxy_rows = []
        for proxy_name in ["M", "D", "K", "X"]:
            proxy_rows.append({
                "run_date": snapshot.run_date,
                "proxy_name": proxy_name,
                "value": self._proxy_value(snapshot.proxy, proxy_name),
                "zscore": None,
                "direction": str(snapshot.proxy.directions.get(proxy_name, "UNKNOWN")),
                "components": json.dumps(dict(snapshot.proxy.components), ensure_ascii=True, sort_keys=True),
                "available": bool(snapshot.proxy.available.get(proxy_name, False)),
            })
        proxy_df = self._read_parquet("proxy_readings")
        proxy_df = self._upsert_rows(proxy_df, pd.DataFrame(proxy_rows), keys=["run_date", "proxy_name"])
        self._write_parquet("proxy_readings", proxy_df)

        # structural_state.parquet — UPSERT on run_date
        state = snapshot.state
        state_row = pd.DataFrame([{
            "run_date": snapshot.run_date,
            "sigma_t": state.sigma_t,
            "singular_flag": state.singular_flag,
            "leading_channel": state.leading_channel,
            "pattern": state.pattern,
            "z_vector": json.dumps(state.z_vector.tolist(), ensure_ascii=True)
            if state.z_vector is not None else None,
            "reflexivity_flags": json.dumps(dict(state.reflexivity_flags), ensure_ascii=True, sort_keys=True),
            "operator_diagnostics": json.dumps(
                state.operator_diagnostics.to_dict() if state.operator_diagnostics is not None else {},
                ensure_ascii=True, sort_keys=True,
            ),
            "belief_state": json.dumps(
                state.belief_state.to_dict() if state.belief_state is not None else {},
                ensure_ascii=True, sort_keys=True,
            ),
            "run_type": snapshot.run_type,
            "anomaly_score": state.anomaly_score,
            "escalation": snapshot.escalation,
            "escalation_reason": snapshot.escalation_reason,
        }])
        state_df = self._read_parquet("structural_state")
        state_df = self._upsert_rows(state_df, state_row, keys=["run_date"])
        self._write_parquet("structural_state", state_df)

    def load(self, run_date: str) -> Snapshot | None:
        df = self._read_parquet("snapshots")
        if df.empty:
            return None
        match = df[df["run_date"] == run_date]
        if match.empty:
            return None
        payload = json.loads(str(match.iloc[0]["payload_json"]))
        return self._payload_to_snapshot(payload)

    def load_range(self, start: str, end: str) -> list[Snapshot]:
        return list(self.iter_range(start, end))

    def iter_range(self, start: str, end: str, batch_size: int = 500) -> Iterator[Snapshot]:
        df = self._read_parquet("snapshots")
        if df.empty:
            return
        mask = (df["run_date"] >= start) & (df["run_date"] <= end)
        subset = df[mask].sort_values("run_date")
        batch_size = max(1, int(batch_size))
        for i in range(0, len(subset), batch_size):
            batch = subset.iloc[i : i + batch_size]
            for _, row in batch.iterrows():
                payload = json.loads(str(row["payload_json"]))
                yield self._payload_to_snapshot(payload)

    def load_latest_before(self, run_date: str) -> Snapshot | None:
        df = self._read_parquet("snapshots")
        if df.empty:
            return None
        subset = df[df["run_date"] < run_date]
        if subset.empty:
            return None
        payload = json.loads(str(subset.sort_values("run_date").iloc[-1]["payload_json"]))
        return self._payload_to_snapshot(payload)

    def load_latest_snapshot(
        self,
        run_date: str,
        run_type: str | None = None,
        inclusive: bool = True,
    ) -> Snapshot | None:
        df = self._read_parquet("snapshots")
        if df.empty:
            return None
        mask = df["run_date"].apply(lambda d: d <= run_date if inclusive else d < run_date)
        subset = df[mask]
        if run_type is not None:
            subset = subset[subset["run_type"] == run_type]
        if subset.empty:
            return None
        payload = json.loads(str(subset.sort_values("run_date").iloc[-1]["payload_json"]))
        return self._payload_to_snapshot(payload)

    # ------------------------------------------------------------------
    # FastSignal / CrossValidation
    # ------------------------------------------------------------------

    def save_fast_signal(self, signal: FastSignal) -> None:
        payload_json = json.dumps(signal.to_dict(), ensure_ascii=True, sort_keys=True)
        now = pd.Timestamp.utcnow()
        df = self._read_parquet("fast_signals")
        new_row = pd.DataFrame([{
            "date": signal.date, "run_type": signal.run_type,
            "payload_json": payload_json, "created_at": now, "updated_at": now,
        }])
        df = self._upsert_rows(df, new_row, keys=["date"])
        self._write_parquet("fast_signals", df)

    def load_fast_signal(self, date: str) -> FastSignal | None:
        df = self._read_parquet("fast_signals")
        if df.empty:
            return None
        match = df[df["date"] == date]
        if match.empty:
            return None
        return FastSignal.from_dict(json.loads(str(match.iloc[0]["payload_json"])))

    def load_latest_fast_signal_before(self, date: str, inclusive: bool = True) -> FastSignal | None:
        df = self._read_parquet("fast_signals")
        if df.empty:
            return None
        mask = df["date"].apply(lambda d: d <= date if inclusive else d < date)
        subset = df[mask]
        if subset.empty:
            return None
        payload = json.loads(str(subset.sort_values("date").iloc[-1]["payload_json"]))
        return FastSignal.from_dict(payload)

    def save_cross_validation(self, validation: CrossValidation) -> None:
        payload_json = json.dumps(validation.to_dict(), ensure_ascii=True, sort_keys=True)
        now = pd.Timestamp.utcnow()
        df = self._read_parquet("cross_validations")
        new_row = pd.DataFrame([{
            "date": validation.date, "canonical_date": validation.canonical_date,
            "fast_date": validation.fast_date, "verdict": validation.verdict,
            "payload_json": payload_json, "created_at": now, "updated_at": now,
        }])
        df = self._upsert_rows(df, new_row, keys=["date"])
        self._write_parquet("cross_validations", df)

    def load_cross_validation(self, date: str) -> CrossValidation | None:
        df = self._read_parquet("cross_validations")
        if df.empty:
            return None
        match = df[df["date"] == date]
        if match.empty:
            return None
        return CrossValidation.from_dict(json.loads(str(match.iloc[0]["payload_json"])))

    # ------------------------------------------------------------------
    # Raw series / event log
    # ------------------------------------------------------------------

    def upsert_raw_series(self, frame: pd.DataFrame, source: str, pulled_at: str) -> None:
        if frame.empty:
            return
        required = {"series_id", "date", "value"}
        if not required.issubset(set(frame.columns)):
            raise ValueError(f"raw_series frame must include columns: {required}")
        df = self._read_parquet("raw_series")
        new_rows = pd.DataFrame({
            "series_id": frame["series_id"].astype(str),
            "source": source,
            "date": frame["date"].astype(str),
            "value": frame["value"].astype(float),
            "pulled_at": pulled_at,
        })
        df = self._upsert_rows(df, new_rows, keys=["series_id", "date"])
        self._write_parquet("raw_series", df)

    def upsert_event_log(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        df = self._read_parquet("event_log")
        new_rows = pd.DataFrame({
            "event_id": frame.get("event_id", "").astype(str),
            "event_date": frame.get("event_date", "").astype(str),
            "actor": frame.get("actor", "").astype(str),
            "intervention_type": frame.get("intervention_type", "").astype(str),
            "description": frame.get("description", "").astype(str),
            "expected_direction": frame.get("expected_direction", "").astype(str),
            "affected_proxy": frame.get("affected_proxy", "").astype(str),
            "t30_direction": frame.get("t30_direction", "").astype(str),
            "t60_direction": frame.get("t60_direction", "").astype(str),
            "reflexivity_active": frame.get("reflexivity_active", False).astype(bool),
        })
        df = self._upsert_rows(df, new_rows, keys=["event_id"])
        self._write_parquet("event_log", df)

    # ------------------------------------------------------------------
    # Parquet I/O helpers
    # ------------------------------------------------------------------

    def _parquet_path(self, table: str) -> Path:
        return self.root / f"{table}.parquet"

    def _read_parquet(self, table: str) -> pd.DataFrame:
        path = self._parquet_path(table)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def _write_parquet(self, table: str, df: pd.DataFrame) -> None:
        path = self._parquet_path(table)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    def _upsert_rows(self, df: pd.DataFrame, new_rows: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        """Idempotent UPSERT: replace rows matching ``keys`` with ``new_rows``."""
        if df.empty:
            return new_rows
        if new_rows.empty:
            return df
        merged = pd.concat([df, new_rows], ignore_index=True)
        # keep last occurrence of each key combo (the new row wins)
        merged = merged.drop_duplicates(subset=keys, keep="last")
        return merged.reset_index(drop=True)

    def _ensure_dirs(self) -> None:
        dirs = [
            self.data_root / "raw" / "fred",
            self.data_root / "raw" / "edgar",
            self.data_root / "raw" / "crunchbase",
            self.data_root / "raw" / "fed_h41",
            self.data_root / "processed" / "proxies",
            self.data_root / "processed" / "state",
            self.data_root / "processed" / "events",
            self.data_root / "processed" / "snapshots",
            self.data_root / "processed" / "signals",
            self.data_root / "calibration" / "thresholds",
            self.data_root / "calibration" / "weights",
        ]
        for p in dirs:
            p.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Snapshot <-> payload (shared with DuckDBSnapshotStore)
    # ------------------------------------------------------------------

    def _proxy_value(self, proxy: ProxyReading, name: str) -> float | None:
        if name == "M":
            return proxy.M
        if name == "D":
            return proxy.D
        if name == "K":
            return proxy.K
        if name == "X":
            return proxy.X
        return None

    def _snapshot_to_payload(self, snapshot: Snapshot) -> dict[str, Any]:
        return {
            "run_date": snapshot.run_date,
            "run_type": snapshot.run_type,
            "proxy": {
                "run_date": snapshot.proxy.run_date,
                "M": snapshot.proxy.M,
                "D": snapshot.proxy.D,
                "K": snapshot.proxy.K,
                "X": snapshot.proxy.X,
                "directions": dict(snapshot.proxy.directions),
                "available": dict(snapshot.proxy.available),
                "components": dict(snapshot.proxy.components),
            },
            "state": {
                "run_date": snapshot.state.run_date,
                "z_vector": snapshot.state.z_vector.tolist() if snapshot.state.z_vector is not None else None,
                "sigma_t": snapshot.state.sigma_t,
                "singular_flag": snapshot.state.singular_flag,
                "structural_singular_time": snapshot.state.structural_singular_time,
                "leading_channel": snapshot.state.leading_channel,
                "pattern": snapshot.state.pattern,
                "anomaly_score": snapshot.state.anomaly_score,
                "reflexivity_flags": dict(snapshot.state.reflexivity_flags),
                "provenance": dict(snapshot.state.provenance),
                "operator_diagnostics": (
                    snapshot.state.operator_diagnostics.to_dict()
                    if snapshot.state.operator_diagnostics is not None
                    else {}
                ),
                "belief_state": (
                    snapshot.state.belief_state.to_dict()
                    if snapshot.state.belief_state is not None
                    else None
                ),
                "primitive_state": (
                    snapshot.state.primitive_state.to_dict()
                    if snapshot.state.primitive_state is not None
                    else None
                ),
                "shadow_mass_state": (
                    snapshot.state.shadow_mass_state.to_dict()
                    if snapshot.state.shadow_mass_state is not None
                    else None
                ),
                "mean_field_gap": (
                    snapshot.state.mean_field_gap.to_dict()
                    if snapshot.state.mean_field_gap is not None
                    else None
                ),
                "diagnostic_state": (
                    snapshot.state.diagnostic_state.to_dict()
                    if snapshot.state.diagnostic_state is not None
                    else None
                ),
            },
            "narrative": (
                {
                    "run_date": snapshot.narrative.run_date,
                    "ai_unicorn": snapshot.narrative.ai_unicorn,
                    "clo_cmbs": snapshot.narrative.clo_cmbs,
                    "policy": snapshot.narrative.policy,
                    "drift_scores": dict(snapshot.narrative.drift_scores),
                }
                if snapshot.narrative is not None
                else None
            ),
            "escalation": snapshot.escalation,
            "escalation_reason": snapshot.escalation_reason,
        }

    def _payload_to_snapshot(self, payload: dict[str, Any]) -> Snapshot:
        proxy = ProxyReading(**payload["proxy"])
        state_payload = dict(payload["state"])
        # operator_diagnostics stored as plain dict; drop on load (typed object
        # only reconstructable by re-running the operator layer).
        state_payload.pop("operator_diagnostics", None)
        belief_payload = state_payload.pop("belief_state", None)
        primitive_payload = state_payload.pop("primitive_state", None)
        shadow_payload = state_payload.pop("shadow_mass_state", None)
        mean_field_payload = state_payload.pop("mean_field_gap", None)
        diagnostic_payload = state_payload.pop("diagnostic_state", None)
        state_payload["z_vector"] = (
            np.array(state_payload["z_vector"], dtype=float) if state_payload["z_vector"] is not None else None
        )
        state_payload["belief_state"] = (
            StructuralBeliefState.from_dict(belief_payload)
            if isinstance(belief_payload, dict) and belief_payload
            else None
        )
        state_payload["primitive_state"] = (
            StructuralPrimitiveState.from_dict(primitive_payload)
            if isinstance(primitive_payload, dict) and primitive_payload
            else None
        )
        state_payload["shadow_mass_state"] = (
            ShadowMassState.from_dict(shadow_payload)
            if isinstance(shadow_payload, dict) and shadow_payload
            else None
        )
        state_payload["mean_field_gap"] = (
            MeanFieldGapState.from_dict(mean_field_payload)
            if isinstance(mean_field_payload, dict) and mean_field_payload
            else None
        )
        state_payload["diagnostic_state"] = (
            StructuralDiagnosticState.from_dict(diagnostic_payload)
            if isinstance(diagnostic_payload, dict) and diagnostic_payload
            else None
        )
        state = StructuralState(**state_payload)
        narrative_payload = payload.get("narrative")
        narrative = NarrativeReading(**narrative_payload) if narrative_payload is not None else None
        return Snapshot(
            run_date=payload["run_date"],
            run_type=payload["run_type"],
            proxy=proxy,
            state=state,
            narrative=narrative,
            escalation=payload["escalation"],
            escalation_reason=payload["escalation_reason"],
        )
