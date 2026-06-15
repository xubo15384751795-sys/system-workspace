#!/usr/bin/env python3
"""
Hermes Visualization Layer - Report Generator

Generates professional-grade charts for:
- Backtest Lens (Plotly)
- MDKX Attribution Lens (ECharts)

Usage:
    python3 generate_report.py                    # Generate all reports
    python3 generate_report.py --type backtest    # Generate backtest report only
    python3 generate_report.py --type mdkx        # Generate MDKX report only
    python3 generate_report.py --export png       # Export as PNG
"""

import json
import argparse
from pathlib import Path
from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
TEMPLATES_DIR = BASE_DIR / "templates"

# Ensure output directory exists
OUTPUT_DIR.mkdir(exist_ok=True)


def load_backtest_data():
    """Load backtest data from files."""
    with open(DATA_DIR / "backtest_summary.json") as f:
        summary = json.load(f)
    
    portfolio_curve = pd.read_csv(DATA_DIR / "portfolio_curve.csv")
    portfolio_curve['date'] = pd.to_datetime(portfolio_curve['date'])
    
    event_results = pd.read_csv(DATA_DIR / "event_results.csv")
    event_results['date'] = pd.to_datetime(event_results['date'])
    
    return summary, portfolio_curve, event_results


def load_mdkx_data():
    """Load MDKX attribution data."""
    with open(DATA_DIR / "mdkx_attribution.json") as f:
        return json.load(f)


def generate_backtest_lens(summary, portfolio_curve, event_results):
    """Generate Backtest Lens report with Plotly."""
    
    # Create subplots
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            'Equity Curve: Strategy vs Benchmark',
            'Drawdown',
            'Monthly Returns Heatmap',
            'Event Returns Distribution',
            'Best Events',
            'Worst Events'
        ),
        specs=[
            [{"type": "scatter"}, {"type": "scatter"}],
            [{"type": "heatmap"}, {"type": "histogram"}],
            [{"type": "table"}, {"type": "table"}]
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.1
    )
    
    # 1. Equity Curve
    fig.add_trace(
        go.Scatter(
            x=portfolio_curve['date'],
            y=portfolio_curve['strategy'] / 1000000,
            name='Strategy',
            line=dict(color='#00d4aa', width=2),
            hovertemplate='%{x|%Y-%m-%d}<br>Strategy: %{y:.2f}x<extra></extra>'
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=portfolio_curve['date'],
            y=portfolio_curve['benchmark'] / 1000000,
            name='Benchmark (SPY)',
            line=dict(color='#666666', width=1, dash='dash'),
            hovertemplate='%{x|%Y-%m-%d}<br>Benchmark: %{y:.2f}x<extra></extra>'
        ),
        row=1, col=1
    )
    
    # 2. Drawdown
    fig.add_trace(
        go.Scatter(
            x=portfolio_curve['date'],
            y=portfolio_curve['drawdown'] * 100,
            name='Drawdown',
            fill='tozeroy',
            fillcolor='rgba(255, 82, 82, 0.3)',
            line=dict(color='#ff5252', width=1),
            hovertemplate='%{x|%Y-%m-%d}<br>Drawdown: %{y:.1f}%<extra></extra>'
        ),
        row=1, col=2
    )
    
    # 3. Monthly Returns Heatmap
    monthly_returns = summary['monthly_returns']
    months = sorted(monthly_returns.keys())
    years = sorted(set(m[:4] for m in months))
    
    # Create heatmap data
    heatmap_data = []
    for year in years:
        year_returns = []
        for month_num in range(1, 13):
            key = f"{year}-{month_num:02d}"
            year_returns.append(monthly_returns.get(key, 0) * 100)
        heatmap_data.append(year_returns)
    
    fig.add_trace(
        go.Heatmap(
            z=heatmap_data,
            x=['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
            y=years,
            colorscale='RdYlGn',
            zmid=0,
            hovertemplate='%{y} %{x}<br>Return: %{z:.1f}%<extra></extra>'
        ),
        row=2, col=1
    )
    
    # 4. Event Returns Distribution
    fig.add_trace(
        go.Histogram(
            x=event_results['excess_return'] * 100,
            nbinsx=15,
            name='Excess Returns',
            marker_color='#00d4aa',
            opacity=0.8,
            hovertemplate='Excess Return: %{x:.1f}%<br>Count: %{y}<extra></extra>'
        ),
        row=2, col=2
    )
    
    # 5. Best Events Table
    best_events = event_results.nlargest(5, 'excess_return')
    fig.add_trace(
        go.Table(
            header=dict(
                values=['Date', 'Event', 'Signal', 'Excess Return', 'Regime'],
                fill_color='#1a1a2e',
                font=dict(color='white', size=11),
                align='left'
            ),
            cells=dict(
                values=[
                    best_events['date'].dt.strftime('%Y-%m-%d'),
                    best_events['description'],
                    best_events['signal_level'],
                    [f"{r:.1f}%" for r in best_events['excess_return'] * 100],
                    best_events['regime']
                ],
                fill_color='#16213e',
                font=dict(color='#e0e0e0', size=10),
                align='left'
            )
        ),
        row=3, col=1
    )
    
    # 6. Worst Events Table
    worst_events = event_results.nsmallest(5, 'excess_return')
    fig.add_trace(
        go.Table(
            header=dict(
                values=['Date', 'Event', 'Signal', 'Excess Return', 'Regime'],
                fill_color='#1a1a2e',
                font=dict(color='white', size=11),
                align='left'
            ),
            cells=dict(
                values=[
                    worst_events['date'].dt.strftime('%Y-%m-%d'),
                    worst_events['description'],
                    worst_events['signal_level'],
                    [f"{r:.1f}%" for r in worst_events['excess_return'] * 100],
                    worst_events['regime']
                ],
                fill_color='#16213e',
                font=dict(color='#e0e0e0', size=10),
                align='left'
            )
        ),
        row=3, col=2
    )
    
    # Update layout
    fig.update_layout(
        title=dict(
            text='Hermes Backtest Lens',
            font=dict(size=24, color='#00d4aa'),
            x=0.5
        ),
        height=1200,
        width=1400,
        template='plotly_dark',
        paper_bgcolor='#0a0a1a',
        plot_bgcolor='#0a0a1a',
        showlegend=True,
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1
        )
    )
    
    # Update axes
    fig.update_xaxes(gridcolor='#1a1a2e', zerolinecolor='#1a1a2e')
    fig.update_yaxes(gridcolor='#1a1a2e', zerolinecolor='#1a1a2e')
    
    # Add summary stats as annotation
    stats_text = (
        f"<b>Strategy Performance</b><br>"
        f"Total Return: {summary['summary']['total_return']:.1%}<br>"
        f"Annual Return: {summary['summary']['annual_return']:.1%}<br>"
        f"Sharpe Ratio: {summary['summary']['sharpe_ratio']:.2f}<br>"
        f"Max Drawdown: {summary['summary']['max_drawdown']:.1%}<br>"
        f"Alpha: {summary['summary']['alpha']:.1%}<br>"
        f"Win Rate: {summary['summary']['win_rate']:.1%}"
    )
    
    fig.add_annotation(
        text=stats_text,
        xref='paper', yref='paper',
        x=0.02, y=0.98,
        showarrow=False,
        font=dict(size=12, color='#00d4aa'),
        bgcolor='rgba(26, 26, 46, 0.8)',
        bordercolor='#00d4aa',
        borderwidth=1,
        borderpad=10,
        align='left'
    )
    
    return fig


