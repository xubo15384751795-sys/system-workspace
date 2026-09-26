"""Strategy Lab — connect M/D/K/X signals to tradeable strategies.

Core positioning: System = structural state identification + risk sizing layer.
It does NOT predict direction. It answers:
  - Is now a good time to trade?
  - Should position size be reduced?
  - Which strategy regime fits the current structural state?

Usage:
    python scripts/strategy_lab/run_backtest.py
    python scripts/strategy_lab/run_backtest.py --start 2010-01-01 --end 2025-12-31
    python scripts/strategy_lab/run_backtest.py --shadow-card  # generate today's card
"""
from __future__ import annotations
