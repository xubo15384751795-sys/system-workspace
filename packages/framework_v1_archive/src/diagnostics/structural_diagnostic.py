from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from src.core.models import ProxyReading, StructuralDiagnosticState
from src.diagnostics.morphology_classifier import classify_morphology
from src.diagnostics.rejection_gates import evaluate_rejection_gates
from src.diagnostics.residualization import latest_residual_value, zscore


AGGREGATE_BENCHMARK_COLUMNS = (
    "NFCI",
    "ANFCI",
    "NFCIRISK",
    "NFCICREDIT",
    "NFCILEVERAGE",
    "STLFSI4",
    "KCFSI",
    "OFRFSI",
    "OFR_FSI",
)

VOL_JUMP_TAIL_CONTROLS = (
    "VIXCLS",
    "VIX",
    "MOVE",
    "SPX_realized_vol_21d",
    "TY_realized_vol_21d",
    "K_REALIZED_JUMP",
    "K_TAIL_CONVEXITY",
)

LEVERAGE_CONTROLS = ("NFCILEVERAGE", "X_MARGIN_DEBT", "X_BROKER_DEALER_ASSETS", "X_REPO_VOLUME_COLLATERAL_REUSE")
LIQUIDITY_CONTROLS = ("D_BID_ASK_SPREAD", "D_AMIHUD_ILLIQUIDITY", "D_MARKET_DEPTH", "SOFR_TBILL_3M")
CREDIT_CONTROLS = ("BAMLH0A0HYM2", "BAMLC0A0CM", "BAA_AAA_spread", "HY_IG_GAP")


def build_structural_diagnostic_state(
    run_date: str,
    proxy: ProxyReading,
    sigma_t: float | None,
    raw_history: pd.DataFrame | None = None,
) -> StructuralDiagnosticState:
    components = {
        "M_anchor_mismatch": proxy.M,
        "D_path_feasibility": proxy.D,
        "D_stress": _positive_or_zero(-(proxy.D or 0.0)),
        "K_transition_deformation": proxy.K,
        "X_shadow_accumulation": proxy.X,
    }
    subcomponents = _subcomponent_tree(proxy.components)
    benchmark_values = _latest_benchmarks(raw_history)
    residuals = _residual_diagnostics(raw_history, proxy, sigma_t)
    morphology = classify_morphology(components=components, residuals=residuals, benchmarks=benchmark_values)
    rejection_flags = evaluate_rejection_gates(
        channels=_channel_frame(raw_history),
        sigma=_series_or_none(raw_history, "SIGMA_T"),
        benchmarks=raw_history,
        incremental_metrics={},
        event_coherence={},
        portfolio_metrics={},
    )
    return StructuralDiagnosticState(
        date=run_date,
        sigma_t=sigma_t,
        components=components,
        subcomponents=subcomponents,
        benchmarks=benchmark_values,
        residual_diagnostics=residuals,
        morphology=morphology.to_dict(),
        rejection_flags=rejection_flags,
    )


def _subcomponent_tree(components: Mapping[str, float | None]) -> dict[str, dict[str, float | None]]:
    mapping = {
        "M": {
            "policy_anchor": "M_POLICY_ANCHOR",
            "funding_anchor": "M_FUNDING_ANCHOR",
            "collateral_anchor": "M_COLLATERAL_ANCHOR",
            "credit_anchor": "M_CREDIT_ANCHOR",
            "verifiability_anchor": "M_VERIFIABILITY_ANCHOR",
        },
        "D": {
            "market_depth": "D_MARKET_DEPTH",
            "hedge_breadth": "D_HEDGE_BREADTH",
            "funding_access": "D_FUNDING_ACCESS",
            "liquidation_paths": "D_LIQUIDATION_PATHS",
        },
        "K": {
            "iv_surface_deformation": "K_IV_SURFACE_DEFORMATION",
            "jump_discontinuity": "K_JUMP_DISCONTINUITY",
            "tail_convexity": "K_TAIL_CONVEXITY",
            "transition_instability": "K_TRANSITION_INSTABILITY",
        },
        "X": {
            "hidden_leverage": "X_HIDDEN_LEVERAGE",
            "shadow_substitution": "X_SHADOW_SUBSTITUTION",
            "maturity_mismatch": "X_MATURITY_MISMATCH",
            "valuation_lag": "X_VALUATION_LAG",
        },
    }
    return {
        channel: {label: components.get(source) for label, source in labels.items()}
        for channel, labels in mapping.items()
    }


