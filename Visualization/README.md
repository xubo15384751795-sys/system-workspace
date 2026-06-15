# Hermes Visualization Layer

**Purpose:** Professional-grade chart system for Market View, Backtest View, Structure View, and Report Export.

**Architecture:**
```
Visualization/
├── market_charts/        # TradingView Lightweight Charts
│   └── lightweight-charts/
├── backtest_charts/      # Plotly + QuantStats
│   ├── plotly/
│   └── quantstats/
├── structure_charts/     # Apache ECharts
│   └── echarts/
├── report_charts/        # Matplotlib/SVG
│   └── matplotlib/
├── templates/            # HTML templates
├── data/                 # Demo data
├── output/               # Generated reports
└── generate_report.py    # Main entry point
```

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Market View | TradingView Lightweight Charts | K线、成交量、指标、signal markers |
| Backtest View | Plotly + QuantStats | Equity curve、drawdown、event return |
| Structure View | Apache ECharts | M/D/K/X、contribution waterfall、regime map |
| Report Export | Matplotlib | PNG/SVG/PDF 静态图 |

## First Phase MVP

### A. Backtest Lens
- Equity curve
- Drawdown curve
- Event return bar chart
- Strategy vs benchmark
- Worst / best events table

### B. MDKX Attribution Lens
- M/D/K/X score radar or bar chart
- 每个通道的 variable contribution waterfall
- Regime label card
- Next variables watchlist

## Data Input

### Backtest Lens
- `data/backtest/results/portfolio_curve.csv`
- `data/backtest/results/event_results.csv`
- `data/backtest/results/summary.json`

### MDKX Attribution Lens
- `data/attribution/mdkx_attribution.json`
- `data/attribution/mdkx_attribution.md`

## Output

- HTML reports with interactive charts
- PNG/SVG/PDF static exports
- JSON data for API consumption

## Usage

```bash
# Generate all reports
python3 generate_report.py

# Generate specific report
python3 generate_report.py --type backtest
python3 generate_report.py --type mdkx
python3 generate_report.py --type all

# Export static images
python3 generate_report.py --export png
python3 generate_report.py --export svg
python3 generate_report.py --export pdf
```
