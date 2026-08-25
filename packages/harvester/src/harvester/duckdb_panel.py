"""DuckDB canonical storage for the cross-asset panel.

The DuckDB writer is the default storage path after the Wave 2 cutover.  The
existing Parquet file remains a compatibility view and
``SYSTEM_DUCKDB_CANONICAL_PANEL=0`` is the rollback escape hatch. Every
candidate is checked before the DuckDB transaction begins; the Parquet export
is checked again before the existing mirror is replaced.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd

from harvester.quality.data_contract import validate_cross_asset_panel_contract

CANONICAL_DB_RELATIVE = Path("Data/canonical/panels.duckdb")
CANONICAL_TABLE = "cross_asset_daily_panel"
PANEL_COLUMNS = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "volatility_20d",
    "drawdown_60d",
)
_RAW_COLUMNS = ("open", "high", "low", "close", "volume")
_DERIVED_COLUMNS = tuple(column for column in PANEL_COLUMNS if column not in {"date", "symbol", *_RAW_COLUMNS})


def canonical_panel_db_path(workspace: Path) -> Path:
    return workspace / CANONICAL_DB_RELATIVE


def _normalise_for_duckdb(frame: pd.DataFrame) -> pd.DataFrame:
    candidate = frame.copy()
    for column in PANEL_COLUMNS:
        if column not in candidate.columns:
            candidate[column] = pd.NA
    candidate = candidate[list(PANEL_COLUMNS)]
    candidate["date"] = pd.to_datetime(candidate["date"], errors="coerce")
    candidate["symbol"] = candidate["symbol"].astype("string")
    for column in _RAW_COLUMNS + _DERIVED_COLUMNS:
        candidate[column] = pd.to_numeric(
            candidate[column], errors="coerce"
        ).astype("float64")
    return candidate


def _ensure_table(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {CANONICAL_TABLE} (
            date DATE NOT NULL,
            symbol VARCHAR NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            volume DOUBLE NOT NULL,
            return_1d DOUBLE,
            return_5d DOUBLE,
            return_20d DOUBLE,
            return_60d DOUBLE,
            volatility_20d DOUBLE,
            drawdown_60d DOUBLE,
            PRIMARY KEY (symbol, date),
            CHECK (close > 0)
        )
        """
    )


