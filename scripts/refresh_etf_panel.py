#!/usr/bin/env python3
"""Update K features from the admitted ETF panel.

TRANSITIONAL BEHAVIOR:
- This script does NOT fetch ETF prices. Root scripts are not allowed to call
  OpenBB or any external provider directly. ETF acquisition must be implemented
  in Harvester and published as an evidence bundle.
- If the ETF panel is missing, this script logs a WARNING and exits 0 (success).
  This prevents the daily pipeline from false-failing when Harvester hasn't
  produced a panel yet.
- If the K features script (k_features_from_etf.py) is missing, this script
  logs a WARNING and exits 0 (success). The K measurement gate handles the
  missing-data case gracefully.

Usage:
    python3 scripts/refresh_etf_panel.py
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
K_FEATURES_PATH = ROOT / "Data" / "features" / "k_features_daily.csv"


def check_panel() -> bool:
    """Report current ETF panel coverage without acquiring data.

    Returns True if panel exists, False otherwise.
    Does NOT raise — logs warning and returns False if missing.
    """
    if not PANEL_PATH.exists():
        logger.warning(
            "ETF panel not found: %s — "
            "ETF acquisition must run through Harvester before this step can compute features. "
            "Skipping gracefully (no false fail).",
            PANEL_PATH,
        )
        return False

    existing = pd.read_parquet(PANEL_PATH)
    existing["date"] = pd.to_datetime(existing["date"]).dt.normalize()
    symbols = sorted(existing["symbol"].unique())
    last_date = existing["date"].max()
    logger.info("ETF panel: %d rows, %d symbols, last=%s", len(existing), len(symbols), last_date.date())
    logger.info("Acquisition skipped: ETF refresh must be implemented as a Harvester evidence release.")
    return True


def update_k_features() -> bool:
    """Re-run K feature computation via importlib (no exec fallback).

    Returns True if features were updated, False otherwise.
    Does NOT raise on missing script — logs warning and returns False.
    """
    import importlib.util

    script_path = ROOT / "scripts" / "k_features_from_etf.py"
    if not script_path.exists():
        logger.warning(
            "K features script not found: %s — "
            "Skipping K feature recomputation. Script must be added before this step works.",
            script_path,
        )
        return False

    spec = importlib.util.spec_from_file_location("k_features", str(script_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "main"):
        raise AttributeError(
            f"{script_path} has no main() function — "
            "cannot call via importlib.  Add main() to the script."
        )
    mod.main()
    return True


def main() -> int:
    """Entry point. Returns 0 on success (including graceful skip)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("=== ETF Panel Boundary Check ===")
    check_panel()
    logger.info("=== Update K Features ===")
    update_k_features()
    # Verify
    if K_FEATURES_PATH.exists():
        df = pd.read_csv(K_FEATURES_PATH)
        filled = df[df["rv_SPY_20d"].notna()]
        if len(filled) > 0:
            logger.info("K features: %d rows, last filled=%s", len(df), filled["date"].iloc[-1])
        else:
            logger.info("K features: %d rows, no filled data yet", len(df))
    else:
        logger.info("K features file not yet available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
