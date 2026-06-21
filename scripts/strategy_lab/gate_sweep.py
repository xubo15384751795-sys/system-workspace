"""Gate Sweep — test multiple risk gate configurations to find the sweet spot.

Sweeps position sizes for each regime class and reports which configs
best preserve returns while reducing drawdown.

Usage:
    python scripts/strategy_lab/gate_sweep.py
    python scripts/strategy_lab/gate_sweep.py --start 2005-01-01 --lookback 63
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

import _runtime_io as rio
from strategy_lab.backtest import compute_metrics, compute_drawdown_series
from strategy_lab.data_loader import load_aligned
from strategy_lab.risk_gate import evaluate_day
from strategy_lab.strategies import compute_baseline_position

OUTPUT_DIR = rio.ROOT / "Output" / "strategy_lab"


# ── Gate configuration ───────────────────────────────────────────────
@dataclass
class GateConfig:
    """Position sizes for each regime class."""
    structural_stress: float = 0.0   # X+K both elevated
    leverage_stress: float = 0.0     # X elevated
    curvature_stress: float = 0.5    # K elevated
    diffuse_stress: float = 0.25     # 3+ channels stressed
    mixed: float = 0.25              # 2 stress + 1 relief
    one_stress: float = 0.5          # 1 channel stressed
    neutral: float = 1.0             # default
    all_clear: float = 1.0           # 3+ relief

    def to_dict(self) -> dict:
        return {
            "structural_stress": self.structural_stress,
            "leverage_stress": self.leverage_stress,
            "curvature_stress": self.curvature_stress,
            "diffuse_stress": self.diffuse_stress,
            "mixed": self.mixed,
            "one_stress": self.one_stress,
            "neutral": self.neutral,
            "all_clear": self.all_clear,
        }

    def label(self) -> str:
        """Short label for this config."""
        parts = []
        for k, v in self.to_dict().items():
            if v != 1.0:
                parts.append(f"{k[:3]}={v}")
        return "|".join(parts) if parts else "all_1.0"


def compute_position_with_config(
    signals: pd.DataFrame,
    config: GateConfig,
) -> pd.Series:
    """Compute position series using a specific gate configuration."""
    positions = []
    for _, row in signals.iterrows():
        state = evaluate_day(row["M"], row["D"], row["K"], row["X"])

        # Map regime to position size from config
        if state.regime == "STRUCTURAL_STRESS":
            pos = config.structural_stress
        elif state.regime == "LEVERAGE_STRESS":
            pos = config.leverage_stress
        elif state.regime == "CURVATURE_STRESS":
            pos = config.curvature_stress
        elif state.regime == "DIFFUSE_STRESS":
            pos = config.diffuse_stress
        elif state.regime == "MIXED":
            pos = config.mixed
        elif state.regime == "ALL_CLEAR":
            pos = config.all_clear
        elif state.n_stress >= 1:
            pos = config.one_stress
        else:
            pos = config.neutral

        positions.append(pos)

    return pd.Series(positions, index=signals.index)


def run_single_config(
    daily_returns: pd.Series,
    baseline_pos: pd.Series,
    risk_pos: pd.Series,
    config: GateConfig,
) -> dict:
    """Run backtest for a single gate configuration."""
    overlay_pos = baseline_pos * risk_pos
    overlay_ret = daily_returns * overlay_pos.shift(1).fillna(0)
    m = compute_metrics(overlay_ret, overlay_pos, config.label())
    return m.to_dict()


def sweep(
    data: pd.DataFrame,
    lookback: int = 63,
) -> list[dict]:
    """Run parameter sweep across gate configurations.

    Tests a grid of position sizes for the key regime classes.
    """
    daily_returns = data["return_1d"]
    baseline_pos = compute_baseline_position(data["close"], lookback=lookback)
    signals = data[["M", "D", "K", "X"]]

    # Baseline metrics
    baseline_ret = daily_returns * baseline_pos.shift(1).fillna(0)
    baseline_m = compute_metrics(baseline_ret, baseline_pos, "baseline")

    # ── Define sweep grid ────────────────────────────────────────────
    # Key insight: the regimes that matter most are LEVERAGE_STRESS and
    # DIFFUSE_STRESS (they trigger most often). STRUCTURAL_STRESS is rare.
    # We want to soften these while keeping the DD reduction benefit.

    configs = []

    # Vary leverage_stress, diffuse_stress, one_stress
    for lev in [0.0, 0.25, 0.5]:
        for diff in [0.25, 0.5, 0.75]:
            for one in [0.5, 0.75, 1.0]:
                for mix in [0.25, 0.5, 0.75]:
                    configs.append(GateConfig(
                        structural_stress=0.0,  # always block on structural stress
                        leverage_stress=lev,
                        curvature_stress=0.5,
                        diffuse_stress=diff,
                        mixed=mix,
                        one_stress=one,
                        neutral=1.0,
                        all_clear=1.0,
                    ))

    # Also test a few "soft" configs that only reduce, never block
    for lev in [0.25, 0.5]:
        configs.append(GateConfig(
            structural_stress=0.0,
            leverage_stress=lev,
            curvature_stress=0.75,
            diffuse_stress=0.5,
            mixed=0.75,
            one_stress=0.75,
            neutral=1.0,
            all_clear=1.0,
        ))

    # "Minimal intervention" config — only block structural stress
    configs.append(GateConfig(
        structural_stress=0.0,
        leverage_stress=0.5,
        curvature_stress=0.75,
        diffuse_stress=0.75,
        mixed=0.75,
        one_stress=1.0,
        neutral=1.0,
        all_clear=1.0,
    ))

    # Deduplicate
    seen = set()
    unique_configs = []
    for c in configs:
        key = tuple(c.to_dict().items())
        if key not in seen:
            seen.add(key)
            unique_configs.append(c)

    print(f"Sweeping {len(unique_configs)} gate configurations...")

    results = []
    for config in unique_configs:
        risk_pos = compute_position_with_config(signals, config)
        overlay_pos = baseline_pos * risk_pos
        overlay_ret = daily_returns * overlay_pos.shift(1).fillna(0)
        m = compute_metrics(overlay_ret, overlay_pos, "overlay")

        # Compute delta vs baseline
        result = {
            "config": config.to_dict(),
            "config_label": config.label(),
            "total_return": m.total_return,
            "ann_return": m.ann_return,
            "sharpe": m.sharpe,
            "max_drawdown": m.max_drawdown,
            "calmar": m.calmar,
            "tail_loss_5pct": m.tail_loss_5pct,
            "time_in_market": m.time_in_market,
            "n_trades": m.n_trades,
            # Deltas vs baseline
            "return_delta": m.total_return - baseline_m.total_return,
            "sharpe_delta": m.sharpe - baseline_m.sharpe,
            "dd_delta": m.max_drawdown - baseline_m.max_drawdown,
            "calmar_delta": m.calmar - baseline_m.calmar,
            "tail_delta": m.tail_loss_5pct - baseline_m.tail_loss_5pct,
        }
        results.append(result)

    # Add baseline for reference
    baseline_result = {
        "config": "baseline",
        "config_label": "baseline",
        "total_return": baseline_m.total_return,
        "ann_return": baseline_m.ann_return,
        "sharpe": baseline_m.sharpe,
        "max_drawdown": baseline_m.max_drawdown,
        "calmar": baseline_m.calmar,
        "tail_loss_5pct": baseline_m.tail_loss_5pct,
        "time_in_market": baseline_m.time_in_market,
        "n_trades": baseline_m.n_trades,
        "return_delta": 0.0,
        "sharpe_delta": 0.0,
        "dd_delta": 0.0,
        "calmar_delta": 0.0,
        "tail_delta": 0.0,
    }

    return [baseline_result] + results


def rank_results(results: list[dict]) -> list[dict]:
    """Rank configs by a composite score.

    Score = Sharpe + 0.5 * (dd_improvement / 0.05) + 0.3 * (tail_improvement / 0.001)
    Penalize return loss: -0.3 * max(0, -return_delta / 0.10)
    """
    for r in results:
        if r["config"] == "baseline":
            r["score"] = 0.0
            continue

        dd_improve = r["dd_delta"]  # positive = better (less negative DD)
        tail_improve = r["tail_delta"]  # positive = better
        return_loss = max(0, -r["return_delta"])

        r["score"] = (
            r["sharpe"]
            + 0.5 * (dd_improve / 0.05)
            + 0.3 * (tail_improve / 0.001)
            - 0.3 * (return_loss / 0.10)
        )

    return sorted(results, key=lambda r: r.get("score", 0), reverse=True)


def print_sweep_report(results: list[dict], top_n: int = 15) -> str:
    """Format sweep results as a readable report."""
    ranked = rank_results(results)
    baseline = [r for r in results if r["config"] == "baseline"][0]

    lines = [
        "# Gate Sweep Report",
        "",
        f"**Baseline:** return={baseline['total_return']:.2%}, sharpe={baseline['sharpe']:.3f}, maxDD={baseline['max_drawdown']:.2%}",
        "",
        f"## Top {top_n} Configurations (by composite score)",
        "",
        "| # | Config | Return | Δ Ret | Sharpe | Δ Sharpe | MaxDD | Δ DD | Calmar | Tail 5% | Time% | Score |",
        "|---|--------|--------|-------|--------|----------|-------|------|--------|---------|-------|-------|",
    ]

    for i, r in enumerate(ranked[:top_n], 1):
        dd_icon = "✅" if r["dd_delta"] > 0.005 else ("⚠️" if r["dd_delta"] < -0.005 else "➖")
        lines.append(
            f"| {i} "
            f"| {r['config_label'][:40]} "
            f"| {r['total_return']:.2%} "
            f"| {r['return_delta']:+.2%} "
            f"| {r['sharpe']:.3f} "
            f"| {r['sharpe_delta']:+.3f} "
            f"| {r['max_drawdown']:.2%} "
            f"| {dd_icon} {r['dd_delta']:+.2%} "
            f"| {r['calmar']:.3f} "
            f"| {r['tail_loss_5pct']:.4%} "
            f"| {r['time_in_market']:.0%} "
            f"| {r.get('score', 0):.2f} |"
        )

    lines.extend([
        "",
        "## Score Formula",
        "score = Sharpe + 0.5*(dd_improve/5%) + 0.3*(tail_improve/0.1%) - 0.3*(return_loss/10%)",
        "",
        "## Interpretation",
        "",
    ])

    if ranked and ranked[0].get("score", 0) > 0:
        best = ranked[0]
        lines.append(f"**Best config:** {best['config_label']}")
        lines.append(f"- Return: {best['total_return']:.2%} (delta {best['return_delta']:+.2%})")
        lines.append(f"- Sharpe: {best['sharpe']:.3f} (delta {best['sharpe_delta']:+.3f})")
        lines.append(f"- Max DD: {best['max_drawdown']:.2%} (delta {best['dd_delta']:+.2%})")
        lines.append(f"- Time in market: {best['time_in_market']:.0%}")
        lines.append("")
        lines.append("**Gate values:**")
        for k, v in best["config"].items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate parameter sweep")
    parser.add_argument("--start", type=str, default="2000-01-01")
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--lookback", type=int, default=63)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data = load_aligned(start=args.start, end=args.end)
    print(f"Loaded {len(data)} trading days ({data.index[0].date()} → {data.index[-1].date()})")

    results = sweep(data, lookback=args.lookback)

    # Save JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "gate_sweep_results.json"
    json_path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")

    # Print report
    report = print_sweep_report(results, top_n=args.top)
    md_path = OUTPUT_DIR / "gate_sweep_report.md"
    md_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nSaved to {md_path}")

    if args.json:
        print(json.dumps(results[:5], indent=2, default=str))


if __name__ == "__main__":
    main()
