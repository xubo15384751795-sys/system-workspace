from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from system_learning.ledger.store import LEDGER_FILES


def connect_ledgers(ledger_dir: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(database=":memory:")
    register_ledger_views(connection, ledger_dir)
    return connection


def register_ledger_views(connection: duckdb.DuckDBPyConnection, ledger_dir: Path) -> None:
    for table_name, filename in LEDGER_FILES.items():
        path = ledger_dir / filename
        if path.exists():
            parquet_path = str(path).replace("'", "''")
            connection.execute(
                f"CREATE OR REPLACE VIEW {table_name} AS SELECT * FROM read_parquet('{parquet_path}')"
            )


def ledger_summary(ledger_dir: Path) -> dict[str, Any]:
    with connect_ledgers(ledger_dir) as connection:
        return {
            "events": _count(connection, "system_event_ledger"),
            "violations": _count(connection, "violation_ledger"),
            "edges": _count(connection, "event_edges"),
            "improvement_items": _count(connection, "improvement_queue"),
            "subsystems": subsystem_health_summary(connection),
            "top_issues": top_issue_families(connection),
        }


def subsystem_health_summary(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    if not _table_exists(connection, "subsystem_health"):
        return []
    rows = connection.execute(
        """
        SELECT subsystem, health_score, health_band, event_count, violation_count, manual_review_count
        FROM subsystem_health
        ORDER BY health_score ASC, subsystem ASC
        """
    ).fetchall()
    return [
        {
            "subsystem": row[0],
            "health_score": row[1],
            "health_band": row[2],
            "event_count": row[3],
            "violation_count": row[4],
            "manual_review_count": row[5],
        }
        for row in rows
    ]


def top_issue_families(connection: duckdb.DuckDBPyConnection, limit: int = 10) -> list[dict[str, Any]]:
    if not _table_exists(connection, "violation_ledger"):
        return []
    rows = connection.execute(
        """
        SELECT
            issue_family,
            SUM(recurrence_count) AS recurrence_count,
            CASE MAX(
                CASE severity
                    WHEN 'critical' THEN 4
                    WHEN 'high' THEN 3
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 1
                    ELSE 0
                END
            )
                WHEN 4 THEN 'critical'
                WHEN 3 THEN 'high'
                WHEN 2 THEN 'medium'
                WHEN 1 THEN 'low'
                ELSE 'info'
            END AS max_severity
        FROM violation_ledger
        GROUP BY issue_family
        ORDER BY recurrence_count DESC, issue_family ASC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return [
        {"issue_family": row[0], "recurrence_count": int(row[1]), "max_severity": row[2]}
        for row in rows
    ]


def _count(connection: duckdb.DuckDBPyConnection, table_name: str) -> int:
    if not _table_exists(connection, table_name):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def _table_exists(connection: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    return bool(
        connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table_name],
        ).fetchone()[0]
    )
