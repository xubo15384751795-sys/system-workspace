"""Convert CaseLab vault into System training datasets.

Reads all CaseLab content through the adapter and produces five
training/calibration datasets that System's models can consume.

Run:
    cd /Users/a1/System
    python -m nlp.caselab.converter

Output (written to Data/nlp/caselab_training/):
    nlp_train.jsonl           — text + mechanism/entity/variable labels
    regime_labels.jsonl       — crisis episodes → K state labels
    mechanism_features.yaml   — mechanism → K feature mapping
    entity_signals.yaml       — entity DNA → observable signals
    feedback_templates.json   — expansion/reversal loop templates
    case_index.json           — master index of all converted cases
"""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from nlp.caselab.adapter import CaseLabAdapter, CaseLabCase, CaseLabEntity


# ── Paths ─────────────────────────────────────────────────────────────────
CASELAB_ROOT = Path("/Users/a1/Paper")
SYSTEM_DATA = WorkspacePaths.discover().root / "Data" / "nlp" / "caselab_training"


# ── Mechanism → K feature mapping ────────────────────────────────────────
# Maps CaseLab mechanism names to System's k_features_daily.csv columns.
# Each mechanism relates to specific observable market features.

MECHANISM_FEATURE_MAP: dict[str, dict[str, Any]] = {
    "Liquidity Spiral": {
        "features": ["rv_SPY_20d", "rv_SPY_60d", "corr_SPY_TLT_60d", "corr_SPY_HYG_60d", "dd_vel_SPY_5d"],
        "signal": "volatility spike + correlation breakdown + drawdown acceleration",
        "k_state_direction": "K3→K4→K5",
    },
    "Forced Selling": {
        "features": ["rv_SPY_20d", "dd_vel_SPY_5d", "dd_vel_SPY_10d", "sector_dispersion_20d"],
        "signal": "sharp drawdown velocity + elevated volatility",
        "k_state_direction": "K3→K4",
    },
    "Risk Transfer": {
        "features": ["ratio_HYG_TLT", "corr_SPY_HYG_60d", "corr_HYG_TLT_60d"],
        "signal": "credit spread widening + credit-equity correlation shift",
        "k_state_direction": "K2→K3",
    },
    "Reflexivity": {
        "features": ["rv_SPY_60d", "sector_dispersion_60d", "ratio_QQQ_SPY", "ratio_IWM_SPY"],
        "signal": "self-reinforcing momentum in sector dispersion or style factors",
        "k_state_direction": "amplifies current state",
    },
    "Duration Mismatch": {
        "features": ["corr_SPY_TLT_60d", "rv_TLT_20d", "ratio_HYG_TLT"],
        "signal": "bond-equity correlation flip + bond volatility rise",
        "k_state_direction": "K2→K3",
    },
    "Balance Sheet Expansion": {
        "features": ["ratio_XLF_SPY", "rv_XLF_20d", "ratio_HYG_TLT"],
        "signal": "financial sector relative strength + compressed credit spreads",
        "k_state_direction": "K1→K2 (buildup)",
    },
    "Repo Financing": {
        "features": ["rv_XLF_20d", "rv_XLF_60d", "dd_vel_XLF_5d"],
        "signal": "financial sector volatility + drawdown stress",
        "k_state_direction": "K3→K4",
    },
    "Carry Trade": {
        "features": ["corr_SPY_UUP_60d", "rv_TLT_20d", "ratio_SLV_GLD"],
        "signal": "currency moves + precious metals ratio + bond volatility",
        "k_state_direction": "K2→K3",
    },
    "Compute CapEx Loop": {
        "features": ["ratio_SMH_SPY", "ratio_QQQ_SPY", "sector_dispersion_20d"],
        "signal": "semiconductor relative strength + tech concentration",
        "k_state_direction": "K1→K2 (momentum)",
    },
    "Vendor Lock-in": {
        "features": ["ratio_SMH_SPY", "sector_dispersion_60d"],
        "signal": "single-sector dominance + concentration risk",
        "k_state_direction": "builds asymmetry",
    },
    "Platform Network Effects": {
        "features": ["ratio_QQQ_SPY", "sector_dispersion_60d"],
        "signal": "tech sector dispersion widening",
        "k_state_direction": "K1→K2",
    },
    "CUDA Ecosystem": {
        "features": ["ratio_SMH_SPY", "ratio_QQQ_SPY"],
        "signal": "semiconductor relative performance vs broad tech",
        "k_state_direction": "concentrated positioning",
    },
    "IPO": {
        "features": ["rv_SPY_20d", "sector_dispersion_20d", "ratio_QQQ_IWM"],
        "signal": "low volatility + positive sentiment = IPO window",
        "k_state_direction": "K0→K1",
    },
    "Securitization": {
        "features": ["ratio_HYG_TLT", "corr_SPY_HYG_60d", "ratio_XLF_SPY"],
        "signal": "credit spread compression + financial sector strength",
        "k_state_direction": "K1→K2 (risk buildup)",
    },
    "CDO": {
        "features": ["ratio_HYG_TLT", "corr_HYG_TLT_60d", "rv_HYG_20d"],
        "signal": "credit product stress indicators",
        "k_state_direction": "K2→K3→K4",
    },
    "CDS": {
        "features": ["ratio_HYG_TLT", "rv_XLF_20d", "corr_SPY_HYG_60d"],
        "signal": "credit default risk repricing",
        "k_state_direction": "K3→K4",
    },
    "Volatility Compression": {
        "features": ["rv_SPY_20d", "rv_SPY_60d", "rv_QQQ_20d"],
        "signal": "unusually low realized volatility across assets",
        "k_state_direction": "K0 (false calm)",
    },
    "Export Control": {
        "features": ["ratio_SMH_SPY", "sector_dispersion_20d", "corr_SPY_GLD_60d"],
        "signal": "semiconductor disruption + safe haven demand",
        "k_state_direction": "K2→K3",
    },
    "Dollar System": {
        "features": ["corr_SPY_UUP_60d", "UUP_level", "ratio_SLV_GLD"],
        "signal": "dollar strength/weakness regime shift",
        "k_state_direction": "amplifies cross-border stress",
    },
    "Standardization": {
        "features": ["sector_dispersion_60d", "ratio_IWM_SPY"],
        "signal": "reduced dispersion = successful standardization",
        "k_state_direction": "stabilizes K",
    },
    "Vertical Integration": {
        "features": ["ratio_SMH_SPY", "sector_dispersion_60d"],
        "signal": "supply chain consolidation effects",
        "k_state_direction": "reduces fragility or increases concentration",
    },
}


