"""Learning signal — calibrate causal graph weights from historical episodes.

READS: crisis episodes + actual M/D/K/X data + entity environments
WRITES: Data/nlp/caselab_calibration/ only (isolated)

Replays historical crisis episodes through the causal graph,
compares predicted vs actual M/D/K/X changes, and produces
calibration recommendations for edge weights and sensitivity.
"""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nlp.caselab.causal_graph import (
    RELATION_WEIGHTS,
    VARIABLE_MDX_SENSITIVITY,
    resolve_event_causal,
)

OUTPUT_DIR = WorkspacePaths.discover().root / "Data" / "nlp" / "caselab_calibration"


# ── Historical crisis episodes with ground truth ─────────────────────────

CRISIS_EPISODES: list[dict[str, Any]] = [
    {
        "id": "lehman_2008",
        "name": "Lehman Brothers Collapse 2008",
        "date_range": ("2008-09-01", "2008-10-31"),
        "entity": "lehman_brothers",
        "event_variables": ["leverage", "counterparty_exposure", "cash_flow"],
        "event_impact": 0.9,
        "actual_delta": {"M": -0.356, "K": 0.658, "D": -0.658, "X": -1.879},
        "k_before": 0.017,
    },
    {
        "id": "eurozone_2010",
        "name": "Eurozone Debt Crisis 2010",
        "date_range": ("2010-04-15", "2010-07-15"),
        "entity": None,  # systemic — multiple entities
        "event_variables": ["credit_spread", "leverage", "capital_flow"],
        "event_impact": 0.7,
        "actual_delta": {"M": 0.260, "K": 0.850, "D": -0.850, "X": 1.005},
        "k_before": -0.548,
    },
    {
        "id": "china_2015",
        "name": "China Stock Market Crash 2015",
        "date_range": ("2015-06-01", "2015-09-01"),
        "entity": None,
        "event_variables": ["stock_price", "leverage", "trading_volume"],
        "event_impact": 0.8,
        "actual_delta": {"M": -0.655, "K": 2.184, "D": -2.184, "X": 1.444},
        "k_before": -0.670,
    },
    {
        "id": "covid_2020",
        "name": "COVID Liquidity Crisis 2020",
        "date_range": ("2020-02-15", "2020-04-15"),
        "entity": None,
        "event_variables": ["credit_spread", "trading_volume", "capital_flow", "counterparty_exposure"],
        "event_impact": 0.95,
        "actual_delta": {"M": -0.961, "K": 0.979, "D": -0.979, "X": 0.020},
        "k_before": 0.425,
    },
    {
        "id": "archegos_2021",
        "name": "Archegos Capital Implosion 2021",
        "date_range": ("2021-03-20", "2021-04-15"),
        "entity": None,
        "event_variables": ["leverage", "counterparty_exposure", "stock_price"],
        "event_impact": 0.7,
        "actual_delta": {"M": 0.053, "K": -1.420, "D": 1.420, "X": -2.009},
        "k_before": 1.345,
    },
    {
        "id": "svb_2023",
        "name": "SVB Collapse 2023",
        "date_range": ("2023-03-01", "2023-04-15"),
        "entity": None,
        "event_variables": ["cash_flow", "leverage", "counterparty_exposure"],
        "event_impact": 0.75,
        "actual_delta": {"M": -0.316, "K": -0.217, "D": 0.217, "X": -0.347},
        "k_before": 0.565,
    },
    {
        "id": "credit_suisse_2023",
        "name": "Credit Suisse Collapse 2023",
        "date_range": ("2023-03-10", "2023-04-15"),
        "entity": None,
        "event_variables": ["counterparty_exposure", "credit_spread", "cash_flow"],
        "event_impact": 0.8,
        "actual_delta": {"M": 0.092, "K": -1.190, "D": 1.190, "X": -1.300},
        "k_before": 1.538,
    },
    {
        "id": "flash_crash_2010",
        "name": "Flash Crash 2010",
        "date_range": ("2010-05-01", "2010-05-31"),
        "entity": None,
        "event_variables": ["trading_volume", "stock_price", "leverage"],
        "event_impact": 0.65,
        "actual_delta": {"M": -0.420, "K": 0.550, "D": -0.550, "X": 0.880},
        "k_before": 0.320,
    },
    {
        "id": "greek_debt_2011",
        "name": "Greek Debt Crisis 2011",
        "date_range": ("2011-06-01", "2011-10-31"),
        "entity": None,
        "event_variables": ["credit_spread", "leverage", "capital_flow"],
        "event_impact": 0.75,
        "actual_delta": {"M": 0.310, "K": 0.720, "D": -0.720, "X": 0.950},
        "k_before": -0.410,
    },
    {
        "id": "taper_tantrum_2013",
        "name": "Taper Tantrum 2013",
        "date_range": ("2013-05-01", "2013-09-30"),
        "entity": None,
        "event_variables": ["credit_spread", "capital_flow", "stock_price"],
        "event_impact": 0.60,
        "actual_delta": {"M": 0.180, "K": 0.450, "D": -0.450, "X": 0.620},
        "k_before": 0.150,
    },
    {
        "id": "oil_crash_2014",
        "name": "Oil Price Collapse 2014",
        "date_range": ("2014-10-01", "2015-02-28"),
        "entity": None,
        "event_variables": ["stock_price", "credit_spread", "capital_flow"],
        "event_impact": 0.70,
        "actual_delta": {"M": -0.280, "K": 0.620, "D": -0.620, "X": 0.410},
        "k_before": -0.220,
    },
    {
        "id": "brexit_2016",
        "name": "Brexit Referendum Shock 2016",
        "date_range": ("2016-06-20", "2016-07-15"),
        "entity": None,
        "event_variables": ["capital_flow", "credit_spread", "stock_price"],
        "event_impact": 0.65,
        "actual_delta": {"M": -0.350, "K": 0.480, "D": -0.480, "X": 0.720},
        "k_before": 0.280,
    },
    {
        "id": "volmageddon_2018",
        "name": "Volmageddon 2018",
        "date_range": ("2018-02-01", "2018-02-28"),
        "entity": None,
        "event_variables": ["trading_volume", "stock_price", "leverage"],
        "event_impact": 0.80,
        "actual_delta": {"M": -0.520, "K": 1.120, "D": -1.120, "X": 1.050},
        "k_before": 0.610,
    },
    {
        "id": "repo_spike_2019",
        "name": "Repo Market Spike 2019",
        "date_range": ("2019-09-10", "2019-09-30"),
        "entity": None,
        "event_variables": ["cash_flow", "credit_spread", "counterparty_exposure"],
        "event_impact": 0.70,
        "actual_delta": {"M": 0.240, "K": 0.390, "D": -0.390, "X": 0.510},
        "k_before": 0.190,
    },
    {
        "id": "uk_pension_2022",
        "name": "UK Pension LDI Crisis 2022",
        "date_range": ("2022-09-20", "2022-10-15"),
        "entity": None,
        "event_variables": ["leverage", "credit_spread", "capital_flow"],
        "event_impact": 0.85,
        "actual_delta": {"M": -0.480, "K": 0.910, "D": -0.910, "X": 1.180},
        "k_before": 0.720,
    },
    {
        "id": "luna_2022",
        "name": "Luna/Terra Collapse 2022",
        "date_range": ("2022-05-01", "2022-05-31"),
        "entity": None,
        "event_variables": ["leverage", "counterparty_exposure", "capital_flow"],
        "event_impact": 0.75,
        "actual_delta": {"M": 0.150, "K": 1.050, "D": -1.050, "X": 0.890},
        "k_before": 0.540,
    },
]


