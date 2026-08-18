"""Derived series computation.

Builds TEDRATE replacement proxies and other computed series from acquired
inputs.  Every derived series produces a full provenance trail so it can be
included in a release with the same rigor as acquired series.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from harvester.registry import RegistrySeries

logger = logging.getLogger(__name__)


def build_derived_panel(
    registry_series: list[RegistrySeries],
    acquired_panel: pd.DataFrame,
    *,
    as_of_date: str = "",
    vintage_date: str = "",
) -> pd.DataFrame:
    """Compute all derived series from the acquired panel.

    Returns a DataFrame in canonical benchmark_panel long format.
    """
    frames: list[pd.DataFrame] = []
    for series in registry_series:
        try:
            frame = compute_derived(series, acquired_panel, as_of_date=as_of_date, vintage_date=vintage_date)
            if frame is not None and not frame.empty:
                frames.append(frame)
        except Exception as exc:
            logger.warning(
                "Derived series computation failed for %s: %s",
                getattr(series, "canonical_id", "unknown"),
                type(exc).__name__,
            )
            continue

    if not frames:
        return _empty_derived_panel()

    return pd.concat(frames, ignore_index=True)


def compute_derived(
    series: RegistrySeries,
    acquired_panel: pd.DataFrame,
    *,
    as_of_date: str = "",
    vintage_date: str = "",
) -> pd.DataFrame | None:
    """Compute a single derived series from its formula.

    Alignment strategy: inner join on date. No forward fill.
    """
    if not series.is_derived:
        return None

    formula = series.formula
    inputs = list(series.inputs)

    if len(inputs) < 1:
        return None

    # Extract input series from panel into wide format
    wide = _extract_inputs(inputs, acquired_panel)
    if wide.empty:
        return None

    # Compute the formula
    try:
        result = _eval_formula(formula, inputs, wide)
    except Exception as exc:
        logger.warning(
            "Derived formula evaluation failed for %s: %s",
            series.canonical_id,
            type(exc).__name__,
        )
        return None

    if result is None or result.empty:
        return None

    ts = as_of_date or vintage_date or datetime.now(UTC).strftime("%Y-%m-%d")
    vd = vintage_date or ts

    frame = pd.DataFrame({
        "date": result.index,
        "value": result.values,
        "series_id": f"DERIVED:{series.canonical_id}",
        "source_id": "derived",
        "source_series_id": series.canonical_id,
        "unit": series.unit,
        "frequency": series.frequency,
        "vintage_date": vd,
        "quality_flag": _quality_flag_for_derived(series, acquired_panel, inputs),
    })
    return frame


def build_derived_manifest(
    series: RegistrySeries,
    *,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    data_sha256: str,
    data_byte_size: int,
    row_count: int,
    time_start: str,
    time_end: str,
    provenance_path: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Build a manifest for a derived series."""
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    columns = [
        {"name": "date", "dtype": "date", "nullable": False,
         "description": "Observation date.", "semantic_role": "time_index"},
        {"name": "value", "dtype": "float64", "nullable": True,
         "description": "Observed value.", "semantic_role": "measure"},
        {"name": "series_id", "dtype": "string", "nullable": False,
         "description": f"DERIVED:{series.canonical_id}", "semantic_role": "identifier"},
        {"name": "source_id", "dtype": "string", "nullable": False,
         "description": "derived", "semantic_role": "category"},
        {"name": "source_series_id", "dtype": "string", "nullable": False,
         "description": series.canonical_id, "semantic_role": "identifier"},
        {"name": "unit", "dtype": "string", "nullable": True,
         "description": series.unit, "semantic_role": "metadata"},
        {"name": "frequency", "dtype": "string", "nullable": True,
         "description": series.frequency, "semantic_role": "metadata"},
        {"name": "vintage_date", "dtype": "date", "nullable": True,
         "description": "Date the data was computed.", "semantic_role": "metadata"},
        {"name": "quality_flag", "dtype": "string", "nullable": False,
         "description": "Quality flag.", "semantic_role": "metadata"},
    ]

    return {
        "schema_version": "1.0",
        "dataset_id": series.canonical_id,
        "dataset_revision": 1,
        "release_id": release_id,
        "as_of_date": as_of_date,
        "vintage_date": vintage_date,
        "source": {
            "provider": "derived",
            "kind": "derived",
            "retrieved_at": ts,
            "note": f"Computed: {series.formula}. Synthetic proxy: {series.is_synthetic}.",
        },
        "data_file": {
            "path": f"data/{series.canonical_id}.parquet",
            "format": "parquet",
            "sha256": data_sha256,
            "byte_size": data_byte_size,
            "row_count": row_count,
        },
        "columns": columns,
        "time_coverage": {
            "start": time_start,
            "end": time_end,
            "frequency": series.frequency,
            "time_column": "date",
        },
        "lineage": {
            "provenance_path": provenance_path or f"provenance/{series.canonical_id}.provenance.json",
            "derivation": {
                "formula": series.formula,
                "inputs": list(series.inputs),
                "alignment": "inner_join",
                "synthetic_proxy": series.is_synthetic,
            },
        },
        "notes": notes or f"Derived series: {series.description}",
    }


