"""Canonical content-clock evaluator.

This module owns content-clock status and delegates table validation to
``pandera_checks`` and session semantics to ``calendar_engine``.  The
freshness validator, Dagster adapter, and quality suite all consume this one
implementation.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from system_runtime.context import RuntimeContext
from orchestration.quality.calendar_engine import (
    DEFAULT_CALENDAR,
    CalendarEngineError,
    sessions_behind,
)
from orchestration.quality.pandera_checks import _read_table, validate_frame



def _load_content_freshness(root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = root or RuntimeContext.current_context().workspace
    registry_path = root / "governance" / "daily_pipeline_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    rows = registry.get("content_freshness", {}) or {}
    return {str(name): dict(config) for name, config in rows.items() if isinstance(config, dict)}


def evaluate_content_clock(
    name: str,
    config: dict[str, Any],
    *,
    root: Path | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Evaluate one registered content clock."""
    root = root or RuntimeContext.current_context().workspace
    as_of = as_of or datetime.now(UTC).date()
    rel = str(config.get("path") or "")
    path = root / rel if rel and not Path(rel).is_absolute() else Path(rel)
    date_column = str(config.get("date_column") or "date")
    max_lag = int(config.get("max_trading_days_behind") or 3)
    decision_critical = bool(config.get("decision_critical", False))
    calendar_name = str(config.get("calendar") or DEFAULT_CALENDAR)

    result: dict[str, Any] = {
        "schema_version": "freshness_result.v1",
        "name": name,
        "path": str(path),
        "date_column": date_column,
        "max_trading_days_behind": max_lag,
        "decision_critical": decision_critical,
        "engine": "pandera",
        "calendar": calendar_name,
        "calendar_engine": "exchange_calendars",
        "status": "missing",
        "lag_days": None,
        "latest_date": None,
        "errors": [],
    }
    if not path.exists():
        result["errors"].append("file_missing")
        return result

    try:
        frame = _read_table(path)
    except Exception as exc:  # noqa: BLE001 - unreadable input is not a PASS
        result["status"] = "unreadable"
        result["errors"].append(str(exc))
        return result

    validation_errors = validate_frame(frame, date_column)
    if validation_errors:
        result["status"] = "schema_fail"
        result["errors"].extend(validation_errors)
        return result

    series = pd.to_datetime(frame[date_column], errors="coerce", utc=True).dropna()
    if series.empty:
        result["status"] = "empty"
        result["errors"].append("no_valid_dates")
        return result

    latest = series.max().date()
    try:
        lag = sessions_behind(latest, as_of, calendar_name=calendar_name)
    except CalendarEngineError as exc:
        result["status"] = "calendar_unavailable"
        result["errors"].append(str(exc))
        return result

    result["latest_date"] = latest.isoformat()
    result["lag_days"] = int(lag)
    result["calendar_days_behind"] = max(0, (as_of - latest).days)
    if lag > max_lag:
        result["status"] = "stale"
        result["errors"].append(f"lag_days>{max_lag}")
    else:
        result["status"] = "fresh"
    return result


def evaluate_all_content_clocks(
    *,
    root: Path | None = None,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    root = root or RuntimeContext.current_context().workspace
    clocks = _load_content_freshness(root)
    return [evaluate_content_clock(name, cfg, root=root, as_of=as_of) for name, cfg in clocks.items()]


def freshness_result_digest(result: dict[str, Any]) -> str:
    """Return the stable digest for one canonical freshness result.

    Adapter-only fields such as an already attached digest are excluded so
    the freshness validator, admission gate, and Dagster adapter can expose
    the same evidence identity without sharing their outer response shape.
    """
    payload = {key: value for key, value in result.items() if key != "result_digest"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def freshness_results_digest(results: list[dict[str, Any]]) -> str:
    """Return a stable digest for an ordered set of freshness checks."""
    entries = [
        {
            "name": str(result.get("name") or ""),
            "result_digest": str(result.get("result_digest") or freshness_result_digest(result)),
        }
        for result in results
    ]
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
