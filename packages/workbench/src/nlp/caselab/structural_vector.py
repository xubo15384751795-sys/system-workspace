"""Rule-based S-A-L-V-P-tau structural vector computation for CaseLab cases.

S = Stress          (market/systemic pressure)
A = Asymmetry       (information/visibility/risk imbalance)
L = Leverage        (balance sheet / capital structure exposure)
V = Volatility      (price/rate movement magnitude)
P = Positioning     (crowded trades / directional exposure)
tau = Time pressure (urgency / maturity mismatch / speed of events)
"""
from __future__ import annotations

import re


# ── Mechanism → vector delta mapping ──────────────────────────────────────
# Each entry: {S, A, L, V, P, tau} as positive deltas (0.0–0.3 typical).
# Mechanisms that REDUCE a dimension use negative values.
MECHANISM_DELTAS: dict[str, dict[str, float]] = {
    # ── Crisis / stress mechanisms ──
    "Liquidity Spiral":         {"S": 0.25, "A": 0.05, "L": 0.05, "V": 0.20, "P": 0.10, "tau": 0.15},
    "Forced Selling":           {"S": 0.20, "A": 0.05, "L": 0.05, "V": 0.25, "P": 0.20, "tau": 0.15},
    "Margin Call":              {"S": 0.20, "A": 0.05, "L": 0.10, "V": 0.20, "P": 0.15, "tau": 0.25},
    "Reflexivity":              {"S": 0.15, "A": 0.15, "L": 0.05, "V": 0.15, "P": 0.10, "tau": 0.10},
    "confidence_spiral":        {"S": 0.25, "A": 0.10, "L": 0.05, "V": 0.15, "P": 0.10, "tau": 0.20},
    "liquidity_crisis":         {"S": 0.25, "A": 0.10, "L": 0.05, "V": 0.20, "P": 0.10, "tau": 0.15},
    "Settlement Fail":          {"S": 0.15, "A": 0.05, "L": 0.00, "V": 0.10, "P": 0.05, "tau": 0.20},
    "Financial Messaging":      {"S": 0.10, "A": 0.05, "L": 0.00, "V": 0.05, "P": 0.00, "tau": 0.15},

    # ── Leverage / balance sheet ──
    "Balance Sheet Expansion":  {"S": 0.05, "A": 0.05, "L": 0.25, "V": 0.05, "P": 0.05, "tau": 0.05},
    "leverage_30x":             {"S": 0.10, "A": 0.10, "L": 0.30, "V": 0.10, "P": 0.10, "tau": 0.10},
    "Repo Financing":           {"S": 0.10, "A": 0.05, "L": 0.20, "V": 0.05, "P": 0.05, "tau": 0.20},
    "repo_dependency":          {"S": 0.15, "A": 0.05, "L": 0.20, "V": 0.10, "P": 0.05, "tau": 0.20},
    "Duration Mismatch":        {"S": 0.10, "A": 0.10, "L": 0.20, "V": 0.05, "P": 0.05, "tau": 0.25},
    "Securitization":           {"S": 0.05, "A": 0.20, "L": 0.15, "V": 0.05, "P": 0.05, "tau": 0.05},
    "CDO":                      {"S": 0.05, "A": 0.25, "L": 0.20, "V": 0.10, "P": 0.05, "tau": 0.05},
    "CDS":                      {"S": 0.05, "A": 0.20, "L": 0.15, "V": 0.10, "P": 0.10, "tau": 0.05},
    "Total Return Swap":        {"S": 0.05, "A": 0.25, "L": 0.20, "V": 0.05, "P": 0.10, "tau": 0.05},
    "Basis Trade":              {"S": 0.05, "A": 0.15, "L": 0.20, "V": 0.10, "P": 0.10, "tau": 0.10},
    "Structured Financing":     {"S": 0.05, "A": 0.15, "L": 0.20, "V": 0.05, "P": 0.05, "tau": 0.05},
    "Carry Trade":              {"S": 0.05, "A": 0.15, "L": 0.20, "V": 0.10, "P": 0.15, "tau": 0.10},
    "AI Compute Credit":        {"S": 0.05, "A": 0.10, "L": 0.20, "V": 0.05, "P": 0.10, "tau": 0.10},

    # ── Asymmetry / visibility ──
    "Risk Transfer":            {"S": 0.05, "A": 0.25, "L": 0.05, "V": 0.05, "P": 0.05, "tau": 0.05},
    "Bundling":                 {"S": 0.00, "A": 0.15, "L": 0.10, "V": 0.05, "P": 0.05, "tau": 0.00},
    "Vendor Lock-in":           {"S": 0.05, "A": 0.20, "L": 0.05, "V": 0.00, "P": 0.15, "tau": 0.05},
    "CUDA Ecosystem":           {"S": 0.00, "A": 0.20, "L": 0.05, "V": 0.00, "P": 0.15, "tau": 0.05},
    "Silicon Valley Asset Definition Power": {"S": 0.05, "A": 0.20, "L": 0.05, "V": 0.05, "P": 0.15, "tau": 0.05},

    # ── Volatility / positioning ──
    "Volatility Compression":   {"S": 0.00, "A": 0.05, "L": 0.00, "V": -0.15, "P": 0.15, "tau": 0.05},

    # ── CapEx / scale / platform ──
    "Compute CapEx Loop":       {"S": 0.05, "A": 0.10, "L": 0.20, "V": 0.05, "P": 0.10, "tau": 0.10},
    "Foundation Model":         {"S": 0.05, "A": 0.15, "L": 0.15, "V": 0.05, "P": 0.10, "tau": 0.10},
    "Scaling Law":              {"S": 0.05, "A": 0.15, "L": 0.15, "V": 0.05, "P": 0.10, "tau": 0.10},
    "Platform Network Effects": {"S": 0.00, "A": 0.15, "L": 0.05, "V": 0.00, "P": 0.10, "tau": 0.05},
    "GPU System Upgrade":       {"S": 0.05, "A": 0.10, "L": 0.15, "V": 0.05, "P": 0.10, "tau": 0.15},
    "Orbital AI Compute":       {"S": 0.05, "A": 0.10, "L": 0.15, "V": 0.05, "P": 0.10, "tau": 0.15},
    "Agent Workflow":            {"S": 0.00, "A": 0.10, "L": 0.05, "V": 0.00, "P": 0.10, "tau": 0.05},

    # ── IPO / capital structure ──
    "IPO":                      {"S": 0.05, "A": 0.10, "L": 0.05, "V": 0.10, "P": 0.15, "tau": 0.10},
    "IPO pricing":              {"S": 0.05, "A": 0.10, "L": 0.05, "V": 0.10, "P": 0.15, "tau": 0.10},
    "Direct Listing":           {"S": 0.05, "A": 0.05, "L": 0.00, "V": 0.10, "P": 0.15, "tau": 0.10},
    "direct listing":           {"S": 0.05, "A": 0.05, "L": 0.00, "V": 0.10, "P": 0.15, "tau": 0.10},
    "dual-class stock":         {"S": 0.00, "A": 0.15, "L": 0.00, "V": 0.00, "P": 0.10, "tau": 0.00},
    "dual-class listing":       {"S": 0.00, "A": 0.15, "L": 0.00, "V": 0.00, "P": 0.10, "tau": 0.00},
    "GP-LP structure transformation": {"S": 0.05, "A": 0.15, "L": 0.10, "V": 0.05, "P": 0.10, "tau": 0.05},
    "PE firm IPO":              {"S": 0.05, "A": 0.10, "L": 0.10, "V": 0.10, "P": 0.15, "tau": 0.05},

    # ── Industrial / standardization ──
    "Standardization":          {"S": 0.00, "A": -0.05, "L": 0.00, "V": -0.05, "P": 0.05, "tau": 0.00},
    "Vertical Integration":     {"S": 0.00, "A": -0.05, "L": 0.05, "V": -0.05, "P": 0.05, "tau": 0.00},
    "First Mover Advantage":    {"S": 0.00, "A": 0.05, "L": 0.05, "V": 0.00, "P": 0.10, "tau": 0.05},

    # ── Macro / systemic ──
    "Dollar System":            {"S": 0.10, "A": 0.10, "L": 0.05, "V": 0.05, "P": 0.05, "tau": 0.10},
    "Export Control":           {"S": 0.15, "A": 0.10, "L": 0.05, "V": 0.10, "P": 0.05, "tau": 0.10},
    "AI Capability Regulation": {"S": 0.10, "A": 0.10, "L": 0.05, "V": 0.10, "P": 0.05, "tau": 0.10},
    "AI Capital Market Regime": {"S": 0.10, "A": 0.10, "L": 0.15, "V": 0.10, "P": 0.15, "tau": 0.05},

    # ── Infrastructure / market structure ──
    "Clearing":                 {"S": -0.10, "A": -0.05, "L": 0.00, "V": -0.05, "P": 0.00, "tau": -0.05},
    "Central Counterparty":     {"S": -0.10, "A": -0.10, "L": 0.00, "V": -0.05, "P": 0.00, "tau": 0.00},
    "Netting":                  {"S": -0.05, "A": 0.00, "L": -0.10, "V": 0.00, "P": 0.00, "tau": -0.05},
    "Collateral Management":    {"S": -0.05, "A": -0.05, "L": -0.10, "V": 0.00, "P": 0.00, "tau": -0.10},
    "Novation":                 {"S": -0.05, "A": -0.10, "L": 0.00, "V": 0.00, "P": 0.00, "tau": 0.00},
    "Settlement":               {"S": -0.10, "A": 0.00, "L": 0.00, "V": 0.00, "P": 0.00, "tau": -0.10},
    "Authorized Participant":   {"S": -0.05, "A": 0.00, "L": 0.00, "V": -0.05, "P": 0.05, "tau": 0.00},
    # ── Ecosystem / talent ──
    "Developer Ecosystem":      {"S": 0.00, "A": -0.05, "L": 0.00, "V": 0.00, "P": 0.05, "tau": 0.00},
    "Open Source Ecosystem":    {"S": 0.00, "A": -0.10, "L": 0.00, "V": 0.00, "P": 0.05, "tau": 0.00},
    "University Startup Pipeline": {"S": 0.00, "A": 0.00, "L": 0.00, "V": 0.00, "P": 0.10, "tau": -0.05},
    "Talent Density":           {"S": 0.00, "A": 0.05, "L": 0.00, "V": 0.00, "P": 0.10, "tau": 0.00},
}