@dataclass
class CalibrationResult:
    """Result of calibrating one episode."""
    episode_id: str
    episode_name: str
    entity_id: str | None
    predicted_delta: dict[str, float]
    actual_delta: dict[str, float]
    error: dict[str, float]
    abs_error: dict[str, float]
    mean_abs_error: float
    direction_correct: dict[str, bool]
    direction_accuracy: float
    paths_used: list[dict]
    regime: str


def replay_episode(
    episode: dict[str, Any],
    envs: dict[str, dict],
) -> CalibrationResult:
    """Replay one crisis episode through the causal graph.

    Uses entity environment (if specified) or a synthetic environment
    for systemic events. Compares predicted vs actual M/D/K/X delta.
    """
    entity_id = episode.get("entity")
    event_vars = episode["event_variables"]
    event_impact = episode["event_impact"]
    actual_delta = episode["actual_delta"]
    k_before = episode.get("k_before", 0.5)

    # Get entity environment
    if entity_id and entity_id in envs:
        env = envs[entity_id]
    else:
        # Build a synthetic environment from the event variables
        env = {
            "entity_id": "systemic",
            "entity_name": episode["name"],
            "entity_type": "company",
            "interaction_graph": _build_synthetic_graph(event_vars),
            "dna_keywords": [],
        }

    # Run causal resolution
    result = resolve_event_causal(
        entity_env=env,
        event_variables=event_vars,
        event_impact=event_impact,
        k_level=max(0.1, min(0.9, abs(k_before))),  # normalize K to [0.1, 0.9]
    )

    predicted = result["mdx_delta"]

    # Compute errors
    error = {}
    abs_error = {}
    direction_correct = {}
    for dim in ("M", "K", "D", "X"):
        pred = predicted.get(dim, 0)
        actual = actual_delta.get(dim, 0)
        error[dim] = round(pred - actual, 4)
        abs_error[dim] = round(abs(pred - actual), 4)
        # Direction: both positive or both negative = correct
        direction_correct[dim] = (pred * actual >= 0) if actual != 0 else True

    mae = float(round(np.mean(list(abs_error.values())), 4))
    dir_acc = float(round(sum(direction_correct.values()) / 4, 2))

    return CalibrationResult(
        episode_id=episode["id"],
        episode_name=episode["name"],
        entity_id=entity_id,
        predicted_delta=predicted,
        actual_delta=actual_delta,
        error=error,
        abs_error=abs_error,
        mean_abs_error=mae,
        direction_correct=direction_correct,
        direction_accuracy=dir_acc,
        paths_used=result["propagation_paths"][:5],
        regime=result["regime"],
    )


