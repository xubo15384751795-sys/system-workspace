#!/usr/bin/env python3
"""Evaluate Pending — 1d/1w/1m window automatic evaluator.

Reads Output/evaluations/pending.jsonl, checks which evaluation windows
have elapsed, computes actual SPY/HYG/TLT forward returns, classifies
outcome, and writes results back.

Usage:
    python3 scripts/evaluate_pending.py           # evaluate all due records
    python3 scripts/evaluate_pending.py --dry-run  # show what would change
    python3 scripts/evaluate_pending.py --json     # print results as JSON

Output:
    Output/evaluations/pending.jsonl  — updated in place
    Output/evaluations/eval_log.jsonl — append-only audit log
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "Output" / "evaluations"
PENDING_PATH = EVAL_DIR / "pending.jsonl"
EVAL_LOG_PATH = EVAL_DIR / "eval_log.jsonl"
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"

HORIZONS = {"1d": 1, "1w": 5, "1m": 21}  # trading days
ETF_SYMBOLS = ("SPY", "HYG", "TLT")


# ── Market data ──────────────────────────────────────────────────────────────

def load_market_series() -> dict[str, pd.Series]:
    """Load SPY/HYG/TLT close-price series from the ETF panel."""
    if not ETF_PANEL.exists():
        return {}
    etf = pd.read_parquet(ETF_PANEL)
    etf["date"] = pd.to_datetime(etf["date"])
    series: dict[str, pd.Series] = {}
    for symbol in ETF_SYMBOLS:
        part = etf[etf["symbol"] == symbol].sort_values("date").drop_duplicates("date")
        if not part.empty:
            series[symbol] = part.set_index("date")["close"].astype(float)
    return series


def compute_forward_return(
    series: pd.Series, as_of: str, horizon_days: int,
) -> float | None:
    """Compute forward return (%) from as_of over horizon_days trading days."""
    clean = series.dropna().sort_index()
    if clean.empty:
        return None
    as_of_ts = pd.Timestamp(as_of)
    # Match tz-awareness of the index
    if clean.index.tz is not None and as_of_ts.tzinfo is None:
        as_of_ts = as_of_ts.tz_localize("UTC")
    pos = clean.index.searchsorted(as_of_ts, side="left")
    if pos >= len(clean):
        return None
    exit_pos = pos + horizon_days
    if exit_pos >= len(clean):
        return None
    entry = float(clean.iloc[pos])
    exit_ = float(clean.iloc[exit_pos])
    if entry == 0:
        return None
    return round((exit_ / entry - 1.0) * 100.0, 4)


# ── Outcome classification ──────────────────────────────────────────────────

def classify_outcome(
    decision: str, confidence: str, spy_return: float | None,
) -> str:
    """Classify whether the decision was correct given actual market return.

    Returns: "correct", "incorrect", "neutral", or "unverifiable"
    """
    if spy_return is None:
        return "unverifiable"

    # NO_TRADE / WATCH_ONLY: correct if market was flat or down
    if decision in ("NO_TRADE", "WATCH_ONLY"):
        if spy_return <= 0:
            return "correct"  # avoided a down market
        elif spy_return < 0.5:
            return "neutral"  # missed negligible move
        else:
            return "incorrect"  # missed a meaningful up move

    # ACTIVE_WATCH / WATCH: neutral — watching is not a position
    if decision in ("ACTIVE_WATCH", "WATCH"):
        return "neutral"

    # Directional decisions (if any future decision types)
    if decision in ("TACTICAL_LONG", "HEDGE"):
        return "correct" if spy_return > 0 else "incorrect"
    if decision in ("TACTICAL_SHORT", "RISK_REDUCE"):
        return "correct" if spy_return < 0 else "incorrect"

    return "neutral"


# ── Pending record processing ───────────────────────────────────────────────

def load_pending_records() -> list[dict[str, Any]]:
    """Load all records from pending.jsonl."""
    if not PENDING_PATH.exists():
        return []
    records = []
    with PENDING_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save_pending_records(records: list[dict[str, Any]]) -> None:
    """Overwrite pending.jsonl with updated records."""
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with PENDING_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_eval_log(entries: list[dict[str, Any]]) -> None:
    """Append evaluation results to the audit log."""
    if not entries:
        return
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    with EVAL_LOG_PATH.open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _is_due(eval_date_str: str, today: datetime) -> bool:
    """Check if the evaluation window date has passed."""
    try:
        eval_date = datetime.strptime(eval_date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        return today >= eval_date
    except (ValueError, TypeError):
        return False


def evaluate_record(
    record: dict[str, Any],
    market_series: dict[str, pd.Series],
    today: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate a single pending record against market data.

    Returns: (updated_record, log_entries)
    """
    log_entries = []
    evaluations = record.get("evaluations", {"1d": None, "1w": None, "1m": None})
    any_updated = False

    for window in ("1d", "1w", "1m"):
        # Skip if already evaluated
        if evaluations.get(window) is not None:
            continue

        # Check if window is due
        eval_after_key = f"eval_after_{window}"
        eval_after_date = record.get(eval_after_key)
        if not eval_after_date or not _is_due(eval_after_date, today):
            continue

        # Compute actual returns
        date_str = record.get("date", "")
        horizon_days = HORIZONS[window]
        returns: dict[str, Any] = {}
        for symbol, series in market_series.items():
            ret = compute_forward_return(series, date_str, horizon_days)
            returns[symbol] = ret

        spy_return = returns.get("SPY")
        outcome = classify_outcome(
            record.get("decision", "UNKNOWN"),
            record.get("confidence", "unknown"),
            spy_return,
        )

        evaluations[window] = {
            "evaluated_at": today.isoformat(),
            "returns": returns,
            "spy_return_pct": spy_return,
            "outcome": outcome,
        }
        any_updated = True

        log_entries.append({
            "eval_id": record.get("eval_id"),
            "window": window,
            "evaluated_at": today.isoformat(),
            "decision": record.get("decision"),
            "confidence": record.get("confidence"),
            "returns": returns,
            "outcome": outcome,
        })

    if any_updated:
        record["evaluations"] = evaluations
        # Update status: "evaluated" if all windows done, else still "pending"
        all_done = all(evaluations.get(w) is not None for w in ("1d", "1w", "1m"))
        record["status"] = "evaluated" if all_done else "pending"

    return record, log_entries


