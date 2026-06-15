"""Daily CaseLab signal — match current System state to historical cases.

Reads the latest M/D/K/X proxy readings and structural state,
converts to S-A-L-V-P-tau, runs EnhancedSimilarityEngine,
and outputs a structured case-match report.

Usage:
    cd /Users/a1/System
    python3 scripts/caselab_daily_signal.py
    python3 scripts/caselab_daily_signal.py --json   # JSON output only
    python3 scripts/caselab_daily_signal.py --top 5   # top N cases

Output:
    Output/caselab/YYYY-MM-DD.json     (structured)
    Output/caselab/YYYY-MM-DD.md       (readable)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "Output" / "caselab"


def get_latest_state() -> dict:
    """Read latest M/D/K/X from proxy_readings and structural_state."""
    proxy_path = ROOT / "Data" / "structural_lab" / "processed" / "proxies" / "proxy_readings.parquet"
    state_path = ROOT / "Data" / "structural_lab" / "processed" / "state" / "structural_state.parquet"

    state = {
        "date": None,
        "M": None, "K": None, "D": None, "X": None,
        "sigma_t": None,
        "pattern": None,
        "leading_channel": None,
        "direction": None,
        "z_vector": None,
        "active_operators": [],
        "escalation": False,
    }

    # Proxy readings
    if proxy_path.exists():
        df = pd.read_parquet(proxy_path)
        latest_date = df["run_date"].max()
        latest = df[df["run_date"] == latest_date]
        state["date"] = str(latest_date)

        for _, row in latest.iterrows():
            name = row["proxy_name"]
            if name in ("M", "K", "D", "X"):
                state[name] = float(row["value"]) if pd.notna(row["value"]) else None
            if name == "M":  # direction from M proxy
                state["direction"] = str(row.get("direction", ""))

    # Structural state
    if state_path.exists():
        df2 = pd.read_parquet(state_path)
        # Find last non-NaN row
        for i in range(len(df2) - 1, -1, -1):
            row = df2.iloc[i]
            if pd.notna(row.get("sigma_t")):
                state["sigma_t"] = float(row["sigma_t"])
                state["pattern"] = str(row.get("pattern", ""))
                state["leading_channel"] = str(row.get("leading_channel", ""))
                state["escalation"] = bool(row.get("escalation", False))

                # z_vector
                zv = row.get("z_vector")
                if zv is not None:
                    try:
                        state["z_vector"] = [float(x) for x in zv]
                    except (TypeError, ValueError):
                        pass

                # Extract active operators from diagnostics
                diag = row.get("operator_diagnostics")
                if isinstance(diag, str):
                    try:
                        diag = json.loads(diag)
                    except json.JSONDecodeError:
                        diag = {}
                if isinstance(diag, dict):
                    state["active_operators"] = [
                        app.get("operator", "")
                        for app in diag.get("applications", [])
                        if app.get("operator")
                    ]
                break

    return state


def mdx_to_salvptau(state: dict) -> dict[str, float]:
    """Convert M/D/K/X proxy values to S-A-L-V-P-tau vector.

    Mapping logic:
      S (Stress)       ← K stress + abs(D) deterioration
      A (Asymmetry     ← abs(D) + sigma_t singularity pressure
      L (Leverage)     ← X (shadow leverage) + K
      V (Volatility)   ← sigma_t + K stress
      P (Positioning)  ← M macro + leading channel
      tau (Time)       ← D direction + escalation + operator time pressure
    """
    M = state.get("M") or 0.3
    K = state.get("K") or 0.3
    D = state.get("D") or 0.0
    X = state.get("X") or 0.3
    sigma = state.get("sigma_t") or 0.5

    d_abs = abs(D)

    # Base mapping
    vec = {
        "S": 0.3 * K + 0.3 * d_abs + 0.2 * sigma,
        "A": 0.3 * d_abs + 0.3 * sigma + 0.2 * X,
        "L": 0.3 * X + 0.3 * K + 0.2 * d_abs,
        "V": 0.4 * sigma + 0.3 * K,
        "P": 0.3 * M + 0.2 * K + 0.2 * X,
        "tau": 0.3 * M + 0.3 * d_abs + 0.2 * sigma,
    }

    # Operator-based adjustments
    operators = " ".join(state.get("active_operators", [])).upper()
    if "FUNDING_LIQUIDITY_SPIRAL" in operators:
        vec["S"] += 0.08
        vec["tau"] += 0.06
    if "COLLATERAL_LEVERAGE_CYCLE" in operators:
        vec["L"] += 0.08
        vec["A"] += 0.05
    if "NETWORK_CONCENTRATION" in operators:
        vec["P"] += 0.08
        vec["A"] += 0.04
    if "POLICY_DELAY" in operators:
        vec["tau"] += 0.08
    if "MARKET_LIQUIDITY_GAP" in operators:
        vec["S"] += 0.06
        vec["V"] += 0.05
    if "PROCyclical_LEVERAGE" in operators:
        vec["L"] += 0.06
    if "COMPRESSION_ERROR" in operators:
        vec["V"] -= 0.05  # compression = low vol
    if "INTERMEDIARY_CAPACITY" in operators:
        vec["L"] += 0.05
    if "CAPITAL_CONSTRAINT" in operators:
        vec["S"] += 0.05
    if "TRANCHING_COMPLEXITY" in operators:
        vec["A"] += 0.06

    # Escalation boost
    if state.get("escalation"):
        vec["S"] += 0.10
        vec["tau"] += 0.10

    # Clamp
    return {k: max(0.0, min(1.0, round(v, 3))) for k, v in vec.items()}


def derive_tags(state: dict) -> list[str]:
    """Derive tags from active operators and state."""
    tags: list[str] = []
    operators = " ".join(state.get("active_operators", [])).upper()

    op_tag_map = {
        "FUNDING_LIQUIDITY_SPIRAL": ["liquidity", "spiral", "funding"],
        "COLLATERAL_LEVERAGE_CYCLE": ["leverage", "collateral"],
        "MARKET_LIQUIDITY_GAP": ["liquidity", "market_microstructure"],
        "NETWORK_CONCENTRATION": ["concentration", "systemic"],
        "POLICY_DELAY": ["policy", "regulation"],
        "PROCyclical_LEVERAGE": ["leverage", "procyclical"],
        "COMPRESSION_ERROR": ["volatility", "compression"],
        "INTERMEDIARY_CAPACITY": ["intermediary", "credit"],
        "CAPITAL_CONSTRAINT": ["capital", "constraint"],
        "TRANCHING_COMPLEXITY": ["structured", "tranching"],
        "COLLATERAL_ANCHOR_GAP": ["collateral", "valuation"],
        "TRANCHE_VERIFIABILITY_GAP": ["visibility", "structured"],
    }

    for op_name, op_tags in op_tag_map.items():
        if op_name in operators:
            tags.extend(op_tags)

    # Pattern-based tags
    pattern = (state.get("pattern") or "").upper()
    if "STABLE" in pattern:
        tags.append("stable")
    if "CRISIS" in pattern:
        tags.append("crisis")
    if "TRANSITION" in pattern:
        tags.append("transition")

    return list(dict.fromkeys(tags))  # dedupe


def derive_event_text(state: dict) -> str:
    """Build a natural language description of current state for text matching."""
    parts: list[str] = []

    M = state.get("M") or 0
    K = state.get("K") or 0
    D = state.get("D") or 0
    X = state.get("X") or 0
    pattern = state.get("pattern", "")
    direction = state.get("direction", "")

    # State description
    if K > 0.6:
        parts.append("High structural stress in the system.")
    elif K > 0.3:
        parts.append("Moderate structural stress with elevated vigilance.")
    else:
        parts.append("Low structural stress, system appears calm.")

    if D < -0.3:
        parts.append("Deteriorating conditions with negative D signal.")
    if M > 0.5:
        parts.append("Macro stress elevated with policy pressure.")
    if X > 0.4:
        parts.append("Cross-market stress and shadow leverage building.")

    parts.append(f"Pattern: {pattern}. Leading channel: {state.get('leading_channel', 'N/A')}.")

    # Operator descriptions
    operators = state.get("active_operators", [])
    if operators:
        op_descriptions = []
        for op in operators:
            op_lower = op.lower()
            if "funding_liquidity" in op_lower:
                op_descriptions.append("funding liquidity spiral active")
            elif "collateral_leverage" in op_lower:
                op_descriptions.append("collateral leverage cycle")
            elif "market_liquidity" in op_lower:
                op_descriptions.append("market liquidity gap")
            elif "network_concentration" in op_lower:
                op_descriptions.append("network concentration risk")
            elif "policy_delay" in op_lower:
                op_descriptions.append("policy delay creating time pressure")
            elif "procyclical" in op_lower:
                op_descriptions.append("procyclical leverage amplification")
            elif "compression" in op_lower:
                op_descriptions.append("volatility compression masking risk")
            elif "intermediary" in op_lower:
                op_descriptions.append("intermediary capacity constraint")
            elif "capital_constraint" in op_lower:
                op_descriptions.append("capital constraint")
            elif "tranching" in op_lower:
                op_descriptions.append("structured product complexity")
            elif "collateral_anchor" in op_lower:
                op_descriptions.append("collateral anchor valuation gap")
        if op_descriptions:
            parts.append("Active mechanisms: " + ", ".join(op_descriptions) + ".")

    if state.get("escalation"):
        parts.append("ESCALATION flagged — conditions worsening.")

    return " ".join(parts)


def run_signal(top_k: int = 5, json_only: bool = False) -> dict:
    """Run the daily CaseLab signal and return results."""
    sys.path.insert(0, str(ROOT / "Workbench" / "src"))

    from nlp.caselab.enhanced_similarity import EnhancedSimilarityEngine

    # 1. Get current state
    state = get_latest_state()

    # 2. Convert to S-A-L-V-P-tau
    vec = mdx_to_salvptau(state)

    # 3. Derive tags and text
    tags = derive_tags(state)
    event_text = derive_event_text(state)

    # 4. Run similarity
    engine = EnhancedSimilarityEngine(ROOT)
    results = engine.find_similar(
        variable_vector=vec,
        tags=tags,
        event_text=event_text,
        top_k=top_k,
    )

    # 5. Build output
    output = {
        "timestamp": datetime.now(UTC).isoformat(),
        "system_state": {
            "date": state.get("date"),
            "M": state.get("M"),
            "K": state.get("K"),
            "D": state.get("D"),
            "X": state.get("X"),
            "sigma_t": state.get("sigma_t"),
            "pattern": state.get("pattern"),
            "leading_channel": state.get("leading_channel"),
            "direction": state.get("direction"),
            "escalation": state.get("escalation"),
            "active_operators": state.get("active_operators", []),
        },
        "derived_vector": vec,
        "derived_tags": tags,
        "event_text": event_text[:500],
        "matches": [
            {
                "rank": i + 1,
                "case_id": r.case_id,
                "case_name": r.case_name,
                "score": r.score,
                "var_score": r.var_score,
                "tag_score": r.tag_score,
                "text_score": r.text_score,
                "shared_tags": r.shared_tags,
                "shared_concepts": [{"concept": c, "freq": s} for c, s in r.shared_concepts],
                "narrative": r.narrative_summary[:200],
            }
            for i, r in enumerate(results)
        ],
    }

    # 6. Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    json_path = OUTPUT_DIR / f"{today}.json"
    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not json_only:
        md_path = OUTPUT_DIR / f"{today}.md"
        md_path.write_text(_format_markdown(output), encoding="utf-8")
        print(f"Output: {md_path}")

    return output


def _format_markdown(output: dict) -> str:
    """Format output as readable markdown."""
    s = output["system_state"]
    vec = output["derived_vector"]
    lines = [
        f"# CaseLab Daily Signal — {output['timestamp'][:10]}",
        "",
        f"## System State",
        f"- **Date:** {s['date']}",
        f"- **M/D/K/X:** {s['M']:.3f} / {s['D']:.3f} / {s['K']:.3f} / {s['X']:.3f}",
        f"- **σ(t):** {s['sigma_t']:.3f}" if s.get("sigma_t") else "- **σ(t):** N/A",
        f"- **Pattern:** {s['pattern']}",
        f"- **Leading channel:** {s['leading_channel']}",
        f"- **Direction:** {s['direction']}",
        f"- **Escalation:** {'YES' if s.get('escalation') else 'No'}",
        "",
        f"## Derived S-A-L-V-P-tau",
        f"```",
        f"S={vec['S']:.3f}  A={vec['A']:.3f}  L={vec['L']:.3f}  V={vec['V']:.3f}  P={vec['P']:.3f}  τ={vec['tau']:.3f}",
        f"```",
        "",
        f"## Tags",
        f"`{'` `'.join(output['derived_tags'])}`",
        "",
        f"## Event Description",
        f"> {output['event_text'][:300]}",
        "",
        f"## Top Matches",
        "",
    ]

    for m in output["matches"]:
        lines.append(f"### {m['rank']}. {m['case_name']} (score={m['score']:.3f})")
        lines.append(f"- var={m['var_score']:.3f}  tag={m['tag_score']:.3f}  text={m['text_score']:.3f}")
        if m["shared_tags"]:
            lines.append(f"- tags: {', '.join(m['shared_tags'])}")
        if m["shared_concepts"]:
            concepts = ", ".join(f"{c['concept']}({c['freq']:.0f})" for c in m["shared_concepts"][:5])
            lines.append(f"- concepts: {concepts}")
        if m["narrative"]:
            lines.append(f"- narrative: {m['narrative'][:150]}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Daily CaseLab signal")
    parser.add_argument("--json", action="store_true", help="JSON output only")
    parser.add_argument("--top", type=int, default=5, help="Top N matches")
    args = parser.parse_args()

    output = run_signal(top_k=args.top, json_only=args.json)

    # Print summary
    s = output["system_state"]
    print(f"\n=== CaseLab Daily Signal — {s['date']} ===")
    print(f"M/D/K/X: {s['M']:.3f} / {s['D']:.3f} / {s['K']:.3f} / {s['X']:.3f}")
    print(f"Pattern: {s['pattern']}  Leading: {s['leading_channel']}  Direction: {s['direction']}")
    print()

    vec = output["derived_vector"]
    print(f"S-A-L-V-P-tau: S={vec['S']:.3f} A={vec['A']:.3f} L={vec['L']:.3f} V={vec['V']:.3f} P={vec['P']:.3f} τ={vec['tau']:.3f}")
    print(f"Tags: {output['derived_tags']}")
    print()

    for m in output["matches"]:
        c = ", ".join(f"{c['concept']}" for c in m["shared_concepts"][:3])
        print(f"  {m['rank']}. {m['case_name'][:50]:<50} {m['score']:.3f}  [{c}]")


if __name__ == "__main__":
    main()