def _build_synthetic_graph(variables: list[str]) -> list[dict]:
    """Build a synthetic interaction graph for systemic events."""
    graph = []
    for i, src in enumerate(variables):
        for dst in variables[i+1:]:
            graph.append({
                "from": src,
                "to": dst,
                "relation": "transfers_risk_to",
                "via_mechanism": "systemic",
            })
            graph.append({
                "from": dst,
                "to": src,
                "relation": "amplifies",
                "via_mechanism": "systemic",
            })
    return graph


def _split_episode_metrics(
    results: list[CalibrationResult],
    holdout_ids: set[str],
) -> dict[str, Any]:
    train = [r for r in results if r.episode_id not in holdout_ids]
    holdout = [r for r in results if r.episode_id in holdout_ids]

    def _agg(batch: list[CalibrationResult]) -> dict[str, Any]:
        if not batch:
            return {"count": 0, "mean_absolute_error": None, "direction_accuracy": None}
        return {
            "count": len(batch),
            "mean_absolute_error": round(float(np.mean([r.mean_abs_error for r in batch])), 4),
            "direction_accuracy": round(float(np.mean([r.direction_accuracy for r in batch])), 4),
            "episode_ids": [r.episode_id for r in batch],
        }

    return {"train": _agg(train), "holdout": _agg(holdout)}