# ── Crisis episode → K state mapping ─────────────────────────────────────
# Based on CaseLab crisis/trading cases, maps episodes to K state transitions.

CRISIS_K_LABELS: dict[str, dict[str, Any]] = {
    "1929_wall_street_crash": {"k_from": 2, "k_to": 5, "severity": 0.95, "episode": "1929-10"},
    "1987_black_monday": {"k_from": 2, "k_to": 5, "severity": 0.85, "episode": "1987-10"},
    "1992_british_pound_crisis": {"k_from": 2, "k_to": 4, "severity": 0.65, "episode": "1992-09"},
    "1997_asian_financial_crisis": {"k_from": 2, "k_to": 4, "severity": 0.70, "episode": "1997-07"},
    "1998_ltcm_collapse": {"k_from": 3, "k_to": 5, "severity": 0.80, "episode": "1998-08"},
    "2000_dot-com_bubble": {"k_from": 2, "k_to": 4, "severity": 0.70, "episode": "2000-03"},
    "2008_aig_bailout": {"k_from": 4, "k_to": 5, "severity": 0.90, "episode": "2008-09"},
    "2008_lehman_collapse": {"k_from": 4, "k_to": 5, "severity": 0.95, "episode": "2008-09"},
    "2010_eurozone_debt_crisis": {"k_from": 2, "k_to": 4, "severity": 0.65, "episode": "2010-05"},
    "2015_china_stock_market_crash": {"k_from": 2, "k_to": 4, "severity": 0.60, "episode": "2015-06"},
    "2020_covid_liquidity_crisis": {"k_from": 2, "k_to": 5, "severity": 0.90, "episode": "2020-03"},
    "2021_archegos_collapse": {"k_from": 2, "k_to": 3, "severity": 0.45, "episode": "2021-03"},
    "2023_credit_suisse_collapse": {"k_from": 3, "k_to": 5, "severity": 0.75, "episode": "2023-03"},
    "2023_svb_collapse": {"k_from": 3, "k_to": 4, "severity": 0.65, "episode": "2023-03"},
}


