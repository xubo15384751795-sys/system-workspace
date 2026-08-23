from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = FRAMEWORK_ROOT.parents[1]

from src.benchmarks import run_historical_replay
from src.data_access.harvester_adapter import HarvesterAdapter


def _load_admitted_benchmark_frame(release_id: str) -> pd.DataFrame:
    """Load the replay input from a finalized local Harvester release.

    The archived replay must never fall back to a provider download. The
    bundle adapter validates catalog, manifest, hashes, and schema before this
    function reshapes the long benchmark panel for the legacy benchmark code.
    """
    adapter = HarvesterAdapter(
        exports_root=WORKSPACE_ROOT / "Data" / "harvester" / "exports",
        release=release_id,
        contract_root=WORKSPACE_ROOT / "packages" / "harvester" / "contracts",
        require_finalized=True,
        validate_hashes=True,
        validate_schema=True,
    )
    panel = adapter.load_bundle().benchmark_panel.copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    panel["value"] = pd.to_numeric(panel["value"], errors="coerce")
    panel = panel.dropna(subset=["date", "value"])
    aliases = {
        "VIXCLS": "FRED:VIXCLS",
        "BAA10Y": "FRED:BAA10YM",
        "NFCI": "FRED:NFCI",
    }
    available = set(panel["series_id"].astype(str))
    missing = [name for name, series_id in aliases.items() if series_id not in available]
    if missing:
        raise RuntimeError(
            "Admitted benchmark release is missing replay series: "
            + ", ".join(missing)
        )
    selected = panel[panel["series_id"].isin(aliases.values())]
    wide = selected.pivot_table(
        index="date", columns="series_id", values="value", aggfunc="last"
    )
    return wide.rename(columns={series_id: name for name, series_id in aliases.items()}).sort_index()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the archived replay against admitted Harvester evidence only."
    )
    parser.add_argument("--release", default="latest", help="Finalized Harvester release id")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=WORKSPACE_ROOT / "Output" / "research" / "historical_replay",
    )
    args = parser.parse_args(argv)

    raw = _load_admitted_benchmark_frame(args.release)
    metrics, signals, state_metrics = run_historical_replay(raw=raw)
    out_dir = args.output_root
    if not out_dir.is_absolute():
        out_dir = WORKSPACE_ROOT / out_dir
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
