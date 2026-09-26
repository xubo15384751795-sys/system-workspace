"""Report generator — produce comparison reports and yearly breakdowns.

Outputs:
  - Markdown report with baseline vs overlay comparison
  - JSON metrics for machine consumption
  - Per-year breakdown table
  - Failure sample list (years where overlay underperformed)
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from verity.runtime import runtime_io as rio

OUTPUT_DIR = rio.ROOT / "Output" / "state" / "strategy_lab"


def generate_markdown_report(result: dict) -> str:
    """Generate a Markdown comparison report from backtest results.

    Args:
        result: dict from backtest.run_comparison().

    Returns:
        Markdown string.
    """
    b = result["baseline"]
    o = result["overlay"]
    c = result["comparison"]
    yearly = result.get("yearly", [])

    lines = [
        "# Strategy Lab: Baseline vs System Overlay",
        "",
        f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Period:** {b['start_date']} → {b['end_date']} ({b['n_days']} trading days)",
        "",
        "## Summary",
        "",
        "| Metric | Baseline | Overlay | Delta |",
        "|--------|----------|---------|-------|",
        f"| Total Return | {b['total_return']:.2%} | {o['total_return']:.2%} | {c['return_delta']:+.2%} |",
        f"| Ann. Return | {b['ann_return']:.2%} | {o['ann_return']:.2%} | {o['ann_return']-b['ann_return']:+.2%} |",
        f"| Ann. Volatility | {b['ann_volatility']:.2%} | {o['ann_volatility']:.2%} | {o['ann_volatility']-b['ann_volatility']:+.2%} |",
        f"| Sharpe Ratio | {b['sharpe']:.3f} | {o['sharpe']:.3f} | {c['sharpe_delta']:+.3f} |",
        f"| Max Drawdown | {b['max_drawdown']:.2%} | {o['max_drawdown']:.2%} | {c['max_dd_delta']:+.2%} |",
        f"| Calmar Ratio | {b['calmar']:.3f} | {o['calmar']:.3f} | {c['calmar_delta']:+.3f} |",
        f"| Win Rate | {b['win_rate']:.2%} | {o['win_rate']:.2%} | {o['win_rate']-b['win_rate']:+.2%} |",
        f"| Time in Market | {b['time_in_market']:.2%} | {o['time_in_market']:.2%} | {o['time_in_market']-b['time_in_market']:+.2%} |",
        f"| Tail Loss (5%) | {b['tail_loss_5pct']:.4%} | {o['tail_loss_5pct']:.4%} | {c['tail_loss_delta']:+.4%} |",
        f"| Trade Count | {b['n_trades']} | {o['n_trades']} | {c['trades_delta']:+d} |",
        "",
    ]

    costs = result.get("costs") or {}
    if costs:
        lines.extend([
            "## Transaction Costs",
            "",
            f"- One-way friction: **{costs.get('one_way_bps')} bp** "
            f"(cost={costs.get('cost_bps')} + slippage={costs.get('slippage_bps')})",
            f"- Baseline total cost drag: {costs.get('baseline_total_cost')}",
            f"- Overlay total cost drag: {costs.get('overlay_total_cost')}",
            f"- Overlay avg daily turnover: {costs.get('overlay_avg_turnover')}",
            "",
        ])

    cfg = result.get("config") or {}
    if cfg:
        lines.extend([
            "## Config",
            "",
            f"- Lookback: {cfg.get('lookback')}",
            f"- Dynamic lookback: {cfg.get('dynamic')}",
            f"- Bull modulation: {cfg.get('bull_modulation')}",
            f"- Cost / slippage (bp): {cfg.get('cost_bps')} / {cfg.get('slippage_bps')}",
            "",
        ])

    # Interpretation
    lines.extend([
        "## Interpretation",
        "",
    ])

    # max_dd_delta = overlay_dd - baseline_dd. Since both are negative,
    # a positive delta means overlay DD is less severe (better).
    if c["max_dd_delta"] > 0.005:
        lines.append(f"✅ **Drawdown reduction:** Overlay reduced max drawdown by {c['max_dd_delta']:.2%}")
    elif c["max_dd_delta"] < -0.005:
        lines.append(f"⚠️ **Drawdown increase:** Overlay worsened max drawdown by {abs(c['max_dd_delta']):.2%}")
    else:
        lines.append("➖ **Drawdown:** Negligible change")

    if c["sharpe_delta"] > 0.05:
        lines.append(f"✅ **Risk-adjusted return:** Sharpe improved by {c['sharpe_delta']:.3f}")
    elif c["sharpe_delta"] < -0.05:
        lines.append(f"⚠️ **Risk-adjusted return:** Sharpe decreased by {abs(c['sharpe_delta']):.3f}")
    else:
        lines.append("➖ **Risk-adjusted return:** Negligible change")

    if c["tail_loss_delta"] > 0.0005:
        lines.append(f"✅ **Tail risk:** Worst 5% returns improved by {abs(c['tail_loss_delta']):.4%}")
    elif c["tail_loss_delta"] < -0.0005:
        lines.append(f"⚠️ **Tail risk:** Worst 5% returns worsened by {abs(c['tail_loss_delta']):.4%}")
    else:
        lines.append("➖ **Tail risk:** Negligible change")

    lines.append("")

    # Yearly breakdown
    if yearly:
        lines.extend([
            "## Per-Year Breakdown",
            "",
            "| Year | Baseline | Overlay | Δ Return | Base MaxDD | Overlay MaxDD | DD Improve |",
            "|------|----------|---------|----------|------------|---------------|------------|",
        ])
        for y in yearly:
            # dd_improvement = overlay_dd - baseline_dd (both negative).
            # Positive = overlay DD less severe = improvement.
            dd_emoji = "✅" if y["dd_improvement"] > 0.005 else ("⚠️" if y["dd_improvement"] < -0.005 else "➖")
            lines.append(
                f"| {y['year']} "
                f"| {y['baseline_return']:.2%} "
                f"| {y['overlay_return']:.2%} "
                f"| {y['return_delta']:+.2%} "
                f"| {y['baseline_max_dd']:.2%} "
                f"| {y['overlay_max_dd']:.2%} "
                f"| {dd_emoji} {y['dd_improvement']:+.2%} |"
            )
        lines.append("")

        # Failure samples
        failures = [y for y in yearly if y["return_delta"] < -0.01]
        if failures:
            lines.extend([
                "## Failure Samples (Overlay Underperformed by >1%)",
                "",
            ])
            for y in failures:
                lines.append(f"- **{y['year']}**: baseline {y['baseline_return']:.2%}, overlay {y['overlay_return']:.2%}, delta {y['return_delta']:+.2%}")
            lines.append("")

        # Best years
        best = sorted(yearly, key=lambda y: y["return_delta"], reverse=True)[:3]
        if best:
            lines.extend([
                "## Best Years for System Overlay",
                "",
            ])
            for y in best:
                lines.append(f"- **{y['year']}**: delta {y['return_delta']:+.2%}, DD improvement {y['dd_improvement']:+.2%}")
            lines.append("")

    lines.extend([
        "---",
        "*System overlay = M/D/K/X velocity gate (binary exit on 20d co-deterioration)*",
        "*Config: velocity_window=20, velocity_threshold=1.5, cofire_n=3, cofire_v=0.2*",
        "*Baseline = SPY 63-day momentum (long if >0, cash if ≤0)*",
    ])

    return "\n".join(lines)


def save_report(result: dict) -> tuple[Path, Path]:
    """Save backtest report as Markdown and JSON.

    Returns:
        (md_path, json_path)
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = OUTPUT_DIR / "backtest_result.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Markdown
    md_path = OUTPUT_DIR / "backtest_report.md"
    md_content = generate_markdown_report(result)
    md_path.write_text(md_content, encoding="utf-8")

    return md_path, json_path