def _extract_feedback_loops(body: str) -> dict[str, Any]:
    """Extract expansion and reversal loops from case body."""
    loops: dict[str, Any] = {"expansion": [], "reversal": []}

    # Look for 反馈环 / Feedback Loops section
    feedback_section = ""
    for pattern in [
        r"^##.*反馈环.*$",
        r"^##.*Feedback.*$",
        r"^##.*Causal Chain.*$",
    ]:
        m = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
        if m:
            start = m.end()
            nxt = re.search(r"^##", body[start:], re.MULTILINE)
            end = start + nxt.start() if nxt else len(body)
            feedback_section = body[start:end].strip()
            break

    if not feedback_section:
        return loops

    # Try to split expansion/reversal
    expansion_match = re.search(
        r"(?:扩张环|Expansion|正反馈|self-reinforcing)(.*?)(?=反转环|Reversal|负反馈|$)",
        feedback_section, re.DOTALL | re.IGNORECASE,
    )
    reversal_match = re.search(
        r"(?:反转环|Reversal|负反馈|self-correcting)(.*?)$",
        feedback_section, re.DOTALL | re.IGNORECASE,
    )

    if expansion_match:
        loops["expansion"] = _parse_chain(expansion_match.group(1))
    if reversal_match:
        loops["reversal"] = _parse_chain(reversal_match.group(1))

    return loops


def _parse_chain(text: str) -> list[str]:
    """Parse a causal chain from text (arrows, →, numbered steps)."""
    # Split by arrows or newlines
    steps = re.split(r"[→➜\n]+", text)
    return [s.strip().strip("*-• ") for s in steps if s.strip() and len(s.strip()) > 2]


def _case_to_nlp_sample(case: CaseLabCase) -> dict[str, Any]:
    """Convert one case to an NLP training sample."""
    # Build input text from key sections
    text_parts = []
    if case.narrative_summary:
        text_parts.append(case.narrative_summary)
    if case.risk_migration:
        text_parts.append(case.risk_migration)
    if case.feedback_loop:
        text_parts.append(case.feedback_loop)
    text = " ".join(text_parts)[:3000]

    return {
        "case_id": case.case_id,
        "case_name": case.case_name,
        "text": text,
        "case_type": case.case_type,
        "mechanisms": case.mechanisms,
        "tags": case.tags,
        "structural_vector": case.variable_vector,
        "event_patterns": case.event_patterns,
        "main_entity": case.main_entity,
        "country": case.country,
        "trade_relevance": case.trade_relevance,
    }


def _entity_to_signal(entity: CaseLabEntity) -> dict[str, Any]:
    """Convert one entity to a signal mapping entry."""
    # Extract observable signals from related_variables and indicators
    signals: list[str] = []

    # From DNA/role
    if "lock-in" in (entity.dna_text or "").lower() or "lock-in" in (entity.positioning or "").lower():
        signals.append("concentration_risk")
    if "risk" in (entity.dna_text or "").lower() or "credit" in (entity.dna_text or "").lower():
        signals.append("credit_stress")
    if "infrastructure" in (entity.positioning or "").lower():
        signals.append("systemic_dependency")
    if "talent" in (entity.positioning or "").lower() or "pipeline" in (entity.positioning or "").lower():
        signals.append("talent_flow")

    return {
        "entity_id": entity.entity_id,
        "entity_name": entity.entity_name,
        "entity_type": entity.entity_type,
        "structural_vector": entity.variable_vector,
        "signals": signals,
        "related_mechanisms": entity.related_mechanisms,
        "related_cases": entity.related_cases,
        "dna_summary": (entity.dna_text or "")[:300],
        "inertia_summary": (entity.inertia_text or "")[:300],
    }


# ── Main converter ───────────────────────────────────────────────────────

