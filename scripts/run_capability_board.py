#!/usr/bin/env python3
"""Weekly capability board — three fixed proof tables (shadow-only).

Tables written under Output/validation/capability_board/:
  1. residual_vs_public.csv   — β₂ / ΔAUC for residual modes A (level) and B (velocity)
  2. paper_nav_compare.csv    — A λ=1 / B λ=1 / λ=0 (public-only) / incumbent velocity
  3. event_sensitivity.csv    — AUC under RV 5%/10% × DD −5%/−8% definitions

Without these three tables, capability upgrades cannot be proven.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from _data_paths import resolve_cross_asset_panel_path
    from professional_methods import build_forward_stress_events
    from public_residual_stress import (
        build_public_residual_bundle,
        event_definition_sensitivity,
        extract_public_levels,
        residual_incremental_vs_public,
    )
    from run_professional_methodology import (
        load_benchmark_panel,
        load_channels,
        load_spy,
    )
    from strategy_lab.risk_gate import compute_velocity_gate
    from strategy_lab.strategies import (
        compute_baseline_position,
        compute_system_overlay_position,
    )
except ModuleNotFoundError:
    from scripts._data_paths import resolve_cross_asset_panel_path
    from scripts.professional_methods import build_forward_stress_events
    from scripts.public_residual_stress import (
        build_public_residual_bundle,
        event_definition_sensitivity,
        extract_public_levels,
        residual_incremental_vs_public,
    )
    from scripts.run_professional_methodology import (
        load_benchmark_panel,
        load_channels,
        load_spy,
    )
    from scripts.strategy_lab.risk_gate import compute_velocity_gate
    from scripts.strategy_lab.strategies import (
        compute_baseline_position,
        compute_system_overlay_position,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
DEFAULT_CROSS_ASSET = resolve_cross_asset_panel_path()
DEFAULT_SIGNALS = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "all_signals.parquet"
DEFAULT_OUTPUT = ROOT / "Output" / "validation" / "capability_board"

RESIDUAL_MODES = ("level", "velocity")


def _finite(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _simulate_nav(
    returns: pd.Series,
    position: pd.Series,
    *,
    cost_bps: float = 3.0,
    slippage_bps: float = 2.0,
) -> pd.Series:
    """Close-to-close NAV with one-way turnover costs."""
    pos = position.reindex(returns.index).fillna(0.0).clip(0.0, 1.0)
    ret = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    cost_rate = (cost_bps + slippage_bps) / 10000.0
    nav = np.empty(len(ret), dtype=float)
    nav[0] = 1.0
    prev = float(pos.iloc[0])
    for i in range(1, len(ret)):
        target = float(pos.iloc[i])
        day_pnl = prev * float(ret.iloc[i])
        cost = abs(target - prev) * cost_rate
        nav[i] = nav[i - 1] * (1.0 + day_pnl - cost)
        prev = target
    return pd.Series(nav, index=returns.index, name="nav")


def table_residual_vs_public(
    events: pd.Series,
    bundles: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    rows = []
    for mode, bundle in bundles.items():
        result = residual_incremental_vs_public(
            events, bundle["p_public"], bundle["p_onset"], embargo=20
        )
        delta = result.get("delta") if isinstance(result.get("delta"), dict) else {}
        aug = result.get("augmented") if isinstance(result.get("augmented"), dict) else {}
        coeffs = aug.get("coefficients") if isinstance(aug.get("coefficients"), dict) else {}
        beta_onset = _finite(coeffs.get("candidate"))
        row_pass = bool(
            result.get("status") == "ok"
            and (delta.get("roc_auc") or -1) > 0
            and (delta.get("pr_auc") or -1) >= 0
            and (beta_onset or 0) > 0
        )
        rows.append(
            {
                "residual_mode": mode,
                "status": result.get("status"),
                "n_train": result.get("n_train"),
                "n_test": result.get("n_test"),
                "embargo": result.get("embargo"),
                "beta_public": _finite(coeffs.get("p_public")),
                "beta_onset": beta_onset,
                "delta_roc_auc": _finite(delta.get("roc_auc")),
                "delta_pr_auc": _finite(delta.get("pr_auc")),
                "brier_improvement": _finite(delta.get("brier_improvement")),
                "pass_incremental": row_pass,
            }
        )
    return pd.DataFrame(rows)


def table_paper_nav_compare(
    close: pd.Series,
    channels: pd.DataFrame,
    public_levels: pd.DataFrame,
    bundles: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    returns = close.pct_change()
    baseline = compute_baseline_position(close, lookback=63)
    gate = compute_velocity_gate(channels, close=close)
    velocity_overlay = compute_system_overlay_position(baseline, gate).reindex(close.index).fillna(0.0)

    schemes: dict[str, pd.Series] = {
        "incumbent_velocity": velocity_overlay,
    }
    # λ=0 via same dual-stress path (onset term disabled) — public-only control.
    lambda0 = build_public_residual_bundle(
        channels,
        public_levels,
        returns,
        residual_mode="level",
        onset_lambda=0.0,
    )
    schemes["public_lambda0"] = (
        baseline.reindex(close.index).fillna(0.0) * lambda0["sizing"]["position"]
    ).clip(0.0, 1.0)

    for mode, bundle in bundles.items():
        schemes[f"public_residual_{mode}"] = (
            baseline.reindex(close.index).fillna(0.0) * bundle["sizing"]["position"]
        ).clip(0.0, 1.0)

    rows = []
    for name, pos in schemes.items():
        nav = _simulate_nav(returns, pos)
        active = pos.dropna()
        rows.append(
            {
                "scheme": name,
                "n": int(nav.notna().sum()),
                "end_nav": _finite(nav.dropna().iloc[-1]) if nav.notna().any() else None,
                "total_return": _finite(nav.dropna().iloc[-1] - 1.0) if nav.notna().any() else None,
                "sharpe": _finite(_nav_sharpe(nav)),
                "max_dd": _finite(_nav_max_drawdown(nav)),
                "mean_position": _finite(active.mean()),
                "turnover_sum": _finite(active.diff().abs().sum()),
            }
        )
    return pd.DataFrame(rows)


def _nav_sharpe(nav: pd.Series, periods: int = 252) -> float:
    ret = pd.to_numeric(nav, errors="coerce").pct_change().dropna()
    if len(ret) < 2 or float(ret.std()) < 1e-12:
        return float("nan")
    return float(ret.mean() / ret.std() * np.sqrt(periods))


def _nav_max_drawdown(nav: pd.Series) -> float:
    level = pd.to_numeric(nav, errors="coerce").dropna()
    if level.empty:
        return float("nan")
    peak = level.cummax()
    dd = level / peak - 1.0
    return float(dd.min())


def table_event_sensitivity(
    close: pd.Series,
    p_public: pd.Series,
    onset_by_mode: dict[str, pd.Series],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    series_map: dict[str, pd.Series] = {"p_public": p_public}
    for mode, onset in onset_by_mode.items():
        series_map[f"p_onset_{mode}"] = onset
        series_map[f"blend_{mode}"] = 0.5 * p_public.fillna(0.5) + 0.5 * onset.fillna(0.0)

    for label, series in series_map.items():
        for item in event_definition_sensitivity(close, series):
            if item.get("definition") == "_consistency":
                rows.append(
                    {
                        "signal": label,
                        "definition": "_consistency",
                        "all_above_random": item.get("all_above_random"),
                        "auc_range": item.get("auc_range"),
                        "n_definitions": item.get("n_definitions"),
                    }
                )
            else:
                rows.append(
                    {
                        "signal": label,
                        "definition": item.get("definition"),
                        "logic": item.get("logic"),
                        "vol_quantile": item.get("vol_quantile"),
                        "drawdown_threshold": item.get("drawdown_threshold"),
                        "event_rate": item.get("event_rate"),
                        "roc_auc": item.get("roc_auc"),
                        "pr_auc": item.get("pr_auc"),
                        "brier": item.get("brier"),
                        "n": item.get("n"),
                    }
                )
    return pd.DataFrame(rows)


def _md_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_empty_"
    cols = list(frame.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [header, sep]
    for _, row in frame.iterrows():
        cells = []
        for col in cols:
            value = row[col]
            if isinstance(value, float):
                cells.append("n/a" if not np.isfinite(value) else f"{value:.4f}")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def table_framework_candidate_board(
    events: pd.Series,
    channels: pd.DataFrame,
    public_levels: pd.DataFrame,
) -> pd.DataFrame:
    """WP-T7: T6-style incremental checks for preregistered nonlinear candidates."""
    try:
        from professional_methods import (
            causal_pit,
            incremental_logistic_test,
            release_intensity_features,
        )
    except ModuleNotFoundError:
        from scripts.professional_methods import (
            causal_pit,
            incremental_logistic_test,
            release_intensity_features,
        )

    rows: list[dict[str, Any]] = []
    if public_levels.empty:
        return pd.DataFrame(rows)
    baseline = public_levels.apply(lambda col: causal_pit(col, min_periods=126)).dropna(how="all")
    if baseline.empty:
        return pd.DataFrame(rows)

    try:
        feats = release_intensity_features(channels, train_end="2018-12-31")
        for name in ("f1_release_kernel", "f2_forced_sale", "f3_injection_amp"):
            result = incremental_logistic_test(events, baseline, feats[name], embargo=20)
            delta = result.get("delta") if isinstance(result.get("delta"), dict) else {}
            dm = delta.get("diebold_mariano") if isinstance(delta.get("diebold_mariano"), dict) else {}
            dm_p = dm.get("p_value")
            rows.append(
                {
                    "candidate": name,
                    "source": "T5",
                    "status": result.get("status"),
                    "delta_pr_auc": _finite(delta.get("pr_auc")),
                    "delta_roc_auc": _finite(delta.get("roc_auc")),
                    "dm_p_value": _finite(dm_p),
                    "pass_t6_incremental": bool(
                        result.get("status") == "ok"
                        and (delta.get("pr_auc") or -1) > 0
                        and (dm_p is None or dm_p < 0.05)
                    ),
                }
            )
    except Exception as exc:  # noqa: BLE001 — board must not crash on research candidates
        rows.append({"candidate": "interaction_block", "source": "T5", "status": f"error:{exc}"})

    try:
        try:
            from absorption_capacity import build_absorption_capacity
        except ModuleNotFoundError:
            from scripts.absorption_capacity import build_absorption_capacity

        abs_frame = build_absorption_capacity(channels, None)
        for name, series, sign in (
            ("absorption_A", abs_frame["absorption_A"], -1.0),
            ("absorption_A_deterioration", abs_frame.get("absorption_A_deterioration"), 1.0),
        ):
            if series is None:
                continue
            score = (series * sign).rename(name)
            result = incremental_logistic_test(events, baseline, score, embargo=20)
            delta = result.get("delta") if isinstance(result.get("delta"), dict) else {}
            dm = delta.get("diebold_mariano") if isinstance(delta.get("diebold_mariano"), dict) else {}
            dm_p = dm.get("p_value")
            rows.append(
                {
                    "candidate": name,
                    "source": "T2",
                    "status": result.get("status"),
                    "delta_pr_auc": _finite(delta.get("pr_auc")),
                    "delta_roc_auc": _finite(delta.get("roc_auc")),
                    "dm_p_value": _finite(dm_p),
                    "pass_t6_incremental": bool(
                        result.get("status") == "ok"
                        and (delta.get("pr_auc") or -1) > 0
                        and (dm_p is None or dm_p < 0.05)
                    ),
                }
            )
    except Exception as exc:  # noqa: BLE001
        rows.append({"candidate": "absorption_block", "source": "T2", "status": f"error:{exc}"})

    return pd.DataFrame(rows)


def render_markdown(
    residual: pd.DataFrame,
    nav: pd.DataFrame,
    sensitivity: pd.DataFrame,
    recommendation: str,
    framework: pd.DataFrame | None = None,
) -> str:
    lines = [
        "# Weekly Capability Board",
        "",
        "Proof tables for the public-level + residual-onset paper path.",
        "",
        f"**Recommendation (this run):** {recommendation}",
        "",
        "## 1. Residual onset vs public (β₂ / ΔAUC)",
        "",
        "Modes: `level` = A (velocity on level residual); `velocity` = B (onset on velocity-PIT residual).",
        "",
        _md_table(residual),
        "",
        "## 2. Paper NAV compare",
        "",
        "`public_lambda0` = same dual-stress path with λ=0 (onset disabled). Includes Sharpe / max_dd.",
        "",
        _md_table(nav),
        "",
        "## 3. Event-definition sensitivity",
        "",
        _md_table(sensitivity),
        "",
    ]
    if framework is not None and not framework.empty:
        lines.extend(
            [
                "## 4. Nonlinear framework candidates (research)",
                "",
                _md_table(framework),
                "",
            ]
        )
    lines.extend(
        [
            "---",
            "",
            "*Shadow validation only. Not live execution.*",
            "",
        ]
    )
    return "\n".join(lines)


def _recommend(
    residual: pd.DataFrame,
    nav: pd.DataFrame,
    framework: pd.DataFrame | None = None,
) -> str:
    passed = residual.loc[residual["pass_incremental"] == True, "residual_mode"].tolist()  # noqa: E712
    framework_pass: list[str] = []
    if framework is not None and not framework.empty and "pass_t6_incremental" in framework:
        framework_pass = framework.loc[
            framework["pass_t6_incremental"] == True, "candidate"  # noqa: E712
        ].astype(str).tolist()
    if not passed and not framework_pass:
        return (
            "Neither residual mode nor nonlinear candidates pass incremental — "
            "paper use public_lambda0 (λ=0); keep research-only."
        )
    if framework_pass and not passed:
        return (
            f"Nonlinear candidates pass incremental ({', '.join(framework_pass)}) "
            "but residual onset does not — keep λ=0 ops; promote only via WP-T7 routing decision."
        )
    subset = residual.loc[residual["residual_mode"].isin(passed)].copy()
    subset = subset.sort_values(
        by=["delta_pr_auc", "delta_roc_auc"],
        ascending=False,
        na_position="last",
    )
    best = str(subset.iloc[0]["residual_mode"])
    lambda0_nav = nav.loc[nav["scheme"] == "public_lambda0", "end_nav"]
    best_nav = nav.loc[nav["scheme"] == f"public_residual_{best}", "end_nav"]
    if not lambda0_nav.empty and not best_nav.empty:
        if float(best_nav.iloc[0] or 0) + 1e-9 < float(lambda0_nav.iloc[0] or 0):
            return (
                f"Mode `{best}` passes incremental but underperforms public_lambda0 on NAV — "
                "keep λ=0 for paper sizing; residual stays shadow."
            )
    return f"Mode `{best}` passes incremental — candidate for paper residual_mode (still not live)."


def run(args: argparse.Namespace) -> dict[str, Any]:
    panel = load_benchmark_panel(args.panel)
    spy = load_spy(args.cross_asset)
    channels = load_channels(args.signals)
    public = extract_public_levels(panel)

    common = channels.index.intersection(spy.index).intersection(
        public.index if not public.empty else channels.index
    )
    channels = channels.reindex(common)
    close = spy["close"].reindex(common)
    public = public.reindex(common)
    returns = close.pct_change()

    bundles = {
        mode: build_public_residual_bundle(
            channels,
            public,
            returns,
            residual_mode=mode,
            onset_lambda=1.0,
        )
        for mode in RESIDUAL_MODES
    }
    events = build_forward_stress_events(
        close, vol_quantile=0.95, drawdown_threshold=-0.08, logic="or"
    )

    residual_tbl = table_residual_vs_public(events["stress_event"], bundles)
    nav_tbl = table_paper_nav_compare(close, channels, public, bundles)
    sens_tbl = table_event_sensitivity(
        close,
        bundles["level"]["p_public"],
        {mode: bundles[mode]["p_onset"] for mode in RESIDUAL_MODES},
    )
    framework_tbl = table_framework_candidate_board(events["stress_event"], channels, public)
    recommendation = _recommend(residual_tbl, nav_tbl, framework_tbl)

    args.output.mkdir(parents=True, exist_ok=True)
    residual_tbl.to_csv(args.output / "residual_vs_public.csv", index=False)
    nav_tbl.to_csv(args.output / "paper_nav_compare.csv", index=False)
    sens_tbl.to_csv(args.output / "event_sensitivity.csv", index=False)
    framework_tbl.to_csv(args.output / "framework_candidates.csv", index=False)
    (args.output / "board.md").write_text(
        render_markdown(residual_tbl, nav_tbl, sens_tbl, recommendation, framework_tbl),
        encoding="utf-8",
    )
    report = {
        "schema_version": "system.capability_board.v3",
        "mode": "shadow_weekly_board",
        "recommendation": recommendation,
        "inputs": {
            "benchmark_panel": str(args.panel),
            "cross_asset_panel": str(args.cross_asset),
            "structural_signals": str(args.signals),
        },
        "residual_vs_public": residual_tbl.to_dict(orient="records"),
        "paper_nav_compare": nav_tbl.to_dict(orient="records"),
        "framework_candidates": framework_tbl.to_dict(orient="records"),
        "event_sensitivity_consistency": sens_tbl.loc[
            sens_tbl["definition"].eq("_consistency")
        ].to_dict(orient="records"),
        "note": "Paper-path only. Do not promote to live without human review.",
    }
    (args.output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--cross-asset", type=Path, default=DEFAULT_CROSS_ASSET)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(DEFAULT_OUTPUT),
                "recommendation": result["recommendation"],
                "residual": result["residual_vs_public"],
            },
            ensure_ascii=False,
        )
    )
