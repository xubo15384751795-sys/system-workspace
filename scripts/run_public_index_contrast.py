#!/usr/bin/env python3
"""Section-9 touchstone: correlate and incrementally test ours vs OFR/NFCI/CISS.

Tests the three differentiation hypotheses claimed in the capability plan:
  1. daily update (public indices lagged)
  2. velocity / change-point dimension
  3. M-channel Kalman anchor dynamics

Shadow-only: writes Output/validation/public_index_contrast/.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from scripts._data_paths import resolve_cross_asset_panel_path
    from professional_methods import (
        bocpd_change_probability,
        build_forward_stress_events,
        causal_pit,
        causal_robust_zscore,
        ciss_index,
        diebold_mariano_logloss,
        probability_metrics,
        release_intensity_features,
    )
    from run_professional_methodology import (
        build_candidates,
        load_benchmark_panel,
        load_channels,
        load_spy,
        public_baselines,
    )
except ModuleNotFoundError:
    from scripts._data_paths import resolve_cross_asset_panel_path
    from scripts.professional_methods import (
        bocpd_change_probability,
        build_forward_stress_events,
        causal_pit,
        causal_robust_zscore,
        ciss_index,
        diebold_mariano_logloss,
        probability_metrics,
        release_intensity_features,
    )
    from scripts.run_professional_methodology import (
        build_candidates,
        load_benchmark_panel,
        load_channels,
        load_spy,
        public_baselines,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
DEFAULT_CROSS_ASSET = resolve_cross_asset_panel_path()
DEFAULT_SIGNALS = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
DEFAULT_OUTPUT = ROOT / "Output" / "validation" / "public_index_contrast"

# Approximate publication lags used to stress-test the "daily update" claim.
PUBLIC_LAGS_TRADING_DAYS = {
    "ofr_fsi": 1,   # OFR FSI typically settles with a short reporting lag
    "nfci": 5,      # weekly NFCI → ~1 week stale on a daily grid
    "ecb_ciss": 5,  # weekly/delayed European composite on daily grid
}


def _finite(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def correlation_block(ours: pd.DataFrame, public: pd.DataFrame) -> dict[str, Any]:
    frame = pd.concat([ours.add_prefix("ours_"), public.add_prefix("public_")], axis=1)
    pearson = frame.corr(method="pearson")
    spearman = frame.corr(method="spearman")
    pairs: list[dict[str, Any]] = []
    for ours_name in ours.columns:
        for public_name in public.columns:
            col_o = f"ours_{ours_name}"
            col_p = f"public_{public_name}"
            aligned = frame[[col_o, col_p]].dropna()
            pairs.append({
                "ours": ours_name,
                "public": public_name,
                "n": int(len(aligned)),
                "pearson": _finite(pearson.loc[col_o, col_p]),
                "spearman": _finite(spearman.loc[col_o, col_p]),
                "above_0_9": bool(abs(pearson.loc[col_o, col_p]) > 0.9) if np.isfinite(pearson.loc[col_o, col_p]) else False,
            })
    max_abs = max((abs(row["pearson"] or 0.0) for row in pairs), default=0.0)
    return {
        "pairs": pairs,
        "max_abs_pearson": _finite(max_abs),
        "any_above_0_9": any(row["above_0_9"] for row in pairs),
        "verdict": "REDUNDANT_IF_ABOVE_0_9" if any(row["above_0_9"] for row in pairs) else "NOT_COLLAPSED_TO_PUBLIC",
    }


def logistic_with_coefficients(
    target: pd.Series,
    features: pd.DataFrame,
    train_fraction: float = 0.7,
    embargo: int = 20,
) -> dict[str, Any]:
    """Chronological logistic with coefficient SE / z / p via statsmodels when available."""
    data = pd.concat([target.rename("y"), features], axis=1).dropna()
    split = int(len(data) * train_fraction)
    train = data.iloc[: max(0, split - embargo)]
    test = data.iloc[min(len(data), split + embargo) :]
    if len(train) < 100 or len(test) < 50 or train["y"].nunique() < 2 or test["y"].nunique() < 2:
        return {"status": "insufficient_sample", "n_train": len(train), "n_test": len(test)}

    columns = list(features.columns)
    x_train = train[columns].to_numpy(dtype=float)
    y_train = train["y"].astype(int).to_numpy()
    x_test = test[columns].to_numpy(dtype=float)
    mean = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale < 1e-8] = 1.0
    z_train = (x_train - mean) / scale
    z_test = (x_test - mean) / scale

    coefficients: dict[str, Any] = {}
    engine = "sklearn"
    try:
        import statsmodels.api as sm

        model = sm.Logit(y_train, sm.add_constant(z_train, has_constant="add")).fit(disp=False, maxiter=200)
        params = model.params
        bse = model.bse
        pvalues = model.pvalues
        # constant first, then features
        for i, name in enumerate(["intercept", *columns]):
            coefficients[name] = {
                "coef": _finite(params[i]),
                "se": _finite(bse[i]),
                "z": _finite(params[i] / bse[i]) if bse[i] else None,
                "p_value": _finite(pvalues[i]),
                "significant_5pct": bool(pvalues[i] < 0.05) if np.isfinite(pvalues[i]) else False,
            }
        probability = model.predict(sm.add_constant(z_test, has_constant="add"))
        engine = "statsmodels"
    except Exception:
        from sklearn.linear_model import LogisticRegression

        model = LogisticRegression(max_iter=2000, solver="liblinear").fit(z_train, y_train)
        probability = model.predict_proba(z_test)[:, 1]
        coefficients["intercept"] = {"coef": _finite(model.intercept_[0]), "se": None, "z": None, "p_value": None, "significant_5pct": None}
        for name, coef in zip(columns, model.coef_[0]):
            coefficients[name] = {"coef": _finite(coef), "se": None, "z": None, "p_value": None, "significant_5pct": None}

    metrics = probability_metrics(test["y"], pd.Series(probability, index=test.index))
    return {
        "status": "ok",
        "engine": engine,
        "n_train": len(train),
        "n_test": len(test),
        "embargo": embargo,
        "features": columns,
        "coefficients": coefficients,
        "metrics": metrics,
    }


def incremental_pair(
    target: pd.Series,
    baseline: pd.DataFrame,
    candidate: pd.Series,
    candidate_name: str,
) -> dict[str, Any]:
    base = logistic_with_coefficients(target, baseline)
    aug = logistic_with_coefficients(target, pd.concat([baseline, candidate.rename(candidate_name)], axis=1))
    if base.get("status") != "ok" or aug.get("status") != "ok":
        return {"status": "insufficient_sample", "baseline": base, "augmented": aug}
    beta = aug["coefficients"].get(candidate_name, {})
    coef = beta.get("coef")
    positive_stress_direction = isinstance(coef, (int, float)) and coef > 0
    return {
        "status": "ok",
        "candidate": candidate_name,
        "baseline_features": list(baseline.columns),
        "baseline": base,
        "augmented": aug,
        "beta2": beta,
        "delta": {
            "roc_auc": _finite(aug["metrics"]["roc_auc"] - base["metrics"]["roc_auc"]),
            "pr_auc": _finite(aug["metrics"]["pr_auc"] - base["metrics"]["pr_auc"]),
            "brier_improvement": _finite(base["metrics"]["brier"] - aug["metrics"]["brier"]),
        },
        "passes": bool(
            beta.get("significant_5pct") is True
            and positive_stress_direction
            and (aug["metrics"]["roc_auc"] - base["metrics"]["roc_auc"]) > 0
        ),
        "sign_note": (
            None if coef is None
            else "ok_positive_stress_loading" if coef > 0
            else "wrong_sign_for_stress_predictor"
        ),
    }


def _gbm_interaction_gate(
    target: pd.Series,
    public: pd.DataFrame,
    interactions: pd.DataFrame,
    *,
    train_fraction: float = 0.7,
    embargo: int = 20,
) -> dict[str, Any]:
    """G1 upper-bound probe: HistGBM(public) vs HistGBM(public + f1/f2/f3)."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, log_loss

    data = pd.concat([target.rename("y"), public, interactions], axis=1).dropna()
    split = int(len(data) * train_fraction)
    train = data.iloc[: max(0, split - embargo)]
    test = data.iloc[min(len(data), split + embargo) :]
    if len(train) < 100 or len(test) < 50 or train["y"].nunique() < 2 or test["y"].nunique() < 2:
        return {"status": "insufficient_sample", "passes": False, "candidate": "g1_gbm_upper_bound"}
    public_cols = list(public.columns)
    interaction_cols = list(interactions.columns)

    def _fit_predict(columns: list[str]) -> np.ndarray:
        model = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=100)
        model.fit(train[columns].to_numpy(dtype=float), train["y"].astype(int))
        return model.predict_proba(test[columns].to_numpy(dtype=float))[:, 1]

    p_base = _fit_predict(public_cols)
    p_aug = _fit_predict(public_cols + interaction_cols)
    y = test["y"].astype(int)
    delta_pr = float(average_precision_score(y, p_aug) - average_precision_score(y, p_base))
    dm = diebold_mariano_logloss(
        y, pd.Series(p_aug, index=test.index), pd.Series(p_base, index=test.index)
    )
    passes = bool(
        delta_pr > 0
        and isinstance(dm.get("p_value"), float)
        and dm["p_value"] < 0.05
        and isinstance(dm.get("mean_diff"), float)
        and dm["mean_diff"] < 0  # aug log-loss lower than base
    )
    return {
        "status": "ok",
        "candidate": "g1_gbm_upper_bound",
        "passes": passes,
        "delta_pr_auc": delta_pr,
        "dm_logloss": dm,
        "baseline_logloss": float(log_loss(y, p_base, labels=[0, 1])),
        "augmented_logloss": float(log_loss(y, p_aug, labels=[0, 1])),
    }


