"""Bridge CaseLab training data into System's models.

Connects the five CaseLab datasets to System's existing NLP/ML pipeline:
1. VariableMapper  — mechanism → structural variable rules
2. RegimeDetector  — crisis episodes → HMM state calibration
3. NarrativeDrift  — feedback templates → baseline narratives

Run:
    cd /Users/a1/Verity
    python -m nlp.caselab.bridge
"""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
from datetime import datetime
from typing import Any

import yaml

CASELAB_TRAINING = WorkspacePaths.discover().root / "Data" / "nlp" / "caselab_training"
MAPPING_RULES = WorkspacePaths.discover().root / "Data" / "nlp" / "mapping_rules.yaml"
ML_SIGNALS_DIR = WorkspacePaths.discover().root / "Output" / "ml_signals"


# ── 1. VariableMapper: add mechanism mapping rules ───────────────────────

def enrich_mapping_rules() -> dict[str, int]:
    """Add mechanism_mapping section to mapping_rules.yaml.

    Reads mechanism_features.yaml from CaseLab training data and
    writes mechanism → structural variable mapping rules into the
    existing mapping_rules.yaml.

    Returns counts of rules added/updated.
    """
    mech_path = CASELAB_TRAINING / "mechanism_features.yaml"
    if not mech_path.exists():
        raise FileNotFoundError(f"Run converter first: {mech_path} not found")

    with open(mech_path, encoding="utf-8") as f:
        mechanisms = yaml.safe_load(f)

    # Load existing rules
    rules: dict[str, Any] = {}
    if MAPPING_RULES.exists():
        with open(MAPPING_RULES, encoding="utf-8") as f:
            rules = yaml.safe_load(f) or {}

    # Build mechanism_mapping section
    mech_mapping: dict[str, Any] = {}
    for name, info in mechanisms.items():
        features = info.get("features", [])
        signal = info.get("signal", "")
        k_state = info.get("k_state_direction", "")
        related_vars = info.get("related_variables", [])

        # Map features to structural variables
        variables: list[str] = []
        for feat in features:
            feat_lower = feat.lower()
            if "rv_" in feat_lower or "vol" in feat_lower:
                if "V" not in variables:
                    variables.append("V")
            if "corr_" in feat_lower:
                if "A" not in variables:
                    variables.append("A")
            if "dd_vel" in feat_lower:
                if "S" not in variables:
                    variables.append("S")
                if "V" not in variables:
                    variables.append("V")
            if "ratio_" in feat_lower:
                if "A" not in variables:
                    variables.append("A")
                if "P" not in variables:
                    variables.append("P")
            if "dispersion" in feat_lower:
                if "P" not in variables:
                    variables.append("P")
                if "V" not in variables:
                    variables.append("V")
            if "uup" in feat_lower:
                if "S" not in variables:
                    variables.append("S")

        # Ensure at least one variable
        if not variables:
            variables = ["S"]

        # Compute weight from signal specificity
        weight = 0.50
        if signal:
            weight = min(0.80, 0.50 + len(features) * 0.05)

        slug = name.lower().replace(" ", "_").replace("-", "_")
        mech_mapping[slug] = {
            "variables": variables,
            "weight": round(weight, 2),
            "description": signal or f"CaseLab mechanism: {name}",
            "k_state_direction": k_state,
            "related_variables": related_vars,
            "source": "caselab",
        }

    # Merge into rules
    existing_mech = rules.get("mechanism_mapping", {})
    existing_mech.update(mech_mapping)
    rules["mechanism_mapping"] = existing_mech

    # Write back
    MAPPING_RULES.parent.mkdir(parents=True, exist_ok=True)
    with open(MAPPING_RULES, "w", encoding="utf-8") as f:
        yaml.dump(rules, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {"total_mechanisms": len(mech_mapping), "total_rules": len(rules)}


# ── 2. RegimeDetector: calibrate HMM states with crisis labels ───────────

def build_regime_calibration() -> dict[str, Any]:
    """Build calibration mapping from CaseLab crisis episodes.

    Creates a JSON file that maps date ranges to K-state labels,
    which can be used to validate/correct HMM regime detection.

    Returns the calibration data.
    """
    regime_path = CASELAB_TRAINING / "regime_labels.jsonl"
    if not regime_path.exists():
        raise FileNotFoundError(f"Run converter first: {regime_path} not found")

    episodes: list[dict[str, Any]] = []
    with open(regime_path, encoding="utf-8") as f:
        for line in f:
            episodes.append(json.loads(line))

    # Build calibration: episode → expected HMM state
    # HMM states: 0=compression, 1=volatile, 2=crisis
    # K states: K0-K5
    # Mapping: K0-K1 → compression, K2-K3 → volatile, K4-K5 → crisis
    calibration: list[dict[str, Any]] = []
    for ep in episodes:
        k_from = ep.get("k_from", 2)
        k_to = ep.get("k_to", 4)
        severity = ep.get("severity", 0.5)

        # Map K state to HMM state
        def k_to_hmm(k: int) -> str:
            if k <= 1:
                return "compression"
            elif k <= 3:
                return "volatile"
            else:
                return "crisis"

        calibration.append({
            "case_id": ep["case_id"],
            "case_name": ep.get("case_name", ""),
            "episode_date": ep.get("episode", ""),
            "k_from": k_from,
            "k_to": k_to,
            "hmm_state_from": k_to_hmm(k_from),
            "hmm_state_to": k_to_hmm(k_to),
            "severity": severity,
            "mechanisms": ep.get("mechanisms", []),
        })

    # Save calibration
    cal_path = CASELAB_TRAINING / "regime_calibration.json"
    with open(cal_path, "w", encoding="utf-8") as f:
        json.dump(calibration, f, indent=2, ensure_ascii=False)

    return {
        "episodes": len(calibration),
        "crisis_transitions": sum(1 for c in calibration if c["hmm_state_to"] == "crisis"),
        "volatile_transitions": sum(1 for c in calibration if c["hmm_state_to"] == "volatile"),
    }


# ── 3. NarrativeDrift: build baseline from feedback templates ────────────

def build_narrative_baseline() -> dict[str, Any]:
    """Build baseline narrative corpus from CaseLab feedback templates.

    Creates a structured baseline that NarrativeDriftDetector can use
    to compare against incoming market narratives.

    Returns summary of baseline.
    """
    templates_path = CASELAB_TRAINING / "feedback_templates.json"
    if not templates_path.exists():
        raise FileNotFoundError(f"Run converter first: {templates_path} not found")

    with open(templates_path, encoding="utf-8") as f:
        templates = json.load(f)

    # Build keyword sets from expansion/reversal loops
    expansion_keywords: dict[str, list[str]] = {}
    reversal_keywords: dict[str, list[str]] = {}
    mechanism_keywords: dict[str, list[str]] = {}

    for t in templates:
        case_id = t["case_id"]
        # Extract meaningful keywords from loop steps
        exp_steps = t.get("expansion_loop", [])
        rev_steps = t.get("reversal_loop", [])
        mechs = t.get("mechanisms", [])

        expansion_keywords[case_id] = _extract_keywords(exp_steps)
        reversal_keywords[case_id] = _extract_keywords(rev_steps)
        mechanism_keywords[case_id] = [m.lower().replace(" ", "_") for m in mechs]

    # Aggregate by case_type
    type_keywords: dict[str, dict[str, list[str]]] = {}
    for t in templates:
        ct = t.get("case_type", "unknown")
        if ct not in type_keywords:
            type_keywords[ct] = {"expansion": [], "reversal": [], "mechanisms": []}
        type_keywords[ct]["expansion"].extend(expansion_keywords.get(t["case_id"], []))
        type_keywords[ct]["reversal"].extend(reversal_keywords.get(t["case_id"], []))
        type_keywords[ct]["mechanisms"].extend(mechanism_keywords.get(t["case_id"], []))

    baseline = {
        "generated_at": datetime.now().isoformat(),
        "total_templates": len(templates),
        "per_case": {
            t["case_id"]: {
                "case_type": t.get("case_type", ""),
                "expansion_keywords": expansion_keywords.get(t["case_id"], []),
                "reversal_keywords": reversal_keywords.get(t["case_id"], []),
                "mechanism_keywords": mechanism_keywords.get(t["case_id"], []),
            }
            for t in templates
        },
        "by_case_type": {
            ct: {
                "expansion_keywords": list(set(kw["expansion"]))[:30],
                "reversal_keywords": list(set(kw["reversal"]))[:30],
                "mechanism_keywords": list(set(kw["mechanisms"]))[:20],
            }
            for ct, kw in type_keywords.items()
        },
    }

    # Save
    baseline_path = CASELAB_TRAINING / "narrative_baseline.json"
    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)

    return {
        "templates": len(templates),
        "case_types": len(type_keywords),
        "total_expansion_keywords": sum(len(v) for v in expansion_keywords.values()),
        "total_reversal_keywords": sum(len(v) for v in reversal_keywords.values()),
    }


