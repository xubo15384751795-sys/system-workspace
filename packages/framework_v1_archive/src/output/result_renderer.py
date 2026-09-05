from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from src.core.interfaces import SnapshotStoreInterface
from src.core.runtime_context import RuntimePaths
from src.output.run_package import export_research_run_package


def render_latest_result(config: dict[str, Any]) -> dict[str, str]:
    """Render the latest persisted run into a stable human-readable report."""

    # Import lazily: runtime.assembly imports output exporters while assembling
    # the pipeline, so a module-level selector import would create a cycle.
    from src.runtime.assembly import _build_snapshot_store

    store = _build_snapshot_store(config)
    latest = _latest_snapshot(store)
    if latest is None:
        store_root = getattr(store, "root", getattr(store, "path", "configured snapshot store"))
        raise FileNotFoundError(f"no snapshots found in {store_root}")
    history = list(store.iter_range("1900-01-01", latest.run_date))

    output_cfg = config.get("output", {}) or {}
    output_root = Path(str(output_cfg.get("dir", str(RuntimePaths.discover().output_root)))).expanduser()
    package = export_research_run_package(
        snapshot=latest,
        history=history,
        config=config,
        output_root=output_root,
        export_image=bool(output_cfg.get("export_image", True)),
        image_width=int(output_cfg.get("image_width", 1400)),
    )
    reports_dir = output_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    dashboard_artifacts = package.get("dashboard_snapshot", {})
    stable_paths = _write_stable_latest_files(reports_dir, dashboard_artifacts)
    index_path = _write_index(reports_dir, latest.run_date, dashboard_artifacts, stable_paths, package)
    result = dict(dashboard_artifacts)
    result.update(stable_paths)
    result["index"] = str(index_path)
    result["run_package"] = package["package_dir"]
    result["executive_summary"] = package["executive_summary"]
    result["artifacts"] = package["artifacts"]
    return result


def _latest_snapshot(store: SnapshotStoreInterface):
    latest = None
    for snapshot in store.iter_range("1900-01-01", "2999-12-31"):
        latest = snapshot
    return latest


def _write_stable_latest_files(reports_dir: Path, artifacts: dict[str, str]) -> dict[str, str]:
    stable: dict[str, str] = {}
    for key, filename in (("html", "latest.html"), ("json", "latest.json"), ("png", "latest.png")):
        source = artifacts.get(key)
        if not source:
            continue
        source_path = Path(source)
        if not source_path.exists():
            continue
        target = reports_dir / filename
        shutil.copyfile(source_path, target)
        stable[f"latest_{key}"] = str(target)
    return stable


def _write_index(
    reports_dir: Path,
    latest_run_date: str,
    artifacts: dict[str, str],
    stable_paths: dict[str, str],
    package: dict[str, Any],
) -> Path:
    entries = {
        "latest_run_date": latest_run_date,
        "latest": stable_paths,
        "run_package": package.get("package_dir"),
        "executive_summary": package.get("executive_summary"),
        "artifacts": package.get("artifacts"),
        "dashboard_snapshot": artifacts,
    }
    index_path = reports_dir / "index.json"
    index_path.write_text(json.dumps(entries, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return index_path


__all__ = ["render_latest_result"]