def lag_public(public: pd.DataFrame) -> pd.DataFrame:
    lagged = public.copy()
    for column, lag in PUBLIC_LAGS_TRADING_DAYS.items():
        if column in lagged:
            lagged[column] = lagged[column].shift(lag)
    return lagged.add_suffix("_lagged")


def run(args: argparse.Namespace) -> dict[str, Any]:
    panel = load_benchmark_panel(args.panel)
    spy = load_spy(args.cross_asset)
    channels = load_channels(args.signals)
    components_path = args.signals.parent / "proxy_components.parquet"
    proxy_components = pd.read_parquet(components_path) if components_path.exists() else None
    candidates, _details, diagnostics = build_candidates(channels, panel, proxy_components)

    # Focused "ours" set for the touchstone, including the three differentiation claims.
    channel_pit = pd.DataFrame({name: causal_pit(channels[name], min_periods=126) for name in channels})
    ciss = ciss_index(channel_pit, span=60, min_periods=20)
    ciss_z = causal_robust_zscore(ciss["ciss_sqrt"], min_periods=126, clip=None)
    ours = pd.DataFrame({
        "composite_level": candidates["incumbent_level"],
        "composite_velocity": candidates["incumbent_velocity"],
        "ciss_ours": candidates["ciss"],
        "k_surface": candidates["k_surface"],
        "kalman_anchor": candidates["kalman_anchor"],
        "cusum": candidates["cusum"],
        "bocpd": bocpd_change_probability(ciss_z.fillna(0.0), hazard=1.0 / 50.0),
    }, index=candidates.index)

    public = public_baselines(panel)
    common = ours.index.intersection(spy.index).intersection(public.dropna(how="all").index)
    ours = ours.reindex(common)
    public = public.reindex(common)
    events = build_forward_stress_events(spy["close"].reindex(common))
    target = events["stress_event"]

    corr = correlation_block(ours, public)

    # Classic incremental: event ~ public + yours (one-at-a-time and all-public control)
    ofr_only = public[["ofr_fsi"]].dropna(how="all") if "ofr_fsi" in public else public.iloc[:, :0]
    all_public = public.dropna(how="all")
    incremental_ofr: dict[str, Any] = {}
    incremental_all: dict[str, Any] = {}
    for name in ours.columns:
        if not ofr_only.empty:
            incremental_ofr[name] = incremental_pair(target, ofr_only, ours[name], name)
        if not all_public.empty:
            incremental_all[name] = incremental_pair(target, all_public, ours[name], name)

    # Hypothesis A: daily update — control on *lagged* public, test contemporaneous ours
    lagged = lag_public(public).reindex(common)
    hyp_daily: dict[str, Any] = {}
    for name in ("composite_level", "composite_velocity", "k_surface", "ciss_ours"):
        hyp_daily[name] = incremental_pair(target, lagged, ours[name], name)

    # Hypothesis B: velocity / change-point beyond public levels
    hyp_velocity = {
        "composite_velocity": incremental_pair(target, all_public, ours["composite_velocity"], "composite_velocity"),
        "cusum": incremental_pair(target, all_public, ours["cusum"], "cusum"),
        "bocpd": incremental_pair(target, all_public, ours["bocpd"], "bocpd"),
    }

    # Hypothesis C: Kalman anchor dynamics beyond public levels
    hyp_kalman = {
        "kalman_anchor": incremental_pair(target, all_public, ours["kalman_anchor"], "kalman_anchor"),
    }

    # WP-T5 / G1: nonlinear interaction features vs public indices
    release_feats = release_intensity_features(channels.reindex(common), train_end="2018-12-31")
    interaction_candidates = release_feats[["f1_release_kernel", "f2_forced_sale", "f3_injection_amp"]]
    hyp_interaction: dict[str, Any] = {}
    for name in interaction_candidates.columns:
        hyp_interaction[name] = incremental_pair(
            target, all_public, interaction_candidates[name], name
        )
    hyp_interaction["g1_gbm_upper_bound"] = _gbm_interaction_gate(
        target, all_public, interaction_candidates
    )

    def _pass_count(block: dict[str, Any]) -> dict[str, Any]:
        tested = [v for v in block.values() if v.get("status") == "ok"]
        passed = [v for v in tested if v.get("passes")]
        return {"tested": len(tested), "passed": len(passed), "names": [v["candidate"] for v in passed]}

    summary = {
        "correlation_collapsed": corr["any_above_0_9"],
        "max_abs_pearson": corr["max_abs_pearson"],
        "incremental_vs_ofr": _pass_count(incremental_ofr),
        "incremental_vs_all_public": _pass_count(incremental_all),
        "hypothesis_daily_update": _pass_count(hyp_daily),
        "hypothesis_velocity_changepoint": _pass_count(hyp_velocity),
        "hypothesis_kalman_anchor": _pass_count(hyp_kalman),
        "hypothesis_interaction_g1": _pass_count(hyp_interaction),
    }
    # Overall differentiation: any of the three claims survives with significant beta2 + AUC lift
    summary["differentiation_supported"] = bool(
        summary["hypothesis_daily_update"]["passed"]
        or summary["hypothesis_velocity_changepoint"]["passed"]
        or summary["hypothesis_kalman_anchor"]["passed"]
        or summary["hypothesis_interaction_g1"]["passed"]
    )
    summary["g1_nonlinear_gate"] = (
        "ADVANCE_T1_T3"
        if summary["hypothesis_interaction_g1"]["passed"]
        else "CUT_TO_T2_T6_ONLY"
    )
    if summary["correlation_collapsed"]:
        overall = "EQUIVALENT_TO_FREE_DOWNLOAD"
    elif summary["differentiation_supported"]:
        overall = "PARTIAL_DIFFERENTIATION"
    elif summary["incremental_vs_all_public"]["passed"]:
        overall = "INCREMENTAL_BUT_NOT_CLAIMED_AXIS"
    else:
        overall = "NO_INCREMENTAL_INFORMATION"
    summary["overall_verdict"] = overall

    report = {
        "schema_version": "system.public_index_contrast.v1",
        "mode": "shadow_touchstone",
        "inputs": {
            "benchmark_panel": str(args.panel),
            "cross_asset_panel": str(args.cross_asset),
            "structural_signals": str(args.signals),
        },
        "window": {
            "start": str(common.min().date()) if len(common) else None,
            "end": str(common.max().date()) if len(common) else None,
            "observations": len(common),
            "event_rate": _finite(target.dropna().astype(bool).mean()) if target.notna().any() else None,
            "valid_labels": int(target.notna().sum()),
        },
        "public_lags_trading_days": PUBLIC_LAGS_TRADING_DAYS,
        "method_diagnostics": diagnostics,
        "correlation": corr,
        "incremental_vs_ofr_only": incremental_ofr,
        "incremental_vs_all_public": incremental_all,
        "hypotheses": {
            "daily_update": {
                "claim": "Contemporaneous ours beats publication-lagged public indices",
                "results": hyp_daily,
            },
            "velocity_changepoint": {
                "claim": "Velocity / CUSUM / BOCPD add stress onset information beyond public levels",
                "results": hyp_velocity,
            },
            "kalman_anchor": {
                "claim": "M-channel Kalman innovation adds information beyond public levels",
                "results": hyp_kalman,
            },
            "interaction_g1": {
                "claim": "Nonlinear release interactions f1–f3 (or GBM upper bound) beat public-only logistic",
                "results": hyp_interaction,
                "gate": summary["g1_nonlinear_gate"],
            },
        },
        "summary": summary,
    }

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    (args.output / "report.md").write_text(_render_md(report), encoding="utf-8")
    pd.concat(
        [target.rename("stress_event"), ours.add_prefix("ours_"), public.add_prefix("public_")],
        axis=1,
    ).to_csv(args.output / "contrast_panel.csv", index_label="date")
    return report


