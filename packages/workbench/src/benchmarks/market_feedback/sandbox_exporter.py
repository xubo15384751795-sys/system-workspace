"""Export copied snapshots of market data and deformation features into sandbox_input/.

Reads from canonical release locations and writes COPIES — never symlinks,
never references — into the benchmark's isolated sandbox_input/ directory.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Any, Optional, cast

BENCHMARKS_ROOT = _workspace_root() / "Output" / "benchmarks" / "market_feedback"


def export_sandbox_input(
    benchmark_id: str,
    market_data_release: str,
    deformation_feature_release: str,
    market_panel_source: Optional[Path] = None,
    deformation_features_source: Optional[Path] = None,
    instruments_source: Optional[Path] = None,
    calendar_source: Optional[Path] = None,
) -> Path:
    """Copy market data and deformation features into the sandbox input directory."""
    sandbox_dir = BENCHMARKS_ROOT / benchmark_id / "sandbox_input"
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    files_written = []

    # Market panel
    if market_panel_source and market_panel_source.exists():
        dest = sandbox_dir / "market_panel.parquet"
        shutil.copy2(market_panel_source, dest)
        os.chmod(dest, 0o444)
        files_written.append({
            "path": "market_panel.parquet",
            "source": str(market_panel_source),
            "mode": "copied_snapshot",
        })

    # Deformation features
    if deformation_features_source and deformation_features_source.exists():
        dest = sandbox_dir / "pressure_features.parquet"
        shutil.copy2(deformation_features_source, dest)
        os.chmod(dest, 0o444)
        files_written.append({
            "path": "pressure_features.parquet",
            "source": str(deformation_features_source),
            "mode": "copied_snapshot",
        })

    # Instruments
    if instruments_source and instruments_source.exists():
        dest = sandbox_dir / "instruments.json"
        shutil.copy2(instruments_source, dest)
        os.chmod(dest, 0o444)
        files_written.append({
            "path": "instruments.json",
            "source": str(instruments_source),
            "mode": "copied_snapshot",
        })

    # Calendar
    if calendar_source and calendar_source.exists():
        dest = sandbox_dir / "calendar.json"
        shutil.copy2(calendar_source, dest)
        os.chmod(dest, 0o444)
        files_written.append({
            "path": "calendar.json",
            "source": str(calendar_source),
            "mode": "copied_snapshot",
        })

    # Joined features (if both market + deformation present)
    market_panel = sandbox_dir / "market_panel.parquet"
    deformation_features = sandbox_dir / "pressure_features.parquet"
    if market_panel.exists() and deformation_features.exists():
        _build_joined_features(sandbox_dir)
        files_written.append({
            "path": "joined_features.parquet",
            "source": "sandbox_exporter:broadcast_deformation_over_instruments",
            "mode": "derived",
        })

    # Write sandbox_input_manifest.json
    manifest = {
        "input_id": f"sandbox_input_{benchmark_id}",
        "market_data_release": market_data_release,
        "deformation_feature_release": deformation_feature_release,
        "files": files_written,
        "feature_scope": {
            "deformation_features": "market_level",
            "broadcast_to_instruments": True,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = sandbox_dir / "sandbox_input_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Lock input directory as read-only
    _make_read_only(sandbox_dir)

    return cast(Path, sandbox_dir)


def _build_joined_features(sandbox_dir: Path) -> None:
    """Broadcast market-level deformation features across the instrument axis.

    Deformation features are emitted at the market level (one value per
    date), so each instrument on a given date receives the same feature
    value.  This produces a (date, instrument) panel ready for Qlib's
    Alpha158 + custom-feature pipeline:

        | date | instrument | deform_<feature_1> | deform_<feature_2> | ...

    Output is written as joined_features.parquet with mode 0o444 (read-only),
    matching the rest of the sandbox-input read-only contract.
    """
    import pandas as pd

    market = pd.read_parquet(sandbox_dir / "market_panel.parquet")
    deform = pd.read_parquet(sandbox_dir / "pressure_features.parquet")

    market = _normalize_date_column(market, pd)
    deform = _normalize_date_column(deform, pd)
    if market is None or deform is None:
        return
    market["date"] = pd.to_datetime(market["date"], errors="coerce")
    deform["date"] = pd.to_datetime(deform["date"], errors="coerce")
    market = market.dropna(subset=["date"])
    deform = deform.dropna(subset=["date"])

    deform_value_cols = [
        c for c in deform.columns
        if c not in ("date", "timestamp", "instrument")
    ]
    if not deform_value_cols:
        return

    # Collapse per-date deformation rows to a single observation (mean).
    deform_daily = (
        deform[["date", *deform_value_cols]]
        .groupby("date", as_index=False)
        .mean(numeric_only=True)
    )
    deform_daily = deform_daily.rename(
        columns={c: c if c.startswith("deform_") else f"deform_{c}" for c in deform_value_cols}
    )

    if "instrument" not in market.columns:
        market = market.assign(instrument="_ALL")

    join_keys = ["date", "instrument"]
    base = market[join_keys].drop_duplicates().reset_index(drop=True)
    joined = base.merge(deform_daily, on="date", how="left")

    target = sandbox_dir / "joined_features.parquet"
    if target.exists():
        os.chmod(target, 0o644)
    joined.to_parquet(target, index=False)
    os.chmod(target, 0o444)


def _normalize_date_column(frame, pd):
    """Normalize a named date column or a DatetimeIndex to ``date``."""
    if "date" in frame.columns:
        return frame
    if not isinstance(frame.index, pd.DatetimeIndex):
        return None
    frame = frame.reset_index()
    return frame.rename(columns={frame.columns[0]: "date"})


# Preserved alias for callers that imported the placeholder by name.
_build_joined_features_placeholder = _build_joined_features


def _make_read_only(directory: Path) -> None:
    """Remove write permissions on all files in directory."""
    for f in directory.rglob("*"):
        if f.is_file():
            current = f.stat().st_mode
            f.chmod(current & ~0o222)


def load_sandbox_input_manifest(benchmark_id: str) -> dict[str, Any]:
    path = BENCHMARKS_ROOT / benchmark_id / "sandbox_input" / "sandbox_input_manifest.json"
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
