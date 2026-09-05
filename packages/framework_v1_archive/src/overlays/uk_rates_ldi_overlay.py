from __future__ import annotations

import pandas as pd

from src.overlays.banking_fragility_overlay import OverlayAssessment


UK_LDI_PROXY_MAP = {
    "gilt_yields": ("UK_30Y_gilt", "UK_10Y_gilt"),
    "long_gilt_drawdown": ("long_gilt_total_return", "GLTL"),
    "gbp_swaps": ("GBP_30Y_swap", "GBP_10Y_swap"),
    "sterling_stress": ("GBPUSD", "sterling_stress"),
    "rates_vol": ("UK_rates_vol", "MOVE"),
    "boe_events": ("BoE_events",),
}


def assess_uk_rates_ldi(frame: pd.DataFrame, event_name: str = "uk_ldi") -> OverlayAssessment:
    available = {key: any(col in frame.columns for col in cols) for key, cols in UK_LDI_PROXY_MAP.items()}
    missing = tuple(key for key, ok in available.items() if not ok)
    confidence = sum(available.values()) / len(available)
    local_scores = {
        "M": _score(frame, ("long_gilt_total_return", "GLTL")),
        "D": _score(frame, ("GBPUSD", "sterling_stress")),
        "K": _score(frame, ("UK_30Y_gilt", "UK_10Y_gilt", "GBP_30Y_swap", "UK_rates_vol", "MOVE")),
        "X": 1.0 if "BoE_events" in frame.columns else 0.0,
    }
    return OverlayAssessment(
        event_name=event_name,
        local_scores=local_scores,
        coverage_status="PUBLIC_PROXY_ONLY" if confidence >= 0.6 else "INCOMPLETE_PUBLIC_PROXY",
        required_missing_data=missing,
        public_proxy_confidence=round(float(confidence), 4),
        allowed_claims=("UK rates public proxy overlay", "Coverage-limited LDI fragility explanation"),
        forbidden_claims=("LDI fund-level margin-call prediction", "Validated early warning", "Portfolio instruction"),
    )


def _score(frame: pd.DataFrame, cols: tuple[str, ...]) -> float:
    present = [col for col in cols if col in frame.columns]
    if not present:
        return 0.0
    values = frame[present].tail(20).diff().abs().mean(numeric_only=True)
    return float(values.mean()) if not values.empty else 0.0