def convert_all(output_dir: Path | None = None) -> dict[str, int]:
    """Run full conversion. Returns counts per output file."""
    out = output_dir or SYSTEM_DATA
    out.mkdir(parents=True, exist_ok=True)

    adapter = CaseLabAdapter(CASELAB_ROOT)
    cases = adapter.load_cases()
    entities = adapter.load_entities()
    mechanisms = adapter.load_mechanisms()

    stats: dict[str, int] = {}

    # 1. nlp_train.jsonl
    nlp_path = out / "nlp_train.jsonl"
    with open(nlp_path, "w", encoding="utf-8") as f:
        for case in cases:
            sample = _case_to_nlp_sample(case)
            if sample["text"]:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    stats["nlp_train"] = len(cases)

    # 2. regime_labels.jsonl
    regime_path = out / "regime_labels.jsonl"
    regime_count = 0
    with open(regime_path, "w", encoding="utf-8") as f:
        for case in cases:
            label = CRISIS_K_LABELS.get(case.case_id)
            if label:
                entry = {
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "case_type": case.case_type,
                    **label,
                    "mechanisms": case.mechanisms,
                    "structural_vector": case.variable_vector,
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                regime_count += 1
    stats["regime_labels"] = regime_count

    # 3. mechanism_features.yaml
    mech_path = out / "mechanism_features.yaml"
    enriched_mechanisms: dict[str, Any] = {}
    for mech in mechanisms:
        name = mech["name"]
        if name in MECHANISM_FEATURE_MAP:
            enriched_mechanisms[name] = {
                **MECHANISM_FEATURE_MAP[name],
                "related_cases": mech.get("related_cases", []),
                "related_entities": mech.get("related_entities", []),
                "related_variables": mech.get("related_variables", []),
                "tags": mech.get("tags", []),
            }
        else:
            enriched_mechanisms[name] = {
                "features": [],
                "signal": "",
                "k_state_direction": "",
                "related_cases": mech.get("related_cases", []),
                "related_entities": mech.get("related_entities", []),
                "related_variables": mech.get("related_variables", []),
                "tags": mech.get("tags", []),
            }
    with open(mech_path, "w", encoding="utf-8") as f:
        yaml.dump(enriched_mechanisms, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    stats["mechanism_features"] = len(enriched_mechanisms)

    # 4. entity_signals.yaml
    entity_path = out / "entity_signals.yaml"
    entity_signals: dict[str, Any] = {}
    for entity in entities:
        entity_signals[entity.entity_id] = _entity_to_signal(entity)
    with open(entity_path, "w", encoding="utf-8") as f:
        yaml.dump(entity_signals, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    stats["entity_signals"] = len(entity_signals)

    # 5. feedback_templates.json
    feedback_path = out / "feedback_templates.json"
    templates: list[dict[str, Any]] = []
    for case in cases:
        if case.feedback_loop or case.risk_migration:
            # Try to extract structured loops from file
            try:
                text = Path(case.file_path).read_text(encoding="utf-8") if case.file_path else ""
                _, body = _parse_frontmatter(text)
                loops = _extract_feedback_loops(body)
            except Exception:
                loops = {"expansion": [], "reversal": []}

            if loops["expansion"] or loops["reversal"]:
                templates.append({
                    "case_id": case.case_id,
                    "case_name": case.case_name,
                    "case_type": case.case_type,
                    "expansion_loop": loops["expansion"],
                    "reversal_loop": loops["reversal"],
                    "mechanisms": case.mechanisms,
                })
    with open(feedback_path, "w", encoding="utf-8") as f:
        json.dump(templates, f, indent=2, ensure_ascii=False)
    stats["feedback_templates"] = len(templates)

    # 6. case_index.json — master index
    index_path = out / "case_index.json"
    index: list[dict[str, Any]] = []
    for case in cases:
        index.append({
            "case_id": case.case_id,
            "case_name": case.case_name,
            "case_type": case.case_type,
            "main_entity": case.main_entity,
            "mechanisms": case.mechanisms,
            "structural_vector": case.variable_vector,
            "trade_relevance": case.trade_relevance,
            "has_regime_label": case.case_id in CRISIS_K_LABELS,
            "file_path": case.file_path,
        })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    stats["case_index"] = len(index)

    return stats


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter. Duplicate of adapter's internal function."""
    text = text.strip()
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    try:
        meta = yaml.safe_load(text[3:end]) or {}
    except Exception:
        meta = {}
    return meta, text[end + 3:].strip()


# ── Incremental update ───────────────────────────────────────────────────

def convert_incremental(output_dir: Path | None = None) -> dict[str, int]:
    """Only convert cases not yet in the index. For daily updates."""
    out = output_dir or SYSTEM_DATA
    index_path = out / "case_index.json"

    existing_ids: set[str] = set()
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            for entry in json.load(f):
                existing_ids.add(entry["case_id"])

    adapter = CaseLabAdapter(CASELAB_ROOT)
    new_cases = [c for c in adapter.load_cases() if c.case_id not in existing_ids]

    if not new_cases:
        return {"new_cases": 0}

    # Append to nlp_train.jsonl
    nlp_path = out / "nlp_train.jsonl"
    with open(nlp_path, "a", encoding="utf-8") as f:
        for case in new_cases:
            sample = _case_to_nlp_sample(case)
            if sample["text"]:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    # Append regime labels if crisis
    regime_path = out / "regime_labels.jsonl"
    with open(regime_path, "a", encoding="utf-8") as f:
        for case in new_cases:
            label = CRISIS_K_LABELS.get(case.case_id)
            if label:
                entry = {"case_id": case.case_id, "case_name": case.case_name, **label}
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Update index
    index: list[dict[str, Any]] = []
    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    for case in new_cases:
        index.append({
            "case_id": case.case_id,
            "case_name": case.case_name,
            "case_type": case.case_type,
            "mechanisms": case.mechanisms,
            "structural_vector": case.variable_vector,
        })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    return {"new_cases": len(new_cases)}


if __name__ == "__main__":
    stats = convert_all()
    print("Conversion complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
