#!/usr/bin/env python3
"""Build evidence_grade_report.json — structured evidence chain transparency.

This script reads all system inputs and produces a machine-readable
explanation of why the evidence grade is D/C/B/A, with per-contributor
details, blocker IDs, and paper_support status.

Usage:
    python3 scripts/commands/weekly/build_evidence_grade_report.py
    python3 scripts/commands/weekly/build_evidence_grade_report.py --json

Output:
    Output/current/evidence_grade_report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts._runtime_io import (
    ROOT,
    current_dir,
    ensure_dir,
    load_json,
    utc_now,
    write_json,
)

JUDGMENT_PATH = ROOT / "Output" / "judgment" / "latest.json"
PROMOTION_GATE_PATH = ROOT / "Output" / "judgment" / "promotion_gate.json"
TRADE_DECISION_PATH = ROOT / "Output" / "trade_decision" / "latest.json"
K_GATE_PATH = ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"
X_GATE_PATH = ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"
HMM_AUDIT_PATH = ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"
FRESHNESS_PATH = ROOT / "Output" / "quality" / "freshness_report.json"
PAPER_MANIFEST_PATH = ROOT / "Data" / "paper_world_model" / "manifest.json"
HARVESTER_CATALOG_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json"
DATA_REQUEST_PATH = ROOT / "governance" / "data_request_registry.yaml"
OUTPUT_PATH = current_dir() / "evidence_grade_report.json"

CONTRIBUTOR_ARTIFACTS: dict[str, list[str]] = {
    "paper_world_model": [str(PAPER_MANIFEST_PATH.relative_to(ROOT))],
    "hmm_stability": [str(HMM_AUDIT_PATH.relative_to(ROOT))],
    "k_measurement_gate": [str(K_GATE_PATH.relative_to(ROOT))],
    "x_measurement_gate": [str(X_GATE_PATH.relative_to(ROOT))],
    "data_freshness": [str(FRESHNESS_PATH.relative_to(ROOT))],
    "harvester_evidence": [str(HARVESTER_CATALOG_PATH.relative_to(ROOT))],
}


def _load_yaml_safe(path: Path) -> dict[str, Any]:
    """Load YAML safely, return empty dict on failure."""
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _build_contributors(
    judgment: dict | None,
    promotion_gate: dict | None,
    k_gate: dict | None,
    x_gate: dict | None,
    hmm_audit: dict | None,
    freshness: dict | None,
    harvester_catalog: dict | None,
) -> list[dict[str, Any]]:
    """Build list of evidence contributors with weights."""
    contributors: list[dict[str, Any]] = []

    # Paper world model — foundational evidence source
    paper_manifest = load_json(PAPER_MANIFEST_PATH)
    paper_entry: dict[str, Any] = {
        "source": "paper_world_model",
        "weight": 0.25,
        "admitted": bool(paper_manifest),
        "status": "available" if paper_manifest else "missing",
    }
    if paper_manifest:
        paper_entry["details"] = {
            "synced_at": paper_manifest.get("synced_at"),
            "record_counts": paper_manifest.get("record_counts"),
        }
    contributors.append(paper_entry)

    # HMM stability — regime detection confidence
    hmm_entry: dict[str, Any] = {
        "source": "hmm_stability",
        "weight": 0.20,
        "admitted": bool(hmm_audit),
        "status": hmm_audit.get("stability_grade", "UNKNOWN") if hmm_audit else "missing",
    }
    if hmm_audit:
        hmm_entry["details"] = {
            "stability_grade": hmm_audit.get("stability_grade"),
            "regime_count": hmm_audit.get("regime_count"),
        }
    contributors.append(hmm_entry)

    # K gate — cross-asset curvature
    k_entry: dict[str, Any] = {
        "source": "k_measurement_gate",
        "weight": 0.15,
        "admitted": bool(k_gate),
        "status": k_gate.get("gate_verdict", k_gate.get("verdict", "UNKNOWN")) if k_gate else "missing",
    }
    if k_gate:
        k_entry["details"] = {
            "verdict": k_gate.get("gate_verdict", k_gate.get("verdict")),
            "role": k_gate.get("current_role", "diagnostic_rebuild"),
        }
    contributors.append(k_entry)

    # X gate — aggregate stress
    x_entry: dict[str, Any] = {
        "source": "x_measurement_gate",
        "weight": 0.15,
        "admitted": bool(x_gate),
        "status": x_gate.get("gate_verdict", x_gate.get("verdict", "UNKNOWN")) if x_gate else "missing",
    }
    if x_gate:
        x_entry["details"] = {
            "verdict": x_gate.get("gate_verdict", x_gate.get("verdict")),
            "daily_trigger_allowed": False,
        }
    contributors.append(x_entry)

    # Freshness — data recency
    fresh_entry: dict[str, Any] = {
        "source": "data_freshness",
        "weight": 0.15,
        "admitted": bool(freshness),
        "status": freshness.get("verdict", "UNKNOWN") if freshness else "missing",
    }
    if freshness:
        fresh_entry["details"] = {
            "verdict": freshness.get("verdict"),
            "stale_count": len(freshness.get("stale_artifacts", [])),
        }
    contributors.append(fresh_entry)

    # Harvester evidence — data provenance
    harv_entry: dict[str, Any] = {
        "source": "harvester_evidence",
        "weight": 0.10,
        "admitted": bool(harvester_catalog),
        "status": "available" if harvester_catalog else "missing",
    }
    if harvester_catalog:
        datasets = harvester_catalog.get("datasets", [])
        harv_entry["details"] = {
            "release_id": harvester_catalog.get("release_id"),
            "dataset_count": len(datasets),
            "datasets": [d.get("dataset_id") for d in datasets],
        }
    contributors.append(harv_entry)

    return contributors


def _build_contributor_drill_down(
    contributors: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-contributor drill-down for evidence grade transparency."""
    drill_down: list[dict[str, Any]] = []
    for contributor in contributors:
        source = contributor["source"]
        related = [b for b in blockers if source in b.get("source", "") or source in b.get("code", "")]
        simulated = []
        for item in contributors:
            if item["source"] == source:
                simulated.append({**item, "admitted": True, "status": "available"})
            else:
                simulated.append(item)
        grade_if_admitted = _compute_grade(simulated, blockers)

        actions: list[str] = []
        if not contributor["admitted"]:
            actions.append(f"Restore artifact for {source}")
        if contributor["status"] in ("WEAK", "FAIL", "UNKNOWN", "missing"):
            actions.append(f"Improve {source} status from {contributor['status']}")

        drill_down.append(
            {
                "source": source,
                "weight": contributor["weight"],
                "admitted": contributor["admitted"],
                "status": contributor["status"],
                "artifact_paths": CONTRIBUTOR_ARTIFACTS.get(source, []),
                "details": contributor.get("details", {}),
                "related_blockers": related,
                "grade_if_admitted": grade_if_admitted,
                "upgrade_actions": actions,
            }
        )
    return drill_down


