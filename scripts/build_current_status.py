#!/usr/bin/env python3
"""Build Output/current/status.json — daily system status snapshot.

Reads judgment card, promotion gate, and gate artifacts. Separate from
build_next_actions.py so status.json refreshes daily while NEXT_ACTIONS.md
can remain weekly.

Usage:
    python3 scripts/build_current_status.py
    python3 scripts/build_current_status.py --json

Output:
    Output/current/status.json
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from scripts._runtime_io import ROOT, current_dir, ensure_dir, load_json, surface_dir

JUDGMENT_PATH = surface_dir("judgment") / "latest.json"
PROMOTION_GATE_PATH = surface_dir("judgment") / "promotion_gate.json"
INDEX_PATH = ROOT / "Data" / "system_index" / "latest.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
HMM_AUDIT_PATH = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
CASELAB_DIR = ROOT / "Output" / "caselab"
OUTPUT_DIR = current_dir()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def gather_status() -> dict[str, Any]:
    """Gather current system status."""
    now = datetime.now(UTC).isoformat()
    judgment = load_json(JUDGMENT_PATH)
    date_str = str((judgment or {}).get("as_of") or now)[:10]
    promotion_gate = load_json(PROMOTION_GATE_PATH)
    _ = load_json(INDEX_PATH)
    k_gate = load_json(K_GATE_PATH)
    x_gate = load_json(X_GATE_PATH)
    hmm_audit = load_json(HMM_AUDIT_PATH)
    caselab = load_json(CASELAB_DIR / f"{date_str}.json")

    return {
        "generated_at": now,
        "date": date_str,
        "judgment": {
            "decision": (judgment or {}).get("decision"),
            "confidence": ((judgment or {}).get("confidence") or {}).get("level"),
            "claim_ceiling": (judgment or {}).get("claim_ceiling"),
            "judgment_id": (judgment or {}).get("judgment_id"),
            "claim_ids": (judgment or {}).get("claim_ids", []),
            "supporting_claim_ids": (judgment or {}).get("supporting_claim_ids", []),
            "conflicting_claim_ids": (judgment or {}).get("conflicting_claim_ids", []),
            "research_only_claim_ids": (judgment or {}).get("research_only_claim_ids", []),
            "lineage_complete": bool(
                isinstance((judgment or {}).get("canonical_chain"), dict)
                and isinstance(((judgment or {}).get("canonical_chain") or {}).get("judgment"), dict)
            ),
        },
        "promotion_gate": {
            "status": (promotion_gate or {}).get("overall_status"),
            "blocked_gates": (promotion_gate or {}).get("blocked_gates", []),
            "watch_gates": (promotion_gate or {}).get("watch_gates", []),
            "blocking_reasons": (promotion_gate or {}).get("blocking_reasons", []),
            "watch_reasons": (promotion_gate or {}).get("watch_reasons", []),
            "forbidden_language": (promotion_gate or {}).get("forbidden_language", []),
            "allowed_language": (promotion_gate or {}).get("allowed_language", []),
            "claim_ceiling": (promotion_gate or {}).get("claim_ceiling"),
            "epistemic_authority": (promotion_gate or {}).get("epistemic_authority", "DIAGNOSTIC_ONLY"),
        },
        "signals": {
            "k_gate": {
                "verdict": (k_gate or {}).get("gate_verdict"),
                "current_role": "diagnostic_rebuild",
            },
            "x_gate": {
                "verdict": (x_gate or {}).get("gate_verdict"),
                "background_allowed": (x_gate or {}).get("usage", {}).get("usable_as_background", False),
                "daily_trigger_allowed": False,
            },
            "hmm": {
                "stability_grade": (hmm_audit or {}).get("stability_grade"),
                "sample_days": (hmm_audit or {}).get("sample_days"),
            },
            "caselab": {
                "top_score": ((caselab or {}).get("match_quality") or {}).get("top_score"),
                "label": ((caselab or {}).get("match_quality") or {}).get("label"),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Output/current/status.json.")
    parser.add_argument("--json", action="store_true", help="Print status JSON to stdout.")
    args = parser.parse_args()

    status = gather_status()
    ensure_dir(OUTPUT_DIR)

    status_path = OUTPUT_DIR / "status.json"
    status_path.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        print(f"Status: {status_path}")
        print("\nCurrent state:")
        print(f"  Decision: {status['judgment'].get('decision')}")
        print(f"  Confidence: {status['judgment'].get('confidence')}")
        print(f"  Promotion gate: {status['promotion_gate'].get('status')}")


if __name__ == "__main__":
    main()
