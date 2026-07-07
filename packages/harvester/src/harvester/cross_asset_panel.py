"""Cross-asset daily ETF panel — Harvester evidence release dataset.

Builds OHLCV + derived return/volatility columns via EtfYfinanceProvider and
stages cross_asset_daily_panel.parquet into release bundles with manifest,
provenance, and quality report.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from harvester.official import make_manifest, make_provenance
from harvester.quality import build_quality_report, write_quality_report

logger = logging.getLogger(__name__)

DATASET_ID = "cross_asset_daily_panel"
PANEL_COLUMNS = [
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
]


def workspace_root() -> Path:
    """Best-effort workspace root when Harvester runs from System/."""
    cwd = Path.cwd()
    if (cwd / "Data" / "panels").exists() or (cwd / "governance").exists():
        return cwd
    return cwd


def resolve_etf_universe(workspace: Path | None = None) -> list[str]:
    root = workspace or workspace_root()
    config_path = root / "Config" / "data" / "etf_universe.yaml"
    if config_path.is_file():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        symbols: list[str] = []
        for key in ("equity", "sector", "credit", "rates", "dollar_commodity", "thematic"):
            symbols.extend(data.get(key, []) or [])
        extras = data.get("extras", []) or []
        symbols.extend(extras)
        deduped = sorted({str(s).strip() for s in symbols if str(s).strip()})
        if deduped:
            return deduped
    from harvester.providers.etf_yfinance import DEFAULT_ETF_TICKERS

    return sorted(DEFAULT_ETF_TICKERS.keys())


def _drop_invalid_quotes(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove rows with non-positive close prices (bad provider rows)."""
    if frame.empty or "close" not in frame.columns:
        return frame
    return frame[frame["close"].astype(float) > 0].copy()


def load_existing_panel(workspace: Path | None = None) -> pd.DataFrame:
    root = workspace or workspace_root()
    path = root / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    if not path.is_file():
        return pd.DataFrame(columns=PANEL_COLUMNS)
    frame = pd.read_parquet(path)
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"])
    return _drop_invalid_quotes(frame)


def fetch_recent_ohlcv(symbols: list[str], *, period: str = "5d") -> pd.DataFrame:
    from harvester.providers.etf_yfinance import EtfYfinanceProvider

    tickers = {symbol: symbol for symbol in symbols}
    provider = EtfYfinanceProvider(tickers=tickers, period=period)
    results = provider.fetch_series(symbols)

    rows: list[dict[str, Any]] = []
    for result in results:
        if result.frame is None or result.frame.empty:
            continue
        for _, row in result.frame.iterrows():
            rows.append(
                {
                    "date": str(row.get("date", ""))[:10],
                    "symbol": result.series_id,
                    "close": float(row.get("close", 0)),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "volume": float(row.get("volume", 0)),
                }
            )
    if not rows:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    return _drop_invalid_quotes(frame)


