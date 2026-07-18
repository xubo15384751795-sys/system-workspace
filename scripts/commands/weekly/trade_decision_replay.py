#!/usr/bin/env python3
"""Trade Decision Replay — calibrate trade decisions against market outcomes.

Reads trade decisions from the ledger and compares them with actual
SPY/HYG/TLT (and VIX/MOVE) forward windows. WATCH / NO_TRADE entries are
kept as counterfactual opportunity-cost samples.

Also writes `market_forward_outcome` back onto ledger rows so daily
accumulation is visible without waiting for claim_evaluator continuity.

Usage:
    python3 scripts/commands/weekly/trade_decision_replay.py
    python3 scripts/commands/weekly/trade_decision_replay.py --since 2026-05-01
    python3 scripts/commands/weekly/trade_decision_replay.py --json

Output:
    Output/trade_ledger/calibration_report.json
    Output/trade_ledger/calibration_report.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._data_paths import resolve_benchmark_panel_path, resolve_cross_asset_panel_path
from scripts._runtime_io import ROOT, load_yaml
from scripts.commands.weekly.backward_pass import build_report as build_backward_report
from scripts.commands.weekly.backward_pass import write_report as write_backward_report
from system_runtime.events import JsonlEventStore

LEDGER_PATH = ROOT / "Output" / "trade_ledger" / "decisions.jsonl"
ETF_PANEL = resolve_cross_asset_panel_path()
BENCHMARK_PANEL = resolve_benchmark_panel_path()
REPORT_JSON = ROOT / "Output" / "trade_ledger" / "calibration_report.json"
REPORT_MD = ROOT / "Output" / "trade_ledger" / "calibration_report.md"

HORIZONS = {"1d": 1, "1w": 5, "1m": 21}
ETF_SYMBOLS = ("SPY", "HYG", "TLT")
COUNTERFACTUAL_DECISIONS = {
    "WATCH",
    "WATCH_ONLY",
    "ACTIVE_WATCH",
    "NO_TRADE",
    "RESEARCH_REVIEW",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL file."""
    return JsonlEventStore(path).read_payloads()


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    JsonlEventStore(path).replace_payloads(
        items,
        event_type="trade_decision_recorded",
        payload_schema="trade_ledger_entry.v2",
        producer="trade_decision_replay",
    )


def load_market_series() -> dict[str, pd.Series]:
    """Load market data for calibration."""
    series: dict[str, pd.Series] = {}

    if ETF_PANEL.exists():
        etf = pd.read_parquet(ETF_PANEL)
        etf["date"] = pd.to_datetime(etf["date"])
        for symbol in ETF_SYMBOLS:
            part = etf[etf["symbol"] == symbol].sort_values("date").drop_duplicates("date")
            if not part.empty:
                series[symbol] = part.set_index("date")["close"].astype(float)

    if BENCHMARK_PANEL.exists():
        panel = pd.read_parquet(BENCHMARK_PANEL)
        panel["date"] = pd.to_datetime(panel["date"])
        for label, series_id in {"VIX": "FRED:VIXCLS", "MOVE": "CBOE:MOVE"}.items():
            part = panel[panel["series_id"] == series_id].sort_values("date").drop_duplicates("date")
            if not part.empty:
                series[label] = part.set_index("date")["value"].astype(float)

    return series


def _entry_and_exit(
    series: pd.Series, as_of: str, horizon_rows: int
) -> tuple[pd.Timestamp, float, pd.Timestamp, float] | None:
    """Get entry and exit points for a horizon."""
    clean = series.dropna().sort_index()
    if clean.empty:
        return None
    as_of_ts = pd.Timestamp(as_of)
    if clean.index.tz is not None and as_of_ts.tzinfo is None:
        as_of_ts = as_of_ts.tz_localize("UTC")
    elif clean.index.tz is None and as_of_ts.tzinfo is not None:
        as_of_ts = as_of_ts.tz_localize(None)
    pos = clean.index.searchsorted(as_of_ts, side="left")
    if pos >= len(clean):
        return None
    exit_pos = pos + horizon_rows
    if exit_pos >= len(clean):
        return None
    entry_date = clean.index[pos]
    exit_date = clean.index[exit_pos]
    return entry_date, float(clean.iloc[pos]), exit_date, float(clean.iloc[exit_pos])


def compute_forward_outcomes(
    as_of: str,
    market_series: dict[str, pd.Series],
) -> dict[str, dict[str, Any]]:
    """Compute forward outcomes for a date."""
    outcomes: dict[str, dict[str, Any]] = {}

    for horizon, rows in HORIZONS.items():
        horizon_result: dict[str, Any] = {"status": "evaluated", "metrics": {}}

        for name, series in market_series.items():
            points = _entry_and_exit(series, as_of, rows)
            if points is None:
                horizon_result["metrics"][name] = {"status": "insufficient_forward_window"}
                continue

            entry_date, entry_value, exit_date, exit_value = points
            metric: dict[str, Any] = {
                "entry_date": entry_date.date().isoformat(),
                "exit_date": exit_date.date().isoformat(),
                "entry_value": round(entry_value, 6),
                "exit_value": round(exit_value, 6),
            }

            if name in ETF_SYMBOLS:
                metric["return_pct"] = (
                    round((exit_value / entry_value - 1.0) * 100.0, 4) if entry_value else None
                )
            else:
                metric["change"] = round(exit_value - entry_value, 4)

            horizon_result["metrics"][name] = metric

        if all(
            m.get("status") == "insufficient_forward_window"
            for m in horizon_result["metrics"].values()
        ):
            horizon_result["status"] = "skipped_insufficient_forward_window"

        outcomes[horizon] = horizon_result

    return outcomes


