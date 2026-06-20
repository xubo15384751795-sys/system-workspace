"""Regime Router — structural state interpretation and action gating.

Reads M/D/K/X channel values from framework_output.json and outputs:
1. Structural state classification
2. Which channels are active vs muted
3. Action gate (NO_TRADE / WATCH / RESEARCH_REVIEW / SMALL_SIZE_ALLOWED)

Usage:
    python scripts/regime_router.py
    python scripts/regime_router.py --json
    python scripts/regime_router.py --values M=-1.5,D=-0.8,K=0.3,X=0.1

This replaces the deprecated 4-channel average approach.
See docs/channel_role_map.md for the full interpretation framework.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from _runtime_io import ROOT, ensure_dir, load_json, write_json

# ── Constants ──────────────────────────────────────────────────────
STRESS_THRESHOLD = 0.3          # channel value above this = "stress signal"
RELIEF_THRESHOLD = -0.3         # channel value below this = "relief signal"
CONSENSUS_MIN = 2               # minimum channels agreeing for directional hypothesis
X_STRESS_BLOCK = 0.5            # X above this blocks directional trades
M_SWING_THRESHOLD = 1.5         # M swing > 1.5σ in 5d = repricing event

OUTPUT_DIR = ROOT / "Output" / "regime_router"
FRAMEWORK_PATH = ROOT / "Output" / "current" / "framework_output.json"
SIGMA_VECTOR_PATH = ROOT / "Output" / "sandbox" / "structural_replay_v2" / "sigma_vector.json"


@dataclass
class ChannelReading:
    name: str
    value: float | None
    role: str
    active: bool = True
    mute_reason: str = ""
    signal: str = "neutral"  # "stress", "relief", "neutral"


@dataclass
class RegimeOutput:
    timestamp: str
    regime: str
    action_gate: str
    channels: dict[str, dict]
    active_channels: list[str]
    muted_channels: list[str]
    consensus: str
    risk_flags: list[str]


def classify_signal(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value > STRESS_THRESHOLD:
        return "stress"
    if value < RELIEF_THRESHOLD:
        return "relief"
    return "neutral"


def route(
    M: float | None = None,
    D: float | None = None,
    K: float | None = None,
    X: float | None = None,
    m_delta_5d: float | None = None,
) -> RegimeOutput:
    """Run the regime router on current channel values.

    Args:
        M, D, K, X: Current channel z-scores.
        m_delta_5d: 5-day change in M (for repricing detection).

    Returns:
        RegimeOutput with regime classification, action gate, and channel details.
    """
    channels = {
        "M": ChannelReading("M", M, "anchor_repricing_detector"),
        "D": ChannelReading("D", D, "path_compression_detector"),
        "K": ChannelReading("K", K, "curvature_stress_detector"),
        "X": ChannelReading("X", X, "primary_stress_volatility_detector"),
    }

    # Classify each channel's signal
    for ch in channels.values():
        ch.signal = classify_signal(ch.value)

    risk_flags: list[str] = []

    # ── Regime classification ──────────────────────────────────────

    # X is the primary stress detector
    x_stress = X is not None and X > X_STRESS_BLOCK
    k_stress = K is not None and K > STRESS_THRESHOLD
    m_stress = M is not None and M > STRESS_THRESHOLD
    m_relief = M is not None and M < RELIEF_THRESHOLD
    m_swing = m_delta_5d is not None and abs(m_delta_5d) > M_SWING_THRESHOLD

    # Count stress vs relief signals
    n_stress = sum(1 for ch in channels.values() if ch.signal == "stress")
    n_relief = sum(1 for ch in channels.values() if ch.signal == "relief")

    # Regime determination
    if x_stress and k_stress:
        regime = "STRUCTURAL_STRESS"
    elif x_stress:
        regime = "LEVERAGE_STRESS"
    elif k_stress:
        regime = "CURVATURE_STRESS"
    elif m_swing:
        regime = "ANCHOR_REPRICING"
    elif n_relief >= 3:
        regime = "ALL_CLEAR"
    elif n_stress >= 3:
        regime = "DIFFUSE_STRESS"
    elif n_stress >= 2 and n_relief >= 1:
        regime = "MIXED"
    else:
        regime = "NEUTRAL"

    # ── Consensus determination ────────────────────────────────────

    if n_stress >= CONSENSUS_MIN and n_relief == 0:
        consensus = "STRESS_CONSENSUS"
    elif n_relief >= CONSENSUS_MIN and n_stress == 0:
        consensus = "RELIEF_CONSENSUS"
    elif n_stress >= 2 and n_relief >= 2:
        consensus = "SPLIT"
    else:
        consensus = "WEAK"

    # ── Action gate ────────────────────────────────────────────────

    if regime == "STRUCTURAL_STRESS":
        action_gate = "NO_TRADE"
        risk_flags.append("X and K both elevated — structural stress confirmed")
    elif x_stress:
        action_gate = "WATCH"
        risk_flags.append(f"X={X:.2f} — leverage stress detected")
    elif m_swing:
        action_gate = "WATCH"
        risk_flags.append(f"M swing {m_delta_5d:+.2f} — anchor repricing risk")
    elif regime == "DIFFUSE_STRESS":
        action_gate = "RESEARCH_REVIEW"
        risk_flags.append("Multiple channels showing stress — investigate")
    elif consensus == "SPLIT":
        action_gate = "NO_TRADE"
        risk_flags.append("Channels disagree — insufficient consensus")
    elif consensus == "RELIEF_CONSENSUS" and not x_stress:
        action_gate = "SMALL_SIZE_ALLOWED"
    elif regime == "ALL_CLEAR":
        action_gate = "SMALL_SIZE_ALLOWED"
    else:
        action_gate = "RESEARCH_REVIEW"

    # Build channel details
    channel_details = {}
    for name, ch in channels.items():
        channel_details[name] = {
            "value": ch.value,
            "signal": ch.signal,
            "role": ch.role,
            "active": ch.active,
            "mute_reason": ch.mute_reason,
        }

    active = [n for n, ch in channels.items() if ch.active]
    muted = [n for n, ch in channels.items() if not ch.active]

    return RegimeOutput(
        timestamp=datetime.now(UTC).isoformat(),
        regime=regime,
        action_gate=action_gate,
        channels=channel_details,
        active_channels=active,
        muted_channels=muted,
        consensus=consensus,
        risk_flags=risk_flags,
    )


def load_from_framework() -> tuple[float | None, float | None, float | None, float | None]:
    """Load M/D/K/X from sigma_vector.json (preferred) or framework_output.json."""
    # Try sigma_vector first (has all 4 channels)
    if SIGMA_VECTOR_PATH.exists():
        sv = load_json(SIGMA_VECTOR_PATH)
        vec = sv.get("sigma_vector", {})
        return (
            vec.get("M"),
            vec.get("D"),
            vec.get("K"),
            vec.get("X_agg"),
        )
    # Fallback to framework_output (may have None for K/X)
    if FRAMEWORK_PATH.exists():
        fw = load_json(FRAMEWORK_PATH)
        primary = fw.get("advanced", {}).get("primary_readout", {})

        def _get(channel: str) -> float | None:
            geom = primary.get(f"{channel}_geometry", {})
            v = geom.get("value")
            return float(v) if v is not None else None

        return _get("M"), _get("D_path"), _get("K"), _get("X_agg")
    return None, None, None, None


def main() -> int:
    parser = argparse.ArgumentParser(description="Regime Router")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--values", type=str, help="M=-1.5,D=-0.8,K=0.3,X=0.1")
    args = parser.parse_args()

    if args.values:
        vals = {}
        for pair in args.values.split(","):
            k, v = pair.split("=")
            vals[k.strip()] = float(v)
        M, D, K, X = vals.get("M"), vals.get("D"), vals.get("K"), vals.get("X")
    else:
        M, D, K, X = load_from_framework()

    result = route(M=M, D=D, K=K, X=X)

    ensure_dir(OUTPUT_DIR)
    write_json(OUTPUT_DIR / "latest.json", result.__dict__)

    if args.json:
        print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))
    else:
        print(f"Regime Router — {result.timestamp[:10]}")
        print(f"  Regime:      {result.regime}")
        print(f"  Action Gate: {result.action_gate}")
        print(f"  Consensus:   {result.consensus}")
        print()
        for name, ch in result.channels.items():
            v = ch['value']
            v_str = f"{v:+.2f}" if v is not None else "N/A"
            print(f"  {name}: {v_str} ({ch['signal']}) — {ch['role']}")
        if result.risk_flags:
            print()
            for flag in result.risk_flags:
                print(f"  ⚠️  {flag}")

    gate_order = {"NO_TRADE": 0, "WATCH": 1, "RESEARCH_REVIEW": 2, "SMALL_SIZE_ALLOWED": 3}
    return gate_order.get(result.action_gate, 2)


if __name__ == "__main__":
    sys.exit(main())