def generate_mdkx_lens(mdkx_data):
    """Generate MDKX Attribution Lens report with ECharts."""
    
    channels = mdkx_data['channels']
    attribution = mdkx_data['attribution']
    watchlist = mdkx_data['watchlist']
    
    # Generate watchlist HTML
    watchlist_rows = []
    for item in watchlist:
        priority_class = f"priority-{item['priority'].lower()}"
        row = f"""
        <tr>
            <td class="{priority_class}">{item['priority']}</td>
            <td>{item['channel']}</td>
            <td>{item['variable']}</td>
            <td>{item['threshold']}</td>
            <td>{item['current']}</td>
            <td>{item['action']}</td>
        </tr>
        """
        watchlist_rows.append(row)
    watchlist_html = ''.join(watchlist_rows)
    
    # Create HTML with ECharts
    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hermes MDKX Attribution Lens</title>
    <script src="echarts.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #0a0a1a;
            color: #e0e0e0;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-size: 28px;
            color: #00d4aa;
            margin-bottom: 10px;
        }}
        .header .subtitle {{
            font-size: 14px;
            color: #666;
        }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }}
        .card {{
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #1a1a2e;
        }}
        .card h2 {{
            font-size: 16px;
            color: #00d4aa;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #1a1a2e;
        }}
        .chart {{
            width: 100%;
            height: 400px;
        }}
        .regime-card {{
            background: linear-gradient(135deg, #16213e 0%, #0a0a1a 100%);
            border: 2px solid #00d4aa;
        }}
        .regime-label {{
            font-size: 32px;
            font-weight: bold;
            color: #00d4aa;
            text-align: center;
            padding: 20px;
        }}
        .regime-details {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 15px;
        }}
        .regime-item {{
            background: rgba(0, 212, 170, 0.1);
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }}
        .regime-item .label {{
            font-size: 11px;
            color: #666;
            margin-bottom: 5px;
        }}
        .regime-item .value {{
            font-size: 18px;
            font-weight: bold;
            color: #00d4aa;
        }}
        .watchlist-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .watchlist-table th {{
            background: #1a1a2e;
            padding: 12px;
            text-align: left;
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .watchlist-table td {{
            padding: 12px;
            border-bottom: 1px solid #1a1a2e;
            font-size: 13px;
        }}
        .priority-p0 {{
            color: #ff5252;
            font-weight: bold;
        }}
        .priority-p1 {{
            color: #ffab40;
            font-weight: bold;
        }}
        .priority-p2 {{
            color: #66bb6a;
            font-weight: bold;
        }}
        .full-width {{
            grid-column: 1 / -1;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Hermes MDKX Attribution Lens</h1>
            <div class="subtitle">
                Run Date: {mdkx_data['metadata']['run_date']} | 
                Regime: {mdkx_data['metadata']['regime']} | 
                Sigma: {mdkx_data['metadata']['sigma']:.3f}
            </div>
        </div>
        
        <div class="grid">
            <!-- Radar Chart -->
            <div class="card">
                <h2>M/D/K/X Channel Scores</h2>
                <div id="radar" class="chart"></div>
            </div>
            
            <!-- Contribution Waterfall -->
            <div class="card">
                <h2>Channel Contributions</h2>
                <div id="waterfall" class="chart"></div>
            </div>
            
            <!-- Regime Card -->
            <div class="card regime-card">
                <h2>Current Regime</h2>
                <div class="regime-label">{mdkx_data['metadata']['regime']}</div>
                <div class="regime-details">
                    <div class="regime-item">
                        <div class="label">Sigma</div>
                        <div class="value">{mdkx_data['metadata']['sigma']:.3f}</div>
                    </div>
                    <div class="regime-item">
                        <div class="label">Leading Channel</div>
                        <div class="value">M</div>
                    </div>
                    <div class="regime-item">
                        <div class="label">Singular Flag</div>
                        <div class="value">No</div>
                    </div>
                    <div class="regime-item">
                        <div class="label">Escalation</div>
                        <div class="value">No</div>
                    </div>
                </div>
            </div>
            
            <!-- Component Breakdown -->
            <div class="card">
                <h2>Component Breakdown</h2>
                <div id="components" class="chart"></div>
            </div>
            
            <!-- Watchlist -->
            <div class="card full-width">
                <h2>Next Variables Watchlist</h2>
                <table class="watchlist-table">
                    <thead>
                        <tr>
                            <th>Priority</th>
                            <th>Channel</th>
                            <th>Variable</th>
                            <th>Threshold</th>
                            <th>Current</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {watchlist_html}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <script>
        // Radar Chart
        var radarChart = echarts.init(document.getElementById('radar'), 'dark');
        var radarOption = {{
            backgroundColor: 'transparent',
            radar: {{
                indicator: [
                    {{ name: 'M (Funding Mismatch)', max: 1, min: -1.5 }},
                    {{ name: 'D (Credit Depth)', max: 1, min: -1.5 }},
                    {{ name: 'K (Jump Instability)', max: 1, min: -1.5 }},
                    {{ name: 'X (Cross-Market)', max: 1, min: -1.5 }}
                ],
                shape: 'polygon',
                splitNumber: 4,
                axisName: {{
                    color: '#00d4aa',
                    fontSize: 12
                }},
                splitLine: {{
                    lineStyle: {{
                        color: '#1a1a2e'
                    }}
                }},
                splitArea: {{
                    show: true,
                    areaStyle: {{
                        color: ['rgba(0, 212, 170, 0.05)', 'rgba(0, 212, 170, 0.1)']
                    }}
                }},
                axisLine: {{
                    lineStyle: {{
                        color: '#1a1a2e'
                    }}
                }}
            }},
            series: [{{
                type: 'radar',
                data: [{{
                    value: [{channels['M']['score']}, {channels['D']['score']}, {channels['K']['score']}, {channels['X']['score']}],
                    name: 'Current',
                    areaStyle: {{
                        color: 'rgba(0, 212, 170, 0.3)'
                    }},
                    lineStyle: {{
                        color: '#00d4aa',
                        width: 2
                    }},
                    itemStyle: {{
                        color: '#00d4aa'
                    }}
                }}]
            }}]
        }};
        radarChart.setOption(radarOption);
        
        // Waterfall Chart
        var waterfallChart = echarts.init(document.getElementById('waterfall'), 'dark');
        var channels = ['M', 'D', 'K', 'X', 'Total'];
        var contributions = [
            {attribution['channel_contributions']['M']},
            {attribution['channel_contributions']['D']},
            {attribution['channel_contributions']['K']},
            {attribution['channel_contributions']['X']},
            {attribution['total_contribution']}
        ];
        var colors = contributions.map(v => v >= 0 ? '#00d4aa' : '#ff5252');
        
        var waterfallOption = {{
            backgroundColor: 'transparent',
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{
                    type: 'shadow'
                }},
                formatter: function(params) {{
                    return params[0].name + ': ' + params[0].value.toFixed(3);
                }}
            }},
            xAxis: {{
                type: 'category',
                data: channels,
                axisLabel: {{
                    color: '#666'
                }},
                axisLine: {{
                    lineStyle: {{
                        color: '#1a1a2e'
                    }}
                }}
            }},
            yAxis: {{
                type: 'value',
                axisLabel: {{
                    color: '#666'
                }},
                axisLine: {{
                    lineStyle: {{
                        color: '#1a1a2e'
                    }}
                }},
                splitLine: {{
                    lineStyle: {{
                        color: '#1a1a2e'
                    }}
                }}
            }},
            series: [{{
                type: 'bar',
                data: contributions.map((v, i) => ({{
                    value: v,
                    itemStyle: {{
                        color: colors[i],
                        borderRadius: [4, 4, 0, 0]
                    }}
                }})),
                barWidth: '40%'
            }}]
        }};
        waterfallChart.setOption(waterfallOption);
        
        // Components Chart
        var componentsChart = echarts.init(document.getElementById('components'), 'dark');
        var componentData = [];
        var componentNames = [];
        
        Object.keys(channels).forEach(ch => {{
            Object.keys(channels[ch].components).forEach(comp => {{
                componentNames.push(ch + ': ' + comp);
                componentData.push(channels[ch].components[comp]);
            }});
        }});
        
        var componentsOption = {{
            backgroundColor: 'transparent',
            tooltip: {{
                trigger: 'axis',
                axisPointer: {{
                    type: 'shadow'
                }}
            }},
            xAxis: {{
                type: 'value',
                axisLabel: {{
                    color: '#666'
                }},
                axisLine: {{
                    lineStyle: {{
                        color: '#1a1a2e'
                    }}
                }},
                splitLine: {{
                    lineStyle: {{
                        color: '#1a1a2e'
                    }}
                }}
            }},
            yAxis: {{
                type: 'category',
                data: componentNames,
                axisLabel: {{
                    color: '#666',
                    fontSize: 10
                }},
                axisLine: {{
                    lineStyle: {{
                        color: '#1a1a2e'
                    }}
                }}
            }},
            series: [{{
                type: 'bar',
                data: componentData.map(v => ({{
                    value: v,
                    itemStyle: {{
                        color: v >= 0 ? '#00d4aa' : '#ff5252',
                        borderRadius: [0, 4, 4, 0]
                    }}
                }})),
                barWidth: '60%'
            }}]
        }};
        componentsChart.setOption(componentsOption);
        
        // Handle resize
        window.addEventListener('resize', function() {{
            radarChart.resize();
            waterfallChart.resize();
            componentsChart.resize();
        }});
    </script>
</body>
</html>
"""
    
    return html_content


def main():
    parser = argparse.ArgumentParser(description='Hermes Visualization Layer - Report Generator')
    parser.add_argument('--type', choices=['backtest', 'mdkx', 'all'], default='all',
                       help='Type of report to generate')
    parser.add_argument('--export', choices=['html', 'png', 'svg', 'pdf'], default='html',
                       help='Export format')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Hermes Visualization Layer - Report Generator")
    print("=" * 60)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if args.type in ['backtest', 'all']:
        print("\n[1/2] Generating Backtest Lens...")
        summary, portfolio_curve, event_results = load_backtest_data()
        fig = generate_backtest_lens(summary, portfolio_curve, event_results)
        
        output_path = OUTPUT_DIR / f"backtest_lens_{timestamp}.html"
        fig.write_html(str(output_path))
        print(f"  ✅ Saved: {output_path}")
        
        if args.export == 'png':
            png_path = OUTPUT_DIR / f"backtest_lens_{timestamp}.png"
            fig.write_image(str(png_path), width=1400, height=1200, scale=2)
            print(f"  ✅ PNG: {png_path}")
    
    if args.type in ['mdkx', 'all']:
        print("\n[2/2] Generating MDKX Attribution Lens...")
        mdkx_data = load_mdkx_data()
        html_content = generate_mdkx_lens(mdkx_data)
        
        output_path = OUTPUT_DIR / f"mdkx_lens_{timestamp}.html"
        with open(output_path, 'w') as f:
            f.write(html_content)
        print(f"  ✅ Saved: {output_path}")
    
    print("\n" + "=" * 60)
    print("✅ All reports generated successfully!")
    print(f"Output directory: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