def _counterfactual_for_decision(
    decision: str,
    outcomes: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if decision not in COUNTERFACTUAL_DECISIONS:
        return None
    by_horizon: dict[str, Any] = {}
    for horizon, result in outcomes.items():
        spy = ((result.get("metrics") or {}).get("SPY") or {})
        ret = spy.get("return_pct")
        by_horizon[horizon] = {
            "spy_return_pct": ret,
            "hyg_return_pct": ((result.get("metrics") or {}).get("HYG") or {}).get("return_pct"),
            "tlt_return_pct": ((result.get("metrics") or {}).get("TLT") or {}).get("return_pct"),
            "status": result.get("status"),
        }
    return {
        "kind": "opportunity_cost_if_long",
        "decision": decision,
        "horizons": by_horizon,
        "note": "Non-action decision recorded as counterfactual market path sample.",
    }


def evaluate_decision(
    entry: dict[str, Any],
    market_series: dict[str, pd.Series],
) -> dict[str, Any]:
    """Evaluate a single trade decision against market outcomes."""
    as_of = entry.get("date", "")
    decision = entry.get("decision")
    outcomes = compute_forward_outcomes(as_of, market_series)
    evaluated_horizons = [h for h, result in outcomes.items() if result.get("status") == "evaluated"]
    counterfactual = _counterfactual_for_decision(str(decision or ""), outcomes)

    return {
        "date": as_of,
        "decision": decision,
        "decision_fingerprint": entry.get("decision_fingerprint"),
        "confidence": entry.get("confidence"),
        "evidence_grade": entry.get("evidence_grade"),
        "risk_gate_status": entry.get("risk_gate_status"),
        "velocity_gate_state": entry.get("velocity_gate_state"),
        "outcomes": outcomes,
        "counterfactual": counterfactual,
        "evaluated_horizons": evaluated_horizons,
        "status": "evaluated" if evaluated_horizons else "skipped_insufficient_forward_window",
    }


def summarize_evaluations(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize calibration results."""
    evaluated = [e for e in evaluations if e["status"] == "evaluated"]
    skipped = [e for e in evaluations if e["status"] != "evaluated"]

    by_decision: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    spy_1w_returns: list[float] = []
    counterfactual_count = 0

    for item in evaluated:
        decision = item.get("decision", "UNKNOWN")
        by_decision[decision] = by_decision.get(decision, 0) + 1
        if item.get("counterfactual"):
            counterfactual_count += 1

        confidence = item.get("confidence", "unknown")
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1

        spy_metric = (((item.get("outcomes") or {}).get("1w") or {}).get("metrics") or {}).get("SPY") or {}
        if isinstance(spy_metric.get("return_pct"), (int, float)):
            spy_1w_returns.append(float(spy_metric["return_pct"]))

    return {
        "total_decisions": len(evaluations),
        "evaluated_decisions": len(evaluated),
        "skipped_decisions": len(skipped),
        "counterfactual_decisions": counterfactual_count,
        "by_decision": by_decision,
        "by_confidence": by_confidence,
        "avg_spy_1w_return_pct": (
            round(sum(spy_1w_returns) / len(spy_1w_returns), 4) if spy_1w_returns else None
        ),
    }


def build_calibration_report(
    entries: list[dict[str, Any]],
    market_series: dict[str, pd.Series],
) -> dict[str, Any]:
    """Build complete calibration report."""
    evaluations = [evaluate_decision(entry, market_series) for entry in entries]

    return {
        "schema_version": "trade_decision_calibration.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "horizons": HORIZONS,
        "market_series": sorted(market_series.keys()),
        "summary": summarize_evaluations(evaluations),
        "evaluations": evaluations,
        "notes": [
            "Uses decisions with at least one elapsed forward window.",
            "ETF metrics are forward close-to-close returns over trading rows.",
            "VIX/MOVE metrics are absolute index changes over trading rows.",
            "WATCH/NO_TRADE are retained as opportunity-cost counterfactual samples.",
            "This report calibrates decision quality; it is not a trading signal.",
        ],
    }


def write_market_outcomes_to_ledger(
    entries: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> int:
    """Attach market_forward_outcome onto matching ledger rows. Returns update count."""
    by_key = {
        (e.get("date"), e.get("decision"), e.get("decision_fingerprint")): e
        for e in evaluations
    }
    updated = 0
    now = datetime.now(UTC).isoformat()
    for entry in entries:
        key = (entry.get("date"), entry.get("decision"), entry.get("decision_fingerprint"))
        # Fingerprint may be absent on older rows — fall back to date+decision first match
        eval_row = by_key.get(key)
        if eval_row is None:
            for e in evaluations:
                if e.get("date") == entry.get("date") and e.get("decision") == entry.get("decision"):
                    eval_row = e
                    break
        if eval_row is None or eval_row.get("status") != "evaluated":
            continue
        entry["market_forward_outcome"] = {
            "evaluated_at": now,
            "status": eval_row["status"],
            "evaluated_horizons": eval_row.get("evaluated_horizons", []),
            "outcomes": eval_row.get("outcomes"),
            "counterfactual": eval_row.get("counterfactual"),
        }
        updated += 1
    return updated


def format_markdown(report: dict[str, Any]) -> str:
    """Format calibration report as markdown."""
    summary = report["summary"]

    lines = [
        "# Trade Decision Calibration Report",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Total decisions: {summary['total_decisions']}",
        f"- Evaluated decisions: {summary['evaluated_decisions']}",
        f"- Skipped decisions: {summary['skipped_decisions']}",
        f"- Counterfactual decisions: {summary.get('counterfactual_decisions', 0)}",
        f"- By decision: {summary['by_decision']}",
        f"- By confidence: {summary['by_confidence']}",
        f"- Avg SPY 1w return: {summary['avg_spy_1w_return_pct']}",
        "",
        "## Evaluations",
        "",
        "| Date | Decision | Confidence | Status | SPY 1d | SPY 1w | SPY 1m | VIX 1w | MOVE 1w |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]

    def fmt_metric(metric: dict[str, Any]) -> str:
        if metric.get("status"):
            return "n/a"
        if "return_pct" in metric:
            return f"{metric['return_pct']:.2f}%"
        if "change" in metric:
            return f"{metric['change']:.2f}"
        return "n/a"

    for item in report["evaluations"]:
        outcomes = item.get("outcomes") or {}
        lines.append(
            "| {date} | {decision} | {confidence} | {status} | {spy1d} | {spy1w} | {spy1m} | {vix1w} | {move1w} |".format(
                date=item.get("date"),
                decision=item.get("decision"),
                confidence=item.get("confidence"),
                status=item.get("status"),
                spy1d=fmt_metric((((outcomes.get("1d") or {}).get("metrics") or {}).get("SPY") or {})),
                spy1w=fmt_metric((((outcomes.get("1w") or {}).get("metrics") or {}).get("SPY") or {})),
                spy1m=fmt_metric((((outcomes.get("1m") or {}).get("metrics") or {}).get("SPY") or {})),
                vix1w=fmt_metric((((outcomes.get("1w") or {}).get("metrics") or {}).get("VIX") or {})),
                move1w=fmt_metric((((outcomes.get("1w") or {}).get("metrics") or {}).get("MOVE") or {})),
            )
        )

    lines += ["", "## Notes", ""]
    lines.extend(f"- {note}" for note in report.get("notes", []))

    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any]) -> dict[str, Path]:
    """Write calibration report."""
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT_MD.write_text(format_markdown(report), encoding="utf-8")
    return {"json": REPORT_JSON, "markdown": REPORT_MD}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run trade decision replay.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument(
        "--since",
        default="2026-05-01",
        help="Only include ledger rows on/after this date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--no-write-ledger",
        action="store_true",
        help="Do not write market_forward_outcome back to decisions.jsonl.",
    )
    args = parser.parse_args()

    entries = load_jsonl(LEDGER_PATH)
    if not entries:
        print("No trade decisions in ledger.")
        return

    if args.since:
        entries = [e for e in entries if str(e.get("date", "")) >= args.since]

    market_series = load_market_series()
    report = build_calibration_report(entries, market_series)
    paths = write_report(report)

    ledger_updates = 0
    ledger_for_learning = load_jsonl(LEDGER_PATH)
    if not args.no_write_ledger:
        # Reload full ledger so we only patch matching rows, preserving others.
        full_ledger = load_jsonl(LEDGER_PATH)
        # Re-evaluate only the filtered subset against full ledger by date+fingerprint
        ledger_updates = write_market_outcomes_to_ledger(full_ledger, report["evaluations"])
        write_jsonl(LEDGER_PATH, full_ledger)
        ledger_for_learning = full_ledger

    backward = build_backward_report(
        ledger_for_learning,
        load_yaml(ROOT / "governance" / "incentive_policy.yaml"),
    )
    write_backward_report(backward)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Calibration report: {paths['markdown']}")
        print(f"Evaluated: {report['summary']['evaluated_decisions']}/{report['summary']['total_decisions']}")
        print(f"Counterfactual: {report['summary'].get('counterfactual_decisions', 0)}")
        print(f"By decision: {report['summary']['by_decision']}")
        print(f"Avg SPY 1w return: {report['summary']['avg_spy_1w_return_pct']}")
        print(f"Ledger market outcomes updated: {ledger_updates}")
        print(f"Backward pass: {backward['status']}")


if __name__ == "__main__":
    main()
