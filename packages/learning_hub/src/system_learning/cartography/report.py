from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from system_learning.cartography.drift_detector import detect_drift
from system_learning.cartography.import_graph import dependency_edges
from system_learning.cartography.metrics import complexity_hotspots, module_metrics, summary_counts
from system_learning.cartography.scanner import FileScan


def write_cartography_outputs(
    project_root: Path,
    scan_root: Path,
    scans: list[FileScan],
) -> dict[str, Path]:
    report_dir = project_root / "reports" / "codebase" / "latest"
    history_path = (
        scan_root / "Data" / "system_learning" / "structural_lab" / "codebase_metrics" / "history.parquet"
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    module_df = module_metrics(scans)
    edges_df = dependency_edges(scans)
    hotspots_df = complexity_hotspots(scans)
    previous_history = pd.read_parquet(history_path) if history_path.exists() else None
    violations_df, events = detect_drift(scans, module_df, edges_df, previous_history)

    module_metrics_path = report_dir / "module_metrics.csv"
    edges_path = report_dir / "dependency_edges.csv"
    violations_path = report_dir / "layer_violations.json"
    hotspots_path = report_dir / "complexity_hotspots.csv"
    structure_path = report_dir / "codebase_structure_report.md"
    drift_path = report_dir / "architecture_drift.md"
    events_path = report_dir / "system_events.jsonl"

    module_df.to_csv(module_metrics_path, index=False)
    edges_df.to_csv(edges_path, index=False)
    hotspots_df.to_csv(hotspots_path, index=False)
    violations_path.write_text(json.dumps(violations_df.to_dict(orient="records"), indent=2, default=str), encoding="utf-8")
    structure_path.write_text(structure_report(scan_root, scans, module_df, edges_df, hotspots_df), encoding="utf-8")
    drift_path.write_text(architecture_drift_report(violations_df), encoding="utf-8")
    events_path.write_text("\n".join(json.dumps(event, sort_keys=True, default=str) for event in events) + ("\n" if events else ""), encoding="utf-8")
    append_history(history_path, module_df)

    return {
        "codebase_structure_report": structure_path,
        "module_metrics": module_metrics_path,
        "dependency_edges": edges_path,
        "layer_violations": violations_path,
        "complexity_hotspots": hotspots_path,
        "architecture_drift": drift_path,
        "system_events": events_path,
        "history": history_path,
    }


def structure_report(scan_root: Path, scans: list[FileScan], module_df: pd.DataFrame, edges_df: pd.DataFrame, hotspots_df: pd.DataFrame) -> str:
    counts = summary_counts(scans)
    lines = [
        "# Codebase Structure Report",
        "",
        f"Scan root: `{scan_root}`",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for key, value in counts.items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", f"Local dependency edges: {len(edges_df)}", ""])
    lines.append("## Largest Module Directories")
    lines.append("")
    lines.extend(["| Directory | Files | LOC | Lines | Largest File |", "|---|---:|---:|---:|---|"])
    for _, row in module_df.head(20).iterrows():
        lines.append(f"| {row['directory']} | {row['file_count']} | {row['loc']} | {row['total_lines']} | {row['largest_file_path']} |")
    lines.extend(["", "## Complexity Hotspots", "", "| Path | LOC | Classes | Functions | Imports | Score |", "|---|---:|---:|---:|---:|---:|"])
    for _, row in hotspots_df.head(20).iterrows():
        lines.append(f"| {row['path']} | {row['loc']} | {row['classes']} | {row['functions']} | {row['imports']} | {row['hotspot_score']} |")
    return "\n".join(lines) + "\n"


def architecture_drift_report(violations_df: pd.DataFrame) -> str:
    lines = ["# Architecture Drift", ""]
    if violations_df.empty:
        lines.append("No architecture drift warnings were detected.")
        return "\n".join(lines) + "\n"
    lines.extend(["| Type | Severity | Path | Message |", "|---|---|---|---|"])
    for _, row in violations_df.iterrows():
        lines.append(f"| {row['violation_type']} | {row['severity']} | {row['path']} | {row['message']} |")
    return "\n".join(lines) + "\n"


def append_history(history_path: Path, module_df: pd.DataFrame) -> None:
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    run_id = timestamp.replace(":", "").replace("-", "")
    current = module_df.copy()
    current.insert(0, "run_id", run_id)
    current.insert(1, "timestamp", timestamp)
    if history_path.exists():
        previous = pd.read_parquet(history_path)
        current = pd.concat([previous, current], ignore_index=True)
    current.to_parquet(history_path, index=False)
