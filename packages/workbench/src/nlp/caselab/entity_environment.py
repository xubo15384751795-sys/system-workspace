"""Entity Environment Index — structured world model for System.

READS: CaseLab vault via adapter
WRITES: Data/nlp/caselab_environments/ (standalone, not System core)

For each of 283 entities, builds a structured environment profile:
  - DNA (behavioral defaults)
  - Inertia (situation → response mapping)
  - Environment variables (what this entity cares about)
  - Variable structure (directed graph of how variables interact)
  - Mechanism activation (which mechanisms this entity triggers)
  - Historical precedents (connected cases)
  - M/D/K/X impact model (how entity stress maps to System state)

This index is the world model. When an event happens to an entity,
the resolver reads this index to understand the structural impact.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CASELAB_ROOT = Path("/Users/a1/Paper")
INDEX_PATH = Path(__file__).resolve().parents[4] / "Data" / "nlp" / "caselab_environments"


# ── Entity type → default environment variable templates ─────────────────

ENTITY_VARIABLE_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "company": {
        "financial": ["balance_sheet", "leverage", "revenue", "cash_flow", "credit_spread"],
        "operational": ["headcount", "talent_density", "product_pipeline", "market_share"],
        "market": ["stock_price", "valuation", "analyst_sentiment", "trading_volume"],
        "risk": ["counterparty_exposure", "concentration_risk", "regulatory_risk"],
    },
    "geo": {
        "economic": ["gdp_growth", "unemployment", "inflation", "capital_flow"],
        "institutional": ["regulatory_quality", "rule_of_law", "tax_policy", "trade_policy"],
        "financial": ["currency_stability", "bond_market_depth", "banking_system_health"],
        "strategic": ["tech_capacity", "talent_pipeline", "infrastructure", "energy_security"],
    },
    "school": {
        "academic": ["research_output", "faculty_quality", "funding_level"],
        "ecosystem": ["startup_output", "vc_connection", "industry_partnership", "talent_export"],
        "strategic": ["government_funding", "endowment_size", "global_ranking"],
    },
    "regulator": {
        "authority": ["jurisdiction_scope", "enforcement_power", "rule_making_authority"],
        "tools": ["interest_rate", "liquidity_injection", "macroprudential_tools"],
        "credibility": ["market_trust", "political_independence", "track_record"],
    },
    "financial-infrastructure": {
        "function": ["clearing_volume", "settlement_efficiency", "counterparty_netting"],
        "risk": ["operational_risk", "concentration_risk", "interconnectedness"],
        "regulatory": ["oversight_quality", "capital_requirements", "stress_test_frequency"],
    },
}

# ── Mechanism → variable interaction edges ───────────────────────────────
# Each mechanism implies certain variable interactions (directed edges).
# These define the causal structure of how variables affect each other.

MECHANISM_EDGES: dict[str, list[tuple[str, str, str]]] = {
    "Risk Transfer": [
        ("balance_sheet", "counterparty_exposure", "transfers_risk_to"),
        ("credit_spread", "balance_sheet", "prices_risk_onto"),
    ],
    "Balance Sheet Expansion": [
        ("leverage", "balance_sheet", "expands"),
        ("leverage", "revenue", "amplifies"),
        ("leverage", "counterparty_exposure", "increases"),
    ],
    "Reflexivity": [
        ("stock_price", "balance_sheet", "feedback_via_collateral"),
        ("analyst_sentiment", "stock_price", "drives"),
        ("stock_price", "talent_density", "attracts_via_equity"),
    ],
    "Liquidity Spiral": [
        ("credit_spread", "trading_volume", "dries_up"),
        ("trading_volume", "stock_price", "depresses"),
        ("stock_price", "leverage", "forces_deleveraging"),
    ],
    "Forced Selling": [
        ("leverage", "stock_price", "liquidation_depresses"),
        ("counterparty_exposure", "credit_spread", "widens"),
    ],
    "Compute CapEx Loop": [
        ("capex", "revenue", "drives_growth"),
        ("revenue", "capex", "funds_next_cycle"),
        ("capex", "talent_density", "attracts_engineers"),
    ],
    "CUDA Ecosystem": [
        ("market_share", "talent_density", "lock_in_developers"),
        ("talent_density", "product_pipeline", "drives_innovation"),
        ("product_pipeline", "market_share", "reinforces_dominance"),
    ],
    "Vendor Lock-in": [
        ("switching_cost", "market_share", "protects"),
        ("market_share", "revenue", "stabilizes"),
    ],
    "Platform Network Effects": [
        ("market_share", "valuation", "amplifies"),
        ("talent_density", "market_share", "attracts_ecosystem"),
    ],
    "University Startup Pipeline": [
        ("research_output", "startup_output", "generates"),
        ("startup_output", "vc_connection", "attracts"),
        ("vc_connection", "talent_pipeline", "retains"),
    ],
    "Talent Density": [
        ("talent_density", "research_output", "enables"),
        ("talent_density", "product_pipeline", "drives"),
    ],
    "IPO": [
        ("valuation", "cash_flow", "provides_liquidity"),
        ("stock_price", "talent_density", "enables_equity_comp"),
        ("analyst_sentiment", "valuation", "prices_in"),
    ],
    "Dollar System": [
        ("currency_stability", "capital_flow", "attracts"),
        ("capital_flow", "bond_market_depth", "deepens"),
        ("bond_market_depth", "banking_system_health", "supports"),
    ],
    "Export Control": [
        ("regulatory_risk", "market_share", "constrains"),
        ("regulatory_risk", "revenue", "threatens"),
    ],
    "Duration Mismatch": [
        ("leverage", "cash_flow", "creates_refinancing_risk"),
        ("cash_flow", "credit_spread", "widens_on_stress"),
    ],
    "Securitization": [
        ("balance_sheet", "counterparty_exposure", "distributes"),
        ("leverage", "credit_spread", "hides_until_crisis"),
    ],
    "CDO": [
        ("counterparty_exposure", "credit_spread", "amplifies_hidden"),
        ("leverage", "balance_sheet", "layers_complexity"),
    ],
    "Standardization": [
        ("market_share", "revenue", "scales"),
        ("talent_density", "product_pipeline", "reduces_custom_work"),
    ],
    "Vertical Integration": [
        ("market_share", "cash_flow", "captures_margin"),
        ("capex", "market_share", "builds_moat"),
    ],
}


def build_entity_environment(entity: dict) -> dict[str, Any]:
    """Build structured environment profile for one entity."""
    eid = entity.get("entity_id", "")
    etype = entity.get("entity_type", "unknown")
    dna = entity.get("dna_text", "")
    inertia = entity.get("inertia_text", "")
    non_transferable = entity.get("non_transferable", "")
    mechanisms = entity.get("related_mechanisms", [])
    cases = entity.get("related_cases", [])
    positioning = entity.get("positioning", "")
    vector = entity.get("variable_vector", {})

    # 1. Environment variables (from template + mechanisms)
    env_vars: dict[str, list[str]] = {}
    template = ENTITY_VARIABLE_TEMPLATES.get(etype, {})
    for category, vars_list in template.items():
        env_vars[category] = vars_list[:]

    # Add mechanism-specific variables
    for mech in mechanisms:
        edges = MECHANISM_EDGES.get(mech, [])
        for src, dst, rel in edges:
            for cat_vars in env_vars.values():
                if src not in cat_vars:
                    # Find appropriate category
                    pass

    # 2. Variable interaction graph (from mechanisms)
    interaction_graph: list[dict[str, str]] = []
    for mech in mechanisms:
        edges = MECHANISM_EDGES.get(mech, [])
        for src, dst, rel in edges:
            interaction_graph.append({
                "from": src,
                "to": dst,
                "relation": rel,
                "via_mechanism": mech,
            })

    # 3. Inertia parsing (situation → response)
    inertia_map = _parse_inertia(inertia)

    # 4. DNA keywords
    dna_keywords = _extract_dna_keywords(dna)

    # 5. M/D/K/X impact profile
    mdx_impact = _compute_mdx_impact(entity, mechanisms, dna_keywords)

    return {
        "entity_id": eid,
        "entity_name": entity.get("entity_name", ""),
        "entity_type": etype,
        "environment_variables": env_vars,
        "interaction_graph": interaction_graph,
        "dna_keywords": dna_keywords,
        "inertia_map": inertia_map,
        "non_transferable": non_transferable[:300] if non_transferable else "",
        "mechanisms": mechanisms,
        "historical_precedents": cases,
        "structural_vector": vector,
        "mdx_impact_profile": mdx_impact,
    }


def _parse_inertia(text: str) -> dict[str, str]:
    """Extract situation → response pairs from inertia text."""
    if not text:
        return {}

    mapping: dict[str, str] = {}
    # Look for "当...时" / "遇到...时" patterns
    patterns = [
        (r"当([^，。,\.]+)时[，,]?\s*(.+?)(?=\n|当|遇到|English|$)", "when"),
        (r"遇到([^，。,\.]+)时[，,]?\s*(.+?)(?=\n|当|遇到|English|$)", "when"),
        (r"When\s+(.+?)[，,]\s*(.+?)(?=\n|When|$)", "when_en"),
    ]

    for pattern, ptype in patterns:
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        for situation, response in matches:
            sit = situation.strip()[:80]
            resp = response.strip()[:150]
            if sit and resp:
                mapping[sit] = resp

    return mapping


def _extract_dna_keywords(text: str) -> list[str]:
    """Extract DNA behavioral keywords from text."""
    if not text:
        return []

    keyword_patterns = [
        "风险定价", "客户网络", "合伙人", "资产负债表", "交易能力",
        "精英文化", "危机自保", "金融化", "结构化", "平台化",
        "创业转化", "硅谷嵌入", "技术合法性", "校友网络", "商业化",
        "工程研究", "开源", "公共研究", "人才密度",
        "操作系统", "分发控制", "开发者生态", "企业客户",
        "硬件工程", "CUDA", "垂直整合", "长期押注",
        "流动性", "货币条件", "紧急贷款", "量化宽松",
        "国家资本", "监管可信度", "财富管理",
        "标准化", "成本压缩", "规模经济",
    ]

    found = []
    text_lower = text.lower()
    for kw in keyword_patterns:
        if kw.lower() in text_lower:
            found.append(kw)

    return found


def _compute_mdx_impact(
    entity: dict,
    mechanisms: list[str],
    dna_keywords: list[str],
) -> dict[str, Any]:
    """Compute how this entity's stress would impact M/D/K/X.

    Returns a profile that maps entity-level events to System state changes.
    """
    etype = entity.get("entity_type", "")
    vector = entity.get("variable_vector", {})

    # Base sensitivity: how much does this entity affect each dimension?
    sensitivity = {
        "M": 0.0,  # macro impact
        "K": 0.0,  # structural stress
        "D": 0.0,  # deterioration
        "X": 0.0,  # cross-market
    }

    # Entity type → base sensitivity
    if etype == "company":
        sector = (entity.get("sector") or "").lower()
        if "financial" in sector or "bank" in sector or "investment" in sector:
            sensitivity["K"] = 0.6
            sensitivity["D"] = 0.5
            sensitivity["X"] = 0.4
        elif "semiconductor" in sector or "ai" in sector or "tech" in sector:
            sensitivity["K"] = 0.3
            sensitivity["M"] = 0.2
            sensitivity["X"] = 0.3
        else:
            sensitivity["K"] = 0.2
            sensitivity["D"] = 0.1
    elif etype == "geo":
        geo_level = entity.get("geo_level", "")
        if geo_level == "country":
            sensitivity["M"] = 0.5
            sensitivity["K"] = 0.3
            sensitivity["X"] = 0.4
        elif geo_level == "state":
            sensitivity["M"] = 0.2
            sensitivity["K"] = 0.2
        else:
            sensitivity["M"] = 0.1
            sensitivity["K"] = 0.1
    elif etype == "regulator":
        sensitivity["M"] = 0.7
        sensitivity["K"] = 0.4
        sensitivity["D"] = 0.3
    elif etype == "school":
        sensitivity["K"] = 0.1
        sensitivity["M"] = 0.05

    # Mechanism boost
    for mech in mechanisms:
        mech_lower = mech.lower()
        if "liquidity" in mech_lower or "spiral" in mech_lower:
            sensitivity["K"] += 0.15
            sensitivity["D"] += 0.10
        if "leverage" in mech_lower or "balance_sheet" in mech_lower:
            sensitivity["K"] += 0.10
            sensitivity["D"] += 0.08
        if "dollar" in mech_lower or "system" in mech_lower:
            sensitivity["M"] += 0.15
            sensitivity["X"] += 0.10
        if "export" in mech_lower or "control" in mech_lower:
            sensitivity["K"] += 0.10
            sensitivity["X"] += 0.15
        if "forced" in mech_lower or "selling" in mech_lower:
            sensitivity["K"] += 0.15
            sensitivity["D"] += 0.12
        if "compute" in mech_lower or "capex" in mech_lower:
            sensitivity["K"] += 0.05
            sensitivity["M"] += 0.05

    # DNA keyword boost
    for kw in dna_keywords:
        if "风险" in kw or "杠杆" in kw:
            sensitivity["K"] += 0.05
        if "流动性" in kw:
            sensitivity["K"] += 0.08
        if "平台" in kw or "生态" in kw:
            sensitivity["X"] += 0.05

    # Clamp
    for k in sensitivity:
        sensitivity[k] = round(min(1.0, max(0.0, sensitivity[k])), 2)

    # Propagation path: how does this entity's stress propagate?
    propagation = _infer_propagation(mechanisms, dna_keywords, etype)

    return {
        "sensitivity": sensitivity,
        "propagation_path": propagation,
        "vector": vector,
    }


def _infer_propagation(
    mechanisms: list[str],
    dna_keywords: list[str],
    etype: str,
) -> list[str]:
    """Infer how this entity's stress propagates through the system."""
    path: list[str] = []

    mech_set = set(m.lower() for m in mechanisms)
    kw_set = set(dna_keywords)

    if etype == "company":
        if "balance_sheet" in kw_set or "leverage" in kw_set:
            path.append("entity_stress → balance_sheet_deterioration → credit_spread_widening")
        if any("liquidity" in m for m in mech_set):
            path.append("entity_stress → counterparties_reevaluate → liquidity_tightens")
        if any("platform" in m or "lock" in m for m in mech_set):
            path.append("entity_stress → ecosystem_dependency_risk → concentration_concern")
        if any("forced" in m for m in mech_set):
            path.append("entity_stress → forced_selling → price_depression → contagion")

    elif etype == "geo":
        path.append("geo_stress → capital_flow_shift → currency_pressure")
        if any("dollar" in m for m in mech_set):
            path.append("geo_stress → dollar_system_transmission → global_risk_repricing")

    elif etype == "regulator":
        path.append("regulator_action → market_condition_change → risk_repricing")
        if any("liquidity" in m for m in mech_set):
            path.append("regulator_stress → liquidity_injection_needed → moral_hazard")

    if not path:
        path.append("entity_stress → local_impact → limited_systemic_propagation")

    return path


def build_all_environments(entities: list[dict]) -> dict[str, dict]:
    """Build environment profiles for all entities."""
    environments: dict[str, dict] = {}
    for entity in entities:
        eid = entity.get("entity_id", "")
        if eid:
            environments[eid] = build_entity_environment(entity)
    return environments


def save_environments(environments: dict[str, dict], output_dir: Path | None = None) -> Path:
    """Save environment index to disk."""
    out = output_dir or INDEX_PATH
    out.mkdir(parents=True, exist_ok=True)

    # Save full index
    index_path = out / "entity_environments.json"
    index_path.write_text(
        json.dumps(environments, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Save individual files for quick lookup
    entities_dir = out / "entities"
    entities_dir.mkdir(exist_ok=True)
    for eid, env in environments.items():
        safe_name = re.sub(r"[^a-z0-9_-]", "_", eid.lower())
        (entities_dir / f"{safe_name}.json").write_text(
            json.dumps(env, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return index_path