def _build_blockers(
    judgment: dict | None,
    promotion_gate: dict | None,
    trade_decision: dict | None,
    contributors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build machine-readable blocker list."""
    blockers: list[dict[str, Any]] = []

    # Promotion gate blockers
    if promotion_gate:
        pg_status = promotion_gate.get("overall_status", "UNKNOWN")
        if pg_status == "BLOCKED":
            for gate in promotion_gate.get("blocked_gates", []):
                blockers.append({
                    "code": f"promotion_gate_{gate}",
                    "category": "promotion_gate",
                    "message": f"Promotion gate blocked: {gate}",
                    "source": "promotion_gate.json",
                })

    # Trade decision blockers
    if trade_decision:
        td_grade = trade_decision.get("evidence_grade", "D")
        if td_grade in ("D",):
            blockers.append({
                "code": "evidence_grade_d",
                "category": "evidence_quality",
                "message": "Evidence grade is D — insufficient approved paper sources or gate failures",
                "source": "trade_decision/latest.json",
            })

    # Paper support missing
    if trade_decision:
        paper_sources = trade_decision.get("paper_sources", {})
        approved = paper_sources.get("approved_support", [])
        background = paper_sources.get("background_context", [])
        if not approved:
            blockers.append({
                "code": "paper_support_missing",
                "category": "paper_support",
                "message": f"No approved paper sources ({len(background)} background only). "
                           "Need approved case reviews to lift evidence grade.",
                "source": "trade_decision/latest.json",
                "detail": {
                    "approved_count": len(approved),
                    "background_count": len(background),
                },
            })

    # Data request blockers from registry
    data_requests = _load_yaml_safe(DATA_REQUEST_PATH)
    for req in data_requests.get("requests", []):
        if req.get("status") in ("pending", "sourcing", "transitional"):
            if req.get("core_judgment_priority", "").startswith("blocked"):
                blockers.append({
                    "code": f"data_request_{req['request_id']}",
                    "category": "data_availability",
                    "message": f"Data request {req['request_id']} ({req.get('priority', '?')} priority): {req.get('needed_for', '')}",
                    "source": "governance/data_request_registry.yaml",
                    "detail": {
                        "request_id": req["request_id"],
                        "status": req["status"],
                        "priority": req.get("priority"),
                    },
                })

    # Contributor-level blockers
    for c in contributors:
        if c["status"] in ("missing", "WEAK", "FAIL", "UNKNOWN"):
            blockers.append({
                "code": f"contributor_{c['source']}_{c['status'].lower()}",
                "category": "contributor_quality",
                "message": f"Evidence contributor {c['source']} status: {c['status']}",
                "source": c["source"],
            })

    return blockers


def _compute_grade(contributors: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> str:
    """Compute evidence grade from contributors and blockers.

    Grade heuristic:
    - A: all contributors admitted, weight sum >= 0.9, no blockers
    - B: all key contributors (weight >= 0.15) admitted, weight sum >= 0.7, <= 1 minor blocker
    - C: most contributors admitted, weight sum >= 0.5, data-driven blockers only
    - D: otherwise
    """
    admitted_weight = sum(c["weight"] for c in contributors if c["admitted"])
    key_missing = [c for c in contributors if c["weight"] >= 0.15 and not c["admitted"]]
    critical_blockers = [b for b in blockers if b["category"] in ("promotion_gate", "evidence_quality")]

    if admitted_weight >= 0.9 and not blockers:
        return "A"
    elif admitted_weight >= 0.7 and not key_missing and len(critical_blockers) <= 1:
        return "B"
    elif admitted_weight >= 0.5:
        return "C"
    else:
        return "D"


def _build_paper_support_status(trade_decision: dict | None) -> dict[str, Any]:
    """Build paper_support status mapping."""
    if not trade_decision:
        return {"status": "unavailable", "approved": 0, "background": 0, "mappings": []}

    paper_sources = trade_decision.get("paper_sources", {})
    approved = paper_sources.get("approved_support", [])
    background = paper_sources.get("background_context", [])

    mappings = []
    for s in approved:
        mappings.append({
            "source_file": s.get("source_file", ""),
            "content_id": s.get("content_id", ""),
            "role": "approved_support",
            "relevance": s.get("relevance", "unknown"),
        })
    for s in background:
        mappings.append({
            "source_file": s.get("source_file", ""),
            "content_id": s.get("content_id", ""),
            "role": "background_context",
            "relevance": s.get("relevance", "unknown"),
        })

    return {
        "status": "partial" if approved else "missing",
        "approved": len(approved),
        "background": len(background),
        "mappings": mappings,
    }


def build_evidence_grade_report() -> dict[str, Any]:
    """Build the complete evidence grade report."""
    now = utc_now()

    # Load all inputs
    judgment = load_json(JUDGMENT_PATH)
    promotion_gate = load_json(PROMOTION_GATE_PATH)
    trade_decision = load_json(TRADE_DECISION_PATH)
    k_gate = load_json(K_GATE_PATH)
    x_gate = load_json(X_GATE_PATH)
    hmm_audit = load_json(HMM_AUDIT_PATH)
    freshness = load_json(FRESHNESS_PATH)
    harvester_catalog = load_json(HARVESTER_CATALOG_PATH)

    # Build contributors
    contributors = _build_contributors(
        judgment, promotion_gate, k_gate, x_gate, hmm_audit, freshness, harvester_catalog
    )

    # Build blockers
    blockers = _build_blockers(judgment, promotion_gate, trade_decision, contributors)

    # Compute grade
    computed_grade = _compute_grade(contributors, blockers)
    trade_grade = trade_decision.get("evidence_grade", "D") if trade_decision else "D"

    # Paper support status
    paper_support = _build_paper_support_status(trade_decision)

    return {
        "schema_version": "evidence_grade_report.v1",
        "generated_at": now.isoformat(),
        "grade": computed_grade,
        "trade_decision_grade": trade_grade,
        "grade_match": computed_grade == trade_grade,
        "admitted_weight": round(sum(c["weight"] for c in contributors if c["admitted"]), 2),
        "total_weight": round(sum(c["weight"] for c in contributors), 2),
        "contributors": contributors,
        "contributor_drill_down": _build_contributor_drill_down(contributors, blockers),
        "blockers": blockers,
        "paper_support_status": paper_support,
        "what_would_upgrade": _build_upgrade_path(contributors, blockers, computed_grade),
    }


def _build_upgrade_path(
    contributors: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    current_grade: str,
) -> list[dict[str, Any]]:
    """Build list of actions that would upgrade the evidence grade."""
    actions: list[dict[str, Any]] = []

    if current_grade == "D":
        # Need to fix critical issues
        for b in blockers:
            if b["category"] in ("evidence_quality", "promotion_gate"):
                actions.append({
                    "action": f"Resolve blocker: {b['code']}",
                    "detail": b["message"],
                    "impact": "unblock_decision",
                })

        # Need admitted contributors
        missing = [c for c in contributors if not c["admitted"] and c["weight"] >= 0.10]
        for c in missing:
            actions.append({
                "action": f"Admit evidence source: {c['source']}",
                "detail": f"Contributor {c['source']} is missing or not admitted (weight: {c['weight']})",
                "impact": "improve_grade",
            })

        # Need paper support
        paper_blockers = [b for b in blockers if b["category"] == "paper_support"]
        if paper_blockers:
            actions.append({
                "action": "Review and approve paper cases",
                "detail": "Approved paper sources are required for evidence grade C or above",
                "impact": "enable_grade_c",
            })

    elif current_grade == "C":
        actions.append({
            "action": "Improve contributor quality",
            "detail": "Move key contributors from weak to adequate status",
            "impact": "enable_grade_b",
        })
        actions.append({
            "action": "Add second approved paper source",
            "detail": "Grade B requires >= 2 approved paper sources",
            "impact": "enable_grade_b",
        })

    elif current_grade == "B":
        # If admitted weight is already 1.0, grade is constrained by trade decision
        # (promotion gate / paper review), not by data quality
        admitted_w = sum(c["weight"] for c in contributors if c["admitted"])
        if admitted_w >= 0.9:
            actions.append({
                "action": "Resolve promotion gate and paper support blockers",
                "detail": "Structural evidence quality is B+ but trade decision remains D due to "
                         "promotion gate constraints and unapproved paper sources. "
                         "Resolve those to unlock higher trade evidence grade.",
                "impact": "unlock_trade_grade",
            })
        else:
            actions.append({
                "action": "Achieve full contributor admission",
                "detail": "Grade A requires all contributors admitted (weight >= 0.9)",
                "impact": "enable_grade_a",
            })

    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description="Build evidence grade report.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = build_evidence_grade_report()
    ensure_dir(OUTPUT_PATH.parent)
    write_json(OUTPUT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Evidence Grade Report: {OUTPUT_PATH}")
        print(f"  Grade: {report['grade']} (trade decision: {report['trade_decision_grade']})")
        print(f"  Match: {report['grade_match']}")
        print(f"  Admitted weight: {report['admitted_weight']}/{report['total_weight']}")
        print(f"  Blockers: {len(report['blockers'])}")
        print(f"  Paper support: {report['paper_support_status']['status']} "
              f"({report['paper_support_status']['approved']} approved, "
              f"{report['paper_support_status']['background']} background)")
        if report["what_would_upgrade"]:
            print(f"  Upgrade path: {len(report['what_would_upgrade'])} actions")


if __name__ == "__main__":
    main()
