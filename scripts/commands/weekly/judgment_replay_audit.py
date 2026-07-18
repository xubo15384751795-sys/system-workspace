#!/usr/bin/env python3
"""Judgment replay audit - compare prior judgment cards with later market path.

This is a calibration tool, not a signal generator. It reads historical
judgment cards and market panels, evaluates only windows that have already
elapsed, and writes a report under Output/judgment/.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._data_paths import resolve_benchmark_panel_path, resolve_cross_asset_panel_path
from scripts._runtime_io import ROOT, ensure_dir, load_json, utc_now, write_json

JUDGMENT_DIR = ROOT / "Output" / "judgment"
ETF_PANEL = resolve_cross_asset_panel_path()
BENCHMARK_PANEL = resolve_benchmark_panel_path()
REPORT_JSON = JUDGMENT_DIR / "calibration_report.json"
REPORT_MD = JUDGMENT_DIR / "calibration_report.md"

HORIZONS = {"1d": 1, "1w": 5, "1m": 21}
ETF_SYMBOLS = ("SPY", "HYG", "TLT")
BENCHMARK_SERIES = {"VIX": "FRED:VIXCLS", "MOVE": "CBOE:MOVE"}


def load_judgment_cards(path: Path = JUDGMENT_DIR) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for card_path in sorted(path.glob("*.json")):
        if card_path.name == "latest.json" or not re.match(r"\d{4}-\d{2}-\d{2}\.json$", card_path.name):
            continue
        payload = load_json(card_path)
        if payload:
            payload["_path"] = str(card_path)
            cards.append(payload)
    return cards


def load_market_series(
    etf_panel_path: Path = ETF_PANEL,
    benchmark_panel_path: Path = BENCHMARK_PANEL,
) -> dict[str, pd.Series]:
    series: dict[str, pd.Series] = {}
    if etf_panel_path.exists():
        etf = pd.read_parquet(etf_panel_path)
        etf["date"] = pd.to_datetime(etf["date"])
        for symbol in ETF_SYMBOLS:
            part = etf[etf["symbol"] == symbol].sort_values("date").drop_duplicates("date")
            if not part.empty:
                series[symbol] = part.set_index("date")["close"].astype(float)

    if benchmark_panel_path.exists():
        panel = pd.read_parquet(benchmark_panel_path)
        panel["date"] = pd.to_datetime(panel["date"])
        for label, series_id in BENCHMARK_SERIES.items():
            part = panel[panel["series_id"] == series_id].sort_values("date").drop_duplicates("date")
            if not part.empty:
                series[label] = part.set_index("date")["value"].astype(float)
    return series


def _entry_and_exit(series: pd.Series, as_of: str, horizon_rows: int) -> tuple[pd.Timestamp, float, pd.Timestamp, float] | None:
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
    horizons: dict[str, int] = HORIZONS,
) -> dict[str, dict[str, Any]]:
    outcomes: dict[str, dict[str, Any]] = {}
    for horizon, rows in horizons.items():
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


def _risk_flags(card: dict[str, Any]) -> list[str]:
    return [str(item) for item in card.get("risk", [])]


def _watch_items(card: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for horizon_items in (card.get("watch_window") or {}).values():
        if isinstance(horizon_items, list):
            items.extend(str(item) for item in horizon_items)
    return items


def _gate_status(card: dict[str, Any]) -> dict[str, str]:
    return card.get("gate_status", {})


def evaluate_card(card: dict[str, Any], market_series: dict[str, pd.Series]) -> dict[str, Any]:
    as_of = str(card.get("as_of") or "")[:10]
    outcomes = compute_forward_outcomes(as_of, market_series)
    evaluated_horizons = [h for h, result in outcomes.items() if result.get("status") == "evaluated"]
    return {
        "as_of": as_of,
        "path": card.get("_path"),
        "decision": card.get("decision"),
        "confidence": (card.get("confidence") or {}).get("level"),
        "claim_ceiling": card.get("claim_ceiling"),
        "risk_flags": _risk_flags(card),
        "watch_items": _watch_items(card),
        "gate_status": _gate_status(card),
        "outcomes": outcomes,
        "evaluated_horizons": evaluated_horizons,
        "status": "evaluated" if evaluated_horizons else "skipped_insufficient_forward_window",
    }


def summarize_evaluations(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [e for e in evaluations if e["status"] == "evaluated"]
    skipped = [e for e in evaluations if e["status"] != "evaluated"]
    by_decision: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    spy_1w_returns: list[float] = []

    # Gate status tracking
    gate_failures: dict[str, int] = {}

    # Calibration tables
    confidence_table: dict[str, dict] = {}
    decision_table: dict[str, dict] = {}

    # Invalidation/watch tracking
    invalidation_triggered = 0
    watch_items_triggered = 0
    total_risk_flags = 0

    for item in evaluated:
        decision = item.get("decision") or "UNKNOWN"
        confidence = item.get("confidence") or "unknown"

        by_decision[decision] = by_decision.get(decision, 0) + 1
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1

        spy_metric = (((item.get("outcomes") or {}).get("1w") or {}).get("metrics") or {}).get("SPY") or {}
        vix_metric = (((item.get("outcomes") or {}).get("1w") or {}).get("metrics") or {}).get("VIX") or {}
        hyg_metric = (((item.get("outcomes") or {}).get("1w") or {}).get("metrics") or {}).get("HYG") or {}

        spy_ret = float(spy_metric.get("return_pct", 0)) if isinstance(spy_metric.get("return_pct"), (int, float)) else None
        vix_change = float(vix_metric.get("change", 0)) if isinstance(vix_metric.get("change"), (int, float)) else None
        hyg_ret = float(hyg_metric.get("return_pct", 0)) if isinstance(hyg_metric.get("return_pct"), (int, float)) else None

        if spy_ret is not None:
            spy_1w_returns.append(spy_ret)

        # Build confidence calibration table
        if confidence not in confidence_table:
            confidence_table[confidence] = {"count": 0, "spy_1w_returns": [], "vix_1w_changes": []}
        confidence_table[confidence]["count"] += 1
        if spy_ret is not None:
            confidence_table[confidence]["spy_1w_returns"].append(spy_ret)
        if vix_change is not None:
            confidence_table[confidence]["vix_1w_changes"].append(vix_change)

        # Build decision outcome table
        if decision not in decision_table:
            decision_table[decision] = {"count": 0, "spy_1w_returns": [], "hyg_1w_returns": [], "vix_1w_changes": []}
        decision_table[decision]["count"] += 1
        if spy_ret is not None:
            decision_table[decision]["spy_1w_returns"].append(spy_ret)
        if hyg_ret is not None:
            decision_table[decision]["hyg_1w_returns"].append(hyg_ret)
        if vix_change is not None:
            decision_table[decision]["vix_1w_changes"].append(vix_change)

        # Track gate failures
        gate = item.get("gate_status", {})
        for gate_name, gate_val in gate.items():
            if gate_val and gate_val not in ("PASS", "ADEQUATE", "NOT_AVAILABLE"):
                gate_failures[gate_name] = gate_failures.get(gate_name, 0) + 1

        # Track risk flags
        risk_flags = item.get("risk_flags", [])
        total_risk_flags += len(risk_flags)

    # Finalize confidence table
    confidence_calibration = {}
    for conf, data in confidence_table.items():
        spy_rets = data["spy_1w_returns"]
        vix_changes = data["vix_1w_changes"]
        confidence_calibration[conf] = {
            "count": data["count"],
            "avg_spy_1w": round(sum(spy_rets) / len(spy_rets), 4) if spy_rets else None,
            "avg_vix_1w_change": round(sum(vix_changes) / len(vix_changes), 4) if vix_changes else None,
        }

    # Finalize decision table
    decision_outcomes = {}
    for dec, data in decision_table.items():
        spy_rets = data["spy_1w_returns"]
        hyg_rets = data["hyg_1w_returns"]
        vix_changes = data["vix_1w_changes"]
        decision_outcomes[dec] = {
            "count": data["count"],
            "avg_spy_1w": round(sum(spy_rets) / len(spy_rets), 4) if spy_rets else None,
            "avg_hyg_1w": round(sum(hyg_rets) / len(hyg_rets), 4) if hyg_rets else None,
            "avg_vix_1w_change": round(sum(vix_changes) / len(vix_changes), 4) if vix_changes else None,
        }

    return {
        "total_cards": len(evaluations),
        "evaluated_cards": len(evaluated),
        "skipped_cards": len(skipped),
        "by_decision": by_decision,
        "by_confidence": by_confidence,
        "avg_spy_1w_return_pct": round(sum(spy_1w_returns) / len(spy_1w_returns), 4) if spy_1w_returns else None,
        "gate_failures": gate_failures,
        "confidence_calibration": confidence_calibration,
        "decision_outcomes": decision_outcomes,
        "invalidation_triggered_rate": round(invalidation_triggered / len(evaluated), 4) if evaluated else 0,
        "watch_items_triggered_rate": round(watch_items_triggered / len(evaluated), 4) if evaluated else 0,
        "total_risk_flags": total_risk_flags,
        "avg_risk_flags_per_card": round(total_risk_flags / len(evaluated), 2) if evaluated else 0,
    }


def build_report(cards: list[dict[str, Any]], market_series: dict[str, pd.Series]) -> dict[str, Any]:
    evaluations = [evaluate_card(card, market_series) for card in cards]
    return {
        "schema_version": "system.judgment_calibration.v1",
        "generated_at": utc_now().isoformat(),
        "horizons": HORIZONS,
        "market_series": sorted(market_series.keys()),
        "summary": summarize_evaluations(evaluations),
        "evaluations": evaluations,
        "notes": [
            "Uses only judgment cards with elapsed forward windows.",
            "ETF metrics are forward close-to-close returns over trading rows.",
            "VIX/MOVE metrics are absolute index changes over trading rows.",
            "This report calibrates judgment usefulness; it is not a trading signal.",
        ],
    }


def _fmt_metric(metric: dict[str, Any]) -> str:
    if metric.get("status"):
        return "n/a"
    if "return_pct" in metric:
        val = metric.get("return_pct")
        if val is None:
            return "n/a"
        return f"{float(val):.2f}%"
    if "change" in metric:
        val = metric.get("change")
        if val is None:
            return "n/a"
        return f"{float(val):.2f}"
    return "n/a"


def format_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Judgment Calibration Report",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Total cards: {summary['total_cards']}",
        f"- Evaluated cards: {summary['evaluated_cards']}",
        f"- Skipped cards: {summary['skipped_cards']}",
        f"- Decisions: {summary['by_decision']}",
        f"- Confidence: {summary['by_confidence']}",
        f"- Avg SPY 1w return: {summary['avg_spy_1w_return_pct']}",
        "",
        "## Confidence Calibration",
        "",
        "| Confidence | Count | Avg SPY 1w | Avg VIX 1w Change |",
        "|---|---:|---:|---:|",
    ]

    for conf, data in summary.get("confidence_calibration", {}).items():
        spy = f"{data['avg_spy_1w']:.2f}%" if data.get("avg_spy_1w") is not None else "n/a"
        vix = f"{data['avg_vix_1w_change']:.2f}" if data.get("avg_vix_1w_change") is not None else "n/a"
        lines.append(f"| {conf} | {data['count']} | {spy} | {vix} |")

    lines += [
        "",
        "## Decision Outcomes",
        "",
        "| Decision | Count | Avg SPY 1w | Avg HYG 1w | Avg VIX 1w Change |",
        "|---|---:|---:|---:|---:|",
    ]

    for dec, data in summary.get("decision_outcomes", {}).items():
        spy = f"{data['avg_spy_1w']:.2f}%" if data.get("avg_spy_1w") is not None else "n/a"
        hyg = f"{data['avg_hyg_1w']:.2f}%" if data.get("avg_hyg_1w") is not None else "n/a"
        vix = f"{data['avg_vix_1w_change']:.2f}" if data.get("avg_vix_1w_change") is not None else "n/a"
        lines.append(f"| {dec} | {data['count']} | {spy} | {hyg} | {vix} |")

    lines += [
        "",
        "## Risk & Invalidation",
        "",
        f"- Total risk flags: {summary.get('total_risk_flags', 0)}",
        f"- Avg risk flags per card: {summary.get('avg_risk_flags_per_card', 0)}",
        f"- Invalidation triggered rate: {summary.get('invalidation_triggered_rate', 0):.2%}",
        f"- Watch items triggered rate: {summary.get('watch_items_triggered_rate', 0):.2%}",
        "",
        "## Gate Failures",
        "",
        "| Gate | Failures |",
        "|---|---:|",
    ]

    for gate, count in summary.get("gate_failures", {}).items():
        lines.append(f"| {gate} | {count} |")

    lines += [
        "",
        "## Individual Evaluations",
        "",
        "| Date | Decision | Confidence | Status | SPY 1d | SPY 1w | SPY 1m | VIX 1w | MOVE 1w |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in report["evaluations"]:
        outcomes = item.get("outcomes") or {}
        lines.append(
            "| {date} | {decision} | {confidence} | {status} | {spy1d} | {spy1w} | {spy1m} | {vix1w} | {move1w} |".format(
                date=item.get("as_of"),
                decision=item.get("decision"),
                confidence=item.get("confidence"),
                status=item.get("status"),
                spy1d=_fmt_metric((((outcomes.get("1d") or {}).get("metrics") or {}).get("SPY") or {})),
                spy1w=_fmt_metric((((outcomes.get("1w") or {}).get("metrics") or {}).get("SPY") or {})),
                spy1m=_fmt_metric((((outcomes.get("1m") or {}).get("metrics") or {}).get("SPY") or {})),
                vix1w=_fmt_metric((((outcomes.get("1w") or {}).get("metrics") or {}).get("VIX") or {})),
                move1w=_fmt_metric((((outcomes.get("1w") or {}).get("metrics") or {}).get("MOVE") or {})),
            )
        )
    lines += ["", "## Notes", ""]
    lines.extend(f"- {note}" for note in report.get("notes", []))
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any]) -> dict[str, Path]:
    ensure_dir(JUDGMENT_DIR)
    write_json(REPORT_JSON, report)
    REPORT_MD.write_text(format_markdown(report), encoding="utf-8")
    return {"json": REPORT_JSON, "markdown": REPORT_MD}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit judgment cards against forward market outcomes.")
    parser.add_argument("--json", action="store_true", help="Print report JSON after writing files.")
    args = parser.parse_args()

    cards = load_judgment_cards()
    market_series = load_market_series()
    report = build_report(cards, market_series)
    paths = write_report(report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Calibration report: {paths['markdown']}")
        print(f"Evaluated: {report['summary']['evaluated_cards']}/{report['summary']['total_cards']}")


if __name__ == "__main__":
    main()
