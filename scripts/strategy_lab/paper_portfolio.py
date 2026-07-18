"""Paper portfolio — shadow NAV with public-level stress × stance×size.

Strategy (paper-only, within system constitution):
  SPY 63d momentum × continuous public stress weight (λ=0 until residual clears board)
    w = w_max · vol_target · (1 − P_public) · (1 − λ · P_onset)
  then scale by trade_decision effective_size (stance × quality size).
  Velocity gate retained as EXIT kill-switch + onset alert source.
  Friction: 3bp cost + 2bp slippage one-way on turnover.

Benchmark: pure 60/40 SPY/TLT (21d rebalance)

Alerts (via notify):
  - level stress: P_public crosses threshold
  - onset: velocity gate FULL → EXIT
  - stance change from trade_decision

Usage:
    python3 scripts/strategy_lab/paper_portfolio.py
    python3 scripts/strategy_lab/paper_portfolio.py --backfill-days 90
    python3 scripts/strategy_lab/paper_portfolio.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Allow `python scripts/strategy_lab/paper_portfolio.py` and package imports

from scripts import _runtime_io as rio  # noqa: E402
from scripts._notify import notify_alert  # noqa: E402
from scripts.strategy_lab.data_loader import load_aligned, load_symbol  # noqa: E402
from scripts.strategy_lab.risk_gate import (  # noqa: E402
    DEFAULT_BULL_VELOCITY_THRESHOLD,
    DEFAULT_COFIRE_N,
    DEFAULT_COFIRE_V,
    DEFAULT_VELOCITY_THRESHOLD,
    DEFAULT_VELOCITY_WINDOW,
    compute_velocity_gate,
)
from scripts.strategy_lab.strategies import (  # noqa: E402
    compute_baseline_position,
    compute_system_overlay_position,
)

ROOT = rio.ROOT
OUTPUT_DIR = ROOT / "Output" / "position"
STATE_PATH = OUTPUT_DIR / "paper_portfolio.json"
NAV_JSONL_PATH = OUTPUT_DIR / "paper_portfolio_nav.jsonl"
LATEST_MD_PATH = OUTPUT_DIR / "paper_portfolio_latest.md"
TRADE_DECISION_PATH = ROOT / "Output" / "trade_decision" / "latest.json"
DEFAULT_PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"

# Matches workbench STANCE_WEIGHT — used only as fallback if effective_size missing.
_STANCE_WEIGHT = {"RISK_ON": 1.0, "RISK_REDUCE": 0.5, "RISK_OFF": 0.0, "WATCH": 0.0}

# Paper sizing uses public level + optional residual onset (not live).
DEFAULT_CONFIG: dict[str, Any] = {
    "name": "mom63_public_stance_size",
    "description": (
        "SPY 63d momentum × public-level stress (λ=0) × trade_decision effective_size; "
        "velocity gate EXIT kill-switch; vs 60/40 — shadow only"
    ),
    "momentum_lookback": 63,
    "velocity_window": DEFAULT_VELOCITY_WINDOW,
    "velocity_threshold": DEFAULT_VELOCITY_THRESHOLD,
    "cofire_n": DEFAULT_COFIRE_N,
    "cofire_v": DEFAULT_COFIRE_V,
    "bull_modulation": True,
    "bull_velocity_threshold": DEFAULT_BULL_VELOCITY_THRESHOLD,
    "continuous_sizing": True,
    "sizing_mode": "public_residual",  # public_residual | legacy_velocity
    "residual_mode": "velocity",  # level=A | velocity=B; board must pass before λ>0
    "onset_method": "velocity",
    "onset_lambda": 0.0,  # λ=0 until residual clears capability board
    "scale_by_effective_size": True,  # stance × quality size from trade_decision.v3
    "target_volatility": 0.10,
    "stress_ewma_span": 20,
    "level_alert_threshold": 0.80,
    "cost_bps": 3.0,
    "slippage_bps": 2.0,
    "initial_nav": 1.0,
    "benchmark": "60_40_spy_tlt",
    "spy_weight_benchmark": 0.6,
    "rebalance_freq_benchmark": 21,
    "benchmark_panel": str(DEFAULT_PANEL),
}



def _date_str(ts: Any) -> str:
    if hasattr(ts, "date"):
        return str(ts.date())
    return str(ts)[:10]


def load_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    return rio.load_json(STATE_PATH)


def _empty_state(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "paper_portfolio.v3",
        "config": config,
        "as_of_date": None,
        "nav": float(config["initial_nav"]),
        "benchmark_nav": float(config["initial_nav"]),
        "position": 0.0,
        "benchmark_spy_weight": float(config["spy_weight_benchmark"]),
        "benchmark_tlt_weight": 1.0 - float(config["spy_weight_benchmark"]),
        "days_since_bench_rebalance": 0,
        "velocity_gate_state": "UNKNOWN",
        "level_alert_state": "UNKNOWN",
        "p_public": None,
        "p_onset": None,
        "stress_probability": None,
        "stance": "UNKNOWN",
        "size": None,
        "effective_size": None,
        "momentum": None,
        "target_position": 0.0,
        "history_len": 0,
        "updated_at": None,
    }


def _load_trade_sizing() -> tuple[str, float | None, float]:
    """Load stance, size, effective_size from trade_decision.v3 (shadow)."""
    trade = rio.load_json(TRADE_DECISION_PATH) if TRADE_DECISION_PATH.exists() else None
    if not isinstance(trade, dict):
        return "UNKNOWN", None, 1.0
    stance = str(trade.get("stance") or trade.get("decision") or "UNKNOWN")
    size_raw = trade.get("size")
    try:
        size_f = float(size_raw) if size_raw is not None else None
    except (TypeError, ValueError):
        size_f = None
    eff_raw = trade.get("effective_size")
    try:
        if eff_raw is not None:
            effective = float(eff_raw)
        elif size_f is not None:
            effective = float(_STANCE_WEIGHT.get(stance, 0.0)) * size_f
        else:
            effective = 1.0
    except (TypeError, ValueError):
        effective = 1.0
    if not (effective == effective):  # NaN
        effective = 1.0
    return stance, size_f, max(0.0, min(1.0, effective))


def _load_stance() -> tuple[str, float | None]:
    stance, size, _eff = _load_trade_sizing()
    return stance, size


def _position_scale_for_day(
    *,
    config: dict[str, Any],
    effective_size: float,
    date_s: str,
    latest_date: str,
    backfill_days: int,
) -> float:
    """Apply trade_decision effective_size on live/latest day only.

    Multi-day backfill keeps scale=1.0 on historical days to avoid writing today's
    stance×size into the past (shadow calibration hygiene).
    """
    if not bool(config.get("scale_by_effective_size", True)):
        return 1.0
    if backfill_days > 1 and date_s != latest_date:
        return 1.0
    return float(effective_size)


def _load_public_levels(index: pd.DatetimeIndex, panel_path: Path) -> pd.DataFrame:
    from public_residual_stress import extract_public_levels
    from run_professional_methodology import load_benchmark_panel

    if not panel_path.exists():
        return pd.DataFrame(index=index)
    # Phase B4: verify the harvester release is finalized before reading the
    # panel, so a tampered/unfinalized latest symlink cannot be silently
    # consumed. Best-effort: if the panel path is not under a harvester
    # release (e.g. a test fixture), skip the finalization check.
    from scripts._release_boundary import verify_release_finalized, ReleaseNotFinalizedError

    release_root = _resolve_release_root(panel_path)
    if release_root is not None:
        try:
            verify_release_finalized(release_root)
        except ReleaseNotFinalizedError:
            # Re-raise as a hard stop: a non-finalized release must not feed
            # the position sizing path.
            raise
    panel = load_benchmark_panel(panel_path)
    return extract_public_levels(panel).reindex(index)


def _resolve_release_root(panel_path: Path) -> Path | None:
    """If panel_path is under Data/harvester/exports/<release>/, return the
    release root; else None (test fixture or non-release path)."""
    parts = panel_path.parts
    for i, part in enumerate(parts):
        if part == "exports" and i + 1 < len(parts):
            return Path(*parts[: i + 2])
    return None


def _compute_target_series(
    data: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    """Return (overlay_position, velocity_gate_position, stress_frame).

    stress_frame columns: p_public, p_onset, position (continuous weight).
    """
    from professional_methods import causal_pit, continuous_position
    from public_residual_stress import build_public_residual_bundle

    close = data["close"]
    # M/D are compatibility keys for the two neutral gauges. K/X are excluded
    # from operations and remain in the v2 research queue.
    signals = data[["M", "D"]]
    baseline = compute_baseline_position(close, lookback=int(config["momentum_lookback"]))
    gate = compute_velocity_gate(
        signals,
        velocity_window=int(config["velocity_window"]),
        velocity_threshold=float(config["velocity_threshold"]),
        cofire_n=int(config["cofire_n"]),
        cofire_v=float(config["cofire_v"]),
        close=close,
        bull_modulation=bool(config["bull_modulation"]),
        bull_velocity_threshold=float(config["bull_velocity_threshold"]),
    )
    returns = close.pct_change()
    quality = signals.notna().mean(axis=1).reindex(data.index).fillna(0.0)

    mode = str(config.get("sizing_mode", "public_residual"))
    if bool(config.get("continuous_sizing", True)) and mode == "public_residual":
        public = _load_public_levels(data.index, Path(config.get("benchmark_panel", DEFAULT_PANEL)))
        bundle = build_public_residual_bundle(
            signals,
            public,
            returns,
            residual_mode=str(config.get("residual_mode", "velocity")),
            onset_method=str(config.get("onset_method", "velocity")),
            onset_lambda=float(config.get("onset_lambda", 0.0)),
            velocity_window=int(config["velocity_window"]),
            target_volatility=float(config.get("target_volatility", 0.10)),
        )
        sized = bundle["sizing"]
        continuous = sized["position"].reindex(data.index).fillna(0.0)
        stress_frame = pd.DataFrame(
            {
                "p_public": sized["p_public"],
                "p_onset": sized["p_onset"],
                "position": continuous,
            },
            index=data.index,
        )
        overlay = baseline.reindex(data.index).fillna(0.0) * continuous
        overlay = overlay.where(gate.reindex(data.index).fillna(1.0) >= 1.0, 0.0)
    elif bool(config.get("continuous_sizing", True)):
        velocity = signals.diff(int(config["velocity_window"])).max(axis=1)
        stress_probability = causal_pit(velocity, min_periods=126).reindex(data.index)
        sized = continuous_position(
            stress_probability=stress_probability.fillna(0.5),
            returns=returns,
            quality_cap=quality,
            target_volatility=float(config.get("target_volatility", 0.10)),
            ewma_span=int(config.get("stress_ewma_span", 20)),
        )
        continuous = sized["position"].reindex(data.index).fillna(0.0)
        stress_frame = pd.DataFrame(
            {
                "p_public": continuous * 0.0,
                "p_onset": stress_probability,
                "position": continuous,
            },
            index=data.index,
        )
        overlay = baseline.reindex(data.index).fillna(0.0) * continuous
        overlay = overlay.where(gate.reindex(data.index).fillna(1.0) >= 1.0, 0.0)
    else:
        overlay = compute_system_overlay_position(baseline, gate).reindex(data.index).fillna(0.0)
        stress_frame = pd.DataFrame(
            {"p_public": 0.0, "p_onset": 0.0, "position": overlay},
            index=data.index,
        )
    return overlay, gate.reindex(data.index).fillna(1.0), stress_frame


def _append_nav_row(row: dict[str, Any]) -> None:
    """Append a NAV row via the two-phase shadow publisher (atomic per row).

    Phase B5: writes go to the shadow_candidate dir (or live if no candidate),
    using temp-file + os.replace so a crash never leaves a partial JSON line.
    """
    from scripts._shadow_publish import append_nav_row_atomic

    append_nav_row_atomic(row)


def _load_nav_history() -> list[dict[str, Any]]:
    if not NAV_JSONL_PATH.exists():
        return []
    rows = []
    for line in NAV_JSONL_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _rewrite_nav_history(rows: list[dict[str, Any]]) -> None:
    rio.ensure_dir(OUTPUT_DIR)
    with NAV_JSONL_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _maybe_alert(
    *,
    prev_vg: str | None,
    new_vg: str,
    prev_level: str | None,
    new_level: str,
    prev_stance: str | None,
    new_stance: str,
    as_of: str,
    dry_run: bool,
) -> list[str]:
    alerts: list[str] = []
    if prev_vg == "FULL" and new_vg == "EXIT":
        msg = f"{as_of}: [onset] velocity gate FULL → EXIT (paper flatten)"
        alerts.append(msg)
        if not dry_run:
            notify_alert("Onset alert: velocity EXIT", msg)
    if prev_level == "CALM" and new_level == "ELEVATED":
        msg = f"{as_of}: [level] public stress P_public crossed alert threshold"
        alerts.append(msg)
        if not dry_run:
            notify_alert("Level alert: public stress elevated", msg)
    if (
        prev_stance
        and new_stance
        and prev_stance not in ("UNKNOWN",)
        and new_stance not in ("UNKNOWN",)
        and prev_stance != new_stance
    ):
        msg = f"{as_of}: shadow stance {prev_stance} → {new_stance}"
        alerts.append(msg)
        if not dry_run:
            notify_alert("Shadow stance change", msg)
    return alerts


def _monthly_comparison(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not history:
        return []
    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    df["month"] = df["date"].dt.to_period("M")
    rows = []
    for month, g in df.groupby("month"):
        first = g.iloc[0]
        last = g.iloc[-1]
        strat = float(last["nav"]) / float(first["nav"]) - 1.0 if first["nav"] else 0.0
        bench = (
            float(last["benchmark_nav"]) / float(first["benchmark_nav"]) - 1.0
            if first["benchmark_nav"]
            else 0.0
        )
        rows.append({
            "month": str(month),
            "strategy_return": round(strat, 4),
            "benchmark_60_40_return": round(bench, 4),
            "excess": round(strat - bench, 4),
            "n_days": int(len(g)),
            "end_nav": round(float(last["nav"]), 6),
            "end_benchmark_nav": round(float(last["benchmark_nav"]), 6),
        })
    return rows


def _format_markdown(state: dict[str, Any], history: list[dict[str, Any]], monthly: list[dict]) -> str:
    cfg = state.get("config") or {}
    lines = [
        f"# Paper Portfolio — {state.get('as_of_date', 'n/a')}",
        "",
        f"**Updated:** {state.get('updated_at', '')}",
        f"**Config:** {cfg.get('name')} (vt={cfg.get('velocity_threshold')}, "
        f"cn={cfg.get('cofire_n')}, bull={cfg.get('bull_modulation')})",
        "",
        "## Snapshot",
        "",
        f"- **NAV:** {state.get('nav')}",
        f"- **60/40 NAV:** {state.get('benchmark_nav')}",
        f"- **Position (SPY):** {state.get('position')}",
        f"- **Target:** {state.get('target_position')}",
        f"- **Momentum:** {state.get('momentum')}",
        f"- **Velocity gate (onset):** {state.get('velocity_gate_state')}",
        f"- **Level alert (public):** {state.get('level_alert_state')}",
        f"- **P_public:** {state.get('p_public')}",
        f"- **P_onset:** {state.get('p_onset')}",
        f"- **Stance:** {state.get('stance')} (size={state.get('size')}, "
        f"effective_size={state.get('effective_size')})",
        f"- **History days:** {state.get('history_len', len(history))}",
        "",
        "## Monthly vs 60/40",
        "",
    ]
    if not monthly:
        lines.append("_Insufficient history for monthly comparison._")
    else:
        lines.append("| Month | Strategy | 60/40 | Excess | Days |")
        lines.append("|---|---:|---:|---:|---:|")
        for m in monthly[-12:]:
            lines.append(
                f"| {m['month']} | {m['strategy_return']:.2%} | "
                f"{m['benchmark_60_40_return']:.2%} | {m['excess']:.2%} | {m['n_days']} |"
            )
    lines += [
        "",
        "---",
        "",
        "*Shadow paper portfolio — research calibration only. Not live execution.*",
        "",
    ]
    return "\n".join(lines)


def simulate_day(
    *,
    state: dict[str, Any],
    as_of: str,
    spy_ret: float,
    tlt_ret: float,
    target_position: float,
    gate_position: float,
    momentum: float | None,
    stance: str,
    size: float | None,
    effective_size: float | None = None,
) -> dict[str, Any]:
    """Advance one trading day: apply prior position to today's return, then rebalance."""
    cfg = state["config"]
    cost_rate = (float(cfg["cost_bps"]) + float(cfg["slippage_bps"])) / 10000.0
    prev_pos = float(state.get("position") or 0.0)
    nav = float(state.get("nav") or cfg["initial_nav"])
    day_pnl = prev_pos * spy_ret
    turnover = abs(target_position - prev_pos)
    cost = turnover * cost_rate
    nav = nav * (1.0 + day_pnl - cost)

    # Benchmark 60/40 with periodic rebalance
    spy_w = float(state.get("benchmark_spy_weight", cfg["spy_weight_benchmark"]))
    tlt_w = float(state.get("benchmark_tlt_weight", 1.0 - cfg["spy_weight_benchmark"]))
    bench_nav = float(state.get("benchmark_nav") or cfg["initial_nav"])
    bench_ret = spy_w * spy_ret + tlt_w * tlt_ret
    bench_nav = bench_nav * (1.0 + bench_ret)
    # Drift weights
    spy_val = spy_w * (1.0 + spy_ret)
    tlt_val = tlt_w * (1.0 + tlt_ret)
    total = spy_val + tlt_val
    if total > 0:
        spy_w = spy_val / total
        tlt_w = tlt_val / total
    days_since = int(state.get("days_since_bench_rebalance") or 0) + 1
    if days_since >= int(cfg["rebalance_freq_benchmark"]):
        spy_w = float(cfg["spy_weight_benchmark"])
        tlt_w = 1.0 - spy_w
        days_since = 0

    vg_state = "EXIT" if float(gate_position) < 1.0 else "FULL"

    return {
        "date": as_of,
        "nav": round(nav, 8),
        "benchmark_nav": round(bench_nav, 8),
        "position": float(target_position),
        "prev_position": prev_pos,
        "target_position": float(target_position),
        "spy_return": round(spy_ret, 6),
        "tlt_return": round(tlt_ret, 6),
        "day_pnl": round(day_pnl, 6),
        "cost": round(cost, 6),
        "turnover": round(turnover, 6),
        "momentum": None if momentum is None else round(float(momentum), 6),
        "velocity_gate_state": vg_state,
        "gate_position": float(gate_position),
        "stance": stance,
        "size": size,
        "effective_size": effective_size,
        "benchmark_spy_weight": round(spy_w, 6),
        "benchmark_tlt_weight": round(tlt_w, 6),
        "days_since_bench_rebalance": days_since,
    }


