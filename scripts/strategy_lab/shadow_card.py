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

import pandas as pd

import _runtime_io as rio
from strategy_lab.data_loader import load_aligned, load_signals
from strategy_lab.risk_gate import RiskState, compute_velocity_gate, evaluate_day

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
    fwd_5d = outcome.get("forward_5d_return")
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