def _latest_benchmarks(raw_history: pd.DataFrame | None) -> dict[str, float | None]:
    if raw_history is None or raw_history.empty:
        return {}
    out: dict[str, float | None] = {}
    aliases = {"OFRFSI": "OFR_FSI", "VIXCLS": "VIX_z", "BAMLH0A0HYM2": "HY_OAS_z", "BAMLC0A0CM": "IG_OAS_z"}
    for col in list(AGGREGATE_BENCHMARK_COLUMNS) + ["VIXCLS", "MOVE", "BAMLH0A0HYM2", "BAMLC0A0CM"]:
        if col not in raw_history.columns:
            continue
        series = pd.to_numeric(raw_history[col], errors="coerce")
        latest_z = zscore(series).dropna()
        latest_raw = series.dropna()
        key = aliases.get(col, col)
        if key.endswith("_z"):
            out[key] = float(latest_z.iloc[-1]) if not latest_z.empty else None
        else:
            out[key] = float(latest_raw.iloc[-1]) if not latest_raw.empty else None
    return out


def _residual_diagnostics(
    raw_history: pd.DataFrame | None,
    proxy: ProxyReading,
    sigma_t: float | None,
) -> dict[str, float | None]:
    if raw_history is None or raw_history.empty:
        return {
            "M_resid_vs_NFCI": None,
            "D_resid_vs_NFCI": None,
            "K_resid_vs_vol_jump_tail": None,
            "X_resid_vs_leverage": None,
            "Sigma_resid_vs_aggregate_stress": None,
        }
    frame = raw_history.copy()
    for channel, value in {"M": proxy.M, "D": proxy.D, "K": proxy.K, "X": proxy.X, "SIGMA_T": sigma_t}.items():
        if channel not in frame.columns and value is not None:
            frame[channel] = np.nan
            frame.loc[frame.index[-1], channel] = float(value)
            frame[channel] = frame[channel].ffill()
    controls_aggregate = _controls(frame, ("NFCI", "ANFCI", "STLFSI4", "OFRFSI", "OFR_FSI"))
    return {
        "M_resid_vs_NFCI": latest_residual_value(frame["M"], _controls(frame, ("NFCI",) + CREDIT_CONTROLS)) if "M" in frame else None,
        "D_resid_vs_NFCI": latest_residual_value(frame["D"], _controls(frame, ("NFCI",) + LIQUIDITY_CONTROLS)) if "D" in frame else None,
        "K_resid_vs_vol_jump_tail": latest_residual_value(frame["K"], _controls(frame, VOL_JUMP_TAIL_CONTROLS)) if "K" in frame else None,
        "X_resid_vs_leverage": latest_residual_value(frame["X"], _controls(frame, LEVERAGE_CONTROLS)) if "X" in frame else None,
        "Sigma_resid_vs_aggregate_stress": latest_residual_value(frame["SIGMA_T"], controls_aggregate) if "SIGMA_T" in frame else None,
    }


def _controls(frame: pd.DataFrame, columns: tuple[str, ...]) -> dict[str, pd.Series]:
    return {col: frame[col] for col in columns if col in frame.columns}


def _channel_frame(raw_history: pd.DataFrame | None) -> pd.DataFrame | None:
    if raw_history is None or raw_history.empty:
        return None
    cols = [col for col in ("M", "D", "K", "X") if col in raw_history.columns]
    if not cols:
        return None
    return raw_history[cols]


def _series_or_none(raw_history: pd.DataFrame | None, column: str) -> pd.Series | None:
    if raw_history is None or raw_history.empty or column not in raw_history.columns:
        return None
    return raw_history[column]


def _positive_or_zero(value: float | None) -> float:
    if value is None or not np.isfinite(value):
        return 0.0
    return float(max(0.0, value))
