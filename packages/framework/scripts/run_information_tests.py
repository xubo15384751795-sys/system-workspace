"""Run the four incremental-information tests against the panel.

Tests:
  A - information regression: Sigma vs NFCI/STLFSI4/KCFSI controls
  B - OOS forecast: Sigma_only vs controls_only vs Sigma+controls
  C - regime lead/lag: Sigma vs an event regime (default: VIX > 30 streaks)
  D - mechanism specificity: leading channel in named case windows

Inputs are taken from a merged benchmark panel CSV or from the legacy
historical replay fallback. New benchmark acquisition belongs in Structural
Risk Harvester. Outputs go to ``output/information_tests/``.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.benchmarks.historical_replay import (
    DEFAULT_CASES,
    build_structural_signals,
    fetch_default_fred_frame,
    weekly_frame,
)
from src.research.incremental_information import (
    IncrementalInformationReport,
    information_regression,
    mechanism_specificity,
    out_of_sample_forecast,
    regime_lead_lag,
)


# Expected leading channel per case (best-guess from the structural framework).
# Update these as the paper's Section 7.4.2 chains are validated.
CASE_EXPECTED_CHANNEL: dict[str, str] = {
    "ltcm_1998": "K",
    "cdo_credit_break_2007": "X",
    "lehman_2008": "D",
    "eurozone_2011": "X",
    "china_deval_2015": "K",
    "treasury_basis_2020": "D",
    "ldi_2022": "K",
    "svb_2023": "X",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--panel", default=None, help="Merged panel CSV (defaults to live fetch)")
    p.add_argument("--out-dir", default="output/information_tests")
    p.add_argument("--start", default="2000-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--horizon", type=int, default=20, help="Forecast horizon in observations (weekly)")
    p.add_argument("--train-end", default="2018-12-31")
    p.add_argument("--eval-start", default="2019-01-01")
    p.add_argument("--eval-end", default=None)
    return p.parse_args()


def _load_panel(path: str | None, start: str, end: str | None) -> pd.DataFrame:
    if path is not None:
        frame = pd.read_csv(path, index_col="date", parse_dates=True)
    else:
        print("Fetching default FRED panel ...")
        frame = fetch_default_fred_frame()
    frame = frame.sort_index()
    if start:
        frame = frame.loc[pd.Timestamp(start) :]
    if end:
        frame = frame.loc[: pd.Timestamp(end)]
    return frame


def _ensure_required_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Make sure replay's required columns exist; if not, raise with clear list."""
    required = {"VIXCLS", "TEDRATE", "BAMLH0A0HYM2", "NFCI"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(
            f"Panel missing required columns for replay: {sorted(missing)}. "
            "Provide an admitted benchmark panel from a Harvester release."
        )
    return frame


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    panel = _ensure_required_columns(_load_panel(args.panel, args.start, args.end))
    weekly = weekly_frame(panel, args.start, args.end or panel.index.max().date().isoformat())
    signals = build_structural_signals(weekly)
    sigma = signals["joint_structural"].rename("SIGMA")
    channels = signals[["M", "D", "K", "X"]]

    controls: dict[str, pd.Series] = {}
    for col in ("NFCI", "ANFCI", "STLFSI4", "KCFSI", "OFRFSI"):
        if col in weekly.columns:
            controls[col] = weekly[col]
    if not controls:
        raise ValueError("No control series available; need at least NFCI on the panel")

    test_a_results = []
    test_b_results = []

    targets = {"VIXCLS": weekly.get("VIXCLS"), "BAMLH0A0HYM2": weekly.get("BAMLH0A0HYM2")}
    for name, ts in targets.items():
        if ts is None:
            continue
        print(f"Test A: information regression on forward-{args.horizon} max of {name} ...")
        ra = information_regression(
            target=ts.rename(name),
            signal=sigma,
            controls=controls,
            horizon=args.horizon,
            signal_name="SIGMA",
        )
        test_a_results.append(ra)

        try:
            print(f"Test B: OOS forecast on {name} ...")
            rb = out_of_sample_forecast(
                target=ts.rename(name),
                signal=sigma,
                controls=controls,
                horizon=args.horizon,
                train_end=args.train_end,
                eval_start=args.eval_start,
                eval_end=args.eval_end,
            )
            test_b_results.append(rb)
        except Exception as exc:
            print(f"  Test B skipped for {name}: {exc}")

    print("Test C: regime lead/lag against VIX>30 ...")
    if "VIXCLS" in weekly.columns:
        regime_high_vix = (weekly["VIXCLS"] > 30).astype(int).rename("VIX_GT_30")
        rc_vix = regime_lead_lag(sigma, regime_high_vix, max_lag=20)
    else:
        rc_vix = None
    test_c_results = [rc_vix] if rc_vix is not None else []

    if "NFCI" in weekly.columns:
        regime_nfci = (weekly["NFCI"] > 0).astype(int).rename("NFCI_POS")
        test_c_results.append(regime_lead_lag(sigma, regime_nfci, max_lag=20))

    print("Test D: mechanism specificity per case ...")
    test_d_results = []
    for case in DEFAULT_CASES:
        expected = CASE_EXPECTED_CHANNEL.get(case.name, "K")
        try:
            rd = mechanism_specificity(
                case_name=case.name,
                channels=channels,
                sigma=sigma,
                window_start=case.start,
                window_end=case.end,
                expected_channel=expected,
            )
            test_d_results.append(rd)
        except Exception as exc:
            print(f"  Skipped case {case.name}: {exc}")

    report = IncrementalInformationReport(
        test_a=tuple(test_a_results),
        test_b=tuple(test_b_results),
        test_c=tuple(test_c_results),
        test_d=tuple(test_d_results),
    )

    summary = report.to_summary_frame()
    summary_path = out_dir / "summary.csv"
    summary.to_csv(summary_path, index=False)

    detail = {
        "test_a": [
            {
                "target": r.target_name,
                "horizon": r.horizon,
                "n_obs": r.n_obs,
                "r_squared": r.r_squared,
                "r_squared_controls_only": r.r_squared_controls_only,
                "incremental_r_squared": r.incremental_r_squared,
                "terms": [asdict(t) for t in r.terms],
                "notes": r.notes,
            }
            for r in report.test_a
        ],
        "test_b": [
            {
                "target": r.target_name,
                "horizon": r.horizon,
                "n_train": r.n_train,
                "n_eval": r.n_eval,
                "winner": r.winner,
                "metrics_per_model": r.metrics_per_model,
            }
            for r in report.test_b
        ],
        "test_c": [
            {
                "signal": r.signal_name,
                "regime": r.regime_name,
                "best_lag": r.best_lag,
                "best_correlation": r.best_correlation,
                "median_lead_days": r.median_lead_days,
                "n_regimes": r.n_regimes,
            }
            for r in report.test_c
        ],
        "test_d": [
            {
                "case": r.case_name,
                "expected": r.expected_leading_channel,
                "observed": r.observed_leading_channel,
                "matches": r.matches_expectation,
                "dominance": r.channel_dominance,
                "leading_share": r.leading_channel_share,
                "sigma_at_event": r.sigma_at_event,
            }
            for r in report.test_d
        ],
    }
    detail_path = out_dir / "detail.json"
    detail_path.write_text(json.dumps(detail, indent=2, default=str), encoding="utf-8")

    print()
    print(summary.to_string(index=False))
    print()
    print(f"Wrote {summary_path}")
    print(f"Wrote {detail_path}")


if __name__ == "__main__":
    main()
