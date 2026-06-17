#!/usr/bin/env python3
"""Generate historical HMM fits for stability assessment.

This script runs the HMM on different historical windows to build
more data points for rolling refit and label stability calculations.

Usage:
    python3 scripts/hmm_generate_history.py
    python3 scripts/hmm_generate_history.py --windows 5 10 20

Output:
    Output/ml_signals/harvester_YYYY-MM-DD/
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HMM_DIR = ROOT / "Output" / "ml_signals"
BP_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"


def run_hmm_for_window(years_back: int) -> dict | None:
    """Run HMM for a specific historical window."""
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=years_back * 365)
    
    tag = f"harvester_{years_back}yr_window"
    output_dir = HMM_DIR / tag
    
    # Run regime detection
    cmd = [
        sys.executable, "-c",
        f"from pathlib import Path; from ml.regime_detector import detect_regime; "
        f"detect_regime(Path('Data/harvester/exports/latest/data/benchmark_panel.parquet'), "
        f"source_release='{tag}', source_created_at='{end_date.strftime('%Y-%m-%d')}', write=True)",
    ]
    
    env = {"PYTHONPATH": str(ROOT / "Workbench" / "src")}
    merged_env = {**dict(__import__('os').environ), **env}
    
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(ROOT), env=merged_env,
        )
        
        if result.returncode == 0:
            hmm_file = output_dir / "regime_hmm.json"
            if hmm_file.exists():
                return json.loads(hmm_file.read_text())
    except Exception as e:
        print(f"Error running HMM for {years_back}yr: {e}")
    
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate historical HMM fits.")
    parser.add_argument("--windows", nargs="+", type=int, default=[1, 2, 3, 5, 10],
                        help="Historical windows in years")
    args = parser.parse_args()
    
    print(f"Generating HMM fits for windows: {args.windows}")
    
    results = []
    for years in args.windows:
        print(f"\nRunning HMM for {years}yr window...")
        result = run_hmm_for_window(years)
        if result:
            regime = result.get("regime", {})
            print(f"  Regime: {regime.get('current')}")
            print(f"  Probability: {regime.get('probability')}")
            results.append({"years": years, "regime": regime.get("current"), "probability": regime.get("probability")})
        else:
            print(f"  Failed")
    
    # Summary
    print(f"\n=== Summary ===")
    print(f"Generated {len(results)} HMM fits")
    regimes = [r["regime"] for r in results]
    from collections import Counter
    regime_counts = Counter(regimes)
    print(f"Regime distribution: {dict(regime_counts)}")
    
    # Stability assessment
    if len(results) >= 2:
        agreements = sum(1 for i in range(1, len(results)) if results[i]["regime"] == results[i-1]["regime"])
        stability = agreements / (len(results) - 1)
        print(f"Label stability: {stability:.3f}")


if __name__ == "__main__":
    main()
