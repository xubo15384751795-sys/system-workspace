#!/usr/bin/env python3
"""Run mechanism causal calibration and evaluate governance gate.

Wraps nlp.caselab.learning_signal with hold-out split and gate evaluation.

Usage:
    python3 scripts/run_mechanism_calibration.py
    python3 scripts/run_mechanism_calibration.py --json

Output:
    Data/nlp/caselab_calibration/calibration_report.json
    Data/nlp/caselab_calibration/weight_adjustments.json
    Output/caselab/causal/mechanism_calibration_gate.json
    Output/caselab/causal/mechanism_calibration_report.md
"""
from __future__ import annotations

import argparse
import json

from _runtime_io import ROOT, ensure_dir, utc_now, write_json
from _workspace_imports import add_workbench_src

add_workbench_src()

from _mechanism_calibration_gate import evaluate_gate, load_gate_policy
from nlp.caselab.learning_signal import calibrate_all

OUTPUT_DIR = ROOT / "Output" / "caselab" / "causal"
GATE_PATH = OUTPUT_DIR / "mechanism_calibration_gate.json"
REPORT_MD = OUTPUT_DIR / "mechanism_calibration_report.md"


def _load_entity_envs() -> dict[str, dict]:
    """Load entity environments when available; systemic episodes use synthetic graphs."""
    env_path = ROOT / "Data" / "nlp" / "entity_environments.json"
    if not env_path.exists():
        return {}
    try:
        payload = json.loads(env_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(payload, dict):
        return {k: v for k, v in payload.items() if isinstance(v, dict)}
    return {}


def _format_markdown(calibration: dict, gate: dict) -> str:
    agg = calibration.get("aggregate", {})
    split = calibration.get("split", {})
    holdout = split.get("holdout", {})
    lines = [
        "# Mechanism Causal Calibration",
        "",
        f"**Generated:** {utc_now().isoformat()}",
        "",
        "## Aggregate",
        "",
        f"- Episodes: {calibration.get('total_episodes', 0)}",
        f"- Direction accuracy (all): {agg.get('direction_accuracy')}",
        f"- Mean absolute error (all): {agg.get('mean_absolute_error')}",
        "",
        "## Hold-out",
        "",
        f"- Episodes: {holdout.get('count', 0)}",
        f"- Direction accuracy: {holdout.get('direction_accuracy')}",
        f"- Mean absolute error: {holdout.get('mean_absolute_error')}",
        f"- IDs: {', '.join(holdout.get('episode_ids', []) or [])}",
        "",
        "## Gate",
        "",
        f"- Achieved level: **{gate.get('achieved_level', 'none')}**",
        f"- Paper export allowed: {gate.get('allow_paper_export')}",
        f"- Judgment support allowed: {gate.get('allow_judgment_support')}",
        "",
    ]
    reasons = gate.get("blocking_reasons") or []
    if reasons:
        lines.append("### Blocking reasons")
        lines.append("")
        for reason in reasons:
            lines.append(f"- {reason}")
        lines.append("")
    recs = calibration.get("recommendations") or []
    if recs:
        lines.append("## Top recommendations")
        lines.append("")
        for rec in recs[:5]:
            lines.append(f"- {rec.get('description', rec.get('type', 'recommendation'))}")
        lines.append("")
    return "\n".join(lines) + "\n"


def run_calibration() -> dict:
    policy = load_gate_policy()
    holdout_ids = set(policy.get("holdout_episode_ids") or [])
    envs = _load_entity_envs()
    calibration = calibrate_all(envs, holdout_ids=holdout_ids)
    gate = evaluate_gate(calibration, policy)
    calibration["gate"] = gate

    ensure_dir(OUTPUT_DIR)
    write_json(GATE_PATH, gate)
    REPORT_MD.write_text(_format_markdown(calibration, gate), encoding="utf-8")

    return {"calibration": calibration, "gate": gate, "paths": {"gate": str(GATE_PATH), "report": str(REPORT_MD)}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mechanism causal calibration.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    result = run_calibration()
    gate = result["gate"]

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    print(f"Mechanism calibration: {result['calibration']['total_episodes']} episodes")
    print(f"Hold-out direction accuracy: {gate['holdout_metrics']['direction_accuracy']}")
    print(f"Gate level: {gate['achieved_level']}")
    print(f"Gate report: {GATE_PATH}")


if __name__ == "__main__":
    main()
