"""Generate a C005 morphology evidence run from sandbox event-window data.

Pulls per-event channel signals and benchmark z-scores from
``Output/sandbox/structural_replay_v2/results.json``, computes
Spearman residual correlations, operator diagnostics, and rejection
flags across the 16 historical stress events, and writes a canonical
``Output/deformation_runs/<run_id>/`` package layout that the C005
morphology reporter and promotion gate can read.

The verdict is fully data-driven: rejection flags fire based on
correlation thresholds, and the C005 reporter then resolves SUPPORTED /
WEAKENED / REJECTED from that. Nothing here is fabricated — the channel
values and benchmark z-scores come from the existing structural_replay_v2
sandbox; sigma_t is computed via the canonical formula in
``src/derivation/singular_detector.py`` (default weights).

This module deliberately does NOT promote the snapshot. The freshness
manifest is written with ``promotion_allowed: false`` and a clear
blocker so that any attempt to run ``promote_snapshot.py`` against this
historical evidence run is blocked at the gate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workbench.workspace._paths import DEFORMATION_RUNS, OUTPUT_DIR, WORKSPACE_ROOT

REPLAY_RESULTS = OUTPUT_DIR / "sandbox" / "structural_replay_v2" / "results.json"

# Thresholds for rejection flags. Each is a Spearman |r| cutoff above which
# the channel is treated as a benchmark proxy (i.e. not adding orthogonal
# information). 0.70 is a conventional cutoff for "strong" rank correlation.
THRESHOLD_BENCHMARK_DOMINANCE = 0.70
THRESHOLD_SIGMA_DISCRIMINATION_LOSS = 0.80
THRESHOLD_PATH_UNIFORMITY = 0.75

# (residual_key, channel_panel_col, benchmark_panel_col, human_label)
RESIDUAL_SPECS: list[tuple[str, str, str, str]] = [
    ("Sigma_resid_vs_aggregate_stress", "sigma_t", "NFCI_zscore", "Sigma_t vs aggregate financial stress (NFCI)"),
    ("M_resid_vs_NFCI", "M", "NFCI_zscore", "Mismatch channel M vs NFCI"),
    ("D_resid_vs_NFCI", "D_contraction", "NFCI_zscore", "Degrees-of-freedom contraction D vs NFCI"),
    ("K_resid_vs_vol_jump_tail", "K", "VIX_zscore", "Curvature channel K vs vol-jump tail (VIX)"),
    ("X_resid_vs_leverage", "X_max", "BAA10YM_zscore", "Shadow/realization channel X vs leverage (BAA10YM)"),
]


def compute_sigma_t(channel_at_peak: dict[str, Any]) -> float:
    """Canonical sigma_t (singular_detector.py default weights, w_*=1, state_pressure_weight=0).

    Uses X_agg as the canonical shadow channel (Finance-2.tex §4.5).
    Falls back to X_PRE for backward compatibility with legacy event data.
    """
    mismatch = max(float(channel_at_peak.get("M") or 0.0), 0.0)
    dof_contraction = max(float(channel_at_peak.get("D_contraction") or 0.0), 0.0)
    curvature = max(float(channel_at_peak.get("K") or 0.0), 0.0)
    # Canonical: use X_agg. Legacy fallback: X_PRE.
    shadow = max(float(channel_at_peak.get("X_agg") or channel_at_peak.get("X_PRE") or 0.0), 0.0)
    return mismatch + dof_contraction + curvature + shadow


def _average_ranks(xs: list[float]) -> list[float]:
    n = len(xs)
    order = sorted(range(n), key=lambda i: xs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sx2 = sum((x - mx) ** 2 for x in xs)
    sy2 = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom = math.sqrt(sx2 * sy2)
    return sxy / denom if denom > 0 else 0.0


def spearman(xs: list[float], ys: list[float]) -> float:
    return _pearson(_average_ranks(xs), _average_ranks(ys))


def load_events(results_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"results.json at {results_path} is empty or not a list")
    return payload


def extract_panel(events: list[dict[str, Any]]) -> dict[str, list[float]]:
    columns: dict[str, list[float]] = {
        "sigma_t": [], "M": [], "D_contraction": [], "K": [], "X_max": [],
        "NFCI_zscore": [], "VIX_zscore": [], "BAA10YM_zscore": [],
        "STLFSI4_zscore": [], "CPBill_zscore": [],
    }
    for event in events:
        cap = event.get("channel_at_peak", {}) or {}
        bc = event.get("benchmark_context", {}) or {}
        columns["sigma_t"].append(compute_sigma_t(cap))
        columns["M"].append(max(float(cap.get("M") or 0.0), 0.0))
        columns["D_contraction"].append(max(float(cap.get("D_contraction") or 0.0), 0.0))
        columns["K"].append(max(float(cap.get("K") or 0.0), 0.0))
        x_pre = max(float(cap.get("X_PRE") or 0.0), 0.0)
        x_rea = max(float(cap.get("X_REALIZED") or 0.0), 0.0)
        columns["X_max"].append(max(x_pre, x_rea))
        columns["NFCI_zscore"].append(float(bc.get("NFCI_zscore") or 0.0))
        columns["VIX_zscore"].append(float(bc.get("VIX_zscore") or 0.0))
        columns["BAA10YM_zscore"].append(float(bc.get("BAA10YM_zscore") or 0.0))
        columns["STLFSI4_zscore"].append(float(bc.get("STLFSI4_zscore") or 0.0))
        columns["CPBill_zscore"].append(float(bc.get("CPBill_zscore") or 0.0))
    return columns


def compute_residuals(panel: dict[str, list[float]]) -> dict[str, float]:
    return {key: spearman(panel[channel_col], panel[bench_col])
            for key, channel_col, bench_col, _label in RESIDUAL_SPECS}


def compute_rejection_flags(
    residuals: dict[str, float],
    events: list[dict[str, Any]],
) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    flags["sigma_no_incremental_discrimination"] = (
        abs(residuals["Sigma_resid_vs_aggregate_stress"]) > THRESHOLD_SIGMA_DISCRIMINATION_LOSS
    )
    flags["benchmark_dominance_M_vs_NFCI"] = (
        abs(residuals["M_resid_vs_NFCI"]) > THRESHOLD_BENCHMARK_DOMINANCE
    )
    flags["benchmark_dominance_D_vs_NFCI"] = (
        abs(residuals["D_resid_vs_NFCI"]) > THRESHOLD_BENCHMARK_DOMINANCE
    )
    flags["benchmark_dominance_K_vs_vol_jump_tail"] = (
        abs(residuals["K_resid_vs_vol_jump_tail"]) > THRESHOLD_BENCHMARK_DOMINANCE
    )
    flags["benchmark_dominance_X_vs_leverage"] = (
        abs(residuals["X_resid_vs_leverage"]) > THRESHOLD_BENCHMARK_DOMINANCE
    )
    paths = [event.get("path_text", "") or "" for event in events]
    if paths:
        most_common_share = Counter(paths).most_common(1)[0][1] / len(paths)
    else:
        most_common_share = 0.0
    flags["path_uniform_across_events"] = most_common_share > THRESHOLD_PATH_UNIFORMITY
    return flags


def compute_operator_diagnostics(events: list[dict[str, Any]]) -> dict[str, Any]:
    all_path_entries: list[dict[str, Any]] = []
    sorted_path_match = 0
    irreversible_count = 0
    shadow_transfer_count = 0
    K_values: list[float] = []
    M_values: list[float] = []
    path_orders: list[tuple[str, ...]] = []

    for event in events:
        path = event.get("observed_path", []) or []
        all_path_entries.extend(path)
        order = tuple(p.get("channel", "") for p in path)
        path_orders.append(order)
        if list(order) == sorted(order):
            sorted_path_match += 1
        if any(p.get("channel") == "X_REALIZED" for p in path):
            irreversible_count += 1
        cap = event.get("channel_at_peak", {}) or {}
        x_pre = float(cap.get("X_PRE") or 0.0)
        x_rea = float(cap.get("X_REALIZED") or 0.0)
        if x_rea > x_pre:
            shadow_transfer_count += 1
        K_values.append(max(float(cap.get("K") or 0.0), 0.0))
        M_values.append(max(float(cap.get("M") or 0.0), 0.0))

    n_events = len(events)
    op_count = len(all_path_entries)
    non_commutativity = 0.0 if n_events == 0 else 1.0 - (sorted_path_match / n_events)
    unique_paths = len({order for order in path_orders})
    compression_ratio = 0.0 if n_events == 0 else unique_paths / n_events

    return {
        "schema_version": "deformation.operator_diagnostics.v1",
        "source": "structural_replay_v2 event windows (16 historical stress events)",
        "operator_count": op_count,
        "compression_ratio": round(compression_ratio, 4),
        "non_commutativity_score": round(non_commutativity, 4),
        "irreversible_count": irreversible_count,
        "curvature_amplification": round(statistics.fmean(K_values), 4) if K_values else 0.0,
        "mismatch_amplification": round(statistics.fmean(M_values), 4) if M_values else 0.0,
        "shadow_transfer": round(shadow_transfer_count / n_events, 4) if n_events else 0.0,
        "events_total": n_events,
        "unique_path_count": unique_paths,
    }


def compute_benchmark_comparison(
    panel: dict[str, list[float]],
    residuals: dict[str, float],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, _channel_col, bench_col, _label in RESIDUAL_SPECS:
        bench_mean = statistics.fmean(panel[bench_col]) if panel[bench_col] else 0.0
        rows.append({
            "name": key,
            "benchmark_value": f"{bench_mean:.4f}",
            "residual_value": f"{residuals[key]:+.4f}",
        })
    return rows


def compute_validation_loop_status(
    residuals: dict[str, float],
    rejection_flags: dict[str, bool],
    operator_diag: dict[str, Any],
    benchmark_rows: list[dict[str, str]],
) -> dict[str, Any]:
    blockers: list[str] = []
    required_keys = {key for key, *_ in RESIDUAL_SPECS}
    missing = sorted(key for key in required_keys if key not in residuals)
    if missing:
        blockers.append(f"residual keys missing: {', '.join(missing)}")
    if not rejection_flags:
        blockers.append("rejection_flags empty")
    if not operator_diag or operator_diag.get("events_total", 0) == 0:
        blockers.append("operator_diagnostics empty")
    if not benchmark_rows or any(row["name"] == "not_available" for row in benchmark_rows):
        blockers.append("benchmark_comparison empty or contains not_available")
    status = "complete" if not blockers else "incomplete"
    return {
        "schema_version": "deformation.validation_loop.v1",
        "status": status,
        "claim_carrying_allowed": status == "complete",
        "actionable_verdict": "PROMOTE" if status == "complete" else "BLOCK",
        "severity": "OK" if status == "complete" else "HIGH",
        "required_action": (
            "C005 evidence loop populated; keep claim language scoped to morphology separation."
            if status == "complete"
            else "Populate the missing C005 evidence inputs before claim-carrying use."
        ),
        "blockers": blockers,
    }


def _config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validation_report_md(
    validation_loop: dict[str, Any],
    residuals: dict[str, float],
    rejection_flags: dict[str, bool],
    operator_diag: dict[str, Any],
) -> str:
    flag_lines = [f"- {k}: {v}" for k, v in sorted(rejection_flags.items())] or ["- not_available"]
    residual_lines = [f"- {k}: {v:+.4f}" for k, v in sorted(residuals.items())]
    return "\n".join([
        "# Validation Report",
        "",
        "## Actionable Verdict",
        f"- Verdict: {validation_loop.get('actionable_verdict', 'BLOCK')}",
        f"- Severity: {validation_loop.get('severity', 'HIGH')}",
        "- Owner: structural-validation",
        f"- Required Action: {validation_loop.get('required_action', 'Populate validation diagnostics before promotion.')}",
        "",
        "## Validation Loop Status",
        f"- status: {validation_loop.get('status', 'incomplete')}",
        f"- claim_carrying_allowed: {validation_loop.get('claim_carrying_allowed', False)}",
        *(f"- blocker: {b}" for b in validation_loop.get('blockers', [])),
        "",
        "## Rejection Flags",
        *flag_lines,
        "",
        "## Residual Diagnostics",
        *residual_lines,
        "",
        "## Operator Diagnostics",
        f"- operator_count: {operator_diag.get('operator_count')}",
        f"- non_commutativity_score: {operator_diag.get('non_commutativity_score')}",
        f"- compression_ratio: {operator_diag.get('compression_ratio')}",
        f"- irreversible_count: {operator_diag.get('irreversible_count')}",
        f"- shadow_transfer: {operator_diag.get('shadow_transfer')}",
        f"- curvature_amplification: {operator_diag.get('curvature_amplification')}",
        f"- mismatch_amplification: {operator_diag.get('mismatch_amplification')}",
        "",
    ])


def _operator_trace_records(events: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    header = {
        "schema_version": "deformation.operator_trace.v1",
        "kind": "trace_header",
        "run_id": run_id,
        "status": "complete",
        "operator_count": sum(len(e.get("observed_path", []) or []) for e in events),
        "note": "Trace records replay one application per observed_path entry across 16 events.",
    }
    records: list[dict[str, Any]] = [header]
    for event in events:
        event_id = event.get("event_id")
        for application in event.get("observed_path", []) or []:
            records.append({
                "kind": "application",
                "event_id": event_id,
                "channel": application.get("channel"),
                "date": application.get("date"),
                "days_before_peak": application.get("days_before_peak"),
                "value": application.get("value"),
                "threshold": application.get("threshold"),
            })
    return records


def _executive_summary_md(
    run_id: str,
    residuals: dict[str, float],
    rejection_flags: dict[str, bool],
    operator_diag: dict[str, Any],
    n_events: int,
) -> str:
    active_flags = sorted(k for k, v in rejection_flags.items() if v)
    flag_text = ", ".join(active_flags) if active_flags else "none"
    return "\n".join([
        f"# C005 Morphology Evidence Run - {run_id}",
        "",
        "## Inputs",
        f"- Event windows: {n_events} historical stress events from structural_replay_v2",
        "- Sigma_t formula: canonical singular_detector defaults (M+max(-D,0)+K+X_agg)",
        "- Residual method: Spearman rank correlation across events at peak",
        "",
        "## Residual Correlations",
        *(f"- {key}: {residuals[key]:+.4f}" for key, *_ in RESIDUAL_SPECS),
        "",
        "## Active Rejection Flags",
        f"- {flag_text}",
        "",
        "## Operator Aggregate",
        f"- operator_count={operator_diag['operator_count']}, "
        f"non_commutativity={operator_diag['non_commutativity_score']}, "
        f"compression_ratio={operator_diag['compression_ratio']}, "
        f"irreversible_count={operator_diag['irreversible_count']}",
        "",
        "## Boundary",
        "- This run is C005 claim evidence, not a fresh-data Deformation snapshot.",
        "- The freshness manifest blocks canonical promotion by design.",
        "- C005 verdict is produced by build_c005_morphology_report.py against this run.",
        "",
    ])


def _machine_snapshot_payload(
    run_id: str,
    panel: dict[str, list[float]],
    residuals: dict[str, float],
    rejection_flags: dict[str, bool],
    operator_diag: dict[str, Any],
    benchmark_rows: list[dict[str, str]],
) -> dict[str, Any]:
    benchmarks = {
        row["name"]: float(row["benchmark_value"]) for row in benchmark_rows
    }
    residual_diagnostics = {key: float(value) for key, value in residuals.items()}
    return {
        "schema_version": "deformation.snapshot.c005_morphology.v1",
        "run_id": run_id,
        "snapshot_type": "c005_morphology_evidence",
        "proxy": {
            "M": statistics.fmean(panel["M"]) if panel["M"] else 0.0,
            "D": -statistics.fmean(panel["D_contraction"]) if panel["D_contraction"] else 0.0,
            "K": statistics.fmean(panel["K"]) if panel["K"] else 0.0,
            "X": statistics.fmean(panel["X_max"]) if panel["X_max"] else 0.0,
            "directions": {"M": "AGGREGATE", "D": "AGGREGATE", "K": "AGGREGATE", "X": "AGGREGATE"},
            "available": {"M": True, "D": True, "K": True, "X": True},
        },
        "state": {
            "sigma_t": statistics.fmean(panel["sigma_t"]) if panel["sigma_t"] else 0.0,
            "singular_flag": False,
            "leading_channel": "AGGREGATE",
            "pattern": "c005_morphology_evidence_aggregate",
            "operator_diagnostics": operator_diag,
            "structural_diagnostic_state": {
                "benchmarks": benchmarks,
                "residual_diagnostics": residual_diagnostics,
                "rejection_flags": {k: bool(v) for k, v in rejection_flags.items()},
                "morphology": {
                    "label": "cross_event_aggregate",
                    "interpretation": "Aggregate over 16 historical stress events to test channel residual orthogonality vs aggregate stress, NFCI, vol-tail, and leverage benchmarks.",
                },
            },
        },
        "escalation": False,
        "escalation_reason": None,
    }


def write_run_package(
    *,
    run_id: str,
    harvester_release: str,
    events: list[dict[str, Any]],
    panel: dict[str, list[float]],
    residuals: dict[str, float],
    rejection_flags: dict[str, bool],
    operator_diag: dict[str, Any],
    benchmark_rows: list[dict[str, str]],
    validation_loop: dict[str, Any],
    output_root: Path,
    results_path: Path,
) -> Path:
    run_dir = output_root / run_id
    subdirs = {name: run_dir / name for name in ("machine", "diagnostics", "tables", "reports", "traces", "logs")}
    for path in subdirs.values():
        path.mkdir(parents=True, exist_ok=True)

    generated_at = _now_iso()
    config = {
        "harvester_release": harvester_release,
        "event_window_source": str(results_path.relative_to(WORKSPACE_ROOT)) if results_path.is_relative_to(WORKSPACE_ROOT) else str(results_path),
        "residual_method": "spearman_rank_correlation",
        "sigma_formula": "M + max(-D,0) + K + X_agg (singular_detector default weights)",
        "thresholds": {
            "benchmark_dominance": THRESHOLD_BENCHMARK_DOMINANCE,
            "sigma_discrimination_loss": THRESHOLD_SIGMA_DISCRIMINATION_LOSS,
            "path_uniformity": THRESHOLD_PATH_UNIFORMITY,
        },
        "n_events": len(events),
    }
    config_hash = _config_hash(config)

    # machine/snapshot.json
    snapshot_payload = _machine_snapshot_payload(run_id, panel, residuals, rejection_flags, operator_diag, benchmark_rows)
    (subdirs["machine"] / "snapshot.json").write_text(
        json.dumps(snapshot_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    # tables/benchmark_comparison.csv
    bench_path = subdirs["tables"] / "benchmark_comparison.csv"
    with bench_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "benchmark_value", "residual_value"])
        writer.writeheader()
        writer.writerows(benchmark_rows)

    # diagnostics/*.json + md
    (subdirs["diagnostics"] / "residual_tests.json").write_text(
        json.dumps({k: round(v, 6) for k, v in residuals.items()}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (subdirs["diagnostics"] / "rejection_flags.json").write_text(
        json.dumps({k: bool(v) for k, v in rejection_flags.items()}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (subdirs["diagnostics"] / "operator_diagnostics.json").write_text(
        json.dumps(operator_diag, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    (subdirs["diagnostics"] / "validation_loop_status.json").write_text(
        json.dumps(validation_loop, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    (subdirs["diagnostics"] / "validation_report.md").write_text(
        _validation_report_md(validation_loop, residuals, rejection_flags, operator_diag),
        encoding="utf-8",
    )

    # traces/operator_trace.jsonl
    trace_path = subdirs["traces"] / "operator_trace.jsonl"
    with trace_path.open("w", encoding="utf-8") as handle:
        for record in _operator_trace_records(events, run_id):
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    # config_snapshot.json
    (run_dir / "config_snapshot.json").write_text(
        json.dumps({
            "schema_version": "deformation.config_snapshot.v1",
            "run_id": run_id,
            "captured_at": generated_at,
            "captured_status": "captured",
            "config_hash": config_hash,
            "config": config,
        }, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    # freshness_manifest.json — historical evidence run, NOT a fresh-data run.
    # Block canonical promotion at the gate; this manifest is what
    # promote_snapshot.py reads to decide whether the run is promotable.
    (run_dir / "freshness_manifest.json").write_text(
        json.dumps({
            "schema_version": "workbench.freshness_manifest.v1",
            "generated_at": generated_at,
            "evidence_release_id": harvester_release,
            "run_id": run_id,
            "model_input_validity": "historical_evidence_run",
            "gate_result": {
                "promotion_allowed": False,
                "canonical_promotion_severity": "block",
                "model_input_validity": "historical_evidence_run",
                "warnings": [],
                "blockers": [
                    "C005 morphology evidence run derived from historical event windows; not a fresh-data snapshot — canonical promotion is not authorized for this run.",
                ],
            },
            "notes": [
                "Indicators: NFCI, VIX, BAA10YM, STLFSI4, CPBill — embedded in event_window context, not pulled fresh at run time.",
                "Promotion of this run as canonical Deformation snapshot is intentionally blocked. C005 claim evidence is consumed via the C005 morphology report, not snapshot promotion.",
            ],
        }, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    # run_manifest.json
    manifest = {
        "kind": "deformation_run",
        "schema_version": "deformation.run.v1",
        "run_id": run_id,
        "run_date": run_id.split("_")[0],
        "run_type": "C005_MORPHOLOGY",
        "generated_at": generated_at,
        "status": "success",
        "git_commit": None,
        "config_hash": config_hash,
        "config_snapshot_path": "config_snapshot.json",
        "data_backend": "sandbox_replay_v2",
        "harvester_release": harvester_release,
        "model_version": "c005_morphology_replay",
        "package_dir": str(run_dir),
        "machine_artifacts": {
            "snapshot": "machine/snapshot.json",
        },
        "traces": {"operator_trace": "traces/operator_trace.jsonl"},
        "diagnostics": {
            "validation_report": "diagnostics/validation_report.md",
            "operator_diagnostics": "diagnostics/operator_diagnostics.json",
            "rejection_flags": "diagnostics/rejection_flags.json",
            "residual_tests": "diagnostics/residual_tests.json",
            "validation_loop_status": "diagnostics/validation_loop_status.json",
        },
        "tables": {"benchmark_comparison": "tables/benchmark_comparison.csv"},
        "reports": {"executive_summary": "reports/executive_summary.md"},
        "logs": {"combined": "logs/run.log"},
        "freshness_manifest_path": "freshness_manifest.json",
        "validation_loop_status": validation_loop,
        "claim_carrying_allowed": validation_loop.get("claim_carrying_allowed", False),
        "model_input_validity": "historical_evidence_run",
        "evidence_source": "Output/sandbox/structural_replay_v2/results.json",
        "promotion_eligibility": {
            "canonical_snapshot": False,
            "reason": "Historical evidence run — does not represent fresh canonical input. Freshness gate blocks promotion by design.",
        },
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    # reports/executive_summary.md
    (subdirs["reports"] / "executive_summary.md").write_text(
        _executive_summary_md(run_id, residuals, rejection_flags, operator_diag, len(events)),
        encoding="utf-8",
    )

    # logs/run.log
    (subdirs["logs"] / "run.log").write_text(
        f"C005 morphology evidence run {run_id} generated at {generated_at}.\n"
        f"Source: {config['event_window_source']}\n"
        f"Events: {len(events)}\n"
        f"Validation loop status: {validation_loop.get('status')}\n",
        encoding="utf-8",
    )

    # artifacts.json
    artifacts = {
        "run_id": run_id,
        "package_dir": str(run_dir),
        "machine": {"snapshot": "machine/snapshot.json"},
        "diagnostics": {
            "residual_tests": "diagnostics/residual_tests.json",
            "rejection_flags": "diagnostics/rejection_flags.json",
            "operator_diagnostics": "diagnostics/operator_diagnostics.json",
            "validation_loop_status": "diagnostics/validation_loop_status.json",
            "validation_report": "diagnostics/validation_report.md",
        },
        "tables": {"benchmark_comparison": "tables/benchmark_comparison.csv"},
        "traces": {"operator_trace": "traces/operator_trace.jsonl"},
        "reports": {"executive_summary": "reports/executive_summary.md"},
        "config_snapshot": "config_snapshot.json",
        "freshness_manifest": "freshness_manifest.json",
        "logs": {"run_log": "logs/run.log"},
    }
    (run_dir / "artifacts.json").write_text(
        json.dumps(artifacts, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    return run_dir


def run_replay(
    *,
    run_id: str,
    harvester_release: str,
    results_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    events = load_events(results_path)
    panel = extract_panel(events)
    residuals = compute_residuals(panel)
    rejection_flags = compute_rejection_flags(residuals, events)
    operator_diag = compute_operator_diagnostics(events)
    benchmark_rows = compute_benchmark_comparison(panel, residuals)
    validation_loop = compute_validation_loop_status(residuals, rejection_flags, operator_diag, benchmark_rows)
    run_dir = write_run_package(
        run_id=run_id,
        harvester_release=harvester_release,
        events=events,
        panel=panel,
        residuals=residuals,
        rejection_flags=rejection_flags,
        operator_diag=operator_diag,
        benchmark_rows=benchmark_rows,
        validation_loop=validation_loop,
        output_root=output_root,
        results_path=results_path,
    )
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "residuals": residuals,
        "rejection_flags": rejection_flags,
        "operator_diagnostics": operator_diag,
        "validation_loop": validation_loop,
        "benchmark_rows": benchmark_rows,
        "n_events": len(events),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", default=None, help="run id (default: <today>_C005_MORPHOLOGY)")
    parser.add_argument("--results", default=str(REPLAY_RESULTS), help="path to structural_replay_v2 results.json")
    parser.add_argument("--output-root", default=str(DEFORMATION_RUNS), help="root for Output/deformation_runs/")
    parser.add_argument("--harvester-release", default="2026-05-05-r1", help="harvester release id for provenance")
    args = parser.parse_args(argv)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y-%m-%d_C005_MORPHOLOGY")
    results_path = Path(args.results)
    output_root = Path(args.output_root)
    if not results_path.exists():
        print(f"ERROR: results.json not found at {results_path}", file=sys.stderr)
        return 2

    summary = run_replay(
        run_id=run_id,
        harvester_release=args.harvester_release,
        results_path=results_path,
        output_root=output_root,
    )

    print(f"Wrote C005 morphology run -> {summary['run_dir']}")
    print(f"Events: {summary['n_events']}")
    print("Residual correlations:")
    for key, value in summary["residuals"].items():
        print(f"  {key}: {value:+.4f}")
    active = sorted(k for k, v in summary["rejection_flags"].items() if v)
    print(f"Active rejection flags: {', '.join(active) if active else 'none'}")
    print(f"Validation loop status: {summary['validation_loop']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
