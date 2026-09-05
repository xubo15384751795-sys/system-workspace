from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class OverlayAssessment:
    event_name: str
    local_scores: dict[str, float]
    coverage_status: str
    required_missing_data: tuple[str, ...]
    public_proxy_confidence: float
    allowed_claims: tuple[str, ...]
    forbidden_claims: tuple[str, ...]


BANKING_PROXY_MAP = {
    "bank_equity": ("KRE", "KBE", "XLF"),
    "deposit_flows": ("H8_deposits",),
    "aoci_htm": ("AOCI_proxy", "HTM_proxy"),
    "fhlb": ("FHLB_advances",),
    "yield_curve": ("T10Y2Y", "T10Y3M"),
}


def assess_banking_fragility(frame: pd.DataFrame, event_name: str = "banking_fragility") -> OverlayAssessment:
    available = {key: any(col in frame.columns for col in cols) for key, cols in BANKING_PROXY_MAP.items()}
    missing = tuple(key for key, ok in available.items() if not ok)
    confidence = sum(available.values()) / len(available)
    local_scores = {
        "M": _score(frame, ("KRE", "KBE", "XLF")),
        "D": _score(frame, ("H8_deposits", "FHLB_advances")),
        "K": _score(frame, ("KRE", "KBE", "XLF", "T10Y2Y", "T10Y3M")),
        "X": _score(frame, ("AOCI_proxy", "HTM_proxy", "FHLB_advances")),
    }
    return OverlayAssessment(
        event_name=event_name,
        local_scores=local_scores,
        coverage_status="PUBLIC_PROXY_ONLY" if confidence >= 0.6 else "INCOMPLETE_PUBLIC_PROXY",
        required_missing_data=missing,
        public_proxy_confidence=round(float(confidence), 4),
        allowed_claims=("Banking-sector public proxy overlay", "Coverage-limited vulnerability explanation"),
        forbidden_claims=("Bank-run prediction", "Supervisory balance-sheet certainty", "Portfolio instruction"),
    )


def _score(frame: pd.DataFrame, cols: tuple[str, ...]) -> float:
    present = [col for col in cols if col in frame.columns]
    if not present:
        return 0.0
    values = frame[present].tail(20).pct_change().abs().mean(numeric_only=True)
    return float(values.mean()) if not values.empty else 0.0
