from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, cast

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
from src.data.paths import resolve_data_root, resolve_snapshot_store_path
from src.data.snapshot_store_freeze import guard_method as _guard_write


class DuckDBSnapshotStore(SnapshotStoreInterface):
    """
    File-backed snapshot store using DuckDB as system-of-record and Parquet mirrors.
    Writes are idempotent via UPSERT semantics on primary keys.

    LEGACY RUNTIME STORE — retire_after: 2026-10-15.
    Sealed read-only per the 2026-07-07-duckdb-snapshot-store-migration (SEAL phase).
    Write methods are guarded by ALLOW_LEGACY_DUCKDB; canonical store is
    HarvesterSnapshotStore (config snapshot_store.backend=harvester).
    Reads remain permitted for historical query compatibility.
    """

    def __init__(self, path: str | None = None, data_root: str | None = None) -> None:
        try:
            import duckdb  # type: ignore
        except Exception as exc:  # pragma: no cover - explicit runtime failure
            raise RuntimeError("duckdb is required for DuckDBSnapshotStore. Install dependency 'duckdb'.") from exc

        self._duckdb = duckdb
        self.path = Path(path) if path is not None else resolve_snapshot_store_path()
        self.data_root = Path(data_root) if data_root is not None else resolve_data_root()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_dirs()
        self.conn = duckdb.connect(str(self.path))
        self._init_tables()

    @_guard_write
    def save(self, snapshot: Snapshot) -> None:
        payload = self._snapshot_to_payload(snapshot)
        payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True)

        self.conn.execute(
            """
            INSERT INTO snapshots (run_date, run_type, payload_json, created_at, updated_at)
            VALUES (CAST(? AS DATE), ?, ?, now(), now())
            ON CONFLICT(run_date)
            DO UPDATE SET
                run_type = EXCLUDED.run_type,
                payload_json = EXCLUDED.payload_json,
                updated_at = now()
            """,
            [snapshot.run_date, snapshot.run_type, payload_json],
        )

        for proxy_name in ["M", "D", "K", "X"]:
            self.conn.execute(
                """
                INSERT INTO proxy_readings
                    (run_date, proxy_name, value, zscore, direction, components, available)
                VALUES
                    (CAST(? AS DATE), ?, ?, NULL, ?, ?, ?)
                ON CONFLICT(run_date, proxy_name)
                DO UPDATE SET
                    value = EXCLUDED.value,
                    zscore = EXCLUDED.zscore,
                    direction = EXCLUDED.direction,
                    components = EXCLUDED.components,
                    available = EXCLUDED.available
                """,
                [
                    snapshot.run_date,
                    proxy_name,
                    self._proxy_value(snapshot.proxy, proxy_name),
                    str(snapshot.proxy.directions.get(proxy_name, "UNKNOWN")),
                    json.dumps(dict(snapshot.proxy.components), ensure_ascii=True, sort_keys=True),
                    bool(snapshot.proxy.available.get(proxy_name, False)),
                ],
            )

        self.conn.execute(
            """
            INSERT INTO structural_state
                (run_date, sigma_t, singular_flag, leading_channel, pattern, z_vector,
                 reflexivity_flags, operator_diagnostics, belief_state, run_type, anomaly_score, escalation, escalation_reason)
            VALUES
                (CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_date)
            DO UPDATE SET
                sigma_t = EXCLUDED.sigma_t,
                singular_flag = EXCLUDED.singular_flag,
                leading_channel = EXCLUDED.leading_channel,
                pattern = EXCLUDED.pattern,
                z_vector = EXCLUDED.z_vector,
                reflexivity_flags = EXCLUDED.reflexivity_flags,
                operator_diagnostics = EXCLUDED.operator_diagnostics,
                belief_state = EXCLUDED.belief_state,
                run_type = EXCLUDED.run_type,
                anomaly_score = EXCLUDED.anomaly_score,
                escalation = EXCLUDED.escalation,
                escalation_reason = EXCLUDED.escalation_reason
            """,
            [
                snapshot.run_date,
                snapshot.state.sigma_t,
                snapshot.state.singular_flag,
                snapshot.state.leading_channel,
                snapshot.state.pattern,
                json.dumps(snapshot.state.z_vector.tolist(), ensure_ascii=True)
                if snapshot.state.z_vector is not None
                else None,
                json.dumps(dict(snapshot.state.reflexivity_flags), ensure_ascii=True, sort_keys=True),
                json.dumps(
                    snapshot.state.operator_diagnostics.to_dict()
                    if snapshot.state.operator_diagnostics is not None
                    else {},
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                json.dumps(
                    snapshot.state.belief_state.to_dict()
                    if snapshot.state.belief_state is not None
                    else {},
                    ensure_ascii=True,
                    sort_keys=True,
                ),
                snapshot.run_type,
                snapshot.state.anomaly_score,
                snapshot.escalation,
                snapshot.escalation_reason,
            ],
        )

        self._sync_parquet_views()

    @_guard_write
    def save_fast_signal(self, signal: FastSignal) -> None:
        payload_json = json.dumps(signal.to_dict(), ensure_ascii=True, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO fast_signals (date, run_type, payload_json, created_at, updated_at)
            VALUES (CAST(? AS DATE), ?, ?, now(), now())
            ON CONFLICT(date)
            DO UPDATE SET
                run_type = EXCLUDED.run_type,
                payload_json = EXCLUDED.payload_json,
                updated_at = now()
            """,
            [signal.date, signal.run_type, payload_json],
        )
        self._copy_table_to_parquet(
            "fast_signals",
            self.data_root / "processed" / "signals" / "fast_signals.parquet",
            "date",
        )

    def load_fast_signal(self, date: str) -> FastSignal | None:
        row = self.conn.execute(
            "SELECT payload_json FROM fast_signals WHERE date = CAST(? AS DATE)", [date]
        ).fetchone()
        if row is None:
            return None
        return FastSignal.from_dict(json.loads(str(row[0])))

    def load_latest_fast_signal_before(self, date: str, inclusive: bool = True) -> FastSignal | None:
        comparator = "<=" if inclusive else "<"
        row = self.conn.execute(
            f"""
            SELECT payload_json
            FROM fast_signals
            WHERE date {comparator} CAST(? AS DATE)
            ORDER BY date DESC
            LIMIT 1
            """,
            [date],
        ).fetchone()
        if row is None:
            return None
        return FastSignal.from_dict(json.loads(str(row[0])))

    @_guard_write
    def save_cross_validation(self, validation: CrossValidation) -> None:
        payload_json = json.dumps(validation.to_dict(), ensure_ascii=True, sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO cross_validations (date, canonical_date, fast_date, verdict, payload_json, created_at, updated_at)
            VALUES (CAST(? AS DATE), CAST(? AS DATE), CAST(? AS DATE), ?, ?, now(), now())
            ON CONFLICT(date)
            DO UPDATE SET
                canonical_date = EXCLUDED.canonical_date,
                fast_date = EXCLUDED.fast_date,
                verdict = EXCLUDED.verdict,
                payload_json = EXCLUDED.payload_json,
                updated_at = now()
            """,
            [
                validation.date,
                validation.canonical_date,
                validation.fast_date,
                validation.verdict,
                payload_json,
            ],
        )
        self._copy_table_to_parquet(
            "cross_validations",
            self.data_root / "processed" / "signals" / "cross_validations.parquet",
            "date",
        )

    def load_cross_validation(self, date: str) -> CrossValidation | None:
        row = self.conn.execute(
            "SELECT payload_json FROM cross_validations WHERE date = CAST(? AS DATE)", [date]
        ).fetchone()
        if row is None:
            return None
        return CrossValidation.from_dict(json.loads(str(row[0])))

    def load(self, run_date: str) -> Snapshot | None:
        row = self.conn.execute(
            "SELECT payload_json FROM snapshots WHERE run_date = CAST(? AS DATE)", [run_date]
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        return self._payload_to_snapshot(payload)

    def load_range(self, start: str, end: str) -> list[Snapshot]:
        return list(self.iter_range(start, end))

    def iter_range(self, start: str, end: str, batch_size: int = 500) -> Iterator[Snapshot]:
        batch_size = max(1, int(batch_size))
        cursor = self.conn.execute(
            """
            SELECT payload_json
            FROM snapshots
            WHERE run_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            ORDER BY run_date
            """,
            [start, end],
        )
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                payload = json.loads(str(row[0]))
                yield self._payload_to_snapshot(payload)

    def load_latest_before(self, run_date: str) -> Snapshot | None:
        row = self.conn.execute(
            """
            SELECT payload_json
            FROM snapshots
            WHERE run_date < CAST(? AS DATE)
            ORDER BY run_date DESC
            LIMIT 1
            """,
            [run_date],
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        return self._payload_to_snapshot(payload)

    def load_latest_snapshot(
        self,
        run_date: str,
        run_type: str | None = None,
        inclusive: bool = True,
    ) -> Snapshot | None:
        comparator = "<=" if inclusive else "<"
        if run_type is None:
            row = self.conn.execute(
                f"""
                SELECT payload_json
                FROM snapshots
                WHERE run_date {comparator} CAST(? AS DATE)
                ORDER BY run_date DESC
                LIMIT 1
                """,
                [run_date],
            ).fetchone()
        else:
            row = self.conn.execute(
                f"""
                SELECT payload_json
                FROM snapshots
                WHERE run_date {comparator} CAST(? AS DATE)
                  AND run_type = ?
                ORDER BY run_date DESC
                LIMIT 1
                """,
                [run_date, run_type],
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        return self._payload_to_snapshot(payload)

    @_guard_write
    def upsert_raw_series(self, frame: pd.DataFrame, source: str, pulled_at: str) -> None:
        if frame.empty:
            return
        required = {"series_id", "date", "value"}
        if not required.issubset(set(frame.columns)):
            raise ValueError(f"raw_series frame must include columns: {required}")

        for _, row in frame.iterrows():
            self.conn.execute(
                """
                INSERT INTO raw_series (series_id, source, date, value, pulled_at)
                VALUES (?, ?, CAST(? AS DATE), ?, CAST(? AS TIMESTAMP))
                ON CONFLICT(series_id, date)
                DO UPDATE SET
                    source = EXCLUDED.source,
                    value = EXCLUDED.value,
                    pulled_at = EXCLUDED.pulled_at
                """,
                [str(row["series_id"]), source, str(row["date"]), float(row["value"]), pulled_at],
            )
        self._copy_table_to_parquet("raw_series", self.data_root / "raw" / "raw_series.parquet", "series_id, date")

    @_guard_write
    def upsert_event_log(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        for _, row in frame.iterrows():
            self.conn.execute(
                """
                INSERT INTO event_log
                    (event_id, event_date, actor, intervention_type, description,
                     expected_direction, affected_proxy, t30_direction, t60_direction, reflexivity_active)
                VALUES
                    (?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id)
                DO UPDATE SET
                    event_date = EXCLUDED.event_date,
                    actor = EXCLUDED.actor,
                    intervention_type = EXCLUDED.intervention_type,
                    description = EXCLUDED.description,
                    expected_direction = EXCLUDED.expected_direction,
                    affected_proxy = EXCLUDED.affected_proxy,
                    t30_direction = EXCLUDED.t30_direction,
                    t60_direction = EXCLUDED.t60_direction,
                    reflexivity_active = EXCLUDED.reflexivity_active
                """,
                [
                    str(row.get("event_id")),
                    str(row.get("event_date")),
                    str(row.get("actor", "")),
                    str(row.get("intervention_type", "")),
                    str(row.get("description", "")),
                    str(row.get("expected_direction", "")),
                    str(row.get("affected_proxy", "")),
                    str(row.get("t30_direction", "")),
                    str(row.get("t60_direction", "")),
                    bool(row.get("reflexivity_active", False)),
                ],
            )
        self._copy_table_to_parquet("event_log", self.data_root / "processed" / "events" / "event_log.parquet", "event_date")

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

    def _init_tables(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_series (
                series_id VARCHAR,
                source VARCHAR,
                date DATE,
                value DOUBLE,
                pulled_at TIMESTAMP,
                PRIMARY KEY(series_id, date)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proxy_readings (
                run_date DATE,
                proxy_name VARCHAR,
                value DOUBLE,
                zscore DOUBLE,
                direction VARCHAR,
                components JSON,
                available BOOLEAN,
                PRIMARY KEY(run_date, proxy_name)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS structural_state (
                run_date DATE PRIMARY KEY,
                sigma_t DOUBLE,
                singular_flag BOOLEAN,
                leading_channel VARCHAR,
                pattern VARCHAR,
                z_vector JSON,
                reflexivity_flags JSON,
                operator_diagnostics JSON,
                belief_state JSON,
                run_type VARCHAR,
                anomaly_score DOUBLE,
                escalation BOOLEAN,
                escalation_reason VARCHAR
            )
            """
        )
        self._ensure_column("structural_state", "operator_diagnostics", "JSON")
        self._ensure_column("structural_state", "belief_state", "JSON")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_log (
                event_id VARCHAR PRIMARY KEY,
                event_date DATE,
                actor VARCHAR,
                intervention_type VARCHAR,
                description VARCHAR,
                expected_direction VARCHAR,
                affected_proxy VARCHAR,
                t30_direction VARCHAR,
                t60_direction VARCHAR,
                reflexivity_active BOOLEAN
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                run_date DATE PRIMARY KEY,
                run_type VARCHAR,
                payload_json VARCHAR,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fast_signals (
                date DATE PRIMARY KEY,
                run_type VARCHAR,
                payload_json VARCHAR,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cross_validations (
                date DATE PRIMARY KEY,
                canonical_date DATE,
                fast_date DATE,
                verdict VARCHAR,
                payload_json VARCHAR,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )

    def _sync_parquet_views(self) -> None:
        self._copy_table_to_parquet(
            "proxy_readings",
            self.data_root / "processed" / "proxies" / "proxy_readings.parquet",
            "run_date, proxy_name",
        )
        self._copy_table_to_parquet(
            "structural_state",
            self.data_root / "processed" / "state" / "structural_state.parquet",
            "run_date",
        )
        self._copy_table_to_parquet(
            "snapshots",
            self.data_root / "processed" / "snapshots" / "snapshots.parquet",
            "run_date",
        )

    def _copy_table_to_parquet(self, table: str, path: Path, order_clause: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        escaped = str(path).replace("'", "''")
        self.conn.execute(
            f"COPY (SELECT * FROM {table} ORDER BY {order_clause}) TO '{escaped}' (FORMAT PARQUET)"
        )

    def _ensure_column(self, table: str, column: str, dtype: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info('{table}')").fetchall()
        names = {str(row[1]) for row in rows}
        if column not in names:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {dtype}")

    def _proxy_value(self, proxy: ProxyReading, name: str) -> float | None:
        if name == "M":
            return cast(float | None, proxy.M)
        if name == "D":
            return cast(float | None, proxy.D)
        if name == "K":
            return cast(float | None, proxy.K)
        if name == "X":
            return cast(float | None, proxy.X)
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
        # operator_diagnostics is stored as a plain dict for export; drop it when
        # loading so StructuralState receives None (typed OperatorDiagnostics can
        # only be reconstructed by re-running the operator layer).
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


class JsonSnapshotStore(DuckDBSnapshotStore):
    """Backward-compatible alias while storage engine is now DuckDB + Parquet.

    Migration note (2026-07-07-duckdb-snapshot-store-migration): callers that
    want the Harvester-backed Parquet store should select
    config["snapshot_store"]["backend"] = "harvester" (HarvesterSnapshotStore)
    or "dual" (DualWriteSnapshotStore) rather than importing this alias.
    """