# ── Case type → base vector ──────────────────────────────────────────────
CASE_TYPE_BASE: dict[str, dict[str, float]] = {
    "crisis":                   {"S": 0.40, "A": 0.30, "L": 0.30, "V": 0.40, "P": 0.25, "tau": 0.35},
    "trading":                  {"S": 0.25, "A": 0.25, "L": 0.25, "V": 0.35, "P": 0.35, "tau": 0.25},
    "ipo":                      {"S": 0.10, "A": 0.20, "L": 0.10, "V": 0.20, "P": 0.30, "tau": 0.15},
    "capital":                  {"S": 0.10, "A": 0.20, "L": 0.15, "V": 0.15, "P": 0.25, "tau": 0.15},
    "industrialization":        {"S": 0.05, "A": 0.10, "L": 0.10, "V": 0.10, "P": 0.15, "tau": 0.05},
    "ai-capex":                 {"S": 0.10, "A": 0.20, "L": 0.20, "V": 0.10, "P": 0.20, "tau": 0.15},
    "financial-infrastructure": {"S": 0.15, "A": 0.15, "L": 0.10, "V": 0.10, "P": 0.10, "tau": 0.10},
    "state-capital":            {"S": 0.10, "A": 0.10, "L": 0.10, "V": 0.05, "P": 0.10, "tau": 0.10},
    "expansion":                {"S": 0.05, "A": 0.10, "L": 0.05, "V": 0.05, "P": 0.15, "tau": 0.05},
    "tech":                     {"S": 0.10, "A": 0.20, "L": 0.15, "V": 0.10, "P": 0.20, "tau": 0.10},
    "macro":                    {"S": 0.15, "A": 0.10, "L": 0.10, "V": 0.10, "P": 0.10, "tau": 0.15},
    "infrastructure":           {"S": 0.20, "A": 0.15, "L": 0.10, "V": 0.15, "P": 0.15, "tau": 0.15},
    "historical-mapping":       {"S": 0.10, "A": 0.10, "L": 0.10, "V": 0.10, "P": 0.10, "tau": 0.10},
}

