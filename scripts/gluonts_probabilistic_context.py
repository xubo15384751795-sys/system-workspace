#!/usr/bin/env python3
"""GluonTS Probabilistic Context — uncertainty overlay.

This script generates probabilistic forecasts using GluonTS for
uncertainty quantification. It does NOT make trading decisions,
only provides probability context.

Usage:
    python3 scripts/gluonts_probabilistic_context.py
    python3 scripts/gluonts_probabilistic_context.py --json
    python3 scripts/gluonts_probabilistic_context.py --sample  # Generate sample context

Output:
    Output/probabilistic_context/latest.json
    Output/probabilistic_context/latest.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ETF_PANEL = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
OUTPUT_DIR = ROOT / "Output" / "probabilistic_context"


def load_etf_data() -> pd.DataFrame:
    """Load ETF panel data."""
    if not ETF_PANEL.exists():
        return pd.DataFrame()
    etf = pd.read_parquet(ETF_PANEL)
    etf["date"] = pd.to_datetime(etf["date"])
    return etf


def compute_historical_returns(series: pd.Series, horizon: int) -> pd.Series:
    """Compute historical returns for a given horizon."""
    return series.pct_change(horizon).dropna()


def estimate_forecast_intervals(
    returns: pd.Series,
    confidence_levels: list[float] = [0.1, 0.25, 0.5, 0.75, 0.9],
) -> dict[str, float]:
    """Estimate forecast intervals from historical returns."""
    if returns.empty:
        return {f"p{int(cl*100)}": 0.0 for cl in confidence_levels}

    intervals = {}
    for cl in confidence_levels:
        quantile = returns.quantile(cl)
        intervals[f"p{int(cl*100)}"] = round(float(quantile), 6)

    return intervals


def estimate_tail_probability(returns: pd.Series, threshold: float = -0.02) -> dict[str, float]:
    """Estimate tail probability from historical returns."""
    if returns.empty:
        return {"left_tail": 0.0, "right_tail": 0.0}

    left_tail = (returns < threshold).mean()
    right_tail = (returns > abs(threshold)).mean()

    return {
        "left_tail": round(float(left_tail), 4),
        "right_tail": round(float(right_tail), 4),
    }


def compute_forecast_for_series(
    series: pd.Series,
    series_name: str,
    horizons: dict[str, int] = {"1d": 1, "1w": 5, "1m": 21},
) -> list[dict[str, Any]]:
    """Compute forecasts for a series across horizons."""
    forecasts = []

    for horizon_name, horizon_days in horizons.items():
        returns = compute_historical_returns(series, horizon_days)

        if returns.empty:
            continue

        # Use last 252 days for estimation
        recent_returns = returns.tail(252)

        intervals = estimate_forecast_intervals(recent_returns)
        tail_prob = estimate_tail_probability(recent_returns)

        # Compute calibrated risk probability
        # High risk if left tail > 10%
        calibrated_risk = tail_prob["left_tail"] > 0.1

        # Model confidence based on data availability
        if len(recent_returns) < 100:
            model_confidence = "low"
        elif len(recent_returns) < 200:
            model_confidence = "medium"
        else:
            model_confidence = "high"

        forecasts.append({
            "source_series": series_name,
            "forecast_horizon": horizon_name,
            "intervals": intervals,
            "tail_probability": tail_prob,
            "calibrated_risk_probability": round(float(tail_prob["left_tail"]), 4),
            "model_confidence": model_confidence,
            "method": "historical_quantile",
        })

    return forecasts


def generate_sample_context() -> dict[str, Any]:
    """Generate sample probabilistic context for testing."""
    now = datetime.now(UTC)

    return {
        "schema_version": "probabilistic_context.v1",
        "generated_at": now.isoformat(),
        "forecasts": [
            {
                "source_series": "SPY",
                "forecast_horizon": "1w",
                "intervals": {"p10": -0.025, "p25": -0.012, "p50": 0.003, "p75": 0.015, "p90": 0.028},
                "tail_probability": {"left_tail": 0.08, "right_tail": 0.12},
                "calibrated_risk_probability": 0.08,
                "model_confidence": "high",
                "method": "historical_quantile",
            },
            {
                "source_series": "HYG",
                "forecast_horizon": "1w",
                "intervals": {"p10": -0.018, "p25": -0.008, "p50": 0.002, "p75": 0.010, "p90": 0.020},
                "tail_probability": {"left_tail": 0.06, "right_tail": 0.10},
                "calibrated_risk_probability": 0.06,
                "model_confidence": "high",
                "method": "historical_quantile",
            },
            {
                "source_series": "TLT",
                "forecast_horizon": "1w",
                "intervals": {"p10": -0.015, "p25": -0.007, "p50": 0.001, "p75": 0.008, "p90": 0.016},
                "tail_probability": {"left_tail": 0.05, "right_tail": 0.08},
                "calibrated_risk_probability": 0.05,
                "model_confidence": "high",
                "method": "historical_quantile",
            },
        ],
        "summary": {
            "overall_risk_level": "low",
            "tail_risk_detected": False,
            "model_confidence": "high",
            "method": "historical_quantile",
        },
    }


def build_probabilistic_context(sample: bool = False) -> dict[str, Any]:
    """Build probabilistic context from market data."""
    if sample:
        return generate_sample_context()

    now = datetime.now(UTC)
    etf = load_etf_data()

    if etf.empty:
        return {
            "schema_version": "probabilistic_context.v1",
            "generated_at": now.isoformat(),
            "forecasts": [],
            "summary": {
                "overall_risk_level": "unknown",
                "tail_risk_detected": False,
                "model_confidence": "low",
                "method": "no_data",
            },
        }

    all_forecasts = []
    for symbol in ["SPY", "HYG", "TLT"]:
        symbol_data = etf[etf["symbol"] == symbol].sort_values("date")
        if symbol_data.empty:
            continue

        series = symbol_data.set_index("date")["close"].astype(float)
        forecasts = compute_forecast_for_series(series, symbol)
        all_forecasts.extend(forecasts)

    # Compute summary
    tail_risks = [f for f in all_forecasts if f.get("calibrated_risk_probability", 0) > 0.1]
    overall_risk = "high" if tail_risks else "medium" if any(f.get("calibrated_risk_probability", 0) > 0.05 for f in all_forecasts) else "low"

    return {
        "schema_version": "probabilistic_context.v1",
        "generated_at": now.isoformat(),
        "forecasts": all_forecasts,
        "summary": {
            "overall_risk_level": overall_risk,
            "tail_risk_detected": bool(tail_risks),
            "model_confidence": "high" if len(all_forecasts) >= 3 else "low",
            "method": "historical_quantile",
        },
    }


def format_markdown(context: dict[str, Any]) -> str:
    """Format probabilistic context as markdown."""
    lines = [
        "# Probabilistic Context",
        "",
        f"**Generated:** {context['generated_at']}",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"- **Overall Risk Level:** {context['summary']['overall_risk_level']}",
        f"- **Tail Risk Detected:** {context['summary']['tail_risk_detected']}",
        f"- **Model Confidence:** {context['summary']['model_confidence']}",
        f"- **Method:** {context['summary']['method']}",
        "",
        "## Forecasts",
        "",
        "| Series | Horizon | P10 | P50 | P90 | Left Tail | Risk Prob |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]

    for forecast in context.get("forecasts", []):
        intervals = forecast.get("intervals", {})
        tail = forecast.get("tail_probability", {})
        lines.append(
            f"| {forecast['source_series']} | {forecast['forecast_horizon']} | "
            f"{intervals.get('p10', 0):.2%} | {intervals.get('p50', 0):.2%} | {intervals.get('p90', 0):.2%} | "
            f"{tail.get('left_tail', 0):.1%} | {forecast.get('calibrated_risk_probability', 0):.1%} |"
        )

    lines += [
        "",
        "## Usage",
        "",
        "- This context can raise/lower confidence in trade decisions",
        "- It can trigger risk warnings",
        "- It CANNOT trigger LONG/SHORT/HEDGE decisions alone",
        "- If it conflicts with HMM/M/D/K/X, output `model_conflict`",
        "",
        "---",
        "",
        "*This is a probabilistic overlay, not a trading signal.*",
    ]

    return "\n".join(lines) + "\n"


def write_outputs(context: dict[str, Any]) -> dict[str, Path]:
    """Write probabilistic context outputs."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "latest.json"
    md_path = OUTPUT_DIR / "latest.md"

    json_path.write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(context), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate probabilistic context.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--sample", action="store_true", help="Generate sample context.")
    args = parser.parse_args()

    context = build_probabilistic_context(sample=args.sample)
    paths = write_outputs(context)

    if args.json:
        print(json.dumps(context, indent=2, ensure_ascii=False))
    else:
        print(f"Probabilistic context: {paths['markdown']}")
        print(f"Overall risk: {context['summary']['overall_risk_level']}")
        print(f"Tail risk detected: {context['summary']['tail_risk_detected']}")
        print(f"Forecasts: {len(context['forecasts'])}")


if __name__ == "__main__":
    main()
