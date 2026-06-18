"""Feedback Sample Factory — Daily Cron Job.

Run this daily to:
1. Ingest today's real judgment card (if available)
2. Backfill forward outcomes for samples whose windows have matured
3. Auto-label newly evaluable samples
4. Append to Learning Hub if new findings emerge

Designed to be run via cron or launchd:
    python3 scripts/feedback_daily_cron.py

Safe to run multiple times — skips already-computed outcomes.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_scripts
add_scripts()
from _runtime_io import load_json, load_jsonl, utc_now, write_json  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MANIFEST_PATH = ROOT / "Data" / "feedback_samples" / "sample_manifest.jsonl"
REPLAY_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs"
PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
VIX_PATH = ROOT / "Data" / "structural_lab" / "runtime" / "fred_cache" / "VIXCLS.csv"


def _ingest_real_judgments() -> int:
    """Import today's real judgment card if available."""
    try:
        from ingest_real_judgments import ingest
        samples = ingest()
        return len(samples)
    except Exception as e:
        print(f"[WARN] Could not ingest real judgments: {e}")
        return 0


def _backfill_forward_outcomes() -> int:
    """Backfill forward outcomes for samples whose windows have matured."""
    import pandas as pd

    replay_files = sorted(REPLAY_DIR.glob("*.json"))
    if not replay_files:
        return 0

    # Load market data
    panel = pd.read_parquet(PANEL_PATH)
    panel["date"] = pd.to_datetime(panel["date"])
    symbols = sorted(panel["symbol"].unique())
    series_map = {}
    for sym in symbols:
        sub = panel[panel["symbol"] == sym][["date", "close"]].set_index("date")["close"]
        series_map[sym] = sub
    close_matrix = pd.DataFrame(series_map).sort_index()

    vix_series = None
    if VIX_PATH.exists():
        try:
            vix_df = pd.read_csv(VIX_PATH, parse_dates=["DATE"], index_col="DATE")
            vix_series = pd.to_numeric(vix_df.iloc[:, 0], errors="coerce").dropna()
            vix_series.index = pd.to_datetime(vix_series.index)
        except Exception:
            pass

    # Import evaluation functions
    from evaluate_feedback_samples import compute_forward_outcome, auto_label

    updated = 0
    today = pd.Timestamp(utc_now().strftime("%Y-%m-%d"))

    for fpath in replay_files:
        sample = load_json(fpath)
        if not sample:
            continue

        # Check if already fully computed
        fo = sample.get("forward_outcome", {})
        if fo.get("computed_at") and fo.get("max_drawdown_1m") is not None:
            continue

        as_of = pd.Timestamp(sample["as_of_date"])

        # Only compute if at least 63 trading days have passed (3m window)
        days_since = (today - as_of).days
        if days_since < 63:
            continue

        # Compute forward outcomes
        outcome = compute_forward_outcome(sample, close_matrix, vix_series)
        sample["forward_outcome"] = outcome

        # Auto-label
        label, reason = auto_label(sample, outcome)
        sample["review_label"] = label
        sample["auto_label_reason"] = reason

        write_json(fpath, sample)
        updated += 1

    return updated


def main() -> None:
    print(f"[CRON] Feedback daily run at {utc_now().isoformat()}")

    # Step 1: Ingest real judgments
    n_ingested = _ingest_real_judgments()
    print(f"[CRON] Ingested {n_ingested} real judgment(s)")

    # Step 2: Backfill forward outcomes
    n_backfilled = _backfill_forward_outcomes()
    print(f"[CRON] Backfilled {n_backfilled} forward outcome(s)")

    # Step 3: Re-ingest to Learning Hub if anything changed
    if n_ingested > 0 or n_backfilled > 0:
        try:
            from ingest_feedback_to_learning_hub import ingest as lh_ingest
            lh_ingest()
            print("[CRON] Learning Hub updated")
        except Exception as e:
            print(f"[WARN] Learning Hub update failed: {e}")

    print(f"[CRON] Done")


if __name__ == "__main__":
    main()
