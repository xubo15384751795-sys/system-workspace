#!/usr/bin/env python3
"""Trade Decision Replay — calibrate trade decisions against market outcomes.

This script reads trade decisions from the ledger and compares them
with actual market outcomes to assess decision quality.

Usage:
    python3 scripts/trade_decision_replay.py
    python3 scripts/trade_decision_replay.py --json

Output:
    Output/trade_ledger/calibration_report.json
    Output/trade_ledger/calibration_report.md
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "Output" / "trade_ledger" / "decisions.jsonl"
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
BENCHMARK_PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
REPORT_JSON = ROOT / "Output" / "trade_ledger" / "calibration_report.json"
REPORT_MD = ROOT / "Output" / "trade_ledger" / "calibration_report.md"

HORIZONS = {"1d": 1, "1w": 5, "1m": 21}
ETF_SYMBOLS = ("SPY", "HYG", "TLT")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load JSONL file."""
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


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
    positions = clean.index.searchsorted(as_of_ts, side="left")
    if positions >= len(clean):
        return None
    exit_pos = positions + horizon_rows
    if exit_pos >= len(clean):
        return None
    entry_date = clean.index[positions]
    exit_date = clean.index[exit_pos]
    return entry_date, float(clean.iloc[positions]), exit_date, float(clean.iloc[exit_pos])


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
                metric["return_pct"] = round((exit_value / entry_value - 1.0) * 100.0, 4) if entry_value else None
            else:
                metric["change"] = round(exit_value - entry_value, 4)

            horizon_result["metrics"][name] = metric

        if all(m.get("status") == "insufficient_forward_window" for m in horizon_result["metrics"].values()):
            horizon_result["status"] = "skipped_insufficient_forward_window"

        outcomes[horizon] = horizon_result

    return outcomes


def evaluate_decision(
    entry: dict[str, Any],
    market_series: dict[str, pd.Series],
) -> dict[str, Any]:
    """Evaluate a single trade decision against market outcomes."""
    as_of = entry.get("date", "")
    outcomes = compute_forward_outcomes(as_of, market_series)

    evaluated_horizons = [h for h, result in outcomes.items() if result.get("status") == "evaluated"]

    return {
        "date": as_of,
        "decision": entry.get("decision"),
        "confidence": entry.get("confidence"),
        "evidence_grade": entry.get("evidence_grade"),
        "risk_gate_status": entry.get("risk_gate_status"),
        "outcomes": outcomes,
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

    for item in evaluated:
        decision = item.get("decision", "UNKNOWN")
        by_decision[decision] = by_decision.get(decision, 0) + 1

        confidence = item.get("confidence", "unknown")
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1

        spy_metric = (((item.get("outcomes") or {}).get("1w") or {}).get("metrics") or {}).get("SPY") or {}
        if isinstance(spy_metric.get("return_pct"), (int, float)):
            spy_1w_returns.append(float(spy_metric["return_pct"]))

    return {
        "total_decisions": len(evaluations),
        "evaluated_decisions": len(evaluated),
        "skipped_decisions": len(skipped),
        "by_decision": by_decision,
        "by_confidence": by_confidence,
        "avg_spy_1w_return_pct": round(sum(spy_1w_returns) / len(spy_1w_returns), 4) if spy_1w_returns else None,
    }


def build_calibration_report(entries: list[dict[str, Any]], market_series: dict[str, pd.Series]) -> dict[str, Any]:
    """Build complete calibration report."""
    evaluations = [evaluate_decision(entry, market_series) for entry in entries]

    return {
        "schema_version": "trade_decision_calibration.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "horizons": HORIZONS,
        "market_series": sorted(market_series.keys()),
        "summary": summarize_evaluations(evaluations),
        "evaluations": evaluations,
        "notes": [
            "Uses only decisions with elapsed forward windows.",
            "ETF metrics are forward close-to-close returns over trading rows.",
            "VIX/MOVE metrics are absolute index changes over trading rows.",
            "This report calibrates decision quality; it is not a trading signal.",
        ],
    }


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
    args = parser.parse_args()

    # Load ledger entries
    entries = load_jsonl(LEDGER_PATH)
    if not entries:
        print("No trade decisions in ledger.")
        return

    # Load market data
    market_series = load_market_series()

    # Build calibration report
    report = build_calibration_report(entries, market_series)

    # Write report
    paths = write_report(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Calibration report: {paths['markdown']}")
        print(f"Evaluated: {report['summary']['evaluated_decisions']}/{report['summary']['total_decisions']}")
        print(f"By decision: {report['summary']['by_decision']}")
        print(f"Avg SPY 1w return: {report['summary']['avg_spy_1w_return_pct']}")


if __name__ == "__main__":
    main()
