"""Four-layer test runner — orchestrates all test layers.

Layer 1: Data tests (future function, missing data, frequency, survivorship)
Layer 2: Signal tests (variance, regime distribution, persistence, independence)
Layer 3: Strategy tests (baseline vs overlay comparison — the backtest itself)
Layer 4: Shadow trading (forward-looking decision cards with outcome tracking)

Usage:
    python scripts/strategy_lab/test_runner.py
    python scripts/strategy_lab/test_runner.py --start 2010-01-01
    python scripts/strategy_lab/test_runner.py --layer 1  # only data tests
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np


from scripts import _runtime_io as rio
from scripts.strategy_lab.backtest import run_comparison
from scripts.strategy_lab.data_loader import load_aligned
from scripts.strategy_lab.data_tests import run_data_tests
from scripts.strategy_lab.report import save_report
from scripts.strategy_lab.risk_gate import compute_position_series
from scripts.strategy_lab.shadow_card import generate_shadow_card, save_shadow_card
from scripts.strategy_lab.signal_tests import run_signal_tests
from scripts.strategy_lab.strategies import (
    compute_baseline_position,
    compute_system_overlay_position,
)

OUTPUT_DIR = rio.ROOT / "Output" / "strategy_lab"


def run_all_layers(
    start: str | None = None,
    end: str | None = None,
    lookback: int = 63,
    layers: list[int] | None = None,
) -> dict:
    """Run all four test layers.

    Returns:
        Dict with results from each layer.
    """
    if layers is None:
        layers = [1, 2, 3, 4]

    results = {"timestamp": datetime.now(UTC).isoformat(), "layers": {}}

    # Load data
    data = load_aligned(start=start, end=end)
    results["data_info"] = {
        "n_days": len(data),
        "start_date": str(data.index[0].date()),
        "end_date": str(data.index[-1].date()),
    }

    # Layer 1: Data tests
    if 1 in layers:
        print("Layer 1: Data quality tests...")
        data_test_results = run_data_tests(data)
        results["layers"]["data_tests"] = [
            {"name": r.name, "passed": bool(r.passed), "severity": r.severity, "message": r.message}
            for r in data_test_results
        ]
        n_pass = sum(1 for r in data_test_results if r.passed)
        print(f"  {n_pass}/{len(data_test_results)} passed")
        for r in data_test_results:
            if not r.passed:
                print(f"  ❌ {r.name}: {r.message}")

    # Layer 2: Signal tests
    if 2 in layers:
        print("Layer 2: Signal quality tests...")
        signal_test_results = run_signal_tests(data)
        results["layers"]["signal_tests"] = [
            {"name": r.name, "passed": bool(r.passed), "severity": r.severity, "message": r.message}
            for r in signal_test_results
        ]
        n_pass = sum(1 for r in signal_test_results if r.passed)
        print(f"  {n_pass}/{len(signal_test_results)} passed")
        for r in signal_test_results:
            if not r.passed:
                print(f"  ⚠️ {r.name}: {r.message}")

    # Layer 3: Strategy tests (backtest)
    if 3 in layers:
        print("Layer 3: Strategy backtest...")
        baseline_pos = compute_baseline_position(data["close"], lookback=lookback)
        risk_pos = compute_position_series(data[["M", "D", "K", "X"]])
        overlay_pos = compute_system_overlay_position(baseline_pos, risk_pos["position_size"])
        comparison = run_comparison(data["return_1d"], baseline_pos, overlay_pos)
        results["layers"]["strategy_tests"] = comparison
        save_report(comparison)
        print(f"  Baseline Sharpe: {comparison['baseline']['sharpe']:.3f}")
        print(f"  Overlay Sharpe:  {comparison['overlay']['sharpe']:.3f}")
        print(f"  Max DD delta:    {comparison['comparison']['max_dd_delta']:+.2%}")

    # Layer 4: Shadow trading (today's card)
    if 4 in layers:
        print("Layer 4: Shadow decision card...")
        card = generate_shadow_card()
        path = save_shadow_card(card)
        results["layers"]["shadow_card"] = card
        print(f"  Card saved: {path}")
        print(f"  Regime: {card['risk_gate']['regime']}")
        print(f"  Position: {card['risk_gate']['position_size']}x")

    # Save full test results
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    test_path = OUTPUT_DIR / "test_results.json"

    def _default(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    test_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=_default) + "\n",
        encoding="utf-8",
    )
    print(f"\nFull results saved to {test_path}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy Lab four-layer test runner")
    parser.add_argument("--start", type=str, default=None)
    parser.add_argument("--end", type=str, default=None)
    parser.add_argument("--lookback", type=int, default=63)
    parser.add_argument("--layer", type=int, nargs="*", help="Run specific layers (1-4)")
    args = parser.parse_args()

    layers = args.layer if args.layer else [1, 2, 3, 4]
    run_all_layers(start=args.start, end=args.end, lookback=args.lookback, layers=layers)


if __name__ == "__main__":
    main()