# ── trade_relevance boost ────────────────────────────────────────────────
TRADE_RELEVANCE_BOOST: dict[str, float] = {
    "high": 0.10,
    "medium": 0.05,
    "low": 0.00,
}

DIMENSIONS = ("S", "A", "L", "V", "P", "tau")


def compute_structural_vector(
    *,
    case_type: str = "",
    mechanisms: list[str] | None = None,
    tags: list[str] | None = None,
    trade_relevance: str = "",
    narrative_text: str = "",
) -> dict[str, float]:
    """Compute S-A-L-V-P-tau from CaseLab metadata.

    Three-stage computation:
    1. Base vector from case_type
    2. Mechanism deltas (cumulative)
    3. Trade relevance boost on P

    Returns dict with keys S, A, L, V, P, tau, each clamped to [0.0, 1.0].
    """
    vec = {d: 0.0 for d in DIMENSIONS}

    # Stage 1: base from case_type
    ct = (case_type or "").lower().strip()
    if ct in CASE_TYPE_BASE:
        for d in DIMENSIONS:
            vec[d] = CASE_TYPE_BASE[ct][d]

    # Stage 2: mechanism deltas
    for mech in (mechanisms or []):
        # Clean [[brackets]] and whitespace
        clean = re.sub(r"[\[\]]", "", str(mech)).strip()
        if clean in MECHANISM_DELTAS:
            for d, delta in MECHANISM_DELTAS[clean].items():
                vec[d] = vec.get(d, 0.0) + delta

    # Stage 3: trade relevance boost on Positioning
    tr = (trade_relevance or "").lower().strip()
    if tr in TRADE_RELEVANCE_BOOST:
        vec["P"] += TRADE_RELEVANCE_BOOST[tr]

    # Clamp to [0.0, 1.0]
    for d in DIMENSIONS:
        vec[d] = max(0.0, min(1.0, round(vec[d], 2)))

    return vec