def _extract_keywords(steps: list[str]) -> list[str]:
    """Extract meaningful keywords from causal chain steps."""
    keywords: list[str] = []
    # Common structural terms to look for
    structural_terms = [
        "leverage", "margin", "liquidity", "credit", "spread", "volatility",
        "forced", "selling", "spiral", "panic", "run", "default", "crash",
        "bubble", "capex", "revenue", "growth", "concentration", "dominance",
        "lock-in", "platform", "network", "ecosystem", "supply", "demand",
        "inflation", "rate", "yield", "spread", "correlation", "breakdown",
        "contagion", "cascade", "feedback", "reflexivity", "momentum",
        "deposit", "withdrawal", "redemption", "liquidation", "collateral",
        "margin_call", "unrealized", "mark_to_market", "haircut", "downgrade",
    ]
    for step in steps:
        step_lower = step.lower()
        for term in structural_terms:
            if term in step_lower and term not in keywords:
                keywords.append(term)
    return keywords


# ── Run all bridges ──────────────────────────────────────────────────────

def run_all() -> dict[str, Any]:
    """Run all three bridge integrations."""
    results: dict[str, Any] = {}

    print("1. Enriching VariableMapper mapping rules...")
    results["mapping_rules"] = enrich_mapping_rules()
    print(f"   → {results['mapping_rules']}")

    print("2. Building regime calibration...")
    results["regime_calibration"] = build_regime_calibration()
    print(f"   → {results['regime_calibration']}")

    print("3. Building narrative baseline...")
    results["narrative_baseline"] = build_narrative_baseline()
    print(f"   → {results['narrative_baseline']}")

    return results


if __name__ == "__main__":
    results = run_all()
    print("\nAll bridges complete.")
    for k, v in results.items():
        print(f"  {k}: {v}")
