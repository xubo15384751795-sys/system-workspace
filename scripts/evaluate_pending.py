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
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from scripts._data_paths import resolve_cross_asset_panel_path
from scripts._runtime_io import ROOT, ensure_dir, load_json, surface_dir, write_jsonl

EVAL_DIR = ROOT / "Output" / "evaluations"
PENDING_PATH = EVAL_DIR / "pending.jsonl"
EVAL_LOG_PATH = EVAL_DIR / "eval_log.jsonl"
ETF_PANEL = resolve_cross_asset_panel_path()
CURRENT_TRADE_DECISION = surface_dir("trade_decision") / "latest.json"

HORIZONS = {"1d": 1, "1w": 5, "1m": 21}  # trading days
ETF_SYMBOLS = ("SPY", "HYG", "TLT")
# Non-action decisions still get market returns as opportunity-cost counterfactuals.
COUNTERFACTUAL_DECISIONS = {
    "WATCH",
    "WATCH_ONLY",
    "ACTIVE_WATCH",
    "NO_TRADE",
    "RESEARCH_REVIEW",
}


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

    WATCH / NO_TRADE / WATCH_ONLY are scored as opportunity-cost counterfactuals:
    staying out of a meaningful rally is incorrect; avoiding a down move is correct.
    """
    del confidence  # reserved for future confidence-weighted scoring
    if spy_return is None:
        return "unverifiable"

    # Non-action / watch decisions: counterfactual vs long-SPY opportunity cost
    if decision in COUNTERFACTUAL_DECISIONS:
        if spy_return <= 0:
            return "correct"  # avoided a flat/down market
        if spy_return < 0.5:
            return "neutral"  # missed negligible move
        return "incorrect"  # missed a meaningful up move

    # Stance spectrum (Phase 4)
    if decision == "RISK_ON":
        return "correct" if spy_return > 0 else "incorrect"
    if decision in ("RISK_OFF", "RISK_REDUCE"):
        return "correct" if spy_return < 0 else "incorrect"

    # Legacy directional labels (pre-Phase 4 ledger rows)
    if decision in ("TACTICAL_LONG", "HEDGE"):
        return "correct" if spy_return > 0 else "incorrect"
    if decision == "TACTICAL_SHORT":
        return "correct" if spy_return < 0 else "incorrect"

    return "neutral"


def build_counterfactual(
    decision: str,
    returns: dict[str, Any],
) -> dict[str, Any] | None:
    """Explicit counterfactual block for non-action decisions."""
    if decision not in COUNTERFACTUAL_DECISIONS:
        return None
    spy = returns.get("SPY")
    if spy is None:
        interpretation = "insufficient_forward_window"
    elif spy > 0.5:
        interpretation = f"if_long_SPY_would_have_gained_{spy:.2f}pct"
    elif spy < -0.5:
        interpretation = f"if_long_SPY_would_have_lost_{abs(spy):.2f}pct"
    else:
        interpretation = "if_long_SPY_near_flat"
    return {
        "kind": "opportunity_cost_if_long",
        "decision": decision,
        "returns": returns,
        "spy_return_pct": spy,
        "interpretation": interpretation,
    }


def _trace_node_values(trace: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {}
    return {
        str(node.get("node_id")): node.get("value")
        for node in trace.get("nodes", [])
        if isinstance(node, dict) and node.get("node_id")
    }


def evaluate_active_inference(
    record: dict[str, Any],
    current_trace: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare the original decision state with the current observable state.

    Only explicit machine-readable conditions are resolved. Free-form
    conditions remain ``UNRESOLVED`` for human review rather than being guessed.
    """
    original = _trace_node_values(record.get("learning_trace"))
    current = _trace_node_values(current_trace)
    if not original:
        return {"status": "NOT_TRACEABLE", "node_changes": [], "condition_checks": []}
    if not current:
        return {"status": "CURRENT_TRACE_UNAVAILABLE", "node_changes": [], "condition_checks": []}

    node_changes = [
        {"node_id": node_id, "original": original[node_id], "current": current.get(node_id)}
        for node_id in sorted(original)
        if node_id in current and original[node_id] != current[node_id]
    ]
    spec = record.get("active_inference_spec") or {}
    conditions = spec.get("invalidation_conditions") or []
    checks = []
    for condition in conditions:
        text = str(condition)
        lower = text.lower()
        resolved = True
        triggered = False
        evidence: Any = None
        if "velocity gate" in lower and "exit" in lower:
            velocity = current.get("velocity_state") or {}
            state = (velocity.get("velocity_gate") or {}).get("state")
            triggered = state == "EXIT"
            evidence = {"velocity_gate_state": state}
        elif "promotion gate" in lower and ("block" in lower or "hard" in lower):
            triggered = current.get("promotion_gate") is True
            evidence = {"promotion_hard_blocked": current.get("promotion_gate")}
        elif "k/x" in lower and "fail" in lower:
            triggered = current.get("k_gate") == "FAIL" or current.get("x_gate") == "FAIL"
            evidence = {"k_gate": current.get("k_gate"), "x_gate": current.get("x_gate")}
        elif "paper" in lower and "stale" in lower:
            triggered = current.get("paper_freshness") is True
            evidence = {"paper_stale": current.get("paper_freshness")}
        else:
            resolved = False
        checks.append({
            "condition": text,
            "status": "TRIGGERED" if resolved and triggered else "CLEAR" if resolved else "UNRESOLVED",
            "evidence": evidence,
        })

    triggered = [check for check in checks if check["status"] == "TRIGGERED"]
    unresolved = [check for check in checks if check["status"] == "UNRESOLVED"]
    status = "INVALIDATED" if triggered else "MANUAL_REVIEW" if unresolved else "TRACKING"
    return {
        "status": status,
        "node_changes": node_changes,
        "condition_checks": checks,
        "watch_conditions": spec.get("watch_conditions") or [],
        "trigger_conditions": spec.get("trigger_conditions") or [],
    }


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