def _fmt(value: Any, digits: int = 3) -> str:
    numeric = _finite(value)
    return "n/a" if numeric is None else f"{numeric:.{digits}f}"


def _render_md(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Public Index Contrast (OFR / NFCI / CISS)",
        "",
        f"- Window: `{report['window']['start']}` → `{report['window']['end']}`",
        f"- Overall verdict: **{summary['overall_verdict']}**",
        f"- Max |Pearson| vs public: `{_fmt(summary['max_abs_pearson'])}` (collapse if >0.9: `{summary['correlation_collapsed']}`)",
        "",
        "## Correlations",
        "",
        "| Ours | Public | Pearson | Spearman | n | >0.9? |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in report["correlation"]["pairs"]:
        lines.append(
            f"| {row['ours']} | {row['public']} | {_fmt(row['pearson'])} | {_fmt(row['spearman'])} | "
            f"{row['n']} | {row['above_0_9']} |"
        )
    lines.extend(["", "## Incremental vs all public (β₂)", "",
                  "| Candidate | β₂ | p | sig@5% | sign | ΔAUC | ΔPR | passes |",
                  "|---|---:|---:|---|---|---:|---:|---|"])
    for name, result in report["incremental_vs_all_public"].items():
        if result.get("status") != "ok":
            lines.append(f"| {name} | n/a | n/a | n/a | n/a | n/a | n/a | False |")
            continue
        beta = result["beta2"]
        d = result["delta"]
        lines.append(
            f"| {name} | {_fmt(beta.get('coef'))} | {_fmt(beta.get('p_value'), 4)} | "
            f"{beta.get('significant_5pct')} | {result.get('sign_note')} | "
            f"{_fmt(d.get('roc_auc'), 4)} | {_fmt(d.get('pr_auc'), 4)} | "
            f"{result.get('passes')} |"
        )
    for key, title in (
        ("daily_update", "Hypothesis: daily update"),
        ("velocity_changepoint", "Hypothesis: velocity / change-point"),
        ("kalman_anchor", "Hypothesis: Kalman anchor"),
    ):
        block = report["hypotheses"][key]
        lines.extend(["", f"## {title}", "", f"Claim: {block['claim']}", "",
                      "| Candidate | β₂ | p | sig@5% | sign | ΔAUC | passes |",
                      "|---|---:|---:|---|---|---:|---|"])
        for name, result in block["results"].items():
            if result.get("status") != "ok":
                lines.append(f"| {name} | n/a | n/a | n/a | n/a | n/a | False |")
                continue
            beta = result["beta2"]
            lines.append(
                f"| {name} | {_fmt(beta.get('coef'))} | {_fmt(beta.get('p_value'), 4)} | "
                f"{beta.get('significant_5pct')} | {result.get('sign_note')} | "
                f"{_fmt(result['delta'].get('roc_auc'), 4)} | "
                f"{result.get('passes')} |"
            )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--cross-asset", type=Path, default=DEFAULT_CROSS_ASSET)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps({
        "status": "ok",
        "output": str(DEFAULT_OUTPUT),
        "overall_verdict": result["summary"]["overall_verdict"],
        "summary": result["summary"],
    }, ensure_ascii=False))
