#!/usr/bin/env python3
"""Build Qlib ↔ structural bridge report (validation-only).

Compares isolated ML experiment metrics (LightGBM baseline vs +deformation)
with Strategy Lab backtest overlay stats. Does not modify core proxies or
judgment inputs.

Usage:
    python3 scripts/build_qlib_structural_bridge.py
    python3 scripts/build_qlib_structural_bridge.py --json

Output:
    Output/validation/qlib_structural_bridge.json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from _runtime_io import ROOT, ensure_dir, load_json, write_json

QLIB_EXPERIMENT = ROOT / "Output" / "strategy_lab" / "qlib_experiment" / "lightgbm_experiment.json"
BACKTEST_RESULT = ROOT / "Output" / "strategy_lab" / "backtest_result.json"
OUTPUT_PATH = ROOT / "Output" / "validation" / "qlib_structural_bridge.json"


def _anti_gaming_checks(experiment: dict[str, Any] | None, backtest: dict[str, Any] | None) -> list[str]:
    """Surface validation-only guardrails."""
    checks: list[str] = []
    if experiment:
        delta_auc = (experiment.get("delta") or {}).get("auc")
        if delta_auc is not None and delta_auc > 0.15:
            checks.append("large_auc_delta_review_required")
        n_test = experiment.get("n_test", 0)
        if isinstance(n_test, int) and n_test < 100:
            checks.append("insufficient_oos_samples")
    if backtest:
        comp = backtest.get("comparison") or {}
        if comp.get("return_delta") is not None and abs(comp["return_delta"]) > 0.5:
            checks.append("extreme_return_delta_review_required")
    if not experiment and not backtest:
        checks.append("no_source_artifacts")
    return checks


def build_bridge_report() -> dict[str, Any]:
    experiment = load_json(QLIB_EXPERIMENT)
    backtest = load_json(BACKTEST_RESULT)
    checks = _anti_gaming_checks(experiment, backtest)

    deform_adds_value = None
    if experiment:
        deform_adds_value = (experiment.get("delta") or {}).get("auc", 0) > 0

    overlay_improves = None
    if backtest:
        comp = backtest.get("comparison") or {}
        overlay_improves = comp.get("sharpe_delta", 0) > 0

    return {
        "schema_version": "validation.qlib_structural_bridge.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "allowed_use": "validation_only",
        "can_affect_core_judgment": False,
        "can_affect_trade_decision": False,
        "sources": {
            "qlib_experiment": str(QLIB_EXPERIMENT.relative_to(ROOT)) if QLIB_EXPERIMENT.exists() else None,
            "strategy_lab_backtest": str(BACKTEST_RESULT.relative_to(ROOT)) if BACKTEST_RESULT.exists() else None,
        },
        "experiment_summary": {
            "baseline_auc": (experiment or {}).get("baseline", {}).get("auc"),
            "treatment_auc": (experiment or {}).get("treatment", {}).get("auc"),
            "delta_auc": (experiment or {}).get("delta", {}).get("auc"),
            "deformation_features_add_value": deform_adds_value,
        }
        if experiment
        else None,
        "backtest_summary": {
            "return_delta": (backtest or {}).get("comparison", {}).get("return_delta"),
            "sharpe_delta": (backtest or {}).get("comparison", {}).get("sharpe_delta"),
            "overlay_improves_sharpe": overlay_improves,
        }
        if backtest
        else None,
        "anti_gaming_checks": checks,
        "bridge_verdict": "review" if checks else ("positive" if deform_adds_value else "inconclusive"),
        "notes": [
            "Bridge report is review-only per governance/ml_validation_policy.yaml.",
            "Run scripts/strategy_lab/qlib_experiment.py to refresh experiment artifact.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Qlib structural bridge report.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = build_bridge_report()
    ensure_dir(OUTPUT_PATH.parent)
    write_json(OUTPUT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Qlib structural bridge: {report['bridge_verdict']}")
        print(f"  Wrote: {OUTPUT_PATH.relative_to(ROOT)}")
        if report["anti_gaming_checks"]:
            print(f"  Checks: {', '.join(report['anti_gaming_checks'])}")


if __name__ == "__main__":
    main()