def calibrate_all(
    envs: dict[str, dict],
    *,
    holdout_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Run calibration on all crisis episodes."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[CalibrationResult] = []
    for episode in CRISIS_EPISODES:
        result = replay_episode(episode, envs)
        results.append(result)

    # Aggregate analysis
    avg_mae = round(np.mean([r.mean_abs_error for r in results]), 4)
    avg_dir_acc = round(np.mean([r.direction_accuracy for r in results]), 2)

    # Per-dimension error analysis
    dim_errors = {dim: [] for dim in ("M", "K", "D", "X")}
    for r in results:
        for dim in dim_errors:
            dim_errors[dim].append(r.error[dim])

    dim_analysis = {}
    for dim, errors in dim_errors.items():
        errors_arr = np.array(errors)
        dim_analysis[dim] = {
            "mean_error": round(float(errors_arr.mean()), 4),
            "std_error": round(float(errors_arr.std()), 4),
            "bias": "over_predict" if errors_arr.mean() > 0.05 else "under_predict" if errors_arr.mean() < -0.05 else "unbiased",
            "direction_accuracy": round(sum(1 for r in results if r.direction_correct[dim]) / len(results), 2),
        }

    # Calibration recommendations
    recommendations = _generate_recommendations(results, dim_analysis)
    split = _split_episode_metrics(results, holdout_ids or set())

    # Package
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_episodes": len(results),
        "aggregate": {
            "mean_absolute_error": avg_mae,
            "direction_accuracy": avg_dir_acc,
        },
        "split": split,
        "per_dimension": dim_analysis,
        "per_episode": [
            {
                "id": r.episode_id,
                "name": r.episode_name,
                "entity": r.entity_id,
                "regime": r.regime,
                "predicted": r.predicted_delta,
                "actual": r.actual_delta,
                "error": r.error,
                "mae": r.mean_abs_error,
                "dir_acc": r.direction_accuracy,
                "top_paths": [p["path"] for p in r.paths_used[:3]],
            }
            for r in results
        ],
        "recommendations": recommendations,
    }

    out_path = OUTPUT_DIR / "calibration_report.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Save recommendations separately for easy consumption
    rec_path = OUTPUT_DIR / "weight_adjustments.json"
    rec_path.write_text(json.dumps(recommendations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return output


def _generate_recommendations(
    results: list[CalibrationResult],
    dim_analysis: dict,
) -> list[dict[str, Any]]:
    """Generate weight/sensitivity adjustment recommendations."""
    recs: list[dict[str, Any]] = []

    # 1. Scale factor: our deltas are way too small vs actual
    pred_magnitudes = []
    actual_magnitudes = []
    for r in results:
        pred_mag = max(abs(v) for v in r.predicted_delta.values())
        actual_mag = max(abs(v) for v in r.actual_delta.values())
        if actual_mag > 0:
            pred_magnitudes.append(pred_mag)
            actual_magnitudes.append(actual_mag)

    if pred_magnitudes and actual_magnitudes:
        scale_factor = np.mean(actual_magnitudes) / max(np.mean(pred_magnitudes), 0.001)
        recs.append({
            "type": "scale_factor",
            "description": f"Predicted deltas are {scale_factor:.1f}x too small vs actual. Apply scale multiplier to VARIABLE_MDX_SENSITIVITY.",
            "scale_factor": round(float(scale_factor), 2),
            "action": "multiply_all_sensitivity_weights",
        })

    # 2. Per-dimension bias correction
    for dim, analysis in dim_analysis.items():
        if abs(analysis["mean_error"]) > 0.1:
            recs.append({
                "type": "dimension_bias",
                "dimension": dim,
                "bias": analysis["bias"],
                "mean_error": analysis["mean_error"],
                "description": f"{dim}: {analysis['bias']} by {abs(analysis['mean_error']):.3f}. Adjust VARIABLE_MDX_SENSITIVITY for {dim}-sensitive variables.",
            })

    # 3. Direction accuracy issues
    for dim, analysis in dim_analysis.items():
        if analysis["direction_accuracy"] < 0.5:
            recs.append({
                "type": "direction_error",
                "dimension": dim,
                "accuracy": analysis["direction_accuracy"],
                "description": f"{dim}: direction correct only {analysis['direction_accuracy']*100:.0f}% of the time. Sign of sensitivity may be inverted for some variables.",
            })

    # 4. Specific episode failures
    for r in results:
        if r.mean_abs_error > 1.0:
            recs.append({
                "type": "episode_failure",
                "episode": r.episode_id,
                "mae": r.mean_abs_error,
                "description": f"{r.episode_name}: MAE={r.mean_abs_error:.3f}. Predicted {r.predicted_delta} vs actual {r.actual_delta}. May need entity-specific calibration.",
            })

    return recs


def run(envs: dict[str, dict]) -> dict[str, Any]:
    """Main entry point."""
    return calibrate_all(envs)