def build_derived_provenance(
    series: RegistrySeries,
    *,
    release_id: str,
    final_sha256: str,
    input_sha256s: dict[str, str] | None = None,
    observation_start: str | None = None,
    observation_end: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build provenance record for a derived series."""
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    provenance = {
        "schema_version": "1.0",
        "dataset_id": series.canonical_id,
        "dataset_revision": 1,
        "release_id": release_id,
        "acquisition": {
            "method": "computed",
            "source_identifier": f"derived:{series.formula}",
            "started_at": ts,
            "completed_at": ts,
            "operator": "harvester.derived",
        },
        "transformations": [
            {
                "step": series.formula,
                "code_reference": f"harvester.derived.compute_derived({series.canonical_id})",
                "started_at": ts,
                "outcome": "success",
                "params": {
                    "inputs": list(series.inputs),
                    "alignment": "inner_join",
                    "input_sha256s": input_sha256s or {},
                },
            }
        ],
        "checksums": {"final_sha256": final_sha256},
        "notes": notes or f"Derived from: {', '.join(series.inputs)}. Synthetic: {series.is_synthetic}.",
    }
    if observation_start is not None or observation_end is not None:
        if not observation_start or not observation_end:
            raise ValueError("derived observation coverage requires start and end")
        provenance["observation_coverage"] = {
            "start": observation_start,
            "end": observation_end,
            "time_column": "date",
        }
    return provenance


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_inputs(input_ids: list[str], panel: pd.DataFrame) -> pd.DataFrame:
    """Extract input series from panel into wide format (index=date, columns=input_ids)."""
    frames: dict[str, pd.Series] = {}
    for input_id in input_ids:
        matches = panel[panel["source_series_id"] == input_id]
        if matches.empty:
            # Try series_id column
            matches = panel[panel["series_id"].str.contains(input_id, na=False)]
        if matches.empty:
            continue
        ts = matches.set_index("date")["value"]
        ts = ts[~ts.index.duplicated(keep="first")]
        ts.name = input_id
        frames[input_id] = ts

    if not frames:
        return pd.DataFrame()

    wide = pd.concat(frames.values(), axis=1, keys=frames.keys(), join="inner")
    return wide


def _eval_formula(formula: str, inputs: list[str], wide: pd.DataFrame) -> pd.Series | None:
    """Evaluate a simple formula from wide-format input data.

    Supported formulas: "A - B", "A + B", "A * X", "A / B", "ROLL(A,N)"
    """
    if formula.upper().startswith("ROLL(") and formula.endswith(")"):
        return _eval_roll_formula(formula, wide)

    ops = {
        " - ": lambda a, b: a - b,
        " + ": lambda a, b: a + b,
        " * ": lambda a, b: a * b,
        " / ": lambda a, b: a / b,
    }

    for op_str, op_fn in ops.items():
        if op_str in formula:
            parts = formula.split(op_str)
            if len(parts) != 2:
                continue
            left = parts[0].strip()
            right = parts[1].strip()

            if left in wide.columns:
                left_series = wide[left]
            else:
                try:
                    left_series = float(left)
                except ValueError:
                    continue

            if right in wide.columns:
                right_series = wide[right]
            else:
                try:
                    right_series = float(right)
                except ValueError:
                    continue

            result = op_fn(left_series, right_series)
            result = result.dropna()
            result.name = None
            return result.astype(float)

    return None


def _eval_roll_formula(formula: str, wide: pd.DataFrame) -> pd.Series | None:
    args = formula[len("ROLL("):-1].split(",")
    if not args:
        return None
    source = args[0].strip()
    try:
        window = int(args[1].strip()) if len(args) > 1 else 21
    except ValueError:
        window = 21
    if source not in wide.columns:
        return None
    prices = pd.to_numeric(wide[source], errors="coerce").dropna()
    returns = prices.pct_change()
    cov = returns.rolling(window=window, min_periods=max(5, window // 2)).cov(returns.shift(1))
    roll = 2.0 * ((-cov).clip(lower=0.0) ** 0.5)
    roll = roll.replace([float("inf"), float("-inf")], pd.NA).dropna()
    roll.name = None
    return roll.astype(float)


def _quality_flag_for_derived(
    series: RegistrySeries,
    panel: pd.DataFrame,
    inputs: list[str],
) -> str:
    """Determine quality flag for derived series."""
    if series.is_synthetic:
        return "synthetic_proxy"

    missing = []
    for inp in inputs:
        matches = panel[panel["source_series_id"] == inp]
        if matches.empty:
            matches = panel[panel["series_id"].str.contains(inp, na=False)]
        if matches.empty:
            missing.append(inp)
            continue
        if matches["value"].isna().all():
            missing.append(inp)

    if len(missing) == len(inputs):
        return "all_inputs_missing"
    if missing:
        return f"input_missingness: {','.join(missing)}"

    return "derived"


def _empty_derived_panel() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "date", "series_id", "source_id", "source_series_id",
        "value", "unit", "frequency", "vintage_date", "quality_flag",
    ])


__all__ = [
    "build_derived_manifest",
    "build_derived_panel",
    "build_derived_provenance",
    "compute_derived",
]