def compute_entity_structural_vector(
    *,
    entity_type: str = "",
    role_in_system: list[str] | str = "",
    sector: str = "",
    related_mechanisms: list[str] | None = None,
) -> dict[str, float]:
    """Compute S-A-L-V-P-tau for an entity based on its role and connections.

    Entities get a lower base than crisis cases. The vector captures
    what kind of systemic exposure this entity represents.
    """
    vec = {d: 0.10 for d in DIMENSIONS}  # neutral base

    et = (entity_type or "").lower().strip()
    roles = role_in_system if isinstance(role_in_system, list) else [role_in_system] if role_in_system else []
    sector_text = (sector or "").lower()

    # Entity type adjustments
    if et == "company":
        if "financial" in sector_text or "bank" in sector_text:
            vec["L"] += 0.15
            vec["A"] += 0.10
        if "semiconductor" in sector_text or "ai" in sector_text:
            vec["A"] += 0.10
            vec["P"] += 0.10
        if "data center" in sector_text or "cloud" in sector_text:
            vec["L"] += 0.10
            vec["P"] += 0.10
    elif et == "geo":
        vec["S"] += 0.05
        vec["tau"] += 0.05
    elif et == "regulator":
        vec["S"] -= 0.05
        vec["A"] -= 0.05
    elif et == "school":
        vec["P"] += 0.05
        vec["tau"] -= 0.05

    # Role-based adjustments
    for role in roles:
        if "chokepoint" in role or "lock-in" in role:
            vec["A"] += 0.15
            vec["P"] += 0.10
        if "risk" in role or "credit" in role:
            vec["S"] += 0.10
            vec["L"] += 0.10
        if "infrastructure" in role or "clearing" in role:
            vec["S"] -= 0.05
            vec["A"] -= 0.05
        if "talent" in role or "pipeline" in role:
            vec["P"] += 0.10
            vec["tau"] -= 0.05

    # Mechanism connections
    for mech in (related_mechanisms or []):
        clean = re.sub(r"[\[\]]", "", str(mech)).strip()
        if clean in MECHANISM_DELTAS:
            for d, delta in MECHANISM_DELTAS[clean].items():
                vec[d] = vec.get(d, 0.0) + delta * 0.5  # half weight for entity connections

    # Clamp
    for d in DIMENSIONS:
        vec[d] = max(0.0, min(1.0, round(vec[d], 2)))

    return vec
