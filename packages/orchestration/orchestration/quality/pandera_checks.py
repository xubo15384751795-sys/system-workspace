"""Pandera DataFrame models for registry content_freshness clocks.

Governance YAML remains the authority for paths and lag budgets; this module
only encodes table shape + lag evaluation used by freshness_validator.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

try:
    import pandera.pandas as pa
    from pandera.typing import Series
except ImportError:  # pragma: no cover
    pa = None  # type: ignore[assignment]
    Series = Any  # type: ignore[misc,assignment]


ROOT = Path(__file__).resolve().parents[4]


def _load_content_freshness(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    registry_path = root / "governance" / "daily_pipeline_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    rows = registry.get("content_freshness", {}) or {}
    return {str(name): dict(config) for name, config in rows.items() if isinstance(config, dict)}


if pa is not None:

    class DatedPanelSchema(pa.DataFrameModel):
        """Minimal dated panel — column name is validated dynamically."""

        class Config:
            strict = False
            coerce = True


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def evaluate_content_clock(
    name: str,
    config: dict[str, Any],
    *,
    root: Path = ROOT,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Evaluate one content_freshness row with Pandera shape + lag check."""
    as_of = as_of or datetime.now(UTC).date()
    rel = str(config.get("path") or "")
    path = root / rel if rel and not Path(rel).is_absolute() else Path(rel)
    date_column = str(config.get("date_column") or "date")
    max_lag = int(config.get("max_trading_days_behind") or 3)
    decision_critical = bool(config.get("decision_critical", False))

    result: dict[str, Any] = {
        "name": name,
        "path": str(path),
        "date_column": date_column,
        "max_trading_days_behind": max_lag,
        "decision_critical": decision_critical,
        "engine": "pandera",
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
    except Exception as exc:  # noqa: BLE001
        result["status"] = "unreadable"
        result["errors"].append(str(exc))
        return result

    if date_column not in frame.columns:
        result["status"] = "schema_fail"
        result["errors"].append(f"missing_column:{date_column}")
        return result

    if pa is not None:
        schema = pa.DataFrameSchema(
            {date_column: pa.Column(nullable=False)},
            coerce=True,
            strict=False,
        )
        try:
            schema.validate(frame[[date_column]], lazy=True)
        except Exception as exc:  # noqa: BLE001
            result["status"] = "schema_fail"
            result["errors"].append(f"pandera:{exc}")
            return result

    series = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
    series = series.dropna()
    if series.empty:
        result["status"] = "empty"
        result["errors"].append("no_valid_dates")
        return result

    latest = series.max().date()
    lag = (as_of - latest).days
    result["latest_date"] = latest.isoformat()
    result["lag_days"] = int(lag)
    if lag > max_lag:
        result["status"] = "stale"
        result["errors"].append(f"lag_days>{max_lag}")
    else:
        result["status"] = "fresh"
    return result


def evaluate_all_content_clocks(*, root: Path = ROOT, as_of: date | None = None) -> list[dict[str, Any]]:
    clocks = _load_content_freshness(root)
    return [evaluate_content_clock(name, cfg, root=root, as_of=as_of) for name, cfg in clocks.items()]
