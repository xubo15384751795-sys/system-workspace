"""deformation_tools — governed read-only tools for Deformation run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from tools.registry import ToolResult, ToolSpec, _register


HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
def _resolve_system_root(workbench_root: Path) -> Path:
    """Repo root for both legacy `Workbench/` and `packages/workbench` layouts."""
    parent = workbench_root.parent
    if workbench_root.name.lower() == "workbench" and parent.name == "packages":
        return parent.parent
    return parent

WORKSPACE_ROOT = _resolve_system_root(WORKBENCH_ROOT)
RUNS_ROOT = WORKSPACE_ROOT / "Output" / "deformation_runs"
CANONICAL_SNAPSHOT_INDEX = WORKSPACE_ROOT / "Data" / "deformation" / "snapshots" / "index.json"


def _resolve_snapshot(snapshot_id: str) -> Path | None:
    if snapshot_id == "latest":
        latest_sym = RUNS_ROOT / "latest"
        if latest_sym.is_symlink():
            return latest_sym.resolve()
        return None
    candidate = RUNS_ROOT / snapshot_id
    return candidate if candidate.is_dir() else None


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path.resolve())


def _run_dirs() -> list[Path]:
    if not RUNS_ROOT.is_dir():
        return []
    return [p for p in sorted(RUNS_ROOT.iterdir(), reverse=True) if p.is_dir() and not p.is_symlink()]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def _snapshot_json_path(run_dir: Path) -> Path | None:
    machine = run_dir / "machine" / "snapshot.json"
    if machine.is_file():
        return machine
    for child in sorted(run_dir.iterdir()):
        if child.suffix == ".json" and child.name not in (
            "run_manifest.json",
            "artifacts.json",
            "config_snapshot.json",
        ):
            return child
    fallback = run_dir / "data" / "snapshot.json"
    return fallback if fallback.is_file() else None


def _canonical_snapshot_entry(run_id: str, snapshot_id: str | None = None) -> dict[str, Any]:
    index = _read_json(CANONICAL_SNAPSHOT_INDEX)
    snapshots = index.get("snapshots", [])
    if not isinstance(snapshots, list):
        return {}
    if snapshot_id:
        for item in snapshots:
            if isinstance(item, dict) and item.get("snapshot_id") == snapshot_id:
                return item
    for item in snapshots:
        if isinstance(item, dict) and item.get("source_run_id") == run_id:
            return item
    latest = index.get("latest")
    for item in snapshots:
        if isinstance(item, dict) and item.get("snapshot_id") == latest:
            return item
    return {}


def _load_trace_header_and_count(path: Path) -> tuple[dict[str, Any], int, list[str]]:
    errors: list[str] = []
    if not path.is_file():
        return {}, 0, [f"operator trace missing: {_rel(path)}"]
    header: dict[str, Any] = {}
    record_count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for idx, line in enumerate(handle):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"operator trace line {idx + 1} invalid JSON: {exc}")
                    continue
                if idx == 0 and payload.get("kind") == "trace_header":
                    header = payload
                else:
                    record_count += 1
    except OSError as exc:
        errors.append(str(exc))
    return header, record_count, errors


def _compare_snapshots(run_snapshot: dict[str, Any], canonical_snapshot: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    keys = ["run_date", "run_type", "escalation", "snapshot_core"]
    for key in keys:
        if run_snapshot.get(key) != canonical_snapshot.get(key):
            mismatches.append(f"snapshot field mismatch: {key}")
    return mismatches


def _extract_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    proxy = snapshot.get("proxy", {})
    state = snapshot.get("state", {})
    interp = snapshot.get("interpretation", {})
    return {
        "run_date": snapshot.get("run_date"),
        "run_type": snapshot.get("run_type"),
        "escalation": snapshot.get("escalation"),
        "proxy": {ch: proxy.get(ch) for ch in ("M", "D", "K", "X")},
        "sigma_t": state.get("sigma_t"),
        "singular_flag": state.get("singular_flag"),
        "leading_channel": state.get("leading_channel"),
        "pattern": state.get("pattern"),
        "severity": interp.get("severity"),
        "summary": interp.get("summary"),
    }


def _h_list_snapshots(input: dict, dry_run: bool) -> ToolResult:
    if dry_run:
        return ToolResult(ok=True, tool_id="deformation.list_snapshots", summary="[DRY RUN] list snapshots")
    runs = _run_dirs()
    items: list[dict[str, Any]] = []
    for run_dir in runs:
        manifest = _read_json(run_dir / "run_manifest.json")
        items.append(
            {
                "run_id": run_dir.name,
                "run_date": manifest.get("run_date", ""),
                "run_type": manifest.get("run_type", ""),
                "status": manifest.get("status", ""),
                "generated_at": manifest.get("generated_at", ""),
            }
        )
    return ToolResult(
        ok=True,
        tool_id="deformation.list_snapshots",
        summary=f"Found {len(items)} deformation snapshots",
        evidence={"snapshots": items, "count": len(items)},
        warnings=[] if items else ["No deformation snapshots found"],
    )


def _h_inspect_snapshot(input: dict, dry_run: bool) -> ToolResult:
    snapshot_id = input.get("snapshot_id", "latest")
    if dry_run:
        return ToolResult(
            ok=True,
            tool_id="deformation.inspect_snapshot",
            summary=f"[DRY RUN] inspect snapshot {snapshot_id}",
        )
    run_dir = _resolve_snapshot(str(snapshot_id))
    if run_dir is None:
        return ToolResult(
            ok=False,
            tool_id="deformation.inspect_snapshot",
            errors=[f"Snapshot not found: {snapshot_id}"],
        )
    manifest = _read_json(run_dir / "run_manifest.json")
    snapshot_path = _snapshot_json_path(run_dir)
    snapshot = _read_json(snapshot_path) if snapshot_path else {}
    return ToolResult(
        ok=True,
        tool_id="deformation.inspect_snapshot",
        summary=f"Snapshot {run_dir.name}: status={manifest.get('status', '-')}",
        evidence={
            "run_id": run_dir.name,
            "manifest": manifest,
            "snapshot_summary": _extract_summary(snapshot),
        },
    )


def _h_evaluate_replay(input: dict, dry_run: bool) -> ToolResult:
    run_id = str(input.get("run_id") or input.get("snapshot_id") or "latest").strip()
    snapshot_id = str(input.get("canonical_snapshot_id") or input.get("canonical") or "").strip() or None
    run_dir = _resolve_snapshot(run_id)
    if run_dir is None:
        return ToolResult(
            ok=False,
            tool_id="deformation.evaluate_replay",
            evidence={
                "replay_evaluation": {
                    "run_id": run_id,
                    "verdict": "FAIL",
                    "errors": [f"deformation run not found: {run_id}"],
                }
            },
            errors=[f"deformation run not found: {run_id}"],
        )

    manifest_path = run_dir / "run_manifest.json"
    artifacts_path = run_dir / "artifacts.json"
    config_path = run_dir / "config_snapshot.json"
    freshness_path = run_dir / "freshness_manifest.json"
    trace_path = run_dir / "traces" / "operator_trace.jsonl"
    snapshot_path = _snapshot_json_path(run_dir)

    errors: list[str] = []
    warnings: list[str] = []
    mismatches: list[str] = []
    missing_required = [
        _rel(path)
        for path in [manifest_path, artifacts_path, config_path, freshness_path, trace_path]
        if not path.exists()
    ]
    if snapshot_path is None:
        missing_required.append(f"Output/deformation_runs/{run_dir.name}/machine/snapshot.json")
    if missing_required:
        errors.extend(f"missing required replay artifact: {path}" for path in missing_required)

    manifest = _read_json(manifest_path)
    artifacts = _read_json(artifacts_path)
    config = _read_json(config_path)
    freshness = _read_json(freshness_path)
    run_snapshot = _read_json(snapshot_path) if snapshot_path else {}

    canonical_entry = _canonical_snapshot_entry(run_dir.name, snapshot_id)
    canonical_path_raw = canonical_entry.get("snapshot_path") if canonical_entry else ""
    canonical_path = WORKSPACE_ROOT / canonical_path_raw if canonical_path_raw else None
    canonical_snapshot = _read_json(canonical_path) if canonical_path else {}
    if not canonical_entry:
        errors.append(f"canonical snapshot entry not found for run: {run_dir.name}")
    elif canonical_path is None or not canonical_path.is_file():
        errors.append(f"canonical snapshot file missing: {canonical_path_raw}")
    else:
        mismatches.extend(_compare_snapshots(run_snapshot, canonical_snapshot))

    trace_header, trace_record_count, trace_errors = _load_trace_header_and_count(trace_path)
    errors.extend(trace_errors)
    if trace_header.get("status") == "missing":
        warnings.append("operator_trace.jsonl header marks the trace as missing")
    if trace_record_count == 0:
        warnings.append("operator_trace.jsonl has no per-operator records")

    captured_status = config.get("captured_status")
    if captured_status in {"missing", "reconstructed_post_hoc"}:
        warnings.append(f"config_snapshot captured_status is {captured_status!r}")
    if not config.get("captured_at"):
        warnings.append("config_snapshot captured_at is missing")

    freshness_gate = freshness.get("gate_result") or manifest.get("freshness_gate_result") or {}
    if isinstance(freshness_gate, dict):
        warnings.extend(str(item) for item in freshness_gate.get("warnings", []) or [])
        errors.extend(str(item) for item in freshness_gate.get("blockers", []) or [])
    if freshness.get("model_input_validity") == "incomplete" or manifest.get("model_input_validity") == "incomplete":
        warnings.append("model_input_validity is incomplete")

    errors.extend(mismatches)
    verdict = "FAIL" if errors else "WARN" if warnings else "PASS"
    evaluation = {
        "run_id": run_dir.name,
        "run_path": _rel(run_dir),
        "canonical_snapshot_id": canonical_entry.get("snapshot_id"),
        "canonical_snapshot_path": canonical_path_raw,
        "verdict": verdict,
        "snapshot_match": not mismatches and bool(canonical_snapshot),
        "mismatches": mismatches,
        "artifacts": {
            "run_manifest": {"path": _rel(manifest_path), "exists": manifest_path.is_file()},
            "output_manifest": {"path": _rel(artifacts_path), "exists": artifacts_path.is_file()},
            "run_snapshot": {"path": _rel(snapshot_path) if snapshot_path else None, "exists": snapshot_path is not None},
            "canonical_snapshot": {
                "path": canonical_path_raw or None,
                "exists": bool(canonical_path and canonical_path.is_file()),
            },
            "config_snapshot": {
                "path": _rel(config_path),
                "exists": config_path.is_file(),
                "captured_status": captured_status,
                "captured_at": config.get("captured_at"),
            },
            "operator_trace": {
                "path": _rel(trace_path),
                "exists": trace_path.is_file(),
                "header_status": trace_header.get("status"),
                "record_count": trace_record_count,
            },
            "freshness_manifest": {
                "path": _rel(freshness_path),
                "exists": freshness_path.is_file(),
                "model_input_validity": freshness.get("model_input_validity") or manifest.get("model_input_validity"),
            },
        },
        "errors": errors,
        "warnings": warnings,
        "governed_surface": "packages/workbench/agents/harness/tools/deformation_tools.py",
    }
    return ToolResult(
        ok=not errors,
        tool_id="deformation.evaluate_replay",
        summary=f"Replay evaluation for {run_dir.name}: {verdict}",
        artifacts=[
            _rel(path)
            for path in [manifest_path, artifacts_path, config_path, freshness_path, trace_path]
            if path.exists()
        ],
        evidence={"replay_evaluation": evaluation},
        warnings=warnings,
        errors=errors,
    )


_register(ToolSpec(
    id="deformation.list_snapshots",
    description="List deformation run snapshots from Output/deformation_runs",
    subsystem="deformation",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=[],
    handler=_h_list_snapshots,
))

_register(ToolSpec(
    id="deformation.inspect_snapshot",
    description="Inspect a deformation snapshot by id or latest",
    subsystem="deformation",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=[],
    handler=_h_inspect_snapshot,
))

_register(ToolSpec(
    id="deformation.evaluate_replay",
    description=(
        "Evaluate replay readiness and canonical snapshot consistency for a "
        "Deformation run without mutating artifacts"
    ),
    subsystem="deformation",
    risk_level="low",
    read_only=True,
    mutates_artifacts=False,
    requires_approval=False,
    allowed_modes=["explore", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_evaluate_replay,
))
