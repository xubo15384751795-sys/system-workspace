#!/usr/bin/env python3
"""Overlay shadow report — base strategy vs System overlay metrics.

Compares SPY momentum baseline against System risk-gate overlay using
Strategy Lab shadow cards and trade decisions.

Output:
    Output/strategy_lab/overlay_shadow_report.json
    Output/strategy_lab/overlay_shadow_report.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from _runtime_io import ROOT, ensure_dir, load_json, write_json

SHADOW_DIR = ROOT / "Output" / "strategy_lab" / "shadow_cards"
TRADE_PATH = ROOT / "Output" / "judgment" / "trade_decision.json"
PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
OUT_JSON = ROOT / "Output" / "strategy_lab" / "overlay_shadow_report.json"
OUT_MD = ROOT / "Output" / "strategy_lab" / "overlay_shadow_report.md"


def _load_spy_momentum(panel: pd.DataFrame, lookback: int = 20) -> pd.Series:
    spy = panel.loc[panel["symbol"] == "SPY"].copy()
    if spy.empty:
        return pd.Series(dtype=float)
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.sort_values("date").set_index("date")
    ret = spy["close"].pct_change(lookback)
    signal = (ret > 0).astype(int)
    signal.name = "base_long"
    return signal


def _overlay_allow(trade: dict | None, card: dict | None) -> bool:
    if trade:
        decision = str(trade.get("decision", "")).upper()
        if decision in {"NO_TRADE", "RESEARCH_REVIEW"}:
            return False
    if card:
        rec = card.get("recommendation", {})
        if rec.get("allow_open") is False:
            return False
    return True


def build_report(days: int = 90) -> dict[str, Any]:
    if not PANEL.exists():
        return {"error": "cross_asset panel missing"}

    panel = pd.read_parquet(PANEL)
    base = _load_spy_momentum(panel)
    if base.empty:
        return {"error": "SPY series missing from panel"}

    cutoff = base.index.max() - pd.Timedelta(days=days)
    base = base.loc[base.index >= cutoff]

    trade = load_json(TRADE_PATH)
    cards_by_date: dict[str, dict] = {}
    if SHADOW_DIR.exists():
        for path in SHADOW_DIR.glob("2*.json"):
            card = json.loads(path.read_text(encoding="utf-8"))
            d = card.get("as_of_date")
            if d:
                cards_by_date[d] = card

    spy = panel.loc[panel["symbol"] == "SPY"].copy()
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.sort_values("date").set_index("date")["close"]

    base_returns: list[float] = []
    overlay_returns: list[float] = []
    bad_adds_base = 0
    bad_adds_overlay = 0
    conflict_regime_trades_base = 0
    conflict_regime_trades_overlay = 0

    for i in range(1, len(base)):
        d = base.index[i]
        prev = base.index[i - 1]
        if d not in spy.index or prev not in spy.index:
            continue
        daily_ret = float(spy.loc[d] / spy.loc[prev] - 1.0)
        long_base = bool(base.iloc[i - 1])
        card = cards_by_date.get(str(d.date()))
        trade_for_day = (
            trade if trade and str(d.date()) == str(trade.get("as_of_date", ""))[:10] else None
        )
        allow = _overlay_allow(trade_for_day, card)
        long_overlay = long_base and allow

        base_returns.append(daily_ret if long_base else 0.0)
        overlay_returns.append(daily_ret if long_overlay else 0.0)

        if daily_ret < -0.01 and long_base:
            bad_adds_base += 1
        if daily_ret < -0.01 and long_overlay:
            bad_adds_overlay += 1

        conflict = card and card.get("risk_gate", {}).get("regime_conflict")
        if conflict and long_base:
            conflict_regime_trades_base += 1
        if conflict and long_overlay:
            conflict_regime_trades_overlay += 1

    def _max_dd(rets: list[float]) -> float:
        if not rets:
            return 0.0
        equity = (1 + pd.Series(rets)).cumprod()
        peak = equity.cummax()
        dd = (equity / peak - 1.0).min()
        return float(round(dd, 4))

    return {
        "schema_version": "overlay_shadow_report.v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "window_days": days,
        "base_strategy": "SPY_20d_momentum",
        "metrics": {
            "base_total_return": round(sum(base_returns), 4),
            "overlay_total_return": round(sum(overlay_returns), 4),
            "base_max_drawdown": _max_dd(base_returns),
            "overlay_max_drawdown": _max_dd(overlay_returns),
            "bad_add_days_base": bad_adds_base,
            "bad_add_days_overlay": bad_adds_overlay,
            "conflict_regime_trades_base": conflict_regime_trades_base,
            "conflict_regime_trades_overlay": conflict_regime_trades_overlay,
            "overlay_reduced_bad_adds": bad_adds_base - bad_adds_overlay,
        },
        "allowed_to_affect_core_judgment": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build overlay shadow report.")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build_report(days=args.days)
    ensure_dir(OUT_JSON.parent)
    write_json(OUT_JSON, report)

    if report.get("error"):
        print(report["error"])
        return

    m = report["metrics"]
    lines = [
        "# Overlay Shadow Report",
        "",
        f"Base: {report['base_strategy']} | Window: {report['window_days']}d",
        "",
        f"- Base max drawdown: {m['base_max_drawdown']}",
        f"- Overlay max drawdown: {m['overlay_max_drawdown']}",
        f"- Bad add days (base / overlay): {m['bad_add_days_base']} / {m['bad_add_days_overlay']}",
        f"- Conflict regime trades (base / overlay): {m['conflict_regime_trades_base']} / {m['conflict_regime_trades_overlay']}",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote: {OUT_JSON}")
    if args.json:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
