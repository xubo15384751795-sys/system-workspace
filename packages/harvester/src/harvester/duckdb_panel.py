"""Opt-in DuckDB canonical storage for the cross-asset panel.

This is the first storage migration seam.  It is not enabled by default: the
existing Parquet mirror remains the production path until dual-run evidence is
complete.  Every candidate is checked before the DuckDB transaction begins;
the Parquet export is checked again before the existing mirror is replaced.
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
                f"COPY (SELECT * FROM {CANONICAL_TABLE} "
                "ORDER BY symbol, date) TO ? (FORMAT PARQUET)",
                [str(temporary_path)],
            )
            exported = pd.read_parquet(temporary_path)
            exported_report = validate_cross_asset_panel_contract(
                exported,
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
    """Return whether the opt-in canonical writer flag is enabled."""
    return os.environ.get("SYSTEM_DUCKDB_CANONICAL_PANEL", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


__all__ = [
    "CANONICAL_DB_RELATIVE",
    "CANONICAL_TABLE",
    "canonical_panel_db_path",
    "duckdb_canonical_panel_enabled",
    "write_canonical_panel",
]
