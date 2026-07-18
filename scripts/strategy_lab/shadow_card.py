"""Shadow Decision Card — daily forward-looking trade recommendation.

Generates a structured card with:
  - Current market state (from latest framework_output.json)
  - M/D/K/X channel readings
  - Risk gate recommendation
  - Suggested position size
  - Primary risk reasons
  - Placeholder for future 5/20/60 day outcome backfill

This is NOT a trade signal. It's a shadow recommendation for
accumulating forward-looking evaluation data.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import _runtime_io as rio
from system_runtime.events import payload_of
import pandas as pd
from scripts.strategy_lab.data_loader import load_aligned, load_signals
from scripts.strategy_lab.risk_gate import compute_velocity_gate, evaluate_day

OUTPUT_DIR = rio.ROOT / "Output" / "strategy_lab"
FRAMEWORK_PATH = rio.ROOT / "Output" / "current" / "framework_output.json"


def generate_shadow_card(
    as_of: str | None = None,
) -> dict:
    """Generate today's shadow decision card.

    Args:
        as_of: date string YYYY-MM-DD. If None, uses latest available data.

    Returns:
        Dict with the full shadow card.
    """
    # Load latest M/D/K/X signals
    signals = load_signals()
    if as_of:
        signals = signals.loc[:as_of]

    if signals.empty:
        return {"error": "No signal data available"}

    latest = signals.iloc[-1]
    latest_date = signals.index[-1]

    # Evaluate risk gate (regime gate for interpretability)
    risk = evaluate_day(latest["M"], latest["D"], latest["K"], latest["X"])

    # Evaluate velocity gate (production gate)
    velocity_gate = compute_velocity_gate(signals)
    velocity_position = float(velocity_gate.iloc[-1])

    # Compute channel velocities (20-day change)
    velocity_20d = {}
    if len(signals) >= 20:
        for ch in ["M", "D", "K", "X"]:
            velocity_20d[ch] = float(round(signals[ch].iloc[-1] - signals[ch].iloc[-20], 4))
    else:
        for ch in ["M", "D", "K", "X"]:
            velocity_20d[ch] = None

    # Load SPY recent data for context
    try:
        merged = load_aligned()
        if as_of:
            merged = merged.loc[:as_of]
        if not merged.empty:
            spy_close = merged.iloc[-1]["close"]
            spy_ret_5d = merged.iloc[-1].get("return_5d", None)
            spy_ret_20d = merged.iloc[-1].get("return_20d", None)
        else:
            spy_close = None
            spy_ret_5d = None
            spy_ret_20d = None
    except Exception:
        spy_close = None
        spy_ret_5d = None
        spy_ret_20d = None

    # Load framework_output for primary_market_space
    framework = rio.load_json(FRAMEWORK_PATH)
    primary_market_space = None
    if framework:
        primary_market_space = framework.get("basic", {}).get("primary_market_space")

    card = {
        "card_type": "shadow_decision",
        "schema_version": "strategy_lab.shadow_card.v1",
        "timestamp": datetime.now(UTC).isoformat(),
        "as_of_date": str(latest_date.date()) if latest_date else None,
        "market_context": {
            "spy_close": float(round(spy_close, 2)) if spy_close else None,
            "spy_return_5d": float(round(spy_ret_5d, 4)) if spy_ret_5d is not None else None,
            "spy_return_20d": float(round(spy_ret_20d, 4)) if spy_ret_20d is not None else None,
            "primary_market_space": primary_market_space,
        },
        "channel_readings": {
            "M": float(round(latest["M"], 4)),
            "D": float(round(latest["D"], 4)),
            "K": float(round(latest["K"], 4)),
            "X": float(round(latest["X"], 4)),
        },
        "risk_gate": {
            "position_size": float(risk.position_size),
            "regime": risk.regime,
            "action_gate": risk.action_gate,
            "n_stress": risk.n_stress,
            "n_relief": risk.n_relief,
            "risk_flags": risk.risk_flags,
        },
        "velocity_gate": {
            "position": velocity_position,
            "velocity_20d": velocity_20d,
            "trigger": velocity_position < 1.0,
            "trigger_reason": _velocity_trigger_reason(velocity_20d),
        },
        "recommendation": {
            "allow_open": velocity_position > 0,
            "suggested_size": velocity_position,
            "sizing_label": "FULL" if velocity_position >= 1.0 else "EXIT",
            "primary_reason": (
                _velocity_trigger_reason(velocity_20d)
                if velocity_position < 1.0
                else "No structural stress detected"
            ),
        },
        "outcome_backfill": {
            "forward_5d_return": None,
            "forward_20d_return": None,
            "forward_60d_return": None,
            "evaluation": None,  # to be filled: correct / wrong / useful_no_trade / state_miss
            "notes": "",
        },
    }

    return card


def _sizing_label(size: float) -> str:
    """Human-readable sizing label."""
    if size >= 1.0:
        return "FULL"
    elif size >= 0.5:
        return "OBSERVE"
    elif size > 0:
        return "STRESS"
    else:
        return "NO_TRADE"


def _velocity_trigger_reason(velocity_20d: dict[str, float | None]) -> str:
    """Generate human-readable reason for velocity gate trigger."""
    if not velocity_20d:
        return "Insufficient data for velocity calculation"

    reasons = []
    for ch, v in velocity_20d.items():
        if v is not None and v > 0.2:
            reasons.append(f"{ch} +{v:.2f}σ")

    if not reasons:
        return "Velocity within normal range"

    # Check for cofire (3+ channels deteriorating)
    if len(reasons) >= 3:
        return f"Co-deterioration: {', '.join(reasons)}"
    elif any(v is not None and v > 1.5 for v in velocity_20d.values()):
        extreme = [ch for ch, v in velocity_20d.items() if v is not None and v > 1.5]
        return f"Extreme velocity: {', '.join(extreme)}"
    else:
        return f"Deterioration: {', '.join(reasons)}"


def save_shadow_card(card: dict) -> Path:
    """Save shadow card to Output/strategy_lab/shadow_cards/."""
    date_str = card.get("as_of_date", "unknown")
    out_dir = OUTPUT_DIR / "shadow_cards"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save as JSON
    path = out_dir / f"{date_str}.json"
    path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Also save latest
    latest_path = out_dir / "latest.json"
    latest_path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return path


def backfill_outcomes(days: int = 90) -> int:
    """Backfill forward returns for recent shadow cards.

    Looks at cards from the last N days and fills in 5/20/60d forward returns
    if the data is now available.

    Returns:
        Number of cards updated.
    """
    card_dir = OUTPUT_DIR / "shadow_cards"
    if not card_dir.exists():
        return 0

    merged = load_aligned()
    updated = 0

    for card_file in sorted(card_dir.glob("2*.json")):
        card = json.loads(card_file.read_text(encoding="utf-8"))
        as_of = card.get("as_of_date")
        if not as_of:
            continue

        as_of_dt = pd.Timestamp(as_of)
        if as_of_dt not in merged.index:
            continue

        loc = merged.index.get_loc(as_of_dt)
        outcome = card.get("outcome_backfill", {})
        changed = False

        for horizon, key in [(5, "forward_5d_return"), (20, "forward_20d_return"), (60, "forward_60d_return")]:
            if outcome.get(key) is not None:
                continue  # already filled
            if loc + horizon < len(merged):
                future_close = merged.iloc[loc + horizon]["close"]
                current_close = merged.iloc[loc]["close"]
                fwd_ret = (future_close / current_close) - 1.0
                outcome[key] = round(fwd_ret, 6)
                changed = True

        # Auto-evaluate if we have 20d forward return and recommendation
        if outcome.get("forward_20d_return") is not None and outcome.get("evaluation") is None:
            outcome["evaluation"] = _auto_evaluate(card, outcome)

        if changed:
            card["outcome_backfill"] = outcome
            card_file.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            updated += 1

    return updated


def _auto_evaluate(card: dict, outcome: dict) -> str:
    """Auto-evaluate a shadow card based on forward returns and recommendation.

    Returns one of:
        correct        — gate triggered AND market dropped (or gate off AND market rose)
        wrong          — gate triggered AND market rose (or gate off AND market dropped)
        useful_no_trade — gate triggered, market dropped, would have lost money
        state_miss     — gate was off but market dropped significantly
    """
    rec = card.get("recommendation", {})
    allow_open = rec.get("allow_open", True)
    fwd_20d = outcome.get("forward_20d_return")

    if fwd_20d is None:
        return "pending"

    # Gate said EXIT
    if not allow_open:
        if fwd_20d < -0.02:
            return "correct"  # gate saved us from a 2%+ drop
        elif fwd_20d > 0.02:
            return "wrong"  # gate made us miss a 2%+ rally
        else:
            return "useful_no_trade"  # market was flat, gate was cautious

    # Gate said FULL
    else:
        if fwd_20d > 0:
            return "correct"  # stayed in and made money
        elif fwd_20d < -0.05:
            return "state_miss"  # gate missed a 5%+ drop
        else:
            return "correct"  # small loss is acceptable


def build_90d_outcomes_summary(days: int = 90) -> dict:
    """Aggregate shadow card outcomes over the last N calendar days.

    Writes promotion metrics for strategy_lab capability_registry requirements.

    Days whose paper-portfolio NAV row was booked under ``sizing_mode ==
    HOLD_DEGRADED`` (P_public incomplete -> hold existing) are excluded from
    the promotion sample counts: a degraded day is not valid evidence for
    strategy promotion. The card file is still on disk for audit; it just
    does not count toward ``cards_total`` / ``min_samples_met``.
    """
    card_dir = OUTPUT_DIR / "shadow_cards"
    if not card_dir.exists():
        return {
            "schema_version": "strategy_lab.shadow_outcomes_90d.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "window_days": days,
            "status": "no_cards",
            "cards_total": 0,
        }

    # Load the set of dates booked as HOLD_DEGRADED in the paper-portfolio
    # NAV ledger, so degraded samples do not enter promotion statistics.
    degraded_dates: set[str] = _load_degraded_nav_dates()

    cutoff = pd.Timestamp(datetime.now(UTC).date()) - pd.Timedelta(days=days)
    evaluations: dict[str, int] = {}
    with_20d = 0
    correct = 0
    cards_total = 0
    excluded_degraded = 0

    for card_file in sorted(card_dir.glob("2*.json")):
        if card_file.name == "latest.json":
            continue
        try:
            card = json.loads(card_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        as_of = card.get("as_of_date")
        if not as_of:
            continue
        as_of_dt = pd.Timestamp(as_of)
        if as_of_dt < cutoff:
            continue
        # Exclude degraded days from promotion evidence.
        if as_of in degraded_dates:
            excluded_degraded += 1
            continue
        cards_total += 1
        outcome = card.get("outcome_backfill", {})
        if outcome.get("forward_20d_return") is not None:
            with_20d += 1
        evaluation = outcome.get("evaluation") or "pending"
        evaluations[evaluation] = evaluations.get(evaluation, 0) + 1
        if evaluation in ("correct", "useful_no_trade"):
            correct += 1

    evaluated = sum(v for k, v in evaluations.items() if k != "pending")
    correct_rate = round(correct / evaluated, 4) if evaluated else None

    return {
        "schema_version": "strategy_lab.shadow_outcomes_90d.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "window_days": days,
        "status": "complete" if cards_total else "no_cards",
        "cards_total": cards_total,
        "cards_with_20d_outcome": with_20d,
        "evaluation_counts": evaluations,
        "correct_rate": correct_rate,
        "promotion_indicators": {
            "min_samples_met": with_20d >= 30,
            "min_correct_rate_met": correct_rate is not None and correct_rate >= 0.55,
        },
        "excluded_degraded_samples": excluded_degraded,
        "allowed_use": "validation_only",
        "notes": "Shadow outcomes do not affect core judgment or trade decisions. "
                 "HOLD_DEGRADED days (incomplete P_public) are excluded from promotion counts.",
    }


def _load_degraded_nav_dates() -> set[str]:
    """Return the set of as_of date strings whose NAV row was HOLD_DEGRADED.

    Reads ``Output/position/paper_portfolio_nav.jsonl``. Robust to missing
    file or rows lacking ``sizing_mode`` (older rows predate the field).
    """
    nav_path = rio.ROOT / "Output" / "position" / "paper_portfolio_nav.jsonl"
    degraded: set[str] = set()
    if not nav_path.exists():
        return degraded
    try:
        for line in nav_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = payload_of(json.loads(line))
            except json.JSONDecodeError:
                continue
            if row.get("sizing_mode") == "HOLD_DEGRADED":
                as_of = row.get("as_of") or row.get("date")
                if as_of:
                    degraded.add(str(as_of))
    except OSError:
        pass
    return degraded


def save_90d_outcomes_summary(summary: dict) -> Path:
    """Persist aggregated shadow outcomes."""
    out_path = OUTPUT_DIR / "shadow_outcomes_90d.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path
