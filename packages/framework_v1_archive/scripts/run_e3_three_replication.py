#!/usr/bin/env python3
"""Run and adjudicate the frozen E3 funding test three times.

Research only: bootstrap seeds vary, while event construction, features,
split, and embargo stay fixed. No current-state artifact is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SYSTEM_ROOT = Path(__file__).resolve().parents[3]
from scripts import run_framework_validation_protocol as protocol

DEFAULT_OUTPUT = SYSTEM_ROOT / "Output" / "state" / "validation" / "e3_three_replication"
SEEDS = (1729, 20260718, 8675309)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def extract_e3(report: dict[str, Any], seed: int) -> dict[str, Any]:
    status = report["event_status"].get("E3_funding", {})
    event = report["evaluation"].get("E3_funding", {})
    candidates = event.get("candidate_evaluation", {})
    framework = candidates.get("framework_full", {})
    funding = candidates.get("funding_only", {})
    incremental = event.get("incremental_tests", {}).get("framework_full_vs_public_baselines", {})
    delta = incremental.get("delta", {})
    dm = delta.get("diebold_mariano", {})
    framework_lead = framework.get("lead_profile", {})
    funding_lead = funding.get("lead_profile", {})
    delta_pr = finite_float(delta.get("pr_auc"))
    dm_p = finite_float(dm.get("p_value"))
    lead_framework = finite_float(framework_lead.get("t_minus_20"))
    lead_funding = finite_float(funding_lead.get("t_minus_20"))
    incremental_pass = delta_pr is not None and dm_p is not None and delta_pr > 0 and dm_p < 0.05
    lead_pass = lead_framework is not None and lead_funding is not None and lead_framework >= lead_funding
    return {
        "seed": seed,
        "event_status": status.get("status"),
        "event_rate": framework.get("metrics", {}).get("event_rate"),
        "delta_pr_auc": delta_pr,
        "delta_roc_auc": finite_float(delta.get("roc_auc")),
        "brier_improvement": finite_float(delta.get("brier_improvement")),
        "dm_p_value": dm_p,
        "dm_stat": finite_float(dm.get("dm_stat")),
        "framework_lead_profile": framework_lead,
        "funding_only_lead_profile": funding_lead,
        "framework_bootstrap_auc": framework.get("stationary_bootstrap_auc", {}),
        "incremental_gate_pass": incremental_pass,
        "lead_time_gate_pass": lead_pass,
        "replication_pass": status.get("status") == "ok" and incremental_pass and lead_pass,
    }


def render(verdict: dict[str, Any]) -> str:
    lines = [
        "# E3 Three-Replication Verdict",
        "",
        "- Mode: `research_shadow`; no operational promotion.",
        f"- Overall verdict: `{verdict['overall_verdict']}`.",
        "- Lead-time rule: framework `t_minus_20` mean score must be at least the funding-only baseline.",
        "- Replications vary the stationary-bootstrap seed only; frozen point-estimate inputs are unchanged.",
        "",
        "| Run | Seed | Delta PR-AUC | DM p | Framework t-20 | Funding t-20 | Incremental | Lead | Verdict |",
        "|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for i, run in enumerate(verdict["replications"], 1):
        lines.append(
            f"| {i} | {run['seed']} | {run['delta_pr_auc']:.6f} | {run['dm_p_value']:.3g} | "
            f"{run['framework_lead_profile']['t_minus_20']:.6f} | "
            f"{run['funding_only_lead_profile']['t_minus_20']:.6f} | "
            f"{'PASS' if run['incremental_gate_pass'] else 'FAIL'} | "
            f"{'PASS' if run['lead_time_gate_pass'] else 'FAIL'} | "
            f"{'PASS' if run['replication_pass'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "Positive incremental discrimination does not rescue a failed lead-time condition. The artifact "
        "supports only a narrow statement about incremental held-out fit, not E3 as a whole.",
        "",
        "The roughly 89.5% event prevalence shows that the frozen 20-day forward-maximum/q95 label is "
        "not rare in this sample. This is a failure-domain diagnostic, not permission to redefine it.",
    ])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=protocol.DEFAULT_PANEL)
    parser.add_argument("--cross-asset", type=Path, default=protocol.DEFAULT_CROSS_ASSET)
    parser.add_argument("--channels", type=Path, default=protocol.DEFAULT_CHANNELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-reps", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    input_paths = [args.panel, args.channels]
    if args.cross_asset and args.cross_asset.exists():
        input_paths.append(args.cross_asset)
    replications = []
    for number, seed in enumerate(SEEDS, 1):
        run_args = SimpleNamespace(
            panel=args.panel,
            cross_asset=args.cross_asset,
            channels=args.channels,
            output=args.output / f"replication_{number}",
            horizon=20,
            bootstrap_reps=args.bootstrap_reps,
            bootstrap_seed=seed,
            case_dates=list(protocol.DEFAULT_CASE_DATES),
        )
        replications.append(extract_e3(protocol.run(run_args), seed))
    overall = "ALIVE_NARROW" if all(run["replication_pass"] for run in replications) else "DEAD_NEGATIVE"
    verdict = {
        "schema_version": "system.e3_three_replication.v1",
        "mode": "research_shadow",
        "overall_verdict": overall,
        "hypothesis_scope": "E3 funding event; no operational promotion",
        "frozen_rule": {
            "incremental": "delta PR-AUC > 0 and DM p < 0.05",
            "lead_time": "framework_full lead_profile.t_minus_20 >= funding_only lead_profile.t_minus_20",
            "replication": "all three seeds pass both conditions",
        },
        "inputs": {str(path): sha256(path) for path in input_paths},
        "bootstrap_reps_per_run": args.bootstrap_reps,
        "replications": replications,
    }
    (args.output / "verdict.json").write_text(json.dumps(verdict, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (args.output / "verdict.md").write_text(render(verdict), encoding="utf-8")
    print(json.dumps({"status": "ok", "overall_verdict": overall, "output": str(args.output)}))


if __name__ == "__main__":
    main()
