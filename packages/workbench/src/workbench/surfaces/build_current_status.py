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
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import (
    ROOT,
    current_dir,
    ensure_dir,
    load_json,
    surface_dir,
    write_json,
)

JUDGMENT_PATH = surface_dir("judgment") / "latest.json"
PROMOTION_GATE_PATH = surface_dir("judgment") / "promotion_gate.json"
INDEX_PATH = ROOT / "Data" / "system_index" / "latest.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
HMM_AUDIT_PATH = ROOT / "Output" / "state" / "hmm_stability" / "hmm_stability_audit.json"
CASELAB_DIR = ROOT / "Output" / "state" / "caselab"
OUTPUT_DIR = current_dir()

_PATH_KEYS = (
    "judgment",
    "promotion_gate",
    "index",
    "k_gate",
    "x_gate",
    "hmm_audit",
    "caselab",
    "output",
)


def _default_paths() -> dict[str, Path]:
    """Return legacy-compatible input/output path bindings."""
    return {
        "judgment": JUDGMENT_PATH,
        "promotion_gate": PROMOTION_GATE_PATH,
        "index": INDEX_PATH,
        "k_gate": K_GATE_PATH,
        "x_gate": X_GATE_PATH,
        "hmm_audit": HMM_AUDIT_PATH,
        "caselab": CASELAB_DIR,
        "output": OUTPUT_DIR,
    }


def _resolve_paths(paths: Mapping[str, Path] | None = None) -> dict[str, Path]:
    """Resolve explicit generation paths without changing no-arg behavior."""
    resolved = _default_paths()
    if paths is None:
        return resolved
    unknown = sorted(set(paths) - set(_PATH_KEYS))
    if unknown:
        raise ValueError(f"unknown current-status path keys: {', '.join(unknown)}")
    resolved.update({key: Path(value) for key, value in paths.items()})
    return resolved


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def gather_status(paths: Mapping[str, Path] | None = None) -> dict[str, Any]:
    """Gather current system status."""
    resolved = _resolve_paths(paths)
    now = datetime.now(UTC).isoformat()
    judgment = load_json(resolved["judgment"])
    date_str = str((judgment or {}).get("as_of") or now)[:10]
    promotion_gate = load_json(resolved["promotion_gate"])
    _ = load_json(resolved["index"])
    k_gate = load_json(resolved["k_gate"])
    x_gate = load_json(resolved["x_gate"])
    hmm_audit = load_json(resolved["hmm_audit"])
    caselab = load_json(resolved["caselab"] / f"{date_str}.json")

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


def write_status(
    status: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    """Write status.json to an explicit current-output surface."""
    target_dir = output_dir or OUTPUT_DIR
    ensure_dir(target_dir)
    status_path = target_dir / "status.json"
    write_json(status_path, status)
    return status_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Output/current/status.json.")
    parser.add_argument("--json", action="store_true", help="Print status JSON to stdout.")
    args = parser.parse_args()

    status = gather_status()
    status_path = write_status(status)

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