def run_paper_portfolio(
    *,
    backfill_days: int = 0,
    dry_run: bool = False,
    notify: bool = True,
) -> dict[str, Any]:
    # Pre-consumption admission gate: refuse to run if any required public
    # component (OFR/NFCI/CISS) is stale or missing, so P_public cannot
    # silently degrade via mean(skipna=True) renormalization. On block this
    # exits non-zero; the executor marks shadow_outcomes/overlay descendants
    # blocked_upstream. Freshness is now a precondition, not a post-run report.
    from scripts._admission_gate import require_admission

    require_admission("paper_portfolio")

    config = dict(DEFAULT_CONFIG)
    aligned = load_aligned()
    if aligned.empty:
        raise SystemExit("No aligned SPY+signal data for paper portfolio")

    tlt = load_symbol("TLT")
    if tlt.empty:
        raise SystemExit("TLT series missing — required for 60/40 benchmark")

    # Align TLT returns onto strategy dates
    data = aligned.join(tlt[["close"]].rename(columns={"close": "tlt_close"}), how="inner")
    data["tlt_return_1d"] = data["tlt_close"].pct_change()
    data = data.dropna(subset=["return_1d", "tlt_return_1d"])

    overlay, gate, stress_frame = _compute_target_series(data, config)
    mom = data["close"].pct_change(int(config["momentum_lookback"]))
    level_threshold = float(config.get("level_alert_threshold", 0.80))

    history = _load_nav_history()
    done_dates = {r["date"] for r in history}
    state = load_state() or _empty_state(config)
    state["config"] = config

    # Dates to process
    all_dates = [_date_str(d) for d in data.index]
    if backfill_days > 0:
        candidates = all_dates[-backfill_days:]
    else:
        candidates = [all_dates[-1]]

    stance, size, effective_size = _load_trade_sizing()
    alerts: list[str] = []
    new_rows: list[dict[str, Any]] = []
    latest_date = all_dates[-1]

    def _level_state(ts: pd.Timestamp) -> str:
        if ts not in stress_frame.index or pd.isna(stress_frame.loc[ts, "p_public"]):
            return "UNKNOWN"
        return "ELEVATED" if float(stress_frame.loc[ts, "p_public"]) >= level_threshold else "CALM"

    def _stress_vals(ts: pd.Timestamp) -> tuple[float | None, float | None]:
        if ts not in stress_frame.index:
            return None, None
        pub = stress_frame.loc[ts, "p_public"]
        onset = stress_frame.loc[ts, "p_onset"]
        pub_f = None if pd.isna(pub) else round(float(pub), 6)
        onset_f = None if pd.isna(onset) else round(float(onset), 6)
        return pub_f, onset_f

    for date_s in candidates:
        if date_s in done_dates:
            # Already booked — still refresh stance metadata / alerts once on latest day
            if date_s == latest_date:
                prev_stance = state.get("stance")
                prev_vg = state.get("velocity_gate_state")
                prev_level = state.get("level_alert_state")
                ts = pd.Timestamp(date_s)
                matches = [i for i in data.index if _date_str(i) == date_s]
                if matches:
                    ts = matches[0]
                gate_pos = float(gate.loc[ts]) if ts in gate.index else 1.0
                vg_now = "EXIT" if gate_pos < 1.0 else "FULL"
                level_now = _level_state(ts)
                if notify and not dry_run:
                    alerts.extend(
                        _maybe_alert(
                            prev_vg=prev_vg,
                            new_vg=vg_now,
                            prev_level=prev_level,
                            new_level=level_now,
                            prev_stance=prev_stance,
                            new_stance=stance,
                            as_of=date_s,
                            dry_run=dry_run,
                        )
                    )
                pub_f, onset_f = _stress_vals(ts)
                state["stance"] = stance
                state["size"] = size
                state["effective_size"] = effective_size
                state["velocity_gate_state"] = vg_now
                state["level_alert_state"] = level_now
                state["p_public"] = pub_f
                state["p_onset"] = onset_f
                state["stress_probability"] = onset_f
                state["updated_at"] = datetime.now(UTC).isoformat()
            continue

        ts = pd.Timestamp(date_s)
        if ts not in data.index:
            matches = [i for i in data.index if _date_str(i) == date_s]
            if not matches:
                continue
            ts = matches[0]

        row = data.loc[ts]
        scale = _position_scale_for_day(
            config=config,
            effective_size=effective_size,
            date_s=date_s,
            latest_date=latest_date,
            backfill_days=backfill_days,
        )
        target = float(overlay.loc[ts]) * scale
        target = max(0.0, min(1.0, target))
        gate_pos = float(gate.loc[ts])
        mom_v = float(mom.loc[ts]) if ts in mom.index and pd.notna(mom.loc[ts]) else None
        pub_f, onset_f = _stress_vals(ts)
        level_now = _level_state(ts)
        # Record effective_size only on days that used trade_decision scale.
        row_effective = effective_size if scale != 1.0 or date_s == latest_date else None

        # Fail-closed HOLD: when P_public is NaN (incomplete public-component
        # coverage - OFR/NFCI/CISS), hold the existing position instead of
        # silently renormalizing or flattening. New/increase is implicitly
        # forbidden (target stays at prev_pos). The day is still booked so NAV
        # history stays continuous (turnover=0, no cost), but flagged
        # HOLD_DEGRADED so shadow promotion stats exclude it.
        sizing_mode = "NORMAL"
        if pub_f is None or (isinstance(pub_f, float) and pd.isna(pub_f)):
            prev_pos = float(state.get("position") or 0.0)
            target = prev_pos
            sizing_mode = "HOLD_DEGRADED"

        prev_vg = state.get("velocity_gate_state")
        prev_level = state.get("level_alert_state")
        prev_stance = state.get("stance")

        day = simulate_day(
            state=state,
            as_of=date_s,
            spy_ret=float(row["return_1d"]),
            tlt_ret=float(row["tlt_return_1d"]),
            target_position=target,
            gate_position=gate_pos,
            momentum=mom_v,
            stance=stance,
            size=size,
            effective_size=row_effective,
        )
        day["p_public"] = pub_f
        day["p_onset"] = onset_f
        day["level_alert_state"] = level_now
        day["stress_probability"] = onset_f
        day["sizing_mode"] = sizing_mode
        # Phase D: tag sample validity so promotion stats can filter.
        from scripts._control_closure import tag_nav_row

        day = tag_nav_row(day)
        new_rows.append(day)

        if notify and not dry_run:
            alerts.extend(
                _maybe_alert(
                    prev_vg=prev_vg,
                    new_vg=day["velocity_gate_state"],
                    prev_level=prev_level,
                    new_level=level_now,
                    prev_stance=prev_stance,
                    new_stance=stance,
                    as_of=date_s,
                    dry_run=dry_run,
                )
            )

        state.update({
            "as_of_date": date_s,
            "nav": day["nav"],
            "benchmark_nav": day["benchmark_nav"],
            "position": day["position"],
            "target_position": day["target_position"],
            "benchmark_spy_weight": day["benchmark_spy_weight"],
            "benchmark_tlt_weight": day["benchmark_tlt_weight"],
            "days_since_bench_rebalance": day["days_since_bench_rebalance"],
            "velocity_gate_state": day["velocity_gate_state"],
            "level_alert_state": level_now,
            "stance": stance,
            "size": size,
            "effective_size": day.get("effective_size"),
            "momentum": day["momentum"],
            "p_public": pub_f,
            "p_onset": onset_f,
            "stress_probability": onset_f,
            "updated_at": datetime.now(UTC).isoformat(),
        })

    if dry_run:
        return {
            "state": state,
            "new_rows": new_rows,
            "alerts": alerts,
            "dry_run": True,
        }

    for row in new_rows:
        _append_nav_row(row)
        done_dates.add(row["date"])

    history = _load_nav_history()
    state["history_len"] = len(history)
    monthly = _monthly_comparison(history)
    state["monthly_vs_60_40"] = monthly
    state["alerts_today"] = alerts

    # Full-sample costed sanity metrics when enough history
    if len(history) >= 5:
        state["nav_total_return"] = round(float(state["nav"]) / float(config["initial_nav"]) - 1.0, 4)
        state["benchmark_total_return"] = round(
            float(state["benchmark_nav"]) / float(config["initial_nav"]) - 1.0, 4
        )

    rio.ensure_dir(OUTPUT_DIR)
    # Phase B5: atomic state + markdown write via shadow publisher (temp +
    # os.replace). On a crash the live state file is never left half-written.
    from scripts._shadow_publish import write_state_atomic

    write_state_atomic(state)
    # Markdown is a display artifact; write via the same candidate path.
    from scripts._shadow_publish import shadow_candidate_dir

    md_path = shadow_candidate_dir() / "paper_portfolio_latest.md"
    md_path.write_text(_format_markdown(state, history, monthly), encoding="utf-8")

    return {
        "state": state,
        "new_rows": new_rows,
        "alerts": alerts,
        "paths": {
            "state": str(STATE_PATH),
            "nav_jsonl": str(NAV_JSONL_PATH),
            "markdown": str(LATEST_MD_PATH),
        },
    }


