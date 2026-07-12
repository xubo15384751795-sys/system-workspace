#!/usr/bin/env python3
"""Run S1-S10 candidate methods against one unified stress-event framework.

The runner is deliberately shadow-only: it writes to Output/validation and
does not alter Output/current, daily governance, or production decisions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from professional_methods import (
        bocpd_change_probability,
        build_forward_stress_events,
        causal_pit,
        causal_robust_zscore,
        ciss_index,
        continuous_position,
        deflated_sharpe_ratio,
        dynamic_factor_score,
        incremental_logistic_test,
        jump_cluster_regime_probability,
        k_surface_features,
        kalman_local_level,
        lead_profile,
        positive_cusum,
        probability_metrics,
        rolling_absorption_ratio,
        rolling_first_factor,
        stationary_bootstrap_metric,
        sticky_filter_probability,
        sticky_gaussian_hmm_probability,
    )
except ModuleNotFoundError:  # imported as scripts.run_professional_methodology
    from scripts.professional_methods import (
        bocpd_change_probability,
        build_forward_stress_events,
        causal_pit,
        causal_robust_zscore,
        ciss_index,
        continuous_position,
        deflated_sharpe_ratio,
        dynamic_factor_score,
        incremental_logistic_test,
        jump_cluster_regime_probability,
        k_surface_features,
        kalman_local_level,
        lead_profile,
        positive_cusum,
        probability_metrics,
        rolling_absorption_ratio,
        rolling_first_factor,
        stationary_bootstrap_metric,
        sticky_filter_probability,
        sticky_gaussian_hmm_probability,
    )


ROOT = Path(__file__).resolve().parents[1]
try:
    from _data_paths import resolve_cross_asset_panel_path
except ModuleNotFoundError:
    from scripts._data_paths import resolve_cross_asset_panel_path

DEFAULT_PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
DEFAULT_CROSS_ASSET = resolve_cross_asset_panel_path()
DEFAULT_SIGNALS = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
DEFAULT_OUTPUT = ROOT / "Output" / "validation" / "professional_methodology"


def load_benchmark_panel(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    required = {"date", "series_id", "value"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Benchmark panel missing columns: {sorted(required - set(raw.columns))}")
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw["value"] = pd.to_numeric(raw["value"], errors="coerce")
    # pandas 3.0/3.14 can produce a duplicated DatetimeIndex when unstacking
    # this mixed-frequency panel.  Explicit per-series alignment is slower but
    # preserves the source dates and is deterministic across pandas versions.
    series: dict[str, pd.Series] = {}
    for series_id, group in raw.dropna(subset=["date"]).groupby("series_id", sort=True):
        values = group.groupby("date", sort=True)["value"].last()
        series[str(series_id)] = values
    panel = pd.concat(series, axis=1).sort_index()
    if not panel.index.is_unique:
        raise ValueError("Explicit benchmark alignment produced duplicate dates")
    return panel


def load_spy(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    if "symbol" not in raw.columns:
        raise ValueError("Cross-asset panel must be long-form with a symbol column")
    spy = raw.loc[raw["symbol"].eq("SPY")].set_index("date").sort_index()
    if spy.empty:
        raise ValueError("SPY missing from cross-asset panel")
    return spy


def load_channels(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path).sort_index()
    mapping = {
        "channel_M": "M",
        "channel_D_contraction": "D",
        "channel_K": "K",
        "channel_X_agg": "X",
    }
    missing = set(mapping) - set(raw.columns)
    if missing:
        raise ValueError(f"Signal panel missing columns: {sorted(missing)}")
    channels = raw.rename(columns=mapping)[list(mapping.values())]
    if not channels.index.is_unique:
        channels = channels.groupby(level=0).last()
    return channels


def build_candidates(
    channels: pd.DataFrame,
    panel: pd.DataFrame,
    proxy_components: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    index = channels.index.union(panel.index).sort_values()
    channels = channels.reindex(index)
    channel_pit = pd.DataFrame({name: causal_pit(channels[name], min_periods=126) for name in channels}, index=index)

    candidates = pd.DataFrame(index=index)
    candidates["incumbent_level"] = causal_pit(channels.max(axis=1), min_periods=126)
    incumbent_velocity = channels.diff(20).max(axis=1)
    candidates["incumbent_velocity"] = causal_pit(incumbent_velocity, min_periods=126)

    ciss = ciss_index(channel_pit, span=60, min_periods=20)
    candidates["ciss"] = causal_pit(ciss["ciss_sqrt"], min_periods=126)
    absorption_inputs = proxy_components.reindex(index) if proxy_components is not None else channels
    candidates["absorption_ratio"] = causal_pit(
        rolling_absorption_ratio(absorption_inputs, min_periods=126), min_periods=126
    )
    ciss_z = causal_robust_zscore(ciss["ciss_sqrt"], min_periods=126, clip=None)
    candidates["cusum"] = positive_cusum(ciss_z.fillna(0.0), reference=0.2, threshold=5.0)["stress_probability"]
    candidates["bocpd"] = bocpd_change_probability(ciss_z.fillna(0.0), hazard=1.0 / 50.0)

    kalman = kalman_local_level(channels["M"].dropna(), refit_every=126, min_fit=252)
    candidates["kalman_anchor"] = causal_pit(kalman.innovation_z.abs(), min_periods=126).reindex(index)

    k_features = k_surface_features(panel.reindex(index))
    k_pits: dict[str, pd.Series] = {}
    abs_features = {"term_structure_curvature", "jump_variation", "variance_risk_premium"}
    for name in k_features:
        if name == "har_rv_forecast":
            continue
        raw = k_features[name].abs() if name in abs_features else k_features[name]
        k_pits[name] = causal_pit(raw, min_periods=126)
    if k_pits:
        candidates["k_surface"] = pd.DataFrame(k_pits, index=index).mean(axis=1, skipna=True)
    candidates["sticky_filter"] = sticky_filter_probability(ciss["ciss_sqrt"])
    candidates["sticky_hmm"] = sticky_gaussian_hmm_probability(
        ciss["ciss_sqrt"], refit_every=126, min_fit=252
    )
    candidates["jump_regime"] = jump_cluster_regime_probability(ciss["ciss_sqrt"])

    # Channel factor: prefer rolling PCA (stable on sparse PIT); DynamicFactorMQ
    # on the dense subpanel is retained as a secondary candidate when it emits.
    channel_factor = rolling_first_factor(channel_pit, min_periods=126)
    candidates["channel_pca_factor"] = causal_pit(channel_factor, min_periods=126)
    dense_pit = channel_pit.dropna(how="any")
    if len(dense_pit) >= 252:
        dyn = dynamic_factor_score(dense_pit)
        candidates["dynamic_factor"] = causal_pit(dyn.reindex(index), min_periods=63)
    else:
        candidates["dynamic_factor"] = pd.Series(np.nan, index=index)
    diagnostics = {
        "channel_pit_coverage": {column: float(channel_pit[column].notna().mean()) for column in channel_pit},
        "ciss_latest_coverage": _finite_or_none(
            ciss.loc[ciss["coverage"].gt(0), "coverage"].iloc[-1]
            if ciss["coverage"].gt(0).any() else np.nan
        ),
        "k_features_available": list(k_features.columns),
        "absorption_input_count": int(absorption_inputs.shape[1]),
        "k_feature_coverage": {column: float(k_features[column].notna().mean()) for column in k_features},
        "kalman_latest_anchor": _finite_or_none(kalman.anchor.dropna().iloc[-1] if kalman.anchor.notna().any() else np.nan),
        "kalman_latest_innovation_z": _finite_or_none(kalman.innovation_z.dropna().iloc[-1] if kalman.innovation_z.notna().any() else np.nan),
        "implementation": {
            "zscore": "causal_robust_median_mad",
            "kalman": "unobserved_components_mle_q_r",
            "sticky_hmm": "hmmlearn_gaussian_sticky_dirichlet",
            "jump_regime": "nystrup_style_jump_penalty",
            "channel_factor": "rolling_pca_and_dynamic_factor_mq",
        },
    }
    details = pd.concat(
        [channel_pit.add_prefix("pit_"), ciss.add_prefix("ciss_"), k_features.add_prefix("k_")], axis=1
    )
    return candidates, details, diagnostics


def evaluate_candidates(events: pd.DataFrame, candidates: pd.DataFrame, bootstrap_reps: int) -> dict[str, Any]:
    report: dict[str, Any] = {}
    target = events["stress_event"]
    for name in candidates:
        probability = candidates[name]
        report[name] = {
            "metrics": probability_metrics(target, probability),
            "lead_profile": lead_profile(target, probability),
            "stationary_bootstrap_auc": stationary_bootstrap_metric(
                target, probability, metric="roc_auc", reps=bootstrap_reps, mean_block=20
            ),
            "stationary_bootstrap_pr_auc": stationary_bootstrap_metric(
                target, probability, metric="pr_auc", reps=bootstrap_reps, mean_block=20
            ),
        }
    return report


def public_baselines(panel: pd.DataFrame) -> pd.DataFrame:
    candidates = {
        "nfci": ("FRED:NFCI",),
        "ofr_fsi": ("OFR_FSI",),
        "ecb_ciss": ("CISS",),
    }
    result: dict[str, pd.Series] = {}
    for label, names in candidates.items():
        for name in names:
            if name in panel:
                result[label] = causal_pit(panel[name], min_periods=126)
                break
    return pd.DataFrame(result, index=panel.index)


def gate_sweep_deflation(spy: pd.DataFrame) -> dict[str, Any]:
    path = ROOT / "Output" / "strategy_lab" / "velocity_cost_sweep_results.json"
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    rows = json.loads(path.read_text(encoding="utf-8"))
    valid = [
        row for row in rows
        if isinstance(row, dict)
        and row.get("config") != "baseline"
        and np.isfinite(row.get("sharpe_delta", np.nan))
    ]
    if not valid:
        return {"status": "no_valid_trials", "path": str(path)}
    winner = max(valid, key=lambda row: float(row["sharpe_delta"]))
    ret = pd.to_numeric(spy.get("return_1d"), errors="coerce").dropna()
    skewness = float(ret.skew())
    kurtosis = float(ret.kurtosis() + 3.0)
    return {
        "status": "ok",
        "source": str(path.relative_to(ROOT)),
        "winner_config": winner.get("config"),
        **deflated_sharpe_ratio(
            observed_sharpe=float(winner["sharpe_delta"]),
            n_observations=len(ret),
            n_trials=len(valid),
            skewness=skewness,
            kurtosis=kurtosis,
        ),
    }


def select_candidate(evaluation: dict[str, Any]) -> str:
    eligible = []
    for name, result in evaluation.items():
        metrics = result["metrics"]
        auc = metrics.get("roc_auc")
        pr = metrics.get("pr_auc")
        if isinstance(auc, (int, float)) and isinstance(pr, (int, float)) and np.isfinite(auc) and np.isfinite(pr):
            eligible.append((float(auc) + float(pr), name))
    return max(eligible)[1] if eligible else "ciss"


def promotion_verdict(
    evaluation: dict[str, Any],
    incumbent: str,
    candidate: str,
    incremental: dict[str, Any] | None = None,
    common_sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = evaluation[incumbent]
    new = evaluation[candidate]
    base_metrics = (common_sample or {}).get("incumbent_metrics", base["metrics"])
    new_metrics = (common_sample or {}).get("candidate_metrics", new["metrics"])
    auc_delta = float(new_metrics["roc_auc"] - base_metrics["roc_auc"])
    pr_delta = float(new_metrics["pr_auc"] - base_metrics["pr_auc"])
    brier_delta = float(base_metrics["brier"] - new_metrics["brier"])
    ci_low = (common_sample or {}).get("candidate_bootstrap_auc", new["stationary_bootstrap_auc"]).get("low", np.nan)
    incremental_delta = (incremental or {}).get("delta", {})
    incremental_ok = incremental is None or (
        incremental.get("status") == "ok"
        and incremental_delta.get("roc_auc", -np.inf) > 0
        and incremental_delta.get("pr_auc", -np.inf) >= 0
        and incremental_delta.get("brier_improvement", -np.inf) >= 0
    )
    pass_rules = bool(
        auc_delta > 0 and pr_delta > 0 and brier_delta >= 0
        and np.isfinite(ci_low) and ci_low > 0.5 and incremental_ok
    )
    return {
        "status": "PROMOTION_ELIGIBLE" if pass_rules else "SHADOW_ONLY",
        "incumbent": incumbent,
        "candidate": candidate,
        "rules": {
            "auc_improves": auc_delta > 0,
            "pr_auc_improves": pr_delta > 0,
            "brier_not_worse": brier_delta >= 0,
            "bootstrap_auc_low_above_random": bool(np.isfinite(ci_low) and ci_low > 0.5),
            "incremental_information_not_worse": incremental_ok,
        },
        "deltas": {"roc_auc": auc_delta, "pr_auc": pr_delta, "brier_improvement": brier_delta},
        "common_sample_n": (common_sample or {}).get("n"),
        "note": "Eligibility is evidence for review, not authorization to change the default path.",
    }


def common_sample_comparison(
    target: pd.Series,
    candidates: pd.DataFrame,
    incumbent: str,
    candidate: str,
    bootstrap_reps: int,
) -> dict[str, Any]:
    aligned = pd.concat(
        [target.rename("target"), candidates[[incumbent, candidate]]], axis=1
    ).dropna()
    incumbent_probability = aligned[incumbent]
    candidate_probability = aligned[candidate]
    return {
        "n": len(aligned),
        "incumbent_metrics": probability_metrics(aligned["target"], incumbent_probability),
        "candidate_metrics": probability_metrics(aligned["target"], candidate_probability),
        "incumbent_bootstrap_auc": stationary_bootstrap_metric(
            aligned["target"], incumbent_probability, reps=bootstrap_reps, mean_block=20
        ),
        "candidate_bootstrap_auc": stationary_bootstrap_metric(
            aligned["target"], candidate_probability, reps=bootstrap_reps, mean_block=20
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    event_rate = report["event_definition"].get("event_rate")
    event_rate_text = "n/a" if event_rate is None else f"{float(event_rate):.2%}"
    lines = [
        "# Professional Methodology Shadow Evaluation",
        "",
        f"- Evaluation window: `{report['window']['start']}` to `{report['window']['end']}`",
        f"- Stress-event rate: `{event_rate_text}`",
        f"- Promotion verdict: **{report['promotion_verdict']['status']}**",
        f"- Best candidate: `{report['promotion_verdict']['candidate']}` vs `{report['promotion_verdict']['incumbent']}`",
        f"- Promotion common-sample size: `{report['promotion_verdict']['common_sample_n']}`",
        "",
        "## Unified comparison",
        "",
        "| Method | ROC-AUC | PR-AUC | Brier | ECE | AUC 95% block-bootstrap CI |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, result in report["candidate_evaluation"].items():
        metrics = result["metrics"]
        ci = result["stationary_bootstrap_auc"]
        lines.append(
            f"| {name} | {_fmt(metrics.get('roc_auc'))} | {_fmt(metrics.get('pr_auc'))} | "
            f"{_fmt(metrics.get('brier'))} | {_fmt(metrics.get('ece'))} | "
            f"[{_fmt(ci.get('low'))}, {_fmt(ci.get('high'))}] |"
        )
    lines.extend(
        [
            "",
            "## Incremental information test",
            "",
            "```json",
            json.dumps(report["incremental_information"], indent=2, ensure_ascii=False),
            "```",
            "",
            "## Gate-sweep multiple-testing review",
            "",
            "```json",
            json.dumps(report["deflated_sharpe"], indent=2, ensure_ascii=False),
            "```",
            "",
            "## Governance boundary",
            "",
            "All results remain shadow-only unless the promotion rules pass and a separate human review authorizes default-path wiring.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    panel = load_benchmark_panel(args.panel)
    spy = load_spy(args.cross_asset)
    channels = load_channels(args.signals)
    components_path = args.signals.parent / "proxy_components.parquet"
    proxy_components = pd.read_parquet(components_path) if components_path.exists() else None
    candidates, details, diagnostics = build_candidates(channels, panel, proxy_components)
    common_index = candidates.index.intersection(spy.index)

    event_defs = {
        "or_loose": dict(logic="or", vol_quantile=0.90, drawdown_threshold=-0.05),
        "and_strict": dict(logic="and", vol_quantile=0.90, drawdown_threshold=-0.05),
        "or_tight": dict(logic="or", vol_quantile=0.95, drawdown_threshold=-0.08),
    }
    primary_key = args.event_logic
    primary_cfg = event_defs.get(primary_key) or event_defs["or_tight"]
    events = build_forward_stress_events(spy["close"].reindex(common_index), **primary_cfg)
    evaluation = evaluate_candidates(events, candidates.reindex(common_index), args.bootstrap_reps)
    selected = select_candidate(evaluation)
    baselines = public_baselines(panel).reindex(common_index)
    incremental = incremental_logistic_test(
        events["stress_event"], baselines, candidates[selected].reindex(common_index), embargo=20
    ) if not baselines.empty else {"status": "no_public_baseline"}
    common_sample = common_sample_comparison(
        events["stress_event"], candidates.reindex(common_index),
        "incumbent_velocity", selected, args.bootstrap_reps,
    )

    alt_event_rates: dict[str, Any] = {}
    for name, cfg in event_defs.items():
        alt = build_forward_stress_events(spy["close"].reindex(common_index), **cfg)
        valid = alt["stress_event"].dropna()
        alt_event_rates[name] = {
            "logic": cfg["logic"],
            "vol_quantile": cfg["vol_quantile"],
            "drawdown_threshold": cfg["drawdown_threshold"],
            "event_rate": _finite_or_none(float(valid.astype(bool).mean()) if len(valid) else float("nan")),
            "valid_labels": int(len(valid)),
        }

    quality_columns = [column for column in channels.columns]
    quality = channels[quality_columns].notna().mean(axis=1).reindex(spy.index).fillna(0.0)
    positions = continuous_position(
        candidates[selected].reindex(spy.index),
        spy["return_1d"],
        quality_cap=quality,
        target_volatility=0.10,
    )
    valid_events = events["stress_event"].dropna()
    event_rate = float(valid_events.astype(bool).mean()) if len(valid_events) else float("nan")
    active_position = positions.loc[
        positions["stress_probability"].notna() & positions["quality_cap"].gt(0)
    ]
    report: dict[str, Any] = {
        "schema_version": "system.professional_methodology_shadow.v2",
        "mode": "shadow_candidate_comparison",
        "inputs": {
            "benchmark_panel": str(args.panel),
            "cross_asset_panel": str(args.cross_asset),
            "structural_signals": str(args.signals),
        },
        "window": {
            "start": str(common_index.min().date()) if len(common_index) else None,
            "end": str(common_index.max().date()) if len(common_index) else None,
            "observations": len(common_index),
        },
        "event_definition": {
            "primary": primary_key,
            "horizon_days": 20,
            "future_realized_vol_quantile": primary_cfg["vol_quantile"],
            "future_max_drawdown_threshold": primary_cfg["drawdown_threshold"],
            "logic": primary_cfg["logic"].upper(),
            "event_rate": _finite_or_none(event_rate),
            "valid_labels": len(valid_events),
            "causal_threshold": True,
            "alternate_definitions": alt_event_rates,
        },
        "method_diagnostics": diagnostics,
        "candidate_evaluation": evaluation,
        "common_sample_comparison": common_sample,
        "incremental_information": incremental,
        "deflated_sharpe": gate_sweep_deflation(spy),
        "promotion_verdict": promotion_verdict(
            evaluation, "incumbent_velocity", selected,
            incremental=incremental, common_sample=common_sample,
        ),
        "continuous_position": {
            "candidate": selected,
            "latest": {
                key: _finite_or_none(value) for key, value in positions.dropna(how="all").iloc[-1].to_dict().items()
            } if not positions.dropna(how="all").empty else {},
            "active_observations": len(active_position),
            "mean_position": _finite_or_none(active_position["position"].mean()),
            "zero_exposure_rate": _finite_or_none((active_position["position"] <= 0.01).mean()),
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(
        json.dumps(_json_safe(report), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    (args.output / "report.md").write_text(render_markdown(report), encoding="utf-8")
    pd.concat(
        [events.add_prefix("event_"), candidates.reindex(common_index).add_prefix("candidate_")], axis=1
    ).to_csv(args.output / "evaluation_panel.csv", index_label="date")
    pd.concat([details.reindex(common_index), positions.reindex(common_index).add_prefix("position_")], axis=1).to_csv(
        args.output / "method_details.csv", index_label="date"
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--cross-asset", type=Path, default=DEFAULT_CROSS_ASSET)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-reps", type=int, default=200)
    parser.add_argument(
        "--event-logic",
        choices=("or_loose", "and_strict", "or_tight"),
        default="or_tight",
        help="Primary stress-event definition for promotion scoring (default: tighter OR).",
    )
    return parser.parse_args()


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _json_safe(value: Any) -> Any:
    """Recursively coerce values so json.dumps(..., allow_nan=False) succeeds."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, bool)) or value is None:
        return value
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return numeric if np.isfinite(numeric) else None


def _fmt(value: Any) -> str:
    numeric = _finite_or_none(value)
    return "n/a" if numeric is None else f"{numeric:.3f}"


if __name__ == "__main__":
    cli_args = parse_args()
    result = run(cli_args)
    print(json.dumps({"status": "ok", "output": str(cli_args.output), "verdict": result["promotion_verdict"]}, ensure_ascii=False))
