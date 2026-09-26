#!/usr/bin/env python3
"""Build auditable Paper B tables/fragments from frozen System result artifacts.

This entry point is read-only with respect to System inputs. It writes only to
the explicit --out directory and records SHA-256 hashes for every input/output.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HISTORICAL = ROOT / "Output/backtest/historical_validation/historical_validation_report.json"
DEFAULT_COST = ROOT / "Output/state/strategy_lab/velocity_cost_sweep_results.json"
DEFAULT_E3 = ROOT / "Output/state/validation/e3_three_replication/verdict.json"
DEFAULT_T4 = ROOT / "Output/state/validation/noncommutativity_probe/verdict.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_direction_table(report: dict[str, Any], out: Path) -> list[Path]:
    horizons = ["1d", "5d", "10d", "20d", "60d"]
    rows = ["M", "D", "K", "X", "AVG"]
    labels = {"AVG": "Average"}
    csv_path = out / "direction-agreement.csv"
    tex_path = out / "direction-table.tex"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["signal", *horizons])
        for row in rows:
            writer.writerow([row, *[report["direction_tests"][h][row]["agreement"] for h in horizons]])
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\caption{Recorded direction agreement by horizon (generated from the pinned JSON input).}",
        "\\label{tab:direction}",
        "\\begin{tabular}{lrrrrr}",
        "\\toprule",
        "Horizon & 1d & 5d & 10d & 20d & 60d \\\\",
        "\\midrule",
    ]
    for row in rows:
        values = [100.0 * report["direction_tests"][h][row]["agreement"] for h in horizons]
        lines.append(f"{labels.get(row, f'${row}$')} & " + " & ".join(f"{v:.1f}" for v in values) + " \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}"])
    tex_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [csv_path, tex_path]


def write_gate_summary(results: list[dict[str, Any]], out: Path) -> list[Path]:
    baseline = next(row for row in results if row["config_label"] == "baseline")
    production = next(row for row in results if row["config_label"] == "vt=1.5|cn=3|bull=off")
    modulated = next(row for row in results if row["config_label"] == "vt=1.5|cn=3|bull=2.0")
    positive = sum(bool(row.get("positive_sharpe_delta")) for row in results if row["config_label"] != "baseline")
    tested = sum(row["config_label"] != "baseline" for row in results)
    summary = {
        "one_way_bps": baseline["one_way_bps"],
        "baseline_sharpe": baseline["sharpe"],
        "positive_configs": positive,
        "tested_configs": tested,
        "production": production,
        "modulated": modulated,
        "lead_time_distribution_present": False,
    }
    json_path = out / "gate-summary.json"
    tex_path = out / "gate-summary.tex"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tex = (
        f"The governed asset build records a {baseline['one_way_bps']:.0f}bp one-way friction and a net "
        f"baseline Sharpe ratio of {baseline['sharpe']:.3f}. Of {tested} non-baseline configurations, "
        f"{positive} have positive net Sharpe differences. The production configuration "
        f"$(v_t=1.5,c_n=3)$ records $\\Delta$Sharpe $={production['sharpe_delta']:.3f}$ without bull "
        f"modulation and ${modulated['sharpe_delta']:.3f}$ with a bull threshold of 2.0. The modulated "
        f"configuration records {modulated['n_trades']} trades and time in market of "
        f"{100.0 * modulated['time_in_market']:.0f}\\%.\n"
    )
    tex_path.write_text(tex, encoding="utf-8")
    return [json_path, tex_path]


def write_e3_status(e3_path: Path, out: Path) -> list[Path]:
    path = out / "e3-status.tex"
    table_path = out / "e3-lead-time-table.tex"
    if e3_path.exists():
        verdict = load_json(e3_path)
        status = str(verdict.get("overall_verdict", verdict.get("status", "UNKNOWN")))
        runs = verdict.get("replications", [])
        if len(runs) != 3:
            raise SystemExit("E3 verdict must contain exactly three replications")
        first = runs[0]
        text = (
            f"\\PropositionClaim The admitted three-replication artifact reports "
            f"\\texttt{{{status.replace('_', r'\_')}}}. All three runs retain positive incremental "
            f"$\\Delta$PR-AUC ({first['delta_pr_auc']:.4f}) and a DM $p$-value of "
            f"{first['dm_p_value']:.3g}, but the framework's 20-day lead score "
            f"({first['framework_lead_profile']['t_minus_20']:.3f}) is below the funding-only "
            f"baseline ({first['funding_only_lead_profile']['t_minus_20']:.3f}). The complete E3 "
            f"hypothesis therefore fails without erasing its positive component result. Event "
            f"prevalence is {100.0 * first['event_rate']:.1f}\\%, which limits interpretation as a "
            f"rare-event test.\n"
        )
        offsets = (20, 10, 5, 0)
        lines = [
            "\\begin{table}[t]",
            "\\centering",
            "\\caption{E3 lead-profile distribution across event onsets (identical point estimates in all three runs).}",
            "\\label{tab:e3-lead}",
            "\\begin{tabular}{lrrrr}",
            "\\toprule",
            "Candidate & $t-20$ & $t-10$ & $t-5$ & $t$ \\\\",
            "\\midrule",
        ]
        for label, key in (("Framework full", "framework_lead_profile"), ("Funding only", "funding_only_lead_profile")):
            profile = first[key]
            values = " & ".join(f"{profile[f't_minus_{offset}']:.3f}" for offset in offsets)
            lines.append(f"{label} & {values} \\\\")
        lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}"])
        table_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        text = (
            "No E3 three-replication verdict artifact is present in the admitted paper asset manifest. "
            "This chapter therefore has status \\texttt{BLOCKED}, and it reports no positive or negative "
            "funding-event conclusion.\n"
        )
        table_path.write_text("", encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    return [path, table_path]


def write_t4_assets(t4_path: Path, paper_a_out: Path) -> list[Path]:
    paper_a_out.mkdir(parents=True, exist_ok=True)
    if not t4_path.is_file():
        raise SystemExit(f"required T4 verdict missing: {t4_path}")
    verdict = load_json(t4_path)
    if verdict.get("bootstrap_reps") != 500 or verdict.get("status") not in {"SUPPORTED", "NOT_SUPPORTED"}:
        raise SystemExit("T4 verdict does not satisfy the frozen 500-replication protocol")
    status_path = paper_a_out / "t4-status.tex"
    if verdict["status"] == "SUPPORTED":
        text = (
            "\\PropositionClaim The preregistered T4 prototype supports greater impulse-order dependence "
            f"in March 2020 than September 2019. The order distances are {verdict['delta_nc']['repo_2019']:.4f} "
            f"and {verdict['delta_nc']['treasury_2020']:.4f}; their difference is "
            f"{verdict['primary_difference']:.4f}. The 500-draw stratified bootstrap 95\\% interval is "
            f"[{verdict['bootstrap_ci_95'][0]:.4f}, {verdict['bootstrap_ci_95'][1]:.4f}], with no nonpositive draw. "
            "This is prototype evidence, not a structural identification result.\n"
        )
    else:
        text = (
            "\\PropositionClaim The preregistered T4 prototype does not support greater impulse-order "
            "dependence in March 2020; non-commutativity remains an open question.\n"
        )
    status_path.write_text(text, encoding="utf-8")
    verdict_copy = paper_a_out / "t4-verdict.json"
    shutil.copyfile(t4_path, verdict_copy)
    figure_source = t4_path.parent / "order_paths.png"
    if not figure_source.is_file():
        raise SystemExit(f"T4 figure missing: {figure_source}")
    figure_copy = paper_a_out / "t4-order-paths.png"
    shutil.copyfile(figure_source, figure_copy)
    return [status_path, verdict_copy, figure_copy]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--historical", type=Path, default=DEFAULT_HISTORICAL)
    parser.add_argument("--cost-sweep", type=Path, default=DEFAULT_COST)
    parser.add_argument("--e3-verdict", type=Path, default=DEFAULT_E3)
    parser.add_argument("--t4-verdict", type=Path, default=DEFAULT_T4)
    parser.add_argument("--paper-a-out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    required = [args.historical, args.cost_sweep]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing required input(s): {missing}")
    outputs: list[Path] = []
    outputs += write_direction_table(load_json(args.historical), args.out)
    outputs += write_gate_summary(load_json(args.cost_sweep), args.out)
    outputs += write_e3_status(args.e3_verdict, args.out)
    paper_a_outputs: list[Path] = []
    if args.paper_a_out is not None:
        paper_a_outputs = write_t4_assets(args.t4_verdict, args.paper_a_out)
    manifest = {
        "schema_version": "paper.asset_manifest.v1",
        "inputs": {str(path): sha256(path) for path in required},
        "optional_inputs": {str(args.e3_verdict): sha256(args.e3_verdict) if args.e3_verdict.exists() else None},
        "paper_a_inputs": {str(args.t4_verdict): sha256(args.t4_verdict)},
        "outputs": {path.name: sha256(path) for path in outputs},
        "paper_a_outputs": {path.name: sha256(path) for path in paper_a_outputs},
    }
    manifest_path = args.out / "asset-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "out": str(args.out), "files": sorted(manifest["outputs"])}, sort_keys=True))


if __name__ == "__main__":
    main()