# ── Main ─────────────────────────────────────────────────────────────────────

def run_evaluation(dry_run: bool = False) -> dict[str, Any]:
    """Run evaluation on all pending records. Returns summary."""
    records = load_pending_records()
    if not records:
        return {"total": 0, "evaluated": 0, "skipped": 0, "message": "No pending records"}

    market_series = load_market_series()
    if not market_series:
        return {"total": len(records), "evaluated": 0, "skipped": len(records),
                "message": "No market data available"}

    today = datetime.now(UTC)
    evaluated_count = 0
    skipped_count = 0
    all_log_entries: list[dict[str, Any]] = []

    updated_records = []
    for record in records:
        if record.get("status") == "evaluated":
            updated_records.append(record)
            skipped_count += 1
            continue

        updated, log_entries = evaluate_record(record, market_series, today)
        updated_records.append(updated)
        if log_entries:
            evaluated_count += len(log_entries)
            all_log_entries.extend(log_entries)
        else:
            skipped_count += 1

    if not dry_run:
        save_pending_records(updated_records)
        append_eval_log(all_log_entries)

    return {
        "total": len(records),
        "evaluated": evaluated_count,
        "skipped": skipped_count,
        "pending_remaining": sum(1 for r in updated_records if r.get("status") == "pending"),
        "evaluated_total": sum(1 for r in updated_records if r.get("status") == "evaluated"),
        "log_entries": all_log_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate pending judgments/trades.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    parser.add_argument("--json", action="store_true", help="Print results as JSON.")
    args = parser.parse_args()

    result = run_evaluation(dry_run=args.dry_run)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Pending evaluation: {result['total']} records")
        print(f"  Windows evaluated: {result['evaluated']}")
        print(f"  Skipped (not due or already done): {result['skipped']}")
        if "pending_remaining" in result:
            print(f"  Pending remaining: {result['pending_remaining']}")
            print(f"  Fully evaluated: {result['evaluated_total']}")


if __name__ == "__main__":
    main()
