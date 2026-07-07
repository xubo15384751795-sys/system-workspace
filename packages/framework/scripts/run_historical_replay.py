from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.benchmarks import run_historical_replay


def main() -> None:
    metrics, signals, state_metrics = run_historical_replay()
    out_dir = Path("output/historical_replay")
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "warning_metrics.csv"
    signals_path = out_dir / "signals.csv"
    state_metrics_path = out_dir / "state_metrics.csv"
    metrics.to_csv(metrics_path, index=False)
    signals.to_csv(signals_path, index=False)
    state_metrics.to_csv(state_metrics_path, index=False)

    display = metrics.copy()
    display["pre_event_coverage"] = (display["pre_event_coverage"] * 100).round(1)
    display["false_positive_rate"] = (display["false_positive_rate"] * 100).round(1)
    display["peak_pre_event"] = display["peak_pre_event"].round(2)
    display["event_value"] = display["event_value"].round(2)

    print("Warning metrics")
    print(display.to_string(index=False))
    print()
    print("Risk-state metrics")
    state_display = state_metrics.copy()
    state_display["state_false_positive_rate"] = (state_display["state_false_positive_rate"] * 100).round(1)
    print(state_display.to_string(index=False))
    print()
    print(f"Wrote {metrics_path}")
    print(f"Wrote {signals_path}")
    print(f"Wrote {state_metrics_path}")


if __name__ == "__main__":
    main()
