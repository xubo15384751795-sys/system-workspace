#!/usr/bin/env python3
"""Build shadow credit evidence from evaluated, replayable trade decisions.

The command is fail-closed: without an explicitly enabled ``outcome_credit``
section in the existing incentive policy it reports ``DECISION_REQUIRED`` and
writes no credit rows. Historical ledger entries without a learning trace are
reported as unidentifiable rather than assigned fabricated credit.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from scripts._runtime_io import ROOT, ensure_dir, load_yaml
from system_runtime.credit_assignment import (
    ablation_marginals,
    exact_shapley_loss_reduction,
    join_activation_costs,
    validate_trace,
)
from system_runtime.events import JsonlEventStore
from workbench.judgment.trade_decision import compose_trade_fields, determine_size, determine_stance


LEDGER_PATH = ROOT / "Output" / "trade_ledger" / "decisions.jsonl"
REPORT_JSON = ROOT / "Output" / "system_learning" / "latest" / "backward_pass.json"
REPORT_MD = ROOT / "Output" / "system_learning" / "latest" / "backward_pass.md"
POLICY_PATH = ROOT / "governance" / "incentive_policy.yaml"

QUALITY_NODE_FIELDS = {
    "k_gate": "k_verdict",
    "x_gate": "x_verdict",
    "hmm_quality": "hmm_grade",
    "caselab_quality": "caselab_label",
    "paper_support": "has_approved_paper",
    "paper_freshness": "paper_stale",
    "proxy_quality": "proxy_quality",
    "promotion_gate": "promotion_hard_blocked",
}


def _node_inputs(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        str(node["node_id"]): node.get("value")
        for node in trace.get("nodes", [])
        if node.get("baseline_status") == "DECISION_REQUIRED"
    }


def _replay(inputs: dict[str, Any]) -> dict[str, Any]:
    velocity_value = inputs.get("velocity_state") or {}
    velocity = velocity_value.get("velocity_gate") or {}
    sigma = velocity_value.get("sigma_vector") or {}
    quality = {
        field: inputs.get(node_id)
        for node_id, field in QUALITY_NODE_FIELDS.items()
    }
    stance = determine_stance(sigma, velocity)
    size = determine_size(quality)
    return compose_trade_fields(stance=stance, size=size, data_available=True)


def _market_return(entry: dict[str, Any], *, horizon: str, market: str) -> float | None:
    outcome = entry.get("market_forward_outcome") or {}
    horizons = outcome.get("outcomes") or outcome
    metric = (((horizons.get(horizon) or {}).get("metrics") or {}).get(market) or {})
    value = metric.get("return_pct")
    return float(value) if isinstance(value, (int, float)) else None


def _loss_for(return_pct: float, objective: str, deadband_pct: float):
    if objective == "realized_utility":
        return lambda output: -float(output.get("effective_size", 0.0)) * return_pct
    if objective == "directional_opportunity_loss":
        target = 1.0 if return_pct > deadband_pct else 0.0 if return_pct < -deadband_pct else 0.5
        return lambda output: (float(output.get("effective_size", 0.0)) - target) ** 2
    raise ValueError(f"unsupported outcome_credit objective: {objective}")


def _decision_requirements() -> list[dict[str, str]]:
    return [
        {
            "id": "loss_objective",
            "question": "Use realized utility or directional opportunity loss?",
            "effect": "Defines what an error means; no credit is valid without it.",
        },
        {
            "id": "evaluation_horizon_market",
            "question": "Which horizon and market are authoritative for fast-loop loss?",
            "effect": "Selects the delayed outcome label (for example SPY 1w).",
        },
        {
            "id": "node_baselines",
            "question": "Approve a neutral replacement for each replayable node.",
            "effect": "Defines the counterfactual derivative; changing it changes credit.",
        },
        {
            "id": "minimum_samples",
            "question": "How many evaluated traced decisions are required before credit affects review priority?",
            "effect": "Prevents sparse/noisy outcomes from driving the incentive loop.",
        },
    ]


def build_report(entries: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    evaluated = [entry for entry in entries if entry.get("market_forward_outcome")]
    all_traceable: list[dict[str, Any]] = []
    invalid_trace = 0
    invalid_evaluated_trace = 0
    for entry in entries:
        trace = entry.get("learning_trace")
        if not isinstance(trace, dict):
            continue
        if validate_trace(trace):
            invalid_trace += 1
            if entry.get("market_forward_outcome"):
                invalid_evaluated_trace += 1
            continue
        all_traceable.append(entry)
    traceable = [entry for entry in all_traceable if entry.get("market_forward_outcome")]

    activation_rows = []
    for entry in all_traceable:
        trace = entry["learning_trace"]
        run_id = trace.get("run_id")
        step_path = ROOT / "Output" / "runs" / str(run_id) / "steps.jsonl" if run_id else None
        steps = JsonlEventStore(step_path).read_payloads() if step_path and step_path.exists() else []
        costs = join_activation_costs(trace, steps)
        activation_rows.append({
            "date": entry.get("date"),
            "decision_fingerprint": entry.get("decision_fingerprint"),
            "activation": trace.get("activation", {}),
            "costs": costs,
        })
    ratios = [
        float(row["activation"].get("activation_ratio"))
        for row in activation_rows
        if isinstance(row["activation"].get("activation_ratio"), (int, float))
    ]
    measured_costs = [
        float(row["costs"]["unique_producer_cost_s"])
        for row in activation_rows
        if row["costs"].get("measured_producer_steps", 0) > 0
    ]

    config = policy.get("outcome_credit") or {}
    base = {
        "schema_version": "backward_pass_report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "shadow_only",
        "credit_can_grant_authority": False,
        "coverage": {
            "ledger_entries": len(entries),
            "evaluated_entries": len(evaluated),
            "traceable_entries": len(all_traceable),
            "traceable_evaluated_entries": len(traceable),
            "historical_unidentifiable_entries": (
                len(evaluated) - len(traceable) - invalid_evaluated_trace
            ),
            "invalid_trace_entries": invalid_trace,
        },
        "activation_metrics": {
            "traced_decisions": len(activation_rows),
            "average_activation_ratio": round(sum(ratios) / len(ratios), 6) if ratios else None,
            "costed_decisions": len(measured_costs),
            "average_unique_producer_cost_s": (
                round(sum(measured_costs) / len(measured_costs), 6) if measured_costs else None
            ),
            "decisions": activation_rows,
        },
    }
    if config.get("enabled") is not True:
        return {
            **base,
            "status": "DECISION_REQUIRED",
            "decision_requirements": _decision_requirements(),
            "credits": [],
            "note": "No credit computed. Existing evaluated rows predate replayable learning traces.",
        }

    horizon = str(config.get("horizon", ""))
    market = str(config.get("market", ""))
    objective = str(config.get("objective", ""))
    baselines = config.get("node_baselines") or {}
    minimum_samples = int(config.get("minimum_samples", 0))
    if not horizon or not market or not objective or not baselines or minimum_samples <= 0:
        return {
            **base,
            "status": "INVALID_POLICY",
            "decision_requirements": _decision_requirements(),
            "credits": [],
        }

    sample_rows: list[dict[str, Any]] = []
    replay_samples: list[dict[str, Any]] = []
    by_node: dict[str, list[float]] = defaultdict(list)
    traceable.sort(key=lambda item: (str(item.get("date", "")), str(item.get("recorded_at", ""))))
    previous_inputs: dict[str, Any] | None = None
    for entry in traceable:
        return_pct = _market_return(entry, horizon=horizon, market=market)
        actual_inputs = _node_inputs(entry["learning_trace"])
        if return_pct is None:
            previous_inputs = actual_inputs
            continue
        sample_baselines = dict(baselines)
        if config.get("velocity_baseline") == "previous_trace" and previous_inputs:
            if "velocity_state" in previous_inputs:
                sample_baselines["velocity_state"] = previous_inputs["velocity_state"]
        loss_function = _loss_for(
            return_pct,
            objective,
            float(config.get("deadband_pct", 0.0)),
        )
        result = ablation_marginals(
            actual_inputs,
            baselines=sample_baselines,
            replay=_replay,
            loss=loss_function,
        )
        for row in result["credits"]:
            if row.get("status") == "evaluated":
                by_node[row["node_id"]].append(float(row["loss_reduction"]))
        sample_rows.append({
            "date": entry.get("date"),
            "decision_fingerprint": entry.get("decision_fingerprint"),
            "market_return_pct": return_pct,
            "credits": result["credits"],
        })
        replay_samples.append({
            "actual_inputs": actual_inputs,
            "baselines": sample_baselines,
            "loss": loss_function,
        })
        previous_inputs = actual_inputs

    eligible = len(sample_rows) >= minimum_samples
    aggregate = [
        {
            "node_id": node_id,
            "samples": len(values),
            "mean_loss_reduction": round(sum(values) / len(values), 8),
        }
        for node_id, values in sorted(by_node.items())
        if values
    ]
    shapley: dict[str, Any] = {
        "status": "INSUFFICIENT_SAMPLES",
        "minimum_samples": int(config.get("shapley_minimum_samples", 30)),
        "node_ids": [],
        "credits": [],
    }
    shapley_minimum = shapley["minimum_samples"]
    shapley_top_nodes = int(config.get("shapley_top_nodes", 3))
    if len(replay_samples) >= shapley_minimum and aggregate:
        top_nodes = [
            row["node_id"]
            for row in sorted(
                aggregate,
                key=lambda row: abs(float(row["mean_loss_reduction"])),
                reverse=True,
            )[:shapley_top_nodes]
        ]
        shapley_values: dict[str, list[float]] = defaultdict(list)
        for sample in replay_samples:
            available = [
                node for node in top_nodes
                if node in sample["actual_inputs"] and node in sample["baselines"]
            ]
            if not available:
                continue
            values = exact_shapley_loss_reduction(
                sample["actual_inputs"],
                baselines=sample["baselines"],
                node_ids=available,
                replay=_replay,
                loss=sample["loss"],
            )
            for node_id, value in values.items():
                shapley_values[node_id].append(float(value))
        shapley = {
            "status": "EVALUATED",
            "minimum_samples": shapley_minimum,
            "node_ids": top_nodes,
            "credits": [
                {
                    "node_id": node_id,
                    "samples": len(values),
                    "mean_loss_reduction": round(sum(values) / len(values), 8),
                }
                for node_id, values in sorted(shapley_values.items())
                if values
            ],
        }

    review_queue = []
    if eligible:
        for rank, row in enumerate(
            sorted(aggregate, key=lambda item: abs(float(item["mean_loss_reduction"])), reverse=True),
            start=1,
        ):
            contribution = float(row["mean_loss_reduction"])
            review_queue.append({
                "rank": rank,
                "node_id": row["node_id"],
                "samples": row["samples"],
                "mean_loss_reduction": contribution,
                "review_action": "preserve_or_reuse" if contribution > 0 else "investigate_drag",
            })

    return {
        **base,
        "status": "ELIGIBLE_FOR_REVIEW_PRIORITY" if eligible else "INSUFFICIENT_SAMPLES",
        "policy": {
            "objective": objective,
            "horizon": horizon,
            "market": market,
            "minimum_samples": minimum_samples,
        },
        "eligible_to_affect_review_priority": eligible,
        "eligible_to_grant_authority": False,
        "sample_count": len(sample_rows),
        "credits": aggregate,
        "shapley": shapley,
        "review_queue": review_queue,
        "samples": sample_rows,
    }


def format_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# Backward Pass (Shadow Only)", "",
        f"Status: **{report['status']}**", "",
        "Credit can grant authority: **false**", "",
        "## Coverage", "",
        f"- Ledger entries: {coverage['ledger_entries']}",
        f"- Evaluated entries: {coverage['evaluated_entries']}",
        f"- Traceable evaluated entries: {coverage['traceable_evaluated_entries']}",
        f"- Historical unidentifiable entries: {coverage['historical_unidentifiable_entries']}",
    ]
    if report.get("decision_requirements"):
        lines += ["", "## Decisions Required", ""]
        lines += [f"- **{item['id']}**: {item['question']}" for item in report["decision_requirements"]]
    if report.get("credits"):
        lines += ["", "## Aggregate Credit Evidence", ""]
        lines += [
            f"- {row['node_id']}: n={row['samples']}, mean loss reduction={row['mean_loss_reduction']}"
            for row in report["credits"]
        ]
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any]) -> dict[str, str]:
    """Write the shadow report and return its two paths."""
    ensure_dir(REPORT_JSON.parent)
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT_MD.write_text(format_markdown(report), encoding="utf-8")
    return {"json": str(REPORT_JSON), "markdown": str(REPORT_MD)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run shadow-only organizational backward pass.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    entries = JsonlEventStore(LEDGER_PATH).read_payloads()
    report = build_report(entries, load_yaml(POLICY_PATH))
    write_report(report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Backward pass: {report['status']}")
        print(f"Report: {REPORT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