def compute_derived_columns(frame: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for symbol, group in frame.groupby("symbol"):
        group = group.sort_values("date").copy()
        close = group["close"].astype(float)
        group["return_1d"] = close.pct_change(1)
        group["return_5d"] = close.pct_change(5)
        group["return_20d"] = close.pct_change(20)
        group["return_60d"] = close.pct_change(60)
        group["volatility_20d"] = close.pct_change(1).rolling(20, min_periods=10).std() * np.sqrt(252)
        rolling_max = close.rolling(60, min_periods=20).max()
        group["drawdown_60d"] = (close - rolling_max) / rolling_max
        parts.append(group)
    if not parts:
        return pd.DataFrame(columns=PANEL_COLUMNS)
    merged = pd.concat(parts, ignore_index=True)
    for column in PANEL_COLUMNS:
        if column not in merged.columns:
            merged[column] = np.nan
    return merged[PANEL_COLUMNS].sort_values(["symbol", "date"]).reset_index(drop=True)


def build_cross_asset_panel(
    *,
    workspace: Path | None = None,
    fetch_period: str = "5d",
) -> pd.DataFrame:
    """Merge workspace history with a fresh provider fetch and derived columns."""
    root = workspace or workspace_root()
    existing = load_existing_panel(root)
    symbols = sorted(set(resolve_etf_universe(root)))
    if existing.empty and not symbols:
        return pd.DataFrame(columns=PANEL_COLUMNS)

    if not symbols and not existing.empty:
        symbols = sorted(existing["symbol"].astype(str).unique())

    fresh = fetch_recent_ohlcv(symbols, period=fetch_period)
    if existing.empty and fresh.empty:
        return pd.DataFrame(columns=PANEL_COLUMNS)

    if existing.empty:
        merged = fresh
    elif fresh.empty:
        merged = existing.copy()
    else:
        fresh_dates = fresh["date"].unique()
        merged = existing[~existing["date"].isin(fresh_dates)]
        merged = pd.concat([merged, fresh], ignore_index=True)

    for column in PANEL_COLUMNS:
        if column not in merged.columns:
            merged[column] = np.nan
    merged = compute_derived_columns(merged)
    return merged


def sync_panel_to_workspace(panel: pd.DataFrame, workspace: Path | None = None) -> Path:
    root = workspace or workspace_root()
    path = root / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(path, index=False)
    return path


def stage_cross_asset_panel(
    release_dir: Path,
    *,
    release_id: str,
    as_of_date: str,
    vintage_date: str,
    workspace: Path | None = None,
    fetch_period: str = "5d",
) -> dict[str, Any]:
    """Build and stage cross_asset_daily_panel into an in-progress release directory."""
    panel = build_cross_asset_panel(workspace=workspace, fetch_period=fetch_period)
    data_dir = release_dir / "data"
    manifests_dir = release_dir / "manifests"
    provenance_dir = release_dir / "provenance"
    for directory in (data_dir, manifests_dir, provenance_dir, release_dir / "quality_reports"):
        directory.mkdir(parents=True, exist_ok=True)

    data_path = data_dir / f"{DATASET_ID}.parquet"
    if panel.empty:
        pd.DataFrame(columns=PANEL_COLUMNS).to_parquet(data_path, index=False)
    else:
        panel.to_parquet(data_path, index=False)

    sha = hashlib.sha256(data_path.read_bytes()).hexdigest()
    size = data_path.stat().st_size
    row_count = len(panel)

    columns = [
        {"name": "date", "dtype": "date", "nullable": False, "description": "Trading date", "semantic_role": "time_index"},
        {"name": "symbol", "dtype": "string", "nullable": False, "description": "ETF ticker", "semantic_role": "category"},
        {"name": "close", "dtype": "float64", "nullable": True, "description": "Close price", "semantic_role": "measure"},
        {"name": "return_1d", "dtype": "float64", "nullable": True, "description": "1-day return", "semantic_role": "measure"},
        {"name": "volatility_20d", "dtype": "float64", "nullable": True, "description": "20-day realized vol", "semantic_role": "measure"},
    ]

    manifest = make_manifest(
        dataset_id=DATASET_ID,
        release_id=release_id,
        as_of_date=as_of_date,
        vintage_date=vintage_date,
        data_path=data_path,
        provider="harvester.providers.etf_yfinance",
        source_url="provider:yfinance",
        columns=columns,
        provenance_path=f"provenance/{DATASET_ID}.provenance.json",
        quality_report_path=f"quality_reports/{DATASET_ID}.quality.json",
        row_count=row_count,
        notes="Cross-asset ETF OHLCV panel for K/X confirmation and feedback loops.",
    )
    manifest["data_file"]["sha256"] = sha
    manifest["data_file"]["byte_size"] = size
    (manifests_dir / f"{DATASET_ID}.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    provenance = make_provenance(
        dataset_id=DATASET_ID,
        release_id=release_id,
        method="api_client",
        source_identifier="harvester.providers.etf_yfinance",
        final_sha256=sha,
        notes="Built from EtfYfinanceProvider with workspace history merge.",
    )
    (provenance_dir / f"{DATASET_ID}.provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    write_quality_report(
        build_quality_report(
            DATASET_ID,
            panel,
            as_of_date=as_of_date,
            required_columns=["date", "symbol", "close"],
            allow_empty=False,
        ),
        release_dir,
        DATASET_ID,
    )

    workspace_path = sync_panel_to_workspace(panel, workspace)
    return {
        "dataset_id": DATASET_ID,
        "data_path": str(data_path),
        "workspace_path": str(workspace_path),
        "row_count": row_count,
        "symbol_count": int(panel["symbol"].nunique()) if not panel.empty else 0,
        "sha256": sha,
    }
