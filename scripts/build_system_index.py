#!/usr/bin/env python3
"""Build system index — unified fact source for all consumers.

This script builds Data/system_index/latest.json which is the ONLY
source of truth for "what is the current state of the system".

All consumers (CLI, dashboard, README, agents) should read this file
instead of scanning directories independently.

Usage:
    python3 scripts/build_system_index.py
    python3 scripts/build_system_index.py --json

Output:
    Data/system_index/latest.json
    Data/system_index/README.md
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scripts._runtime_io import ROOT, ensure_dir, load_json

OUTPUT_DIR = ROOT / "Output"
DATA_DIR = ROOT / "Data"
INDEX_DIR = DATA_DIR / "system_index"
INDEX_PATH = INDEX_DIR / "latest.json"


def check_path(path: Path) -> dict:
    """Check if path exists and get metadata."""
    if not path.exists():
        return {"exists": False, "path": str(path)}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
    }


def build_index() -> dict:
    """Build the complete system index."""
    now = datetime.now(UTC).isoformat()

    # Core outputs
    current_output = check_path(OUTPUT_DIR / "current" / "framework_output.json")
    readme_first = check_path(OUTPUT_DIR / "current" / "00_READ_ME_FIRST.md")
    next_actions = check_path(OUTPUT_DIR / "current" / "NEXT_ACTIONS.md")
    status_json = check_path(OUTPUT_DIR / "current" / "status.json")

    # Judgment chain
    judgment_latest = check_path(OUTPUT_DIR / "judgment" / "latest.json")
    judgment_md = check_path(OUTPUT_DIR / "judgment" / "latest.md")
    promotion_gate = check_path(OUTPUT_DIR / "judgment" / "promotion_gate.json")
    calibration_report = check_path(OUTPUT_DIR / "judgment" / "calibration_report.json")

    # Signal sources
    hmm_latest = check_path(OUTPUT_DIR / "ml_signals" / "latest" / "regime_hmm.json")
    hmm_stability = check_path(OUTPUT_DIR / "hmm_stability" / "hmm_stability_audit.json")
    caselab_signal = check_path(OUTPUT_DIR / "caselab" / f"{datetime.now(UTC).strftime('%Y-%m-%d')}.json")
    k_gate = check_path(OUTPUT_DIR / "k_measurement" / "k_measurement_gate.json")
    x_gate = check_path(OUTPUT_DIR / "x_measurement" / "x_measurement_gate.json")

    # Structural replay
    replay_latest = None
    replay_dirs = sorted(OUTPUT_DIR.glob("deformation_runs/run_*"), reverse=True)
    if replay_dirs:
        replay_latest = check_path(replay_dirs[0] / "framework_output.json")

    # Learning hub
    # The canonical learning summary file is comprehensive_summary.json (the
    # freshness_validator monitors this same path). The earlier learning_summary.json
    # reference was a stale name that never existed -> false MISSING. See WB-A3.
    learning_summary = check_path(OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json")
    learning_events_dir = OUTPUT_DIR / "system_learning" / "events"
    calibration_events = list(learning_events_dir.glob("judgment_calibration_*.jsonl")) if learning_events_dir.exists() else []
    trade_calibration = check_path(OUTPUT_DIR / "system_learning" / "latest" / "trade_decision_calibration_summary.json")
    comprehensive_summary = check_path(OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json")

    # Freshness report
    freshness_report = load_json(OUTPUT_DIR / "quality" / "freshness_report.json")
    freshness_verdict = freshness_report.get("verdict", "UNKNOWN") if freshness_report else "UNKNOWN"
    stale_artifacts = freshness_report.get("stale_artifacts", []) if freshness_report else []

    # Harvester
    harvester_latest = check_path(DATA_DIR / "harvester" / "exports" / "latest" / "catalog.json")

    # Build judgment summary
    judgment_data = load_json(OUTPUT_DIR / "judgment" / "latest.json")
    judgment_summary = None
    if judgment_data:
        judgment_summary = {
            "decision": judgment_data.get("decision"),
            "confidence": (judgment_data.get("confidence") or {}).get("level"),
            "claim_ceiling": judgment_data.get("claim_ceiling"),
            "as_of": judgment_data.get("as_of"),
        }

    # Build promotion gate summary
    gate_data = load_json(OUTPUT_DIR / "judgment" / "promotion_gate.json")
    gate_summary = None
    if gate_data:
        gate_summary = {
            "overall_status": gate_data.get("overall_status"),
            "claim_ceiling": gate_data.get("claim_ceiling"),
            "blocked_gates": gate_data.get("blocked_gates", []),
            "watch_gates": gate_data.get("watch_gates", []),
            "blocking_reasons": gate_data.get("blocking_reasons", []),
            "watch_reasons": gate_data.get("watch_reasons", []),
            "forbidden_language": gate_data.get("forbidden_language", []),
        }

    # Build HMM summary (includes stability from audit)
    hmm_data = load_json(OUTPUT_DIR / "ml_signals" / "latest" / "regime_hmm.json")
    hmm_audit_data = load_json(OUTPUT_DIR / "hmm_stability" / "hmm_stability_audit.json")
    hmm_summary = None
    if hmm_data:
        regime = hmm_data.get("regime", {})
        hmm_summary = {
            "current_regime": regime.get("current"),
            "probability": regime.get("current_probability"),
            "stability_grade": hmm_audit_data.get("stability_grade") if hmm_audit_data else None,
            "source": "latest",
        }

    # Build K/X gate summaries
    k_gate_data = load_json(OUTPUT_DIR / "k_measurement" / "k_measurement_gate.json")
    k_summary = None
    if k_gate_data:
        k_summary = {
            "verdict": k_gate_data.get("gate_verdict"),
            "current_role": "diagnostic_rebuild",
        }

    x_gate_data = load_json(OUTPUT_DIR / "x_measurement" / "x_measurement_gate.json")
    x_summary = None
    if x_gate_data:
        x_summary = {
            "verdict": x_gate_data.get("gate_verdict"),
            "daily_trigger_allowed": False,
            "background_allowed": x_gate_data.get("usage", {}).get("usable_as_background", False),
        }

    # Trade decision
    trade_decision = check_path(OUTPUT_DIR / "trade_decision" / "latest.json")
    trade_decision_data = load_json(OUTPUT_DIR / "trade_decision" / "latest.json")
    trade_decision_summary = None
    if trade_decision_data:
        trade_decision_summary = {
            "decision": trade_decision_data.get("decision"),
            "confidence": trade_decision_data.get("confidence"),
            "evidence_grade": trade_decision_data.get("evidence_grade"),
        }

    # Risk gate
    risk_gate = check_path(OUTPUT_DIR / "trade_decision" / "risk_gate.json")
    risk_gate_data = load_json(OUTPUT_DIR / "trade_decision" / "risk_gate.json")
    risk_gate_summary = None
    if risk_gate_data:
        risk_gate_summary = {
            "status": risk_gate_data.get("risk_check", {}).get("status"),
            "risk_level": risk_gate_data.get("risk_check", {}).get("risk_level"),
        }

    # Paper world model
    paper_cases = check_path(DATA_DIR / "paper_world_model" / "cases.jsonl")
    paper_mechanisms = check_path(DATA_DIR / "paper_world_model" / "mechanisms.jsonl")
    paper_variables = check_path(DATA_DIR / "paper_world_model" / "variables.jsonl")
    paper_indicators = check_path(DATA_DIR / "paper_world_model" / "indicators.jsonl")
    paper_trade_ideas = check_path(DATA_DIR / "paper_world_model" / "trade_ideas.jsonl")
    paper_manifest = load_json(DATA_DIR / "paper_world_model" / "manifest.json")
    paper_manifest_summary = None
    if paper_manifest:
        paper_manifest_summary = {
            "synced_at": paper_manifest.get("synced_at"),
            "paper_root": paper_manifest.get("paper_root"),
            "record_counts": paper_manifest.get("record_counts"),
            "paper_mtime_hash": paper_manifest.get("paper_mtime_hash"),
        }

    # Horizon events
    horizon_events = check_path(DATA_DIR / "horizon_events" / "events.jsonl")
    horizon_matches = check_path(DATA_DIR / "horizon_events" / "event_mechanism_matches.jsonl")

    # Market feedback (Qlib/replay)
    market_feedback = check_path(OUTPUT_DIR / "market_feedback" / "feedback_decision.json")

    # Probabilistic context (GluonTS)
    probabilistic_context = check_path(OUTPUT_DIR / "probabilistic_context" / "latest.json")

    # Trade ledger
    check_path(OUTPUT_DIR / "trade_ledger" / "decisions.jsonl")
    trade_calibration = check_path(OUTPUT_DIR / "trade_ledger" / "calibration_report.json")

    # Evidence grade report - loaded early because the position translation
    # (below) derives its live blockers from here (WB-A2).
    evidence_report_data = load_json(OUTPUT_DIR / "current" / "evidence_grade_report.json")
    evidence_grade_summary = None
    if evidence_report_data:
        evidence_grade_summary = {
            "structural_grade": evidence_report_data.get("grade"),
            "trade_decision_grade": evidence_report_data.get("trade_decision_grade"),
            "grade_match": evidence_report_data.get("grade_match"),
            "blocker_count": len(evidence_report_data.get("blockers", [])),
            "paper_support_status": (evidence_report_data.get("paper_support_status") or {}).get("status"),
        }

    # Position translation - derived from trade_decision.v3 (stance + effective_size
    # + velocity_gate_state), NOT from the legacy position_intent.v1 file which is a
    # stale artifact (last written 2026-06-18, predates the v3 migration). The v1
    # file carries a contradictory decision dialect (WATCH/hold_flat/0%) vs the live
    # v3 decision (RISK_ON/effective_size 0.5). See WB-A1 in the workbench plan.
    # Blockers come from the current evidence_grade_report.json (WB-A2): the v1
    # file's `evidence_grade_d` blocker was stale (current grade is B).
    position_intent = check_path(OUTPUT_DIR / "position" / "latest.json")
    position_summary = None
    if trade_decision_data:
        stance = trade_decision_data.get("stance", trade_decision_data.get("decision", "WATCH"))
        effective_size = float(trade_decision_data.get("effective_size", 0.0) or 0.0)
        velocity_gate_state = trade_decision_data.get("velocity_gate_state", "FULL")
        # Derive a single consistent decision dialect from stance x size x velocity.
        # velocity_gate EXIT overrides to flat regardless of stance.
        if velocity_gate_state == "EXIT":
            portfolio_action = "hold_flat"
            target_weight = 0.0
            decision = "WATCH"
        elif stance in ("RISK_ON", "ON"):
            portfolio_action = "hold_flat" if effective_size <= 0.0 else "target_weight"
            target_weight = effective_size
            decision = "RISK_ON"
        elif stance in ("RISK_OFF", "OFF"):
            portfolio_action = "hold_flat"
            target_weight = 0.0
            decision = "RISK_OFF"
        else:  # WATCH or unknown
            portfolio_action = "hold_flat" if effective_size <= 0.0 else "target_weight"
            target_weight = effective_size
            decision = "WATCH"
        # Blockers: live from the current evidence report, not the stale v1 file.
        live_blockers = []
        if evidence_report_data:
            for b in evidence_report_data.get("blockers", []):
                code = b.get("code") if isinstance(b, dict) else str(b)
                if code:
                    live_blockers.append(code)
        position_summary = {
            "decision": decision,
            "allowed_mode": "research_only",
            "portfolio_action": portfolio_action,
            "target_weight": target_weight,
            "blockers": live_blockers,
            # Provenance: make it auditable that this is derived, not read from v1.
            "derived_from": "trade_decision.v3",
            "stance": stance,
            "effective_size": effective_size,
            "velocity_gate_state": velocity_gate_state,
        }

    # Operator registry audit
    operator_audit = check_path(OUTPUT_DIR / "quality" / "operator_registry_audit.json")
    operator_audit_data = load_json(OUTPUT_DIR / "quality" / "operator_registry_audit.json")
    operator_audit_summary = None
    if operator_audit_data:
        operator_audit_summary = {
            "status": operator_audit_data.get("status"),
            "total_operators": operator_audit_data.get("total_operators"),
            "issues": len(operator_audit_data.get("issues", [])),
        }

    return {
        "schema_version": "system.index.v3",
        "generated_at": now,
        "current_output": current_output,
        "readme_first": readme_first,
        "next_actions": next_actions,
        "status_json": status_json,
        "harvester": harvester_latest,
        "structural_replay": {
            "latest": replay_latest,
        },
        "paper_world_model": {
            "cases": paper_cases,
            "mechanisms": paper_mechanisms,
            "variables": paper_variables,
            "indicators": paper_indicators,
            "trade_ideas": paper_trade_ideas,
            "manifest": paper_manifest_summary,
        },
        "horizon_events": {
            "events": horizon_events,
            "mechanism_matches": horizon_matches,
        },
        "measurement_state": {
            "judgment": {
                "latest_json": judgment_latest,
                "latest_md": judgment_md,
                "summary": judgment_summary,
            },
            "promotion_gate": {
                "json": promotion_gate,
                "summary": gate_summary,
            },
            "signals": {
                "hmm": {
                    "latest": hmm_latest,
                    "stability": hmm_stability,
                    "summary": hmm_summary,
                },
                "k_gate": {
                    "json": k_gate,
                    "summary": k_summary,
                },
                "x_gate": {
                    "json": x_gate,
                    "summary": x_summary,
                },
                "caselab": caselab_signal,
            },
            "probabilistic_context": probabilistic_context,
        },
        "trade_decision": {
            "latest": trade_decision,
            "summary": trade_decision_summary,
        },
        "risk_gate": {
            "latest": risk_gate,
            "summary": risk_gate_summary,
        },
        "market_feedback": {
            "latest": market_feedback,
        },
        "position": {
            "latest": position_intent,
            "summary": position_summary,
        },
        "operator_registry": {
            "audit": operator_audit,
            "summary": operator_audit_summary,
        },
        "learning_hub": {
            "summary": learning_summary,
            "comprehensive_summary": comprehensive_summary,
            "calibration_events_count": len(calibration_events),
            "trade_calibration": trade_calibration,
        },
        "freshness": {
            "verdict": freshness_verdict,
            "stale_artifacts": stale_artifacts,
        },
        "evidence_grade": {
            "report": check_path(OUTPUT_DIR / "current" / "evidence_grade_report.json"),
            "summary": evidence_grade_summary,
        },
        "calibration_report": calibration_report,
    }


def write_readme() -> None:
    """Write README explaining how to use the index."""
    lines = [
        "# System Index",
        "",
        "This directory contains the unified system index.",
        "",
        "## Primary Entry Points",
        "",
        "For users:",
        "- `Output/current/00_READ_ME_FIRST.md` — start here",
        "- `Output/judgment/latest.md` — daily judgment card",
        "",
        "For agents/CLI:",
        "- `Data/system_index/latest.json` — machine-readable index",
        "",
        "## Index Schema",
        "",
        "The index (`latest.json`) contains:",
        "",
        "- `current_output` — framework_output.json status",
        "- `judgment` — latest judgment card + summary",
        "- `promotion_gate` — gate status + blocked terms",
        "- `signals` — HMM, K gate, X gate, CaseLab status",
        "- `structural_replay` — latest replay run",
        "- `learning_hub` — governance summary + calibration events",
        "- `harvester` — latest data release",
        "",
        "## Usage",
        "",
        "```python",
        "import json",
        "from pathlib import Path",
        "",
        "index = json.loads(Path('Data/system_index/latest.json').read_text())",
        "judgment = index['judgment']['summary']",
        "print(f\"Decision: {judgment['decision']}, Confidence: {judgment['confidence']}\")",
        "```",
        "",
        "## Important",
        "",
        "- Do NOT scan directories independently",
        "- Do NOT cache this file across sessions",
        "- Always read fresh from disk",
    ]
    ensure_dir(INDEX_DIR)
    (INDEX_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build system index.")
    parser.add_argument("--json", action="store_true", help="Print index to stdout.")
    args = parser.parse_args()

    index = build_index()

    ensure_dir(INDEX_DIR)
    INDEX_PATH.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_readme()

    if args.json:
        print(json.dumps(index, indent=2, ensure_ascii=False))
    else:
        print(f"System index: {INDEX_PATH}")
        print(f"Judgment: {index.get('measurement_state', {}).get('judgment', {}).get('summary')}")
        print(f"Trade decision: {index.get('trade_decision', {}).get('summary')}")
        print(f"Risk gate: {index.get('risk_gate', {}).get('summary')}")


if __name__ == "__main__":
    main()
