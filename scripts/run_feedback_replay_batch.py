"""Run Feedback Replay Batch.

For each sample in the manifest, extract system state as of as_of_date
using only data available before that date. Compute proxy values (M/D/K/X),
generate a judgment card, and record watch/invalidation conditions.

This is NOT the full daily pipeline — it is a lightweight replay that
extracts measurable state from historical data. The purpose is to
create judgment-closed-loop samples at scale.

Output: Output/feedback_samples/replay_runs/{sample_id}.json

Usage:
    python3 scripts/run_feedback_replay_batch.py
    python3 scripts/run_feedback_replay_batch.py --limit 50
    python3 scripts/run_feedback_replay_batch.py --sample-id 2020-03-15_stress_window_a1b2c3d4
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_scripts
add_scripts()
from _runtime_io import ensure_dir, load_jsonl, utc_now, write_json  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MANIFEST_PATH = ROOT / "Data" / "feedback_samples" / "sample_manifest.jsonl"
PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
VIX_PATH = ROOT / "Data" / "structural_lab" / "runtime" / "fred_cache" / "VIXCLS.csv"
T10Y2Y_PATH = ROOT / "Data" / "structural_lab" / "runtime" / "fred_cache" / "T10Y2Y.csv"
DFF_PATH = ROOT / "Data" / "structural_lab" / "runtime" / "fred_cache" / "DFF.csv"
HY_OAS_PATH = ROOT / "Data" / "structural_lab" / "runtime" / "fred_cache" / "BAMLH0A0HYM2.csv"
REPLAY_DIR = ROOT / "Output" / "feedback_samples" / "replay_runs"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_panel() -> pd.DataFrame:
    """Load cross-asset panel, indexed by date with symbol columns."""
    df = pd.read_parquet(PANEL_PATH)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _load_fred_csv(path: Path) -> pd.Series | None:
    """Load a FRED CSV as a date-indexed Series of float values."""
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, parse_dates=["DATE"], index_col="DATE")
        col = df.columns[0]
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        s.index = pd.to_datetime(s.index)
        return s
    except Exception:
        return None


def _build_close_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    """Build date x symbol close price matrix.

    Uses per-symbol Series construction to avoid pandas groupby/unstack
    index corruption on large panels.
    """
    symbols = sorted(panel["symbol"].unique())
    series_map = {}
    for sym in symbols:
        sub = panel[panel["symbol"] == sym][["date", "close"]].set_index("date")["close"]
        series_map[sym] = sub
    mat = pd.DataFrame(series_map).sort_index()
    return mat


def _build_return_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    """Build date x symbol return_1d matrix."""
    symbols = sorted(panel["symbol"].unique())
    series_map = {}
    for sym in symbols:
        sub = panel[panel["symbol"] == sym][["date", "return_1d"]].set_index("date")["return_1d"]
        series_map[sym] = sub
    mat = pd.DataFrame(series_map).sort_index()
    return mat


# ---------------------------------------------------------------------------
# Proxy computation (M / D / K / X)
# ---------------------------------------------------------------------------

def _compute_m_proxy(
    close_matrix: pd.DataFrame,
    hy_oas: pd.Series | None,
    vix_series: pd.Series | None,
    as_of: pd.Timestamp,
) -> dict:
    """Compute M (stress measurement) proxy from available data.

    M combines:
    - HYG/TLT relative performance (credit vs safety)
    - VIX level
    - HY OAS spread (if available)
    """
    lookback = as_of - pd.Timedelta(days=90)
    window = close_matrix.loc[lookback:as_of]
    if window.empty:
        return {"value": None, "components": {}, "status": "insufficient_data"}

    components = {}

    # HYG/TLT ratio z-score (credit stress)
    if "HYG" in window.columns and "TLT" in window.columns:
        ratio = (window["HYG"] / window["TLT"]).dropna()
        if len(ratio) >= 20:
            z = (ratio.iloc[-1] - ratio.mean()) / max(ratio.std(), 1e-8)
            components["hyg_tlt_z"] = round(float(z), 4)
        else:
            components["hyg_tlt_z"] = None
    else:
        components["hyg_tlt_z"] = None

    # SPY drawdown from 60d high
    if "SPY" in window.columns:
        spy = window["SPY"].dropna()
        if len(spy) >= 20:
            high_60d = spy.rolling(60, min_periods=20).max()
            dd = (spy.iloc[-1] / high_60d.iloc[-1]) - 1 if high_60d.iloc[-1] > 0 else 0
            components["spy_drawdown_60d"] = round(float(dd), 4)
        else:
            components["spy_drawdown_60d"] = None
    else:
        components["spy_drawdown_60d"] = None

    # VIX level
    if vix_series is not None:
        vix_window = vix_series.loc[lookback:as_of].dropna()
        if len(vix_window) > 0:
            components["vix_level"] = round(float(vix_window.iloc[-1]), 2)
        else:
            components["vix_level"] = None
    else:
        components["vix_level"] = None

    # HY OAS
    if hy_oas is not None:
        oas_window = hy_oas.loc[lookback:as_of].dropna()
        if len(oas_window) > 0:
            components["hy_oas"] = round(float(oas_window.iloc[-1]), 2)
        else:
            components["hy_oas"] = None
    else:
        components["hy_oas"] = None

    # Composite M value (weighted sum of z-scores, negative = stress)
    vals = []
    if components.get("hyg_tlt_z") is not None:
        vals.append(components["hyg_tlt_z"] * -1.0)  # lower ratio = more stress
    if components.get("spy_drawdown_60d") is not None:
        vals.append(components["spy_drawdown_60d"] * 10)  # scale drawdown
    if components.get("vix_level") is not None:
        # VIX z-score over 2-year window
        vix_full = vix_series.loc[:as_of].dropna()
        if len(vix_full) > 252:
            vix_mean = vix_full.iloc[-504:].mean() if len(vix_full) >= 504 else vix_full.mean()
            vix_std = vix_full.iloc[-504:].std() if len(vix_full) >= 504 else vix_full.std()
            vix_z = (components["vix_level"] - vix_mean) / max(vix_std, 1e-8)
            vals.append(vix_z * 0.5)

    m_value = round(float(np.mean(vals)), 4) if vals else None

    return {
        "value": m_value,
        "components": components,
        "status": "computed" if m_value is not None else "insufficient_data",
    }


def _compute_d_proxy(
    return_matrix: pd.DataFrame,
    close_matrix: pd.DataFrame,
    as_of: pd.Timestamp,
) -> dict:
    """Compute D (directional measurement) proxy.

    D captures the direction and magnitude of cross-asset moves.
    """
    lookback = as_of - pd.Timedelta(days=30)
    window = close_matrix.loc[lookback:as_of]
    if window.empty:
        return {"value": None, "components": {}, "status": "insufficient_data"}

    components = {}

    # SPY 20d return
    if "SPY" in window.columns:
        spy = window["SPY"].dropna()
        if len(spy) >= 20:
            ret_20d = (spy.iloc[-1] / spy.iloc[-20]) - 1
            components["spy_return_20d"] = round(float(ret_20d), 4)
        else:
            components["spy_return_20d"] = None
    else:
        components["spy_return_20d"] = None

    # HYG 20d return
    if "HYG" in window.columns:
        hyg = window["HYG"].dropna()
        if len(hyg) >= 20:
            ret_20d = (hyg.iloc[-1] / hyg.iloc[-20]) - 1
            components["hyg_return_20d"] = round(float(ret_20d), 4)
        else:
            components["hyg_return_20d"] = None
    else:
        components["hyg_return_20d"] = None

    # SPY-HYG co-movement (are they moving together or diverging?)
    if components.get("spy_return_20d") is not None and components.get("hyg_return_20d") is not None:
        sign_same = (components["spy_return_20d"] > 0) == (components["hyg_return_20d"] > 0)
        components["direction_alignment"] = sign_same
    else:
        components["direction_alignment"] = None

    # Composite D
    vals = []
    if components.get("spy_return_20d") is not None:
        vals.append(components["spy_return_20d"])
    if components.get("hyg_return_20d") is not None:
        vals.append(components["hyg_return_20d"])

    d_value = round(float(np.mean(vals)), 4) if vals else None

    return {
        "value": d_value,
        "components": components,
        "status": "computed" if d_value is not None else "insufficient_data",
    }


def _compute_k_proxy(
    t10y2y: pd.Series | None,
    close_matrix: pd.DataFrame,
    as_of: pd.Timestamp,
) -> dict:
    """Compute K (curvature) proxy.

    K captures yield curve shape and convexity stress.
    """
    components = {}

    # T10Y2Y spread
    if t10y2y is not None:
        spread_window = t10y2y.loc[:as_of].dropna()
        if len(spread_window) > 0:
            current_spread = float(spread_window.iloc[-1])
            components["t10y2y"] = round(current_spread, 4)
            # Historical percentile
            if len(spread_window) >= 252:
                pct = (spread_window.iloc[-252:] < current_spread).mean()
                components["t10y2y_percentile_1y"] = round(float(pct), 4)
        else:
            components["t10y2y"] = None
    else:
        components["t10y2y"] = None

    # Curvature: TLT convexity stress (large moves in long bonds)
    if "TLT" in close_matrix.columns:
        lookback = as_of - pd.Timedelta(days=60)
        tlt_window = close_matrix.loc[lookback:as_of, "TLT"].dropna()
        if len(tlt_window) >= 20:
            tlt_returns = tlt_window.pct_change().dropna()
            if len(tlt_returns) > 5:
                kurtosis = float(tlt_returns.kurtosis())
                components["tlt_return_kurtosis_60d"] = round(kurtosis, 4)
        else:
            components["tlt_return_kurtosis_60d"] = None
    else:
        components["tlt_return_kurtosis_60d"] = None

    # Composite K (inverted yield curve = negative, stress = high curvature)
    k_value = None
    if components.get("t10y2y") is not None:
        k_value = round(-1.0 * components["t10y2y"], 4)  # negative spread = positive K stress

    return {
        "value": k_value,
        "components": components,
        "status": "computed" if k_value is not None else "insufficient_data",
    }


def _compute_x_proxy(
    close_matrix: pd.DataFrame,
    as_of: pd.Timestamp,
) -> dict:
    """Compute X (cross-market contagion) proxy.

    X captures cross-asset correlation breakdown.
    """
    lookback = as_of - pd.Timedelta(days=60)
    window = close_matrix.loc[lookback:as_of]
    if window.empty or len(window) < 20:
        return {"value": None, "components": {}, "status": "insufficient_data"}

    components = {}

    # Compute pairwise returns correlation
    rets = window.pct_change(fill_method=None).dropna()
    assets = [a for a in ["SPY", "HYG", "TLT", "GLD"] if a in rets.columns]
    if len(assets) >= 3:
        corr_matrix = rets[assets].corr()
        # Average off-diagonal correlation
        n = len(assets)
        off_diag = []
        for i in range(n):
            for j in range(i + 1, n):
                off_diag.append(corr_matrix.iloc[i, j])
        avg_corr = float(np.mean(off_diag))
        components["avg_cross_corr_60d"] = round(avg_corr, 4)

        # SPY-HYG correlation breakdown (normally positive, negative = stress)
        if "SPY" in rets.columns and "HYG" in rets.columns:
            spy_hyg_corr = float(rets["SPY"].corr(rets["HYG"]))
            components["spy_hyg_corr_60d"] = round(spy_hyg_corr, 4)
    else:
        components["avg_cross_corr_60d"] = None

    # X value: high correlation = contagion risk
    x_value = components.get("avg_cross_corr_60d")
    # Guard against NaN
    if x_value is not None and (x_value != x_value):  # NaN check
        x_value = None

    return {
        "value": x_value,
        "components": components,
        "status": "computed" if x_value is not None else "insufficient_data",
    }


# ---------------------------------------------------------------------------
# Judgment generation
# ---------------------------------------------------------------------------

def _generate_judgment(
    m: dict, d: dict, k: dict, x: dict,
    as_of: pd.Timestamp,
    sample_type: str,
) -> dict:
    """Generate a judgment card from M/D/K/X proxies.

    Follows the system's claim ladder logic:
    - Tier 0: observation
    - Tier 1: mechanism_hypothesis
    - Tier 2: watch_condition
    - Tier 3: operational
    """
    m_val = m.get("value")
    d_val = d.get("value")
    k_val = k.get("value")
    x_val = x.get("value")

    # Determine stress direction
    stress_signals = []
    if m_val is not None and m_val < -0.5:
        stress_signals.append("m_stress")
    if d_val is not None and d_val < -0.02:
        stress_signals.append("d_negative")
    if k_val is not None and k_val > 0.5:
        stress_signals.append("k_curve_stress")
    if x_val is not None and x_val > 0.7:
        stress_signals.append("x_contagion")

    relief_signals = []
    if m_val is not None and m_val > 0.3:
        relief_signals.append("m_relief")
    if d_val is not None and d_val > 0.02:
        relief_signals.append("d_positive")

    # Determine decision
    if len(stress_signals) >= 3:
        decision = "WATCH"
        confidence = "medium"
        claim_tier = 2
        claim_label = "watch_condition"
    elif len(stress_signals) >= 2:
        decision = "RESEARCH_REVIEW"
        confidence = "low" if len(stress_signals) == 2 else "medium"
        claim_tier = 1
        claim_label = "mechanism_hypothesis"
    elif len(relief_signals) >= 2:
        decision = "NO_TRADE"
        confidence = "low"
        claim_tier = 1
        claim_label = "mechanism_hypothesis"
    else:
        decision = "NO_TRADE"
        confidence = "low"
        claim_tier = 0
        claim_label = "observation"

    # Mechanism hypothesis
    if stress_signals:
        mech = f"Cross-asset stress indicators: {', '.join(stress_signals)}"
    elif relief_signals:
        mech = f"Cross-asset relief indicators: {', '.join(relief_signals)}"
    else:
        mech = "No clear directional signal from M/D/K/X"

    # Clean NaN values for display
    def _clean(v):
        if v is None:
            return None
        try:
            if v != v:  # NaN
                return None
        except (TypeError, ValueError):
            pass
        return v

    m_val = _clean(m_val)
    d_val = _clean(d_val)
    k_val = _clean(k_val)
    x_val = _clean(x_val)

    # Watch conditions
    watch_conditions = []
    if m_val is not None:
        if m_val < -0.5:
            watch_conditions.append(f"If M deepens below {m_val - 0.3:.2f}, escalate to operational tier")
        else:
            watch_conditions.append(f"If M drops below -0.5 (currently {m_val:.2f}), enter stress monitoring")
    if k_val is not None and k_val > 0.3:
        watch_conditions.append(f"Monitor K curvature ({k_val:.2f}) for further inversion stress")

    # Invalidation conditions
    invalidation = []
    if m_val is not None:
        invalidation.append(f"If M reverses sign (currently {m_val:.2f}), the stress hypothesis is invalidated")
    if d_val is not None:
        invalidation.append(f"If D direction reverses (currently {d_val:.4f}), re-evaluate")
    if k_val is not None and k_val > 0.3:
        invalidation.append(f"If K curvature normalizes below 0.3 (currently {k_val:.2f}), curve stress resolved")

    # Confidence reasons
    conf_reasons = []
    data_points = sum(1 for v in [m_val, d_val, k_val, x_val] if v is not None)
    conf_reasons.append(f"{data_points}/4 proxy channels available")
    if x_val is not None and x_val > 0.7:
        conf_reasons.append("High cross-asset correlation suggests regime stress")

    return {
        "decision": decision,
        "confidence": confidence,
        "claim_tier": claim_tier,
        "claim_label": claim_label,
        "claim_statement": f"{mech}. M={m_val}, D={d_val}, K={k_val}, X={x_val}.",
        "mechanism_hypothesis": mech,
        "evidence_grade": "C" if data_points >= 3 else "D",
        "watch_conditions": watch_conditions,
        "invalidation_conditions": invalidation,
        "confidence_reasons": conf_reasons,
    }


# ---------------------------------------------------------------------------
# Single sample replay
# ---------------------------------------------------------------------------

def replay_sample(
    sample: dict,
    close_matrix: pd.DataFrame,
    return_matrix: pd.DataFrame,
    vix_series: pd.Series | None,
    t10y2y: pd.Series | None,
    hy_oas: pd.Series | None,
    dff: pd.Series | None,
) -> dict:
    """Run replay for a single sample entry."""
    as_of = pd.Timestamp(sample["as_of_date"])
    allowed_lookback = pd.Timestamp(sample.get("allowed_lookback", "2000-01-01"))

    # Compute proxies using only data up to as_of
    m = _compute_m_proxy(close_matrix, hy_oas, vix_series, as_of)
    d = _compute_d_proxy(return_matrix, close_matrix, as_of)
    k = _compute_k_proxy(t10y2y, close_matrix, as_of)
    x = _compute_x_proxy(close_matrix, as_of)

    # Generate judgment
    judgment = _generate_judgment(m, d, k, x, as_of, sample["sample_type"])

    # Build the replay output
    result = {
        "schema_version": "feedback_sample.v1",
        "sample_id": sample["sample_id"],
        "as_of_date": sample["as_of_date"],
        "sample_type": sample["sample_type"],
        "why_selected": sample.get("why_selected", ""),
        "generated_at": utc_now().isoformat(),
        "allowed_lookback": sample.get("allowed_lookback", ""),
        "system_state": {
            "m_value": m.get("value"),
            "d_value": d.get("value"),
            "k_value": k.get("value"),
            "x_value": x.get("value"),
            "m_components": m.get("components", {}),
            "d_components": d.get("components", {}),
            "k_components": k.get("components", {}),
            "x_components": x.get("components", {}),
            "data_quality": {
                "m_status": m.get("status"),
                "d_status": d.get("status"),
                "k_status": k.get("status"),
                "x_status": x.get("status"),
            },
        },
        "system_judgment": judgment,
        "conditions": {
            "watch_conditions": judgment.get("watch_conditions", []),
            "invalidation_conditions": judgment.get("invalidation_conditions", []),
        },
        "forward_outcome": {},  # To be filled by evaluate_feedback_samples.py
        "review_label": "needs_review",
    }

    return result


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_batch(
    limit: int | None = None,
    sample_id: str | None = None,
    force: bool = False,
) -> int:
    """Run replay for all (or a subset of) samples in the manifest."""
    # Load manifest
    manifest = load_jsonl(MANIFEST_PATH)
    if not manifest:
        print(f"[ERROR] No manifest found at {MANIFEST_PATH}")
        print("        Run build_feedback_sample_pool.py first.")
        return 1

    print(f"[INFO] Manifest has {len(manifest)} entries")

    # Filter if sample_id specified
    if sample_id:
        manifest = [e for e in manifest if e.get("sample_id") == sample_id]
        if not manifest:
            print(f"[ERROR] sample_id '{sample_id}' not found in manifest")
            return 1

    # Limit
    if limit and limit < len(manifest):
        manifest = manifest[:limit]
        print(f"[INFO] Limited to first {limit} entries")

    # Load data
    print("[INFO] Loading market data...")
    panel = _load_panel()
    close_matrix = _build_close_matrix(panel)
    return_matrix = _build_return_matrix(panel)
    vix_series = _load_fred_csv(VIX_PATH)
    t10y2y = _load_fred_csv(T10Y2Y_PATH)
    hy_oas = _load_fred_csv(HY_OAS_PATH)
    dff = _load_fred_csv(DFF_PATH)
    print("[INFO] Data loaded")

    # Ensure output directory
    ensure_dir(REPLAY_DIR)

    # Run replays
    completed = 0
    skipped = 0
    errors = 0

    for i, sample in enumerate(manifest):
        sid = sample.get("sample_id", f"unknown_{i}")
        out_path = REPLAY_DIR / f"{sid}.json"

        # Skip if already exists (unless --force)
        if out_path.exists() and not force:
            skipped += 1
            continue

        try:
            result = replay_sample(
                sample, close_matrix, return_matrix,
                vix_series, t10y2y, hy_oas, dff,
            )
            write_json(out_path, result)
            completed += 1

            if (completed + skipped) % 50 == 0:
                print(f"  [{completed + skipped}/{len(manifest)}] processed")

        except Exception as e:
            print(f"  [ERROR] {sid}: {e}")
            errors += 1

    print(f"\n[DONE] Completed: {completed}, Skipped: {skipped}, Errors: {errors}")
    print(f"       Outputs in: {REPLAY_DIR}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run feedback replay batch on sample manifest"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit number of samples to process"
    )
    parser.add_argument(
        "--sample-id", type=str, default=None,
        help="Process only a specific sample ID"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing replay outputs"
    )
    args = parser.parse_args()
    run_batch(limit=args.limit, sample_id=args.sample_id, force=args.force)


if __name__ == "__main__":
    main()