def write_canonical_panel(
    frame: pd.DataFrame,
    *,
    workspace: Path,
    database_path: Path | None = None,
    parquet_path: Path | None = None,
    expected_symbols: Iterable[str] | None = None,
    require_nonempty: bool = True,
) -> dict[str, Any]:
    """Replace the canonical DuckDB snapshot and optionally export Parquet.

    The caller receives an exception before any write when the project
    contract blocks.  A failed insert/export rolls back the DB transaction and
    leaves an existing Parquet mirror untouched.
    """
    report = validate_cross_asset_panel_contract(
        frame,
        expected_symbols=expected_symbols,
        require_nonempty=require_nonempty,
        raise_on_error=True,
    )
    candidate = _normalise_for_duckdb(frame)
    compatibility_date_dtype = candidate["date"].dtype
    db_path = (database_path or canonical_panel_db_path(workspace)).resolve()
    output_path = parquet_path.resolve() if parquet_path is not None else None
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    committed = False
    connection = duckdb.connect(str(db_path))
    try:
        _ensure_table(connection)
        connection.execute("BEGIN TRANSACTION")
        connection.register("_candidate_panel_df", candidate)
        connection.execute(
            "CREATE OR REPLACE TEMP TABLE _panel_staging AS "
            "SELECT * FROM _candidate_panel_df"
        )
        connection.execute(f"DELETE FROM {CANONICAL_TABLE}")
        connection.execute(
            f"INSERT INTO {CANONICAL_TABLE} ({', '.join(PANEL_COLUMNS)}) "
            f"SELECT {', '.join(PANEL_COLUMNS)} FROM _panel_staging"
        )

        exported_report: dict[str, Any] | None = None
        if output_path is not None:
            with tempfile.NamedTemporaryFile(
                dir=output_path.parent,
                prefix=f".{output_path.name}.",
                suffix=".tmp.parquet",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            connection.execute(
                f"COPY (SELECT * REPLACE (CAST(date AS TIMESTAMP) AS date) "
                f"FROM {CANONICAL_TABLE} "
                "ORDER BY symbol, date) TO ? (FORMAT PARQUET)",
                [str(temporary_path)],
            )
            exported = pd.read_parquet(temporary_path)
            # Keep the compatibility view at the input/legacy Parquet
            # timestamp precision. Pandas 2.x commonly uses ns while pandas
            # 3.x commonly uses us; hard-coding either unit makes an otherwise
            # identical key frame fail pandas ``DataFrame.equals`` on one of
            # the supported runtimes. Validate a separate ns-normalized copy
            # because Pandera's contract is about calendar semantics, not the
            # consumer-facing physical timestamp unit.
            exported["date"] = pd.to_datetime(
                exported["date"], errors="coerce"
            ).astype(compatibility_date_dtype)
            exported.to_parquet(temporary_path, index=False)
            exported_for_validation = exported.copy()
            exported_for_validation["date"] = pd.to_datetime(
                exported_for_validation["date"], errors="coerce"
            ).astype("datetime64[ns]")
            exported_report = validate_cross_asset_panel_contract(
                exported_for_validation,
                expected_symbols=expected_symbols,
                require_nonempty=require_nonempty,
                raise_on_error=True,
            )

        connection.execute("COMMIT")
        committed = True
        if output_path is not None and temporary_path is not None:
            os.replace(temporary_path, output_path)
            temporary_path = None
        return {
            "database_path": str(db_path),
            "parquet_path": str(output_path) if output_path is not None else None,
            "table": CANONICAL_TABLE,
            "row_count": int(len(candidate)),
            "data_contract": report,
            "exported_data_contract": exported_report,
        }
    except Exception:
        if not committed:
            try:
                connection.execute("ROLLBACK")
            except duckdb.Error:
                pass
        raise
    finally:
        connection.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def duckdb_canonical_panel_enabled() -> bool:
    """Return whether the canonical DuckDB writer is enabled.

    Defaults to enabled. Set ``SYSTEM_DUCKDB_CANONICAL_PANEL`` to
    0/false/no/off to fall back to the legacy parquet mirror path.
    """
    return os.environ.get("SYSTEM_DUCKDB_CANONICAL_PANEL", "").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def run_offline_parity_drill(
    frame: pd.DataFrame,
    *,
    scratch: Path,
    expected_symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Prove PK/CHECK/rollback in an isolated directory.

    The drill never consults ``SYSTEM_DUCKDB_CANONICAL_PANEL`` and never writes
    the workspace canonical database.  Default launchd storage is unchanged.
    """
    scratch = scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    database_path = scratch / "parity.duckdb"
    parquet_path = scratch / "parity.parquet"
    first = write_canonical_panel(
        frame,
        workspace=scratch,
        database_path=database_path,
        parquet_path=parquet_path,
        expected_symbols=expected_symbols,
        require_nonempty=True,
    )
    before = parquet_path.read_bytes()
    duplicate_rejected = False
    with duckdb.connect(str(database_path)) as connection:
        row = connection.execute(
            f"SELECT date, symbol, open, high, low, close, volume "
            f"FROM {CANONICAL_TABLE} LIMIT 1"
        ).fetchone()
        try:
            connection.execute(
                f"INSERT INTO {CANONICAL_TABLE} "
                "(date, symbol, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                list(row),
            )
        except duckdb.ConstraintException:
            duplicate_rejected = True
    invalid = frame.copy()
    if "close" in invalid.columns and len(invalid):
        invalid.iloc[0, invalid.columns.get_loc("close")] = 0.0
    blocked_without_clobber = False
    try:
        write_canonical_panel(
            invalid,
            workspace=scratch,
            database_path=database_path,
            parquet_path=parquet_path,
            expected_symbols=expected_symbols,
            require_nonempty=True,
        )
    except (ValueError, duckdb.Error):
        blocked_without_clobber = parquet_path.read_bytes() == before
    return {
        "database_path": str(database_path),
        "parquet_path": str(parquet_path),
        "row_count": first["row_count"],
        "data_contract": first["data_contract"],
        "duplicate_rejected": duplicate_rejected,
        "blocked_without_clobber": blocked_without_clobber,
        "canonical_flag_consulted": False,
        "workspace_canonical_written": False,
    }


__all__ = [
    "CANONICAL_DB_RELATIVE",
    "CANONICAL_TABLE",
    "canonical_panel_db_path",
    "duckdb_canonical_panel_enabled",
    "run_offline_parity_drill",
    "write_canonical_panel",
]
