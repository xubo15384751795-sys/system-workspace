"""Evaluate mechanism causal calibration against governance thresholds."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from _runtime_io import ROOT, load_yaml

GATE_PATH = ROOT / "governance" / "mechanism_calibration_gate.yaml"

_LEVEL_ORDER = ("research", "paper_draft", "judgment_support")


def load_gate_policy(path: Path = GATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return load_yaml(path)


def _holdout_metrics(
    calibration_report: dict[str, Any],
    holdout_ids: set[str],
) -> dict[str, Any]:
    episodes = calibration_report.get("per_episode", [])
    holdout = [ep for ep in episodes if ep.get("id") in holdout_ids]
    if not holdout:
        return {
            "count": 0,
            "direction_accuracy": 0.0,
            "mean_absolute_error": None,
            "per_dimension": {},
        }

    dir_acc = sum(float(ep.get("dir_acc", 0)) for ep in holdout) / len(holdout)
    mae = sum(float(ep.get("mae", 0)) for ep in holdout) / len(holdout)

    per_dim: dict[str, list[bool]] = {"M": [], "K": [], "D": [], "X": []}
    for ep in holdout:
        predicted = ep.get("predicted") or {}
        actual = ep.get("actual") or {}
        for dim in per_dim:
            pred = float(predicted.get(dim, 0))
            act = float(actual.get(dim, 0))
            if act == 0:
                per_dim[dim].append(True)
            else:
                per_dim[dim].append(pred * act >= 0)

    per_dimension = {
        dim: (sum(vals) / len(vals) if vals else 0.0)
        for dim, vals in per_dim.items()
    }

    return {
        "count": len(holdout),
        "direction_accuracy": round(dir_acc, 4),
        "mean_absolute_error": round(mae, 4),
        "per_dimension": {k: round(v, 4) for k, v in per_dimension.items()},
        "episode_ids": [ep.get("id") for ep in holdout],
    }


def _level_passes(level_cfg: dict[str, Any], metrics: dict[str, Any], total_episodes: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    min_eps = int(level_cfg.get("min_total_episodes", 0))
    if min_eps and total_episodes < min_eps:
        reasons.append(f"total_episodes {total_episodes} < {min_eps}")

    min_holdout = int(level_cfg.get("min_holdout_episodes", 0))
    if metrics["count"] < min_holdout:
        reasons.append(f"holdout_episodes {metrics['count']} < {min_holdout}")

    min_dir = float(level_cfg.get("min_holdout_direction_accuracy", 1.0))
    if metrics["direction_accuracy"] < min_dir:
        reasons.append(
            f"holdout_direction_accuracy {metrics['direction_accuracy']:.2%} < {min_dir:.0%}"
        )

    max_mae = level_cfg.get("max_holdout_mean_absolute_error")
    if max_mae is not None and metrics["mean_absolute_error"] is not None:
        if metrics["mean_absolute_error"] > float(max_mae):
            reasons.append(
                f"holdout_mae {metrics['mean_absolute_error']:.3f} > {float(max_mae):.3f}"
            )

    min_per_dim = float(level_cfg.get("min_per_dimension_direction_accuracy", 0.0))
    if min_per_dim > 0:
        for dim, acc in (metrics.get("per_dimension") or {}).items():
            if acc < min_per_dim:
                reasons.append(f"{dim} holdout_direction {acc:.0%} < {min_per_dim:.0%}")

    return len(reasons) == 0, reasons


def evaluate_gate(calibration_report: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return gate level achieved and whether Paper export is allowed."""
    policy = policy or load_gate_policy()
    holdout_ids = set(policy.get("holdout_episode_ids") or [])
    levels = policy.get("levels") or {}
    total_episodes = int(calibration_report.get("total_episodes", 0))

    holdout = _holdout_metrics(calibration_report, holdout_ids)
    train_ids = {
        ep.get("id")
        for ep in calibration_report.get("per_episode", [])
        if ep.get("id") not in holdout_ids
    }

    achieved = "none"
    blocking_reasons: list[str] = []
    level_results: dict[str, Any] = {}

    for level_name in _LEVEL_ORDER:
        cfg = levels.get(level_name) or {}
        passed, reasons = _level_passes(cfg, holdout, total_episodes)
        level_results[level_name] = {"passed": passed, "reasons": reasons}
        if passed:
            achieved = level_name
        elif achieved == "none" and not blocking_reasons:
            blocking_reasons = reasons

    if achieved == "none" and level_results.get("research", {}).get("reasons"):
        blocking_reasons = level_results["research"]["reasons"]

    return {
        "schema_version": "mechanism_calibration_gate.v1",
        "achieved_level": achieved,
        "allow_paper_export": achieved in {"paper_draft", "judgment_support"},
        "allow_judgment_support": achieved == "judgment_support",
        "holdout_metrics": holdout,
        "train_episode_count": len(train_ids),
        "total_episodes": total_episodes,
        "holdout_episode_ids": sorted(holdout_ids),
        "level_results": level_results,
        "blocking_reasons": blocking_reasons,
    }
