from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Iterable

from src.core.models import Snapshot
from src.core.runtime_context import RuntimePaths
from src.output.output_exporter import export_snapshot_artifacts, snapshot_to_dict


def export_research_run_package(
    *,
    snapshot: Snapshot,
    history: Iterable[Snapshot] = (),
    config: dict[str, Any] | None = None,
    output_root: str | Path | None = None,
    export_image: bool = True,
    image_width: int = 1400,
) -> dict[str, Any]:
    """Write a standard Deformation research run package for one snapshot."""

    cfg = config or {}
    if output_root is None:
        output_root = RuntimePaths.discover().output_root
    root = Path(output_root).expanduser()
    run_id = _run_id(snapshot)
    package_dir = root / "deformation_runs" / run_id
    dirs = {
        "figures": package_dir / "figures",
        "tables": package_dir / "tables",
        "machine": package_dir / "machine",
        "diagnostics": package_dir / "diagnostics",
        "reports": package_dir / "reports",
        "logs": package_dir / "logs",
        "traces": package_dir / "traces",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    all_snapshots = list(history)
    if not any(item.run_date == snapshot.run_date for item in all_snapshots):
        all_snapshots.append(snapshot)
    all_snapshots.sort(key=lambda item: item.run_date)

    payload = snapshot_to_dict(snapshot)
    previous = _previous_snapshot(all_snapshots, snapshot.run_date)

    snapshot_json = dirs["machine"] / "snapshot.json"
    snapshot_json.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    component_table = _write_component_snapshot(dirs["tables"] / "component_snapshot.csv", snapshot, previous)
    state_table = _write_structural_state_table(dirs["machine"] / "structural_state.csv", all_snapshots)
    proxy_table = _write_proxy_readings_table(dirs["machine"] / "proxy_readings.csv", all_snapshots)
    benchmark_table = _write_benchmark_comparison(dirs["tables"] / "benchmark_comparison.csv", payload)
    diagnostics_files = _write_diagnostics(dirs["diagnostics"], payload)

    figures = _write_figures(dirs["figures"], all_snapshots, snapshot)
    dashboard_artifacts = export_snapshot_artifacts(
        snapshot=snapshot,
        output_dir=str(dirs["reports"]),
        export_image=export_image,
        image_width=image_width,
    )
    dashboard_artifacts = _standardize_report_artifacts(dirs["reports"], dashboard_artifacts)

    manifest = _run_manifest(snapshot=snapshot, config=cfg, package_dir=package_dir)
    config_snapshot_path = package_dir / "config_snapshot.json"
    config_snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": "deformation.config_snapshot.v1",
                "run_id": run_id,
                "captured_at": manifest["generated_at"],
                "captured_status": "captured",
                "config_hash": manifest["config_hash"],
                "config": cfg,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    trace_path = dirs["traces"] / "operator_trace.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "schema_version": "deformation.operator_trace.v1",
                "kind": "trace_header",
                "run_id": run_id,
                "status": "complete",
                "operator_count": 0,
                "note": "No applied operator records were emitted for this run package.",
            },
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = package_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    summary_path = dirs["reports"] / "executive_summary.md"
    summary_path.write_text(
        _executive_summary(snapshot=snapshot, payload=payload, previous=previous, manifest=manifest),
        encoding="utf-8",
    )

    logs_path = dirs["logs"] / "run.log"
    logs_path.write_text(
        f"Research run package generated at {manifest['generated_at']} for {snapshot.run_date}.\n",
        encoding="utf-8",
    )

    artifacts = {
        "run_id": run_id,
        "package_dir": str(package_dir),
        "executive_summary": str(summary_path),
        "dashboard_snapshot": dashboard_artifacts,
        "figures": figures,
        "tables": {
            "component_snapshot": str(component_table),
            "benchmark_comparison": str(benchmark_table),
        },
        "machine": {
            "snapshot": str(snapshot_json),
            "structural_state": str(state_table),
            "proxy_readings": str(proxy_table),
        },
        "diagnostics": diagnostics_files,
        "traces": {"operator_trace": str(trace_path)},
        "config_snapshot": str(config_snapshot_path),
        "manifests": {"run_manifest": str(manifest_path)},
        "logs": {"run_log": str(logs_path)},
        "reports": {
            "executive_summary": str(summary_path),
            "report_html": dashboard_artifacts.get("html"),
            "dashboard_snapshot": dashboard_artifacts.get("json"),
            "report_html_png": dashboard_artifacts.get("png"),
        },
    }
    artifacts_path = package_dir / "artifacts.json"
    artifacts_path.write_text(json.dumps(artifacts, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    artifacts["artifacts"] = str(artifacts_path)
    _update_latest_pointer(root, package_dir)
    return artifacts


def _run_id(snapshot: Snapshot) -> str:
    return f"{snapshot.run_date}_{snapshot.run_type}".replace(" ", "_").replace(":", "")


def _previous_snapshot(history: list[Snapshot], run_date: str) -> Snapshot | None:
    prior = [item for item in history if item.run_date < run_date]
    return prior[-1] if prior else None


def _write_component_snapshot(path: Path, snapshot: Snapshot, previous: Snapshot | None) -> Path:
    rows = []
    for channel in ("M", "D", "K", "X"):
        value = float(getattr(snapshot.proxy, channel))
        previous_value = float(getattr(previous.proxy, channel)) if previous is not None else None
        rows.append(
            {
                "run_date": snapshot.run_date,
                "channel": channel,
                "value": value,
                "previous_value": previous_value,
                "change": value - previous_value if previous_value is not None else None,
                "direction": snapshot.proxy.directions.get(channel, "UNKNOWN"),
                "available": snapshot.proxy.available.get(channel, False),
            }
        )
    _write_csv(path, rows)
    return path


def _write_structural_state_table(path: Path, snapshots: list[Snapshot]) -> Path:
    rows = [
        {
            "run_date": item.run_date,
            "run_type": item.run_type,
            "sigma_t": item.state.sigma_t,
            "singular_flag": item.state.singular_flag,
            "leading_channel": item.state.leading_channel,
            "pattern": item.state.pattern,
            "escalation": item.escalation,
            "escalation_reason": item.escalation_reason,
        }
        for item in snapshots
    ]
    _write_csv(path, rows)
    return path


def _write_proxy_readings_table(path: Path, snapshots: list[Snapshot]) -> Path:
    rows = []
    for item in snapshots:
        row = {
            "run_date": item.run_date,
            "M": item.proxy.M,
            "D": item.proxy.D,
            "K": item.proxy.K,
            "X": item.proxy.X,
            "sigma_t": item.state.sigma_t,
            "morphology": item.state.pattern,
        }
        rows.append(row)
    _write_csv(path, rows)
    return path


def _write_benchmark_comparison(path: Path, payload: dict[str, Any]) -> Path:
    diagnostic = payload.get("state", {}).get("structural_diagnostic_state") or {}
    benchmarks = diagnostic.get("benchmarks") or {}
    residuals = diagnostic.get("residual_diagnostics") or {}
    keys = sorted(set(benchmarks) | set(residuals))
    rows = [{"name": key, "benchmark_value": benchmarks.get(key), "residual_value": residuals.get(key)} for key in keys]
    if not rows:
        rows = [{"name": "not_available", "benchmark_value": None, "residual_value": None}]
    _write_csv(path, rows)
    return path


def _write_diagnostics(path: Path, payload: dict[str, Any]) -> dict[str, str]:
    diagnostic = payload.get("state", {}).get("structural_diagnostic_state") or {}
    operator = payload.get("state", {}).get("operator_diagnostics") or {}
    rejection_flags = diagnostic.get("rejection_flags") or {}
    residual_tests = diagnostic.get("residual_diagnostics") or {}
    files = {
        "rejection_flags": path / "rejection_flags.json",
        "residual_tests": path / "residual_tests.json",
        "operator_diagnostics": path / "operator_diagnostics.json",
        "validation_report": path / "validation_report.md",
    }
    files["rejection_flags"].write_text(json.dumps(rejection_flags, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    files["residual_tests"].write_text(json.dumps(residual_tests, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    files["operator_diagnostics"].write_text(json.dumps(operator, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    files["validation_report"].write_text(_validation_report(diagnostic), encoding="utf-8")
    return {key: str(value) for key, value in files.items()}


def _write_figures(path: Path, snapshots: list[Snapshot], snapshot: Snapshot) -> dict[str, str]:
    figures: dict[str, str] = {}
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return figures

    dates = [item.run_date for item in snapshots]
    sigma = [item.state.sigma_t for item in snapshots]
    fig, ax = plt.subplots(figsize=(8, 3.5))
    ax.plot(dates, sigma, marker="o", linewidth=1.5)
    ax.set_title("Sigma Timeline")
    ax.set_ylabel("sigma_t")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    sigma_path = path / "sigma_timeline.png"
    fig.savefig(sigma_path, dpi=150)
    plt.close(fig)
    figures["sigma_timeline"] = str(sigma_path)

    channels = ["M", "D", "K", "X"]
    values = [getattr(snapshot.proxy, channel) for channel in channels]
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar(channels, values)
    ax.set_title("M/D/K/X Component Snapshot")
    ax.set_ylabel("value")
    fig.tight_layout()
    components_path = path / "components.png"
    fig.savefig(components_path, dpi=150)
    plt.close(fig)
    figures["components"] = str(components_path)
    return figures


def _standardize_report_artifacts(reports_dir: Path, artifacts: dict[str, str]) -> dict[str, str]:
    names = {"html": "report.html", "json": "dashboard_snapshot.json", "png": "report.html.png"}
    standardized: dict[str, str] = {}
    for key, filename in names.items():
        source = artifacts.get(key)
        if not source:
            continue
        source_path = Path(source)
        target = reports_dir / filename
        if source_path.resolve() != target.resolve():
            if target.exists():
                target.unlink()
            source_path.replace(target)
        standardized[key] = str(target)
    return standardized


def _run_manifest(snapshot: Snapshot, config: dict[str, Any], package_dir: Path) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    harvester = config.get("harvester") or {}
    data = config.get("data") or {}
    return {
        "kind": "deformation_run",
        "schema_version": "deformation.run.v1",
        "run_id": _run_id(snapshot),
        "run_date": snapshot.run_date,
        "run_type": snapshot.run_type,
        "generated_at": generated_at,
        "status": "success",
        "git_commit": _git_commit(),
        "config_hash": _config_hash(config),
        "data_backend": data.get("backend") or config.get("data_backend") or (config.get("data_access") or {}).get("backend"),
        "harvester_release": harvester.get("release"),
        "harvester_exports_root": harvester.get("exports_root"),
        "model_version": "structural_deformation_research_system",
        "package_dir": str(package_dir),
        "config_snapshot_path": "config_snapshot.json",
        "machine_artifacts": {
            "snapshot": "machine/snapshot.json",
            "proxy_readings": "machine/proxy_readings.csv",
            "structural_state": "machine/structural_state.csv",
        },
        "traces": {"operator_trace": "traces/operator_trace.jsonl"},
        "diagnostics": {
            "validation_report": "diagnostics/validation_report.md",
            "operator_diagnostics": "diagnostics/operator_diagnostics.json",
            "rejection_flags": "diagnostics/rejection_flags.json",
            "residual_tests": "diagnostics/residual_tests.json",
        },
        "reports": {
            "executive_summary": "reports/executive_summary.md",
            "report_html": "reports/report.html",
            "report_html_png": "reports/report.html.png",
            "dashboard_snapshot": "reports/dashboard_snapshot.json",
        },
    }


def _executive_summary(
    *,
    snapshot: Snapshot,
    payload: dict[str, Any],
    previous: Snapshot | None,
    manifest: dict[str, Any],
) -> str:
    interpretation = payload.get("interpretation", {})
    changes = _change_lines(snapshot, previous)
    watchlist = _watchlist(snapshot, payload)
    return "\n".join(
        [
            f"# Structural Risk Run - {snapshot.run_date}",
            "",
            "## Main Signal",
            f"- Morphology: {snapshot.state.pattern}",
            f"- Sigma: {_fmt(snapshot.state.sigma_t)}",
            f"- Singular regime: {'yes' if snapshot.state.singular_flag else 'no'}",
            f"- Leading channel: {snapshot.state.leading_channel}",
            f"- Escalation: {'yes' if snapshot.escalation else 'no'}",
            "",
            "## Interpretation",
            str(interpretation.get("summary") or "No interpretation summary available."),
            "",
            "## M/D/K/X Snapshot",
            f"- M: {_fmt(snapshot.proxy.M)} ({snapshot.proxy.directions.get('M', 'UNKNOWN')})",
            f"- D: {_fmt(snapshot.proxy.D)} ({snapshot.proxy.directions.get('D', 'UNKNOWN')})",
            f"- K: {_fmt(snapshot.proxy.K)} ({snapshot.proxy.directions.get('K', 'UNKNOWN')})",
            f"- X: {_fmt(snapshot.proxy.X)} ({snapshot.proxy.directions.get('X', 'UNKNOWN')})",
            "",
            "## Change Vs Previous Run",
            *changes,
            "",
            "## Watchlist",
            *watchlist,
            "",
            "## Data And Reproducibility",
            f"- Data backend: {manifest.get('data_backend') or 'unknown'}",
            f"- Harvester release: {manifest.get('harvester_release') or 'not selected'}",
            f"- Git commit: {manifest.get('git_commit') or 'unknown'}",
            f"- Config hash: {manifest.get('config_hash')}",
            "",
            "## Caveats",
            "- This package summarizes the persisted structural snapshot and available diagnostics.",
            "- It is not a trading instruction.",
            "- Benchmark and residual sections are report diagnostics; they do not alter M/D/K/X proxy construction.",
            "",
        ]
    )


def _validation_report(diagnostic: dict[str, Any]) -> str:
    morphology = diagnostic.get("morphology") or {}
    flags = diagnostic.get("rejection_flags") or {}
    residuals = diagnostic.get("residual_diagnostics") or {}
    lines = [
        "# Validation Report",
        "",
        "## Morphology",
        f"- label: {morphology.get('label', 'not_available')}",
        f"- interpretation: {morphology.get('interpretation', 'not_available')}",
        "",
        "## Rejection Flags",
    ]
    if flags:
        lines.extend(f"- {key}: {value}" for key, value in sorted(flags.items()))
    else:
        lines.append("- not_available")
    lines.extend(["", "## Residual Diagnostics"])
    if residuals:
        lines.extend(f"- {key}: {value}" for key, value in sorted(residuals.items()))
    else:
        lines.append("- not_available")
    lines.append("")
    return "\n".join(lines)


def _change_lines(snapshot: Snapshot, previous: Snapshot | None) -> list[str]:
    if previous is None:
        return ["- No previous run available in the persisted history."]
    lines = []
    for channel in ("M", "D", "K", "X"):
        current = _to_float(getattr(snapshot.proxy, channel))
        prior = _to_float(getattr(previous.proxy, channel))
        delta = current - prior if current is not None and prior is not None else None
        lines.append(f"- {channel}: {_fmt(prior)} -> {_fmt(current)} ({_fmt(delta, signed=True)})")
    current_sigma = _to_float(snapshot.state.sigma_t)
    prior_sigma = _to_float(previous.state.sigma_t)
    sigma_delta = current_sigma - prior_sigma if current_sigma is not None and prior_sigma is not None else None
    lines.append(f"- Sigma: {_fmt(prior_sigma)} -> {_fmt(current_sigma)} ({_fmt(sigma_delta, signed=True)})")
    return lines


def _watchlist(snapshot: Snapshot, payload: dict[str, Any]) -> list[str]:
    rows = []
    leading = str(snapshot.state.leading_channel or "NONE")
    if leading != "NONE":
        rows.append(f"- Inspect leading structural channel: {leading}.")
    for channel in ("M", "D", "K", "X"):
        if str(snapshot.proxy.directions.get(channel, "")).upper() == "WORSENING":
            rows.append(f"- Review {channel} channel contributors and benchmark residuals.")
    if snapshot.escalation:
        rows.append(f"- Escalation reason: {snapshot.escalation_reason or 'not recorded'}.")
    diagnostic = payload.get("state", {}).get("structural_diagnostic_state") or {}
    morphology = diagnostic.get("morphology") or {}
    label = morphology.get("label")
    if label:
        rows.append(f"- Check morphology classification: {label}.")
    return rows or ["- Continue standard monitoring; no dominant watch item was emitted."]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _update_latest_pointer(output_root: Path, package_dir: Path) -> None:
    latest = output_root / "deformation_runs" / "latest"
    if latest.exists() or latest.is_symlink():
        if latest.is_symlink() or latest.is_file():
            latest.unlink()
        else:
            shutil.rmtree(latest)
    try:
        latest.symlink_to(package_dir.name)
    except OSError:
        shutil.copytree(package_dir, latest)


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def _config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fmt(value: Any, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except Exception:
        return str(value)
    prefix = "+" if signed and number >= 0 else ""
    return f"{prefix}{number:.3f}"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


__all__ = ["export_research_run_package"]
