from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Any, cast


ROOT = _workspace_root()
OUTPUT = ROOT / "Output"
CURRENT = OUTPUT / "current"
WORKBENCH = OUTPUT / "workbench" / "artifacts"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return {}


def _safe_unlink(path: Path) -> None:
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            raise RuntimeError(f"Refusing to remove real directory: {path}")
        path.unlink()


def _link_current(target: Path, name: str) -> None:
    CURRENT.mkdir(parents=True, exist_ok=True)
    link = CURRENT / name
    _safe_unlink(link)
    link.symlink_to(Path("..") / "workbench" / "artifacts" / target.name)


def _artifact(name: str, rel_path: str, kind: str, open_first: bool = False) -> dict[str, Any]:
    path = ROOT / rel_path
    exists = path.exists()
    target = path.resolve() if exists else None
    return {
        "name": name,
        "path": rel_path,
        "kind": kind,
        "exists": exists,
        "target": str(target.relative_to(ROOT)) if target and str(target).startswith(str(ROOT)) else str(target) if target else None,
        "open_first": open_first,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    run = payload.get("model_run", {})
    lines = [
        "# Artifact Navigator",
        "",
        "This is a Workbench tool surface. It indexes user-facing artifacts without owning framework semantics.",
        "",
        "## Current Model Run",
        f"- Model ID: `{run.get('model_id', 'unknown')}`",
        f"- Producer: `{run.get('producer', 'unknown')}`",
        f"- Run ID: `{run.get('run_id', 'unknown')}`",
        f"- Run date: `{run.get('run_date', 'unknown')}`",
        f"- Status: `{run.get('status', 'unknown')}`",
        "",
        "## Open First",
        "",
        "| Artifact | Path | Kind | Status | Target |",
        "|---|---|---|---|---|",
    ]
    for item in payload["artifacts"]:
        if not item["open_first"]:
            continue
        status = "ok" if item["exists"] else "missing"
        lines.append(f"| {item['name']} | `{item['path']}` | {item['kind']} | {status} | `{item.get('target') or ''}` |")
    lines.extend(["", "## All Artifacts", "", "| Artifact | Path | Kind | Status |", "|---|---|---|---|"])
    for item in payload["artifacts"]:
        status = "ok" if item["exists"] else "missing"
        lines.append(f"| {item['name']} | `{item['path']}` | {item['kind']} | {status} |")
    lines.extend(
        [
            "",
            "## Commands",
            "- `./sys current`",
            "- `./sys open`",
            "- `./sys evidence`",
            "- `./sys artifacts`",
            "",
        ]
    )
    return "\n".join(lines)


def _artifacts_from_registry() -> list[dict[str, Any]] | None:
    registry = _read_json(CURRENT / "artifact_registry.json")
    entries = registry.get("artifacts")
    if not isinstance(entries, list) or not entries:
        return None

    open_first_names = {
        "00_READ_ME_FIRST.md",
        "framework_output.json",
        "status.json",
        "NEXT_ACTIONS.md",
        "evidence_grade_report.json",
        "artifact_registry.json",
        "benchmark_evidence_dashboard.md",
    }
    display_names = {
        "00_READ_ME_FIRST.md": "Current status card",
        "framework_output.json": "Framework output",
        "status.json": "Status",
        "NEXT_ACTIONS.md": "Next actions",
        "evidence_grade_report.json": "Evidence grade report",
        "artifact_registry.json": "Artifact registry",
        "benchmark_evidence_dashboard.md": "Benchmark evidence dashboard",
        "benchmark_evidence_dashboard.html": "Benchmark evidence HTML",
        "model_run.json": "Workbench model run",
        "model_run_macro_pressure_measurement.json": "Neutral macro pressure model run",
    }
    artifacts: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        display = display_names.get(name, name)
        rel_path = str(entry.get("path", f"Output/current/{name}"))
        if rel_path.endswith(".json"):
            kind = "json"
        elif rel_path.endswith(".html"):
            kind = "html"
        elif rel_path.endswith(".md"):
            kind = "markdown"
        else:
            kind = "text"
        item = _artifact(display, rel_path, kind, open_first=name in open_first_names)
        item["producer_step"] = entry.get("producer_step")
        artifacts.append(item)
    return artifacts or None


def build() -> dict[str, Path]:
    WORKBENCH.mkdir(parents=True, exist_ok=True)
    model_run = _read_json(CURRENT / "model_run_macro_pressure_measurement.json")
    if not model_run:
        model_run = _read_json(CURRENT / "model_run.json")
    artifacts = _artifacts_from_registry()
    if artifacts is None:
        artifacts = [
            _artifact("Current status card", "Output/current/00_READ_ME_FIRST.md", "markdown", True),
            _artifact("Framework output", "Output/current/framework_output.json", "json", True),
            _artifact("Status", "Output/current/status.json", "json", True),
            _artifact("Next actions", "Output/current/NEXT_ACTIONS.md", "markdown", True),
            _artifact("Evidence grade report", "Output/current/evidence_grade_report.json", "json", True),
            _artifact("Artifact registry", "Output/current/artifact_registry.json", "json", True),
            _artifact("System health", "Output/system_learning/latest/system_health_report.md", "markdown"),
            _artifact("Learning summary", "Output/system_learning/latest/learning_summary.md", "markdown"),
            _artifact("Benchmark evidence dashboard", "Output/current/benchmark_evidence_dashboard.md", "markdown", True),
            _artifact("Benchmark evidence HTML", "Output/current/benchmark_evidence_dashboard.html", "html"),
            _artifact("Neutral macro pressure model run", "Output/current/model_run_macro_pressure_measurement.json", "json"),
            _artifact("System latest index", "Data/system_index/latest.json", "json"),
            _artifact("System catalog", "Data/system_index/system_catalog.json", "json"),
            _artifact("Lineage graph", "Data/system_index/lineage_graph.json", "json"),
        ]
    payload = {
        "schema_version": "workbench.report_artifact.v1",
        "generated_at": _now(),
        "model_run": model_run,
        "artifacts": artifacts,
    }
    json_path = WORKBENCH / "artifact_navigator.json"
    md_path = WORKBENCH / "artifact_navigator.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    _link_current(md_path, "artifact_navigator.md")
    _link_current(json_path, "artifact_navigator.json")
    return {"json": json_path, "markdown": md_path}


def main() -> None:
    paths = build()
    print("Done.")
    print("Artifact Navigator:")
    print(f"  Markdown: {paths['markdown'].relative_to(ROOT)}")
    print(f"  JSON:     {paths['json'].relative_to(ROOT)}")
    print("Commands:")
    print("  ./sys artifacts")
    print("  ./sys current")


if __name__ == "__main__":
    main()