def _pending_identity(record: dict[str, Any]) -> str:
    fingerprint = record.get("observation_fingerprint")
    if fingerprint:
        return str(fingerprint)
    payload = {
        "source": record.get("source"),
        "date": record.get("date"),
        "decision": record.get("decision"),
        "confidence": record.get("confidence"),
        "modules": sorted(record.get("contributing_modules") or []),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def dedupe_pending_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge repeated queue states while preserving completed windows."""
    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _pending_identity(record)
        candidate = dict(record)
        candidate["observation_fingerprint"] = key
        if key not in merged:
            merged[key] = candidate
            continue
        existing = merged[key]
        evaluations = dict(existing.get("evaluations") or {})
        for window, value in (candidate.get("evaluations") or {}).items():
            if value is not None:
                evaluations[window] = value
        # Prefer the newer structured trace/spec, but never discard completed outcomes.
        if candidate.get("learning_trace"):
            existing["learning_trace"] = candidate["learning_trace"]
        if candidate.get("active_inference_spec"):
            existing["active_inference_spec"] = candidate["active_inference_spec"]
        existing["evaluations"] = evaluations
        existing["status"] = (
            "evaluated" if all(evaluations.get(window) is not None for window in HORIZONS) else "pending"
        )
    return list(merged.values())


def save_pending_records(records: list[dict[str, Any]]) -> None:
    """Overwrite pending.jsonl with updated records."""
    ensure_dir(EVAL_DIR)
    write_jsonl(PENDING_PATH, records)


def append_eval_log(entries: list[dict[str, Any]]) -> None:
    """Append evaluation results to the audit log."""
    if not entries:
        return
    ensure_dir(EVAL_DIR)
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
    windows: tuple[str, ...] = ("1d", "1w", "1m"),
    current_trace: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Evaluate a single pending record against market data.

    Args:
        record: Pending evaluation record.
        market_series: SPY/HYG/TLT price series.
        today: Current datetime (UTC).
        windows: Which windows to evaluate. Default all; pass ("1d",) for daily-only.

    Returns: (updated_record, log_entries)
    """
    log_entries = []
    evaluations = record.get("evaluations", {"1d": None, "1w": None, "1m": None})
    any_updated = False

    for window in windows:
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
        decision = record.get("decision", "UNKNOWN")
        outcome = classify_outcome(
            decision,
            record.get("confidence", "unknown"),
            spy_return,
        )
        counterfactual = build_counterfactual(decision, returns)
        active_inference = evaluate_active_inference(record, current_trace)

        evaluations[window] = {
            "evaluated_at": today.isoformat(),
            "returns": returns,
            "spy_return_pct": spy_return,
            "outcome": outcome,
            "counterfactual": counterfactual,
            "active_inference": active_inference,
        }
        any_updated = True

        log_entries.append({
            "eval_id": record.get("eval_id"),
            "source": record.get("source", "unknown"),
            "contributing_modules": record.get("contributing_modules", []),
            "window": window,
            "evaluated_at": today.isoformat(),
            "decision": decision,
            "confidence": record.get("confidence"),
            "returns": returns,
            "outcome": outcome,
            "counterfactual": counterfactual,
            "active_inference": active_inference,
        })

    if any_updated:
        record["evaluations"] = evaluations
        # Update status: "evaluated" if all windows done, else still "pending"
        all_done = all(evaluations.get(w) is not None for w in ("1d", "1w", "1m"))
        record["status"] = "evaluated" if all_done else "pending"

    return record, log_entries


# ── Main ─────────────────────────────────────────────────────────────────────

def run_evaluation(dry_run: bool = False, daily_only: bool = False) -> dict[str, Any]:
    """Run evaluation on all pending records. Returns summary.

    Args:
        dry_run: Show changes without writing.
        daily_only: Only evaluate 1d window (lightweight daily pass).
                    1w/1m windows are evaluated on Monday or --force-weekly.
    """
    raw_records = load_pending_records()
    records = dedupe_pending_records(raw_records)
    if not records:
        return {"total": 0, "raw_total": 0, "evaluated": 0, "skipped": 0, "message": "No pending records"}

    market_series = load_market_series()
    if not market_series:
        return {"total": len(records), "evaluated": 0, "skipped": len(records),
                "message": "No market data available"}

    today = datetime.now(UTC)
    windows = ("1d",) if daily_only else ("1d", "1w", "1m")
    evaluated_count = 0
    skipped_count = 0
    all_log_entries: list[dict[str, Any]] = []
    current_decision = load_json(CURRENT_TRADE_DECISION) or {}
    current_trace = current_decision.get("learning_trace")

    updated_records = []
    for record in records:
        if record.get("status") == "evaluated":
            updated_records.append(record)
            skipped_count += 1
            continue

        updated, log_entries = evaluate_record(
            record,
            market_series,
            today,
            windows=windows,
            current_trace=current_trace,
        )
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
        "raw_total": len(raw_records),
        "duplicates_collapsed": len(raw_records) - len(records),
        "evaluated": evaluated_count,
        "skipped": skipped_count,
        "pending_remaining": sum(1 for r in updated_records if r.get("status") == "pending"),
        "evaluated_total": sum(1 for r in updated_records if r.get("status") == "evaluated"),
        "daily_only": daily_only,
        "windows_evaluated": list(windows),
        "log_entries": all_log_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate pending judgments/trades.")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing.")
    parser.add_argument("--json", action="store_true", help="Print results as JSON.")
    parser.add_argument(
        "--daily-only", action="store_true",
        help="Only evaluate 1d window (lightweight daily pass). "
             "1w/1m windows are evaluated on Monday or --force-weekly.",
    )
    args = parser.parse_args()

    result = run_evaluation(dry_run=args.dry_run, daily_only=args.daily_only)

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
