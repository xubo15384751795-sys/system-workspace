"""
Hermes Research Terminal - Report Generator
Generates self-contained HTML reports for ticker analysis.

Usage:
    from report import generate_terminal_report
    generate_terminal_report("GOOGL", start="2024-01-01")
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from research_terminal.data.router import DataRouter
from research_terminal.strategies.engine import QuickBacktest

REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_terminal_report(
    symbol: str,
    start: str = "2024-01-01",
    end: Optional[str] = None,
    benchmark: str = "SPY",
    signals: list = None,
    themes: list = None,
) -> str:
    """Generate a complete terminal report for a ticker.
    
    Args:
        symbol: Ticker symbol
        start: Start date
        end: End date (default: today)
        benchmark: Benchmark ticker
        signals: List of signal dicts with date, label, level
        themes: List of theme strings
    
    Returns:
        Path to generated HTML file
    """
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    if signals is None:
        signals = []
    if themes is None:
        themes = []
    
    # Get data
    router = DataRouter()
    df = router.get_ohlcv(symbol, start, end)
    info = router.get_info(symbol)
    
    benchmark_df = None
    try:
        benchmark_df = router.get_ohlcv(benchmark, start, end)
    except Exception:
        pass
    
    # Run backtests
    bt = QuickBacktest(df, benchmark_df)
    results = bt.run_all()
    
    # Calculate summary stats
    current_price = df["close"].iloc[-1]
    return_1d = df["return_1d"].iloc[-1] if len(df) > 1 else 0
    return_5d = df["return_5d"].iloc[-1] if len(df) > 5 else 0
    return_1m = df["return_20d"].iloc[-1] if len(df) > 20 else 0
    return_3m = df["return_60d"].iloc[-1] if len(df) > 60 else 0
    ytd_start = f"{datetime.now().year}-01-01"
    ytd_return = 0
    try:
        ytd_df = df[df["date"] >= ytd_start]
        if len(ytd_df) > 1:
            ytd_return = ytd_df["close"].iloc[-1] / ytd_df["close"].iloc[0] - 1
    except Exception:
        pass
    
    max_drawdown = df["drawdown"].min()
    vol_20d = df["volatility_20d"].iloc[-1] if "volatility_20d" in df.columns else 0
    
    # Generate charts
    price_chart = _create_price_chart(df, symbol, signals)
    backtest_chart = _create_backtest_chart(results, symbol, benchmark)
    
    # Generate HTML
    html = _render_html(
        symbol=symbol,
        info=info,
        current_price=current_price,
        return_1d=return_1d,
        return_5d=return_5d,
        return_1m=return_1m,
        return_3m=return_3m,
        ytd_return=ytd_return,
        max_drawdown=max_drawdown,
        vol_20d=vol_20d,
        themes=themes,
        signals=signals,
        results=results,
        price_chart=price_chart,
        backtest_chart=backtest_chart,
        benchmark=benchmark,
    )
    
    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = REPORTS_DIR / f"{symbol}_terminal_{timestamp}.html"
    with open(output_path, "w") as f:
        f.write(html)
    
    # Also save as latest
    latest_path = REPORTS_DIR / f"{symbol}_terminal.html"
    with open(latest_path, "w") as f:
        f.write(html)
    
    return str(latest_path)


def _create_price_chart(df: pd.DataFrame, symbol: str, signals: list) -> str:
    """Create price chart with Plotly."""
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
        subplot_titles=(f"{symbol} Price", "Volume")
    )
    
    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=symbol,
            increasing_line_color="#00d4aa",
            decreasing_line_color="#ff5252",
        ),
        row=1, col=1
    )
    
    # Moving averages
    if "ma20" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"], y=df["ma20"],
                name="MA20", line=dict(color="#ffab40", width=1)
            ),
            row=1, col=1
        )
    if "ma60" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"], y=df["ma60"],
                name="MA60", line=dict(color="#42a5f5", width=1)
            ),
            row=1, col=1
        )
    
    # Signal markers
    for sig in signals:
        sig_date = pd.to_datetime(sig["date"])
        sig_row = df[df["date"] == sig_date]
        if len(sig_row) > 0:
            color = "#ff5252" if sig.get("level") == "HIGH" else "#ffab40" if sig.get("level") == "MEDIUM" else "#66bb6a"
            fig.add_trace(
                go.Scatter(
                    x=[sig_date],
                    y=[sig_row["low"].iloc[0] * 0.98],
                    mode="markers+text",
                    marker=dict(size=12, color=color, symbol="triangle-up"),
                    text=[sig.get("label", "")],
                    textposition="bottom center",
                    name=sig.get("label", "Signal"),
                ),
                row=1, col=1
            )
    
    # Volume
    colors = ["#00d4aa" if c >= o else "#ff5252" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(
        go.Bar(x=df["date"], y=df["volume"], name="Volume", marker_color=colors, opacity=0.5),
        row=2, col=1
    )
    
    fig.update_layout(
        height=600,
        template="plotly_dark",
        paper_bgcolor="#0a0a1a",
        plot_bgcolor="#0a0a1a",
        showlegend=False,
        xaxis_rangeslider_visible=False,
        margin=dict(l=50, r=50, t=30, b=30),
    )
    
    fig.update_xaxes(gridcolor="#1a1a2e", zerolinecolor="#1a1a2e")
    fig.update_yaxes(gridcolor="#1a1a2e", zerolinecolor="#1a1a2e")
    
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _create_backtest_chart(results: dict, symbol: str, benchmark: str) -> str:
    """Create backtest comparison chart."""
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        subplot_titles=("Equity Curve", "Drawdown")
    )
    
    colors = {
        "buy_and_hold": "#00d4aa",
        "ma_cross_20_60": "#42a5f5",
        "momentum_20d": "#ffab40",
        "mean_reversion_20d": "#ab47bc",
    }
    
    for name, result in results.items():
        color = colors.get(name, "#666666")
        fig.add_trace(
            go.Scatter(
                x=result.equity_curve.index,
                y=result.equity_curve.values,
                name=result.name,
                line=dict(color=color, width=1.5),
            ),
            row=1, col=1
        )
        
        # Drawdown
        cummax = result.equity_curve.cummax()
        dd = (result.equity_curve - cummax) / cummax
        fig.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd.values,
                name=f"{result.name} DD",
                fill="tozeroy",
                fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.2)",
                line=dict(color=color, width=1),
                showlegend=False,
            ),
            row=2, col=1
        )
    
    fig.update_layout(
        height=500,
        template="plotly_dark",
        paper_bgcolor="#0a0a1a",
        plot_bgcolor="#0a0a1a",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=50, b=30),
    )
    
    fig.update_xaxes(gridcolor="#1a1a2e", zerolinecolor="#1a1a2e")
    fig.update_yaxes(gridcolor="#1a1a2e", zerolinecolor="#1a1a2e")
    
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _render_html(
    symbol, info, current_price,
    return_1d, return_5d, return_1m, return_3m, ytd_return,
    max_drawdown, vol_20d, themes, signals, results,
    price_chart, backtest_chart, benchmark
) -> str:
    """Render final HTML report."""
    
    # Format returns
    def fmt_pct(v):
        color = "#00d4aa" if v >= 0 else "#ff5252"
        sign = "+" if v >= 0 else ""
        return f'<span style="color:{color}">{sign}{v:.1%}</span>'
    
    # Backtest table rows
    bt_rows = ""
    for name, r in results.items():
        bt_rows += f"""
        <tr>
            <td>{r.name}</td>
            <td>{r.total_return:.1%}</td>
            <td>{r.max_drawdown:.1%}</td>
            <td>{r.sharpe_ratio:.2f}</td>
            <td>{r.win_rate:.1%}</td>
            <td>{r.excess_return:.1%}</td>
            <td>{r.total_trades}</td>
        </tr>
        """
    
    # Themes
    themes_html = "".join(f'<span class="theme-tag">{t}</span>' for t in themes) if themes else '<span style="color:#666">None linked</span>'
    
    # Signals
    signals_html = ""
    if signals:
        for s in signals:
            level = s.get("level", "MEDIUM")
            color = "#ff5252" if level == "HIGH" else "#ffab40" if level == "MEDIUM" else "#66bb6a"
            signals_html += f"""
            <div class="signal-item">
                <span class="signal-date">{s['date']}</span>
                <span class="signal-level" style="color:{color}">{level}</span>
                <span class="signal-label">{s.get('label', '')}</span>
            </div>
            """
    else:
        signals_html = '<span style="color:#666">No signals recorded</span>'
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hermes Research Terminal - {symbol}</title>
    <script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', -apple-system, sans-serif; background: #0a0a1a; color: #e0e0e0; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 20px; border-bottom: 1px solid #1a1a2e; }}
        .header h1 {{ font-size: 24px; color: #00d4aa; }}
        .header .subtitle {{ color: #666; font-size: 14px; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 15px; margin-bottom: 20px; }}
        .stat-card {{ background: #16213e; padding: 15px; border-radius: 8px; border: 1px solid #1a1a2e; }}
        .stat-card .label {{ font-size: 11px; color: #666; text-transform: uppercase; }}
        .stat-card .value {{ font-size: 20px; font-weight: bold; margin-top: 5px; }}
        .card {{ background: #16213e; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #1a1a2e; }}
        .card h2 {{ font-size: 16px; color: #00d4aa; margin-bottom: 15px; }}
        .theme-tag {{ display: inline-block; background: rgba(0,212,170,0.15); color: #00d4aa; padding: 4px 12px; border-radius: 20px; font-size: 12px; margin: 2px; }}
        .signal-item {{ display: flex; gap: 15px; align-items: center; padding: 8px 0; border-bottom: 1px solid #1a1a2e; }}
        .signal-date {{ color: #666; font-size: 12px; min-width: 80px; }}
        .signal-level {{ font-weight: bold; font-size: 12px; min-width: 60px; }}
        .signal-label {{ font-size: 13px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #1a1a2e; padding: 10px; text-align: left; font-size: 11px; color: #666; text-transform: uppercase; }}
        td {{ padding: 10px; border-bottom: 1px solid #1a1a2e; font-size: 13px; }}
        .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>{info.get('name', symbol)} ({symbol})</h1>
                <div class="subtitle">{info.get('sector', '')} · {info.get('industry', '')} · Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
            </div>
            <div style="text-align:right">
                <div style="font-size:28px;font-weight:bold">${current_price:.2f}</div>
                <div style="font-size:14px">{fmt_pct(return_1d)} today</div>
            </div>
        </div>
        
        <div class="grid">
            <div class="stat-card">
                <div class="label">1D Return</div>
                <div class="value">{fmt_pct(return_1d)}</div>
            </div>
            <div class="stat-card">
                <div class="label">5D Return</div>
                <div class="value">{fmt_pct(return_5d)}</div>
            </div>
            <div class="stat-card">
                <div class="label">1M Return</div>
                <div class="value">{fmt_pct(return_1m)}</div>
            </div>
            <div class="stat-card">
                <div class="label">YTD Return</div>
                <div class="value">{fmt_pct(ytd_return)}</div>
            </div>
            <div class="stat-card">
                <div class="label">3M Return</div>
                <div class="value">{fmt_pct(return_3m)}</div>
            </div>
            <div class="stat-card">
                <div class="label">Max Drawdown</div>
                <div class="value" style="color:#ff5252">{max_drawdown:.1%}</div>
            </div>
            <div class="stat-card">
                <div class="label">20D Volatility</div>
                <div class="value">{vol_20d:.1%}</div>
            </div>
            <div class="stat-card">
                <div class="label">Themes</div>
                <div class="value" style="font-size:12px">{themes_html}</div>
            </div>
        </div>
        
        <div class="card">
            <h2>Price Chart</h2>
            {price_chart}
        </div>
        
        <div class="two-col">
            <div class="card">
                <h2>Hermes Signals</h2>
                {signals_html}
            </div>
            <div class="card">
                <h2>Quick Backtest vs {benchmark}</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Strategy</th>
                            <th>Return</th>
                            <th>Max DD</th>
                            <th>Sharpe</th>
                            <th>Win Rate</th>
                            <th>Excess</th>
                            <th>Trades</th>
                        </tr>
                    </thead>
                    <tbody>
                        {bt_rows}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="card">
            <h2>Backtest Equity Curves</h2>
            {backtest_chart}
        </div>
    </div>
</body>
</html>"""
