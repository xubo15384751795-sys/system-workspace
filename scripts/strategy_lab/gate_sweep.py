"""Gate Sweep — test risk gate configurations (regime + velocity-with-cost).

Sweeps position sizes for each regime class, and (with --velocity-cost)
sweeps velocity-gate parameters under transaction costs.

Usage:
    python scripts/strategy_lab/gate_sweep.py
    python scripts/strategy_lab/gate_sweep.py --start 2005-01-01 --lookback 63
    python scripts/strategy_lab/gate_sweep.py --velocity-cost
    python scripts/strategy_lab/gate_sweep.py --velocity-cost --cost-bps 3 --slippage-bps 2
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


from scripts import _runtime_io as rio
import pandas as pd
from scripts.strategy_lab.backtest import apply_transaction_costs, compute_metrics
from scripts.strategy_lab.data_loader import load_aligned
from scripts.strategy_lab.risk_gate import compute_velocity_gate, evaluate_day
from scripts.strategy_lab.strategies import compute_baseline_position

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


def velocity_cost_sweep(
    data: pd.DataFrame,
    *,
    lookback: int = 63,
    cost_bps: float = 3.0,
    slippage_bps: float = 2.0,
) -> list[dict]:
    """Sweep velocity-gate configs under transaction costs.

    Returns ranked rows including sharpe_delta vs costed baseline.
    """
    daily_returns = data["return_1d"]
    close = data["close"]
    baseline_pos = compute_baseline_position(close, lookback=lookback)
    signals = data[["M", "D", "K", "X"]]

    baseline_ret, _ = apply_transaction_costs(
        daily_returns, baseline_pos, cost_bps=cost_bps, slippage_bps=slippage_bps
    )
    baseline_m = compute_metrics(baseline_ret, baseline_pos, "baseline")

    grid: list[dict] = []
    for velocity_threshold in (1.0, 1.5, 2.0, 2.5):
        for cofire_n in (2, 3, 4):
            for bull_modulation in (False, True):
                for bull_threshold in ((2.0, 2.5) if bull_modulation else (None,)):
                    grid.append({
                        "velocity_window": 20,
                        "velocity_threshold": velocity_threshold,
                        "cofire_n": cofire_n,
                        "cofire_v": 0.2,
                        "bull_modulation": bull_modulation,
                        "bull_velocity_threshold": bull_threshold if bull_modulation else None,
                    })

    # Deduplicate
    seen: set[tuple] = set()
    unique = []
    for cfg in grid:
        key = tuple(sorted((k, v) for k, v in cfg.items()))
        if key not in seen:
            seen.add(key)
            unique.append(cfg)

    print(
        f"Velocity+cost sweep: {len(unique)} configs "
        f"(friction={cost_bps + slippage_bps}bp one-way)..."
    )

    results = []
    for cfg in unique:
        gate_kwargs = {
            "velocity_window": cfg["velocity_window"],
            "velocity_threshold": cfg["velocity_threshold"],
            "cofire_n": cfg["cofire_n"],
            "cofire_v": cfg["cofire_v"],
            "bull_modulation": cfg["bull_modulation"],
        }
        if cfg["bull_modulation"]:
            gate_kwargs["bull_velocity_threshold"] = cfg["bull_velocity_threshold"]
            gate_kwargs["close"] = close

        gate = compute_velocity_gate(signals, **gate_kwargs)
        overlay_pos = baseline_pos * gate
        overlay_ret, cost_series = apply_transaction_costs(
            daily_returns, overlay_pos, cost_bps=cost_bps, slippage_bps=slippage_bps
        )
        m = compute_metrics(overlay_ret, overlay_pos, "overlay")

        # Bull-year / crisis-year slices for modulation acceptance
        yearly_deltas = {}
        for year in (2008, 2013, 2017, 2022, 2023, 2025):
            mask = daily_returns.index.year == year
            if mask.sum() < 20:
                continue
            b_y = (1 + baseline_ret[mask]).cumprod().iloc[-1] - 1
            o_y = (1 + overlay_ret[mask]).cumprod().iloc[-1] - 1
            yearly_deltas[str(year)] = float(round(o_y - b_y, 4))

        label_parts = [
            f"vt={cfg['velocity_threshold']}",
            f"cn={cfg['cofire_n']}",
        ]
        if cfg["bull_modulation"]:
            label_parts.append(f"bull={cfg['bull_velocity_threshold']}")
        else:
            label_parts.append("bull=off")

        result = {
            "config": cfg,
            "config_label": "|".join(label_parts),
            "cost_bps": cost_bps,
            "slippage_bps": slippage_bps,
            "one_way_bps": cost_bps + slippage_bps,
            "total_return": m.total_return,
            "ann_return": m.ann_return,
            "sharpe": m.sharpe,
            "max_drawdown": m.max_drawdown,
            "calmar": m.calmar,
            "time_in_market": m.time_in_market,
            "n_trades": m.n_trades,
            "total_cost": float(cost_series.sum()),
            "return_delta": m.total_return - baseline_m.total_return,
            "sharpe_delta": m.sharpe - baseline_m.sharpe,
            "dd_delta": m.max_drawdown - baseline_m.max_drawdown,
            "tim_delta": m.time_in_market - baseline_m.time_in_market,
            "yearly_return_delta": yearly_deltas,
            "positive_sharpe_delta": m.sharpe - baseline_m.sharpe > 0,
        }
        results.append(result)

    baseline_row = {
        "config": "baseline",
        "config_label": "baseline",
        "cost_bps": cost_bps,
        "slippage_bps": slippage_bps,
        "one_way_bps": cost_bps + slippage_bps,
        "total_return": baseline_m.total_return,
        "ann_return": baseline_m.ann_return,
        "sharpe": baseline_m.sharpe,
        "max_drawdown": baseline_m.max_drawdown,
        "calmar": baseline_m.calmar,
        "time_in_market": baseline_m.time_in_market,
        "n_trades": baseline_m.n_trades,
        "total_cost": 0.0,
        "return_delta": 0.0,
        "sharpe_delta": 0.0,
        "dd_delta": 0.0,
        "tim_delta": 0.0,
        "yearly_return_delta": {},
        "positive_sharpe_delta": False,
    }
    return [baseline_row] + sorted(results, key=lambda r: r["sharpe_delta"], reverse=True)


def print_velocity_cost_report(results: list[dict], top_n: int = 20) -> str:
    """Format velocity+cost sweep as markdown with positive-Sharpe inventory."""
    baseline = next(r for r in results if r["config"] == "baseline")
    overlays = [r for r in results if r["config"] != "baseline"]
    positive = [r for r in overlays if r["positive_sharpe_delta"]]

    lines = [
        "# Velocity Gate Cost Sweep",
        "",
        f"**Friction:** {baseline['one_way_bps']} bp one-way "
        f"(cost={baseline['cost_bps']} + slippage={baseline['slippage_bps']})",
        f"**Baseline (net):** Sharpe={baseline['sharpe']:.3f}, "
        f"return={baseline['total_return']:.2%}, TIM={baseline['time_in_market']:.0%}",
        "",
        f"## Configs with positive Sharpe Δ after costs: {len(positive)}/{len(overlays)}",
        "",
    ]

    if not positive:
        lines.append(
            "**All configs lost net Sharpe after costs.** "
            "Raise velocity_threshold / cofire_n (lower turnover) before Phase 4."
        )
        lines.append("")
    else:
        lines += [
            "| # | Config | Sharpe | Δ Sharpe | Return Δ | MaxDD Δ | TIM | Trades | Cost |",
            "|---|--------|--------|----------|----------|---------|-----|--------|------|",
        ]
        for i, r in enumerate(positive[:top_n], 1):
            lines.append(
                f"| {i} | `{r['config_label']}` "
                f"| {r['sharpe']:.3f} "
                f"| {r['sharpe_delta']:+.3f} "
                f"| {r['return_delta']:+.2%} "
                f"| {r['dd_delta']:+.2%} "
                f"| {r['time_in_market']:.0%} "
                f"| {r['n_trades']} "
                f"| {r['total_cost']:.4f} |"
            )
        lines.append("")

    # Highlight production + bull modulation
    lines += ["## Production / bull-modulation focus", ""]
    for label in ("vt=1.5|cn=3|bull=off", "vt=1.5|cn=3|bull=2.0", "vt=2.0|cn=3|bull=off"):
        match = next((r for r in overlays if r["config_label"] == label), None)
        if not match:
            continue
        yd = match.get("yearly_return_delta") or {}
        lines.append(f"### `{label}`")
        lines.append(
            f"- Sharpe {match['sharpe']:.3f} (Δ {match['sharpe_delta']:+.3f}), "
            f"TIM {match['time_in_market']:.0%}, trades {match['n_trades']}"
        )
        lines.append(
            f"- Bull years return Δ: 2013={yd.get('2013', 'n/a')}, "
            f"2017={yd.get('2017', 'n/a')}, 2023={yd.get('2023', 'n/a')}, "
            f"2025={yd.get('2025', 'n/a')}"
        )
        lines.append(
            f"- Crisis years return Δ: 2008={yd.get('2008', 'n/a')}, "
            f"2022={yd.get('2022', 'n/a')}"
        )
        lines.append("")

    lines += [
        "## Acceptance inventory (Sharpe Δ > 0 net of costs)",
        "",
    ]
    if positive:
        for r in positive:
            lines.append(
                f"- `{r['config_label']}`: Sharpe Δ {r['sharpe_delta']:+.3f}, "
                f"TIM {r['time_in_market']:.0%}"
            )
    else:
        lines.append("- _(none)_")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate parameter sweep")
    parser.add_argument("--start", type=str, default="2000-01-01")
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--lookback", type=int, default=63)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--velocity-cost", action="store_true",
                        help="Sweep velocity gate under transaction costs")
    parser.add_argument("--cost-bps", type=float, default=3.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data = load_aligned(start=args.start, end=args.end)
    print(f"Loaded {len(data)} trading days ({data.index[0].date()} → {data.index[-1].date()})")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.velocity_cost:
        results = velocity_cost_sweep(
            data,
            lookback=args.lookback,
            cost_bps=args.cost_bps,
            slippage_bps=args.slippage_bps,
        )
        json_path = OUTPUT_DIR / "velocity_cost_sweep_results.json"
        json_path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
        report = print_velocity_cost_report(results, top_n=args.top)
        md_path = OUTPUT_DIR / "velocity_cost_sweep_report.md"
        md_path.write_text(report, encoding="utf-8")
        print(report)
        print(f"\nSaved to {md_path}")
        if args.json:
            print(json.dumps(results[:8], indent=2, default=str))
        return

    results = sweep(data, lookback=args.lookback)

    # Save JSON
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