def backfill_from_scratch(days: int = 90, *, dry_run: bool = False) -> dict[str, Any]:
    """Reset NAV history and rebuild last N trading days (bootstrap only)."""
    if not dry_run:
        if NAV_JSONL_PATH.exists():
            NAV_JSONL_PATH.unlink()
        if STATE_PATH.exists():
            STATE_PATH.unlink()
    return run_paper_portfolio(backfill_days=days, dry_run=dry_run, notify=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Update paper portfolio NAV (shadow).")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=0,
        help="Bootstrap/rebuild last N trading days (resets history if >0 via --reset)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing NAV history before backfill",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()

    if args.backfill_days > 0 and args.reset:
        result = backfill_from_scratch(args.backfill_days, dry_run=args.dry_run)
    else:
        result = run_paper_portfolio(
            backfill_days=args.backfill_days,
            dry_run=args.dry_run,
            notify=not args.no_notify,
        )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        state = result["state"]
        print(f"Paper portfolio: {LATEST_MD_PATH}")
        print(f"As of: {state.get('as_of_date')}")
        print(f"NAV: {state.get('nav')}  |  60/40: {state.get('benchmark_nav')}")
        print(f"Position: {state.get('position')}  gate={state.get('velocity_gate_state')}")
        print(f"Stance: {state.get('stance')}  effective_size={state.get('effective_size')}  "
              f"history_days={state.get('history_len')}")
        if result.get("alerts"):
            print("Alerts:")
            for a in result["alerts"]:
                print(f"  - {a}")
        if result.get("new_rows"):
            print(f"New rows: {len(result['new_rows'])}")


if __name__ == "__main__":
    main()
