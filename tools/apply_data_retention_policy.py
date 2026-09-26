"""Apply data retention policy — dry-run report plus executable reclaim.

Reads governance/data_retention_policy.yaml.  ``--dry-run`` (default) lists
Harvester releases that would be removed.  ``--apply`` packs a recoverable
parquet+catalog archive, deletes the listed exports, strips retained JSONL,
and still moves eligible ``Output/runs`` into the policy archive.

Usage:
    python3 scripts/apply_data_retention_policy.py --dry-run
    python3 scripts/apply_data_retention_policy.py --json
    python3 scripts/apply_data_retention_policy.py --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT, ensure_dir, load_yaml, surface_dir

logger = logging.getLogger(__name__)

POLICY_PATH = ROOT / "governance" / "data_retention_policy.yaml"
OUTPUT_DIR = surface_dir("system_learning") / "latest"
RELEASE_DIR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-r(\d+)$")
RELEASE_ID_RE = re.compile(r"(20\d{2}-\d{2}-\d{2}-r\d+)")
DEFAULT_HARVESTER_ARCHIVE = "Data/archive/harvester_releases_2026H1.tar.zst"
DEFAULT_LINEAGE_GENERATIONS = 14


def _load_policy() -> dict[str, Any]:
    return load_yaml(POLICY_PATH)


def _dir_size_bytes(path: Path) -> int:
    """Estimate directory size without following directory symlinks."""
    total = 0
    if not path.exists():
        return 0
    for root, dirnames, filenames in os.walk(path, followlinks=False):
        root_path = Path(root)
        dirnames[:] = [name for name in dirnames if not (root_path / name).is_symlink()]
        for name in filenames:
            file_path = root_path / name
            if file_path.is_symlink():
                continue
            try:
                total += file_path.stat().st_size
            except OSError:
                logger.warning("Unable to stat retained file: %s", file_path, exc_info=True)
    return total


def _dir_size_mb(path: Path) -> float:
    """Estimate directory size in MB."""
    return _dir_size_bytes(path) / (1024 * 1024)


def _is_debug_release(name: str, debug_names: list[str] | tuple[str, ...] | set[str]) -> bool:
    lowered = name.lower()
    if lowered.startswith("test-debug"):
        return True
    return any(token and token in name for token in debug_names)


def _exports_dir() -> Path:
    return ROOT / "Data" / "harvester" / "exports"


def _latest_release_name(exports_dir: Path) -> str | None:
    latest = exports_dir / "latest"
    if not latest.is_symlink():
        return None
    target = Path(os.readlink(latest))
    return target.name


def _iter_top_level_dirs(exports_dir: Path) -> list[Path]:
    if not exports_dir.exists():
        return []
    dirs: list[Path] = []
    for item in exports_dir.iterdir():
        if item.is_symlink() or not item.is_dir():
            continue
        dirs.append(item)
    return dirs


def _dated_releases(exports_dir: Path) -> list[tuple[str, int, Path]]:
    found: list[tuple[str, int, Path]] = []
    for item in _iter_top_level_dirs(exports_dir):
        match = RELEASE_DIR_RE.match(item.name)
        if match:
            found.append((match.group(1), int(match.group(2)), item))
    found.sort(key=lambda row: (row[0], row[1]))
    return found


def _make_tree_writable(path: Path) -> None:
    for root, dirnames, filenames in os.walk(path, followlinks=False, topdown=True):
        root_path = Path(root)
        dirnames[:] = [name for name in dirnames if not (root_path / name).is_symlink()]
        try:
            mode = root_path.stat().st_mode
            os.chmod(root_path, mode | stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
        except OSError:
            logger.warning("Unable to chmod: %s", root_path, exc_info=True)
        for name in filenames:
            item = root_path / name
            if item.is_symlink():
                continue
            try:
                mode = item.stat().st_mode
                os.chmod(item, mode | stat.S_IWUSR | stat.S_IRUSR)
            except OSError:
                logger.warning("Unable to chmod: %s", item, exc_info=True)
    try:
        mode = path.stat().st_mode
        os.chmod(path, mode | stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
    except OSError:
        logger.warning("Unable to chmod: %s", path, exc_info=True)


def _generation_dirs() -> list[Path]:
    generations = ROOT / "Output" / "generations"
    dirs: list[Path] = []
    if generations.is_dir():
        for item in generations.iterdir():
            if item.is_symlink() or not item.is_dir():
                continue
            dirs.append(item)
    dirs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    live = ROOT / "Output" / "live"
    if live.exists():
        resolved = live.resolve()
        if resolved.is_dir() and resolved not in dirs:
            dirs.insert(0, resolved)
    return dirs


def _release_ids_from_text(text: str) -> set[str]:
    return set(RELEASE_ID_RE.findall(text))


def _release_ids_from_lineage(generation_dir: Path) -> set[str]:
    """Collect release ids written in lineage.json and the files it lists."""
    found: set[str] = set()
    lineage_path = generation_dir / "lineage.json"
    if not lineage_path.is_file() or lineage_path.is_symlink():
        return found
    try:
        text = lineage_path.read_text(encoding="utf-8")
    except OSError:
        return found
    found.update(_release_ids_from_text(text))
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return found
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return found
    for entry in files:
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("path") or "").strip()
        if not rel or rel.endswith(".jsonl"):
            continue
        artifact = generation_dir / rel
        if artifact.is_symlink() or not artifact.is_file():
            continue
        if artifact.suffix.lower() not in {".json", ".md", ".txt"}:
            continue
        if artifact.stat().st_size > 8_000_000:
            continue
        try:
            found.update(_release_ids_from_text(artifact.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return found


def _lineage_keep_names(exports_dir: Path, *, keep_generations: int) -> dict[str, str]:
    kept: dict[str, str] = {}
    existing = {item.name for item in _iter_top_level_dirs(exports_dir)}
    for generation in _generation_dirs()[:keep_generations]:
        for release_id in _release_ids_from_lineage(generation):
            if release_id in existing:
                kept[release_id] = f"lineage:{generation.name}"
    return kept


def plan_harvester_export_actions(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decide which export directories to keep, delete, and strip."""
    config = (policy or _load_policy()).get("harvester_exports", {})
    exports_dir = _exports_dir()
    debug_names = list(config.get("current_debug_releases") or [])
    keep_n = int(config.get("keep_last_n_daily") or 0)
    keep_latest = bool(config.get("keep_latest", True))
    keep_monthly = bool(config.get("keep_monthly_checkpoints", True))
    keep_generations = int(config.get("keep_lineage_generations") or DEFAULT_LINEAGE_GENERATIONS)
    archive_rel = str(config.get("archive_tarball") or DEFAULT_HARVESTER_ARCHIVE)
    keep_reasons: dict[str, list[str]] = {}

    def _keep(name: str, reason: str) -> None:
        keep_reasons.setdefault(name, []).append(reason)

    dated = _dated_releases(exports_dir)
    by_day: dict[str, list[tuple[int, Path]]] = {}
    for day, rev, path in dated:
        by_day.setdefault(day, []).append((rev, path))

    if keep_latest:
        latest_name = _latest_release_name(exports_dir)
        if latest_name:
            _keep(latest_name, "latest_symlink")

    if keep_n and by_day:
        for day in sorted(by_day)[-keep_n:]:
            rev, path = max(by_day[day], key=lambda row: row[0])
            _keep(path.name, f"last_{keep_n}_daily")

    if keep_monthly and dated:
        by_month: dict[str, list[tuple[str, int, Path]]] = {}
        for day, rev, path in dated:
            by_month.setdefault(day[:7], []).append((day, rev, path))
        for month, rows in by_month.items():
            rows.sort()
            _keep(rows[0][2].name, f"monthly_first:{month}")

    for name, reason in _lineage_keep_names(exports_dir, keep_generations=keep_generations).items():
        _keep(name, reason)

    debug_delete: list[str] = []
    delete: list[str] = []
    for item in _iter_top_level_dirs(exports_dir):
        if _is_debug_release(item.name, debug_names):
            debug_delete.append(item.name)
            keep_reasons.pop(item.name, None)
            continue
        if RELEASE_DIR_RE.match(item.name) and item.name not in keep_reasons:
            delete.append(item.name)

    delete.sort()
    debug_delete.sort()
    jsonl_strip: list[str] = []
    for name in sorted(keep_reasons):
        release = exports_dir / name
        if not release.is_dir() or release.is_symlink():
            continue
        for root, dirnames, filenames in os.walk(release, followlinks=False):
            root_path = Path(root)
            dirnames[:] = [d for d in dirnames if not (root_path / d).is_symlink()]
            for filename in filenames:
                if filename.endswith(".jsonl"):
                    jsonl_strip.append(str((root_path / filename).relative_to(exports_dir)))
    jsonl_strip.sort()
    return {
        "exports_dir": str(exports_dir.relative_to(ROOT)) if exports_dir.exists() else "Data/harvester/exports",
        "archive_tarball": archive_rel,
        "keep": {name: reasons for name, reasons in sorted(keep_reasons.items())},
        "delete": delete,
        "debug_delete": debug_delete,
        "strip_jsonl": jsonl_strip,
        "size_mb": f"{_dir_size_mb(exports_dir):.1f}" if exports_dir.exists() else "0.0",
    }


def _archive_members_for_release(release: Path) -> list[tuple[Path, str]]:
    members: list[tuple[Path, str]] = []
    catalog = release / "catalog.json"
    if catalog.is_file() and not catalog.is_symlink():
        members.append((catalog, f"{release.name}/catalog.json"))
    data_dir = release / "data"
    if data_dir.is_dir() and not data_dir.is_symlink():
        for root, dirnames, filenames in os.walk(data_dir, followlinks=False):
            root_path = Path(root)
            dirnames[:] = [d for d in dirnames if not (root_path / d).is_symlink()]
            for filename in filenames:
                path = root_path / filename
                if path.is_symlink() or path.suffix.lower() != ".parquet":
                    continue
                rel = path.relative_to(release).as_posix()
                members.append((path, f"{release.name}/{rel}"))
    return members


def _write_tar_zst(members: list[tuple[Path, str]], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd is required to write harvester_releases_2026H1.tar.zst")
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / "harvester_releases.tar"
        with tarfile.open(tar_path, "w") as tar:
            for source, arcname in members:
                tar.add(source, arcname=arcname, recursive=False)
        staged = dest.with_name(dest.name + ".tmp")
        subprocess.run(
            [zstd, "-f", "-T0", "-o", str(staged), str(tar_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        staged.replace(dest)


def _delete_release_dir(path: Path) -> None:
    _make_tree_writable(path)
    shutil.rmtree(path)


def apply_harvester_export_retention(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Archive parquet+catalog, delete reclaimable releases, strip retained JSONL."""
    loaded = policy or _load_policy()
    plan = plan_harvester_export_actions(loaded)
    exports_dir = _exports_dir()
    delete_names = list(plan["delete"]) + list(plan["debug_delete"])
    members: list[tuple[Path, str]] = []
    for name in delete_names:
        release = exports_dir / name
        if release.is_symlink() or not release.is_dir():
            continue
        members.extend(_archive_members_for_release(release))
    archive_path = ROOT / str(plan["archive_tarball"])
    archived = False
    if members:
        _write_tar_zst(members, archive_path)
        archived = True
    deleted: list[str] = []
    for name in delete_names:
        release = exports_dir / name
        if release.is_symlink() or not release.is_dir():
            continue
        _delete_release_dir(release)
        deleted.append(name)
    stripped: list[str] = []
    for rel in plan["strip_jsonl"]:
        path = exports_dir / rel
        if path.is_symlink() or not path.is_file() or not path.name.endswith(".jsonl"):
            continue
        try:
            _make_tree_writable(path.parent)
            path.unlink()
            stripped.append(rel)
        except OSError:
            logger.warning("Unable to strip JSONL: %s", path, exc_info=True)
    latest = exports_dir / "latest"
    latest_state = "symlink" if latest.is_symlink() else ("missing" if not latest.exists() else "not_symlink")
    return {
        "status": "harvester_exports_applied",
        "deleted": deleted,
        "deleted_count": str(len(deleted)),
        "archived": archived,
        "archive_path": str(plan["archive_tarball"]),
        "archive_members": str(len(members)),
        "stripped_jsonl": stripped,
        "stripped_jsonl_count": str(len(stripped)),
        "kept": plan["keep"],
        "latest": latest_state,
        "size_mb": f"{_dir_size_mb(exports_dir):.1f}" if exports_dir.exists() else "0.0",
    }


def live_lineage_unresolved_releases() -> list[str]:
    """Return lineage-referenced release ids missing under exports."""
    exports_dir = _exports_dir()
    existing = {item.name for item in _iter_top_level_dirs(exports_dir)}
    latest = _latest_release_name(exports_dir)
    if latest:
        existing.add(latest)
    missing: list[str] = []
    live = ROOT / "Output" / "live"
    generation = live.resolve() if live.exists() else None
    if generation is None or not generation.is_dir():
        current = surface_dir("current")
        generation = current.resolve() if current.exists() else None
        if generation is not None and generation.name == "current":
            generation = generation.parent
    if generation is None or not generation.is_dir():
        return missing
    for release_id in sorted(_release_ids_from_lineage(generation)):
        if release_id not in existing:
            missing.append(release_id)
    return missing


def _check_harvester_debug_releases(policy: dict) -> list[dict[str, str]]:
    """Report debug releases that --apply will delete."""
    plan = plan_harvester_export_actions(policy)
    return [
        {
            "path": f"Data/harvester/exports/{name}",
            "status": "debug_release_should_delete",
            "note": "test-debug* is always reclaimed; packed then deleted on --apply",
        }
        for name in plan["debug_delete"]
    ]


def _check_harvester_release_retention(policy: dict) -> list[dict[str, str]]:
    """Report reclaimable dated releases. Dry-run never mutates the tree."""
    config = policy.get("harvester_exports", {})
    if not config.get("keep_last_n_daily") and not config.get("keep_latest"):
        return []
    plan = plan_harvester_export_actions(policy)
    findings: list[dict[str, str]] = []
    if plan["delete"]:
        findings.append({
            "path": "Data/harvester/exports",
            "status": "harvester_releases_to_delete",
            "count": str(len(plan["delete"])),
            "size_mb": f"{sum(_dir_size_mb(_exports_dir() / name) for name in plan['delete']):.1f}",
            "note": (
                f"--dry-run lists {len(plan['delete'])} dated releases; "
                f"--apply packs catalog+parquet into {plan['archive_tarball']} then deletes."
            ),
        })
    if plan["strip_jsonl"]:
        findings.append({
            "path": "Data/harvester/exports",
            "status": "retained_jsonl_to_strip",
            "count": str(len(plan["strip_jsonl"])),
            "note": "Retained releases keep catalog+parquet; JSONL is stripped on --apply.",
        })
    return findings


def _check_structural_lab_runtime(policy: dict) -> list[dict[str, str]]:
    """Check structural_lab/runtime against retention policy."""
    findings = []
    config = policy.get("structural_lab", {}).get("runtime", {})
    if not config:
        return findings

    runtime_dir = ROOT / "Data" / "structural_lab" / "runtime"
    if not runtime_dir.exists():
        return findings

    status = config.get("status", "")
    archive_days = config.get("archive_after_days", 0)

    # Check DuckDB size
    db_path = runtime_dir / "system.duckdb"
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        if size_mb > 10:
            findings.append({
                "path": str(db_path.relative_to(ROOT)),
                "status": status,
                "size_mb": f"{size_mb:.1f}",
                "note": f"Large runtime store ({size_mb:.1f}MB) — {config.get('note', '')}",
            })

    # Check mtime
    if archive_days:
        cutoff = datetime.now(UTC) - timedelta(days=archive_days)
        for f in runtime_dir.rglob("*"):
            if f.is_file():
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
                if mtime < cutoff:
                    findings.append({
                        "path": str(f.relative_to(ROOT)),
                        "status": status,
                        "age_days": str((datetime.now(UTC) - mtime).days),
                        "note": f"Older than {archive_days} day retention",
                    })
                    break  # One finding per directory is enough
    return findings


def _check_merged_data(policy: dict) -> list[dict[str, str]]:
    """Check merged_data against retention policy."""
    findings = []
    config = policy.get("merged_data", {})
    if not config:
        return findings

    merged_dir = ROOT / "Data" / "merged_data"
    if not merged_dir.exists():
        return findings

    status = config.get("status", "")
    config.get("archive_after_days", 0)

    size_mb = _dir_size_mb(merged_dir)
    if size_mb > 0:
        findings.append({
            "path": str(merged_dir.relative_to(ROOT)),
            "status": status,
            "size_mb": f"{size_mb:.1f}",
            "note": config.get("note", ""),
        })
    return findings


def _check_panels_csv(policy: dict) -> list[dict[str, str]]:
    """Check for stale CSV exports in panels/."""
    findings = []
    config = policy.get("panels", {})
    csv_config = config.get("csv_exports", {})
    retention_days = csv_config.get("retention_days", 7)

    panels_dir = ROOT / "Data" / "panels"
    if not panels_dir.exists():
        return findings

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    for f in panels_dir.glob("*.csv*"):
        if f.is_file():
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
            if mtime < cutoff:
                findings.append({
                    "path": str(f.relative_to(ROOT)),
                    "status": "stale_csv_export",
                    "age_days": str((datetime.now(UTC) - mtime).days),
                    "note": f"CSV older than {retention_days} day retention",
                })
    return findings


def _check_data_root_size(policy: dict) -> list[dict[str, str]]:
    """Check Data/ total size against budget."""
    findings = []
    config = policy.get("data_root", {})
    budget = config.get("total_size_budget_mb", 300)

    data_dir = ROOT / "Data"
    if not data_dir.exists():
        return findings

    actual = _dir_size_mb(data_dir)
    if actual > budget:
        findings.append({
            "path": "Data/",
            "status": "over_budget",
            "actual_mb": f"{actual:.1f}",
            "budget_mb": str(budget),
            "note": f"Data/ is {actual - budget:.1f}MB over budget",
        })
    return findings


def _output_runs_state(policy: dict) -> dict[str, Any]:
    """Return the run directories outside both retention bounds."""
    config = policy.get("output_runs", {})
    runs_dir = ROOT / str(config.get("path", "Output/runs"))
    if not runs_dir.exists():
        return {
            "runs_dir": runs_dir,
            "archive_dir": ROOT / str(config.get("archive_path", "Output/archive/runs")),
            "keep_last_n": 0,
            "retention_days": 0,
            "cutoff": None,
            "candidates": [],
        }

    try:
        keep_last_n = max(0, int(config.get("keep_last_n", 200)))
        raw_retention_days = config.get("retention_days")
        retention_days = (
            max(0, int(raw_retention_days)) if raw_retention_days is not None else None
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("output_runs.keep_last_n and retention_days must be integers") from exc

    archive_dir = ROOT / str(config.get("archive_path", "Output/archive/runs"))
    runs_resolved = runs_dir.resolve()
    archive_resolved = archive_dir.resolve()
    if archive_resolved == runs_resolved or archive_resolved.is_relative_to(runs_resolved):
        raise ValueError("output_runs.archive_path must not be inside Output/runs")

    runs: list[Path] = []
    for item in runs_dir.iterdir():
        if item.is_dir() and not item.is_symlink():
            runs.append(item)
    runs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    cutoff = (
        datetime.now(UTC) - timedelta(days=retention_days)
        if retention_days
        else None
    )
    candidates = [
        item
        for index, item in enumerate(runs)
        if index >= keep_last_n
        and (cutoff is None or datetime.fromtimestamp(item.stat().st_mtime, tz=UTC) < cutoff)
    ]
    return {
        "runs_dir": runs_dir,
        "archive_dir": archive_dir,
        "keep_last_n": keep_last_n,
        "retention_days": retention_days,
        "cutoff": cutoff,
        "runs": runs,
        "candidates": candidates,
    }


def _check_output_runs_retention(policy: dict) -> list[dict[str, str]]:
    """Report old run bundles without changing the run tree."""
    config = policy.get("output_runs", {})
    if not config:
        return []
    state = _output_runs_state(policy)
    candidates = state["candidates"]
    if not candidates:
        return []
    return [
        {
            "path": str(state["runs_dir"].relative_to(ROOT)),
            "status": "output_runs_outside_retention",
            "count": str(len(candidates)),
            "total_count": str(len(state.get("runs", []))),
            "keep_last_n": str(state["keep_last_n"]),
            "retention_days": str(state["retention_days"]),
            "size_mb": f"{sum(_dir_size_mb(item) for item in candidates):.1f}",
            "archive_path": str(state["archive_dir"].relative_to(ROOT)),
            "note": "--apply moves these directories recoverably; it never deletes them.",
        }
    ]


def _apply_output_runs_retention(policy: dict) -> dict[str, str]:
    """Move eligible run bundles to the policy archive and report the action."""
    state = _output_runs_state(policy)
    candidates: list[Path] = state["candidates"]
    archive_dir: Path = state["archive_dir"]
    if not candidates:
        return {
            "status": "output_runs_clean",
            "count": "0",
            "path": str(state["runs_dir"].relative_to(ROOT)),
            "archive_path": str(archive_dir.relative_to(ROOT)),
        }

    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = 0
    for source in candidates:
        destination = archive_dir / source.name
        if destination.exists() or destination.is_symlink():
            suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            destination = archive_dir / f"{source.name}__archived_{suffix}"
        shutil.move(str(source), str(destination))
        archived += 1
    return {
        "status": "output_runs_archived",
        "count": str(archived),
        "path": str(state["runs_dir"].relative_to(ROOT)),
        "archive_path": str(archive_dir.relative_to(ROOT)),
    }


def run_retention_check(*, mode: str = "dry-run") -> dict[str, Any]:
    """Run all retention policy checks."""
    policy = _load_policy()

    checks = {
        "harvester_debug_releases": _check_harvester_debug_releases(policy),
        "harvester_release_retention": _check_harvester_release_retention(policy),
        "structural_lab_runtime": _check_structural_lab_runtime(policy),
        "merged_data": _check_merged_data(policy),
        "panels_csv_exports": _check_panels_csv(policy),
        "data_root_size": _check_data_root_size(policy),
        "output_runs": _check_output_runs_retention(policy),
    }

    total_findings = sum(len(v) for v in checks.values())
    harvester_plan = plan_harvester_export_actions(policy)

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "policy": str(POLICY_PATH.relative_to(ROOT)),
        "mode": mode,
        "harvester_plan": {
            "delete": harvester_plan["delete"],
            "debug_delete": harvester_plan["debug_delete"],
            "keep": harvester_plan["keep"],
            "strip_jsonl": harvester_plan["strip_jsonl"],
            "archive_tarball": harvester_plan["archive_tarball"],
            "exports_size_mb": harvester_plan["size_mb"],
        },
        "checks": {k: {"count": len(v), "findings": v} for k, v in checks.items()},
        "summary": {
            "total_findings": total_findings,
            "overall_status": "CLEAN" if total_findings == 0 else "FINDINGS",
            "harvester_delete_count": len(harvester_plan["delete"]) + len(harvester_plan["debug_delete"]),
        },
    }


def generate_report(results: dict[str, str]) -> str:
    """Generate markdown report."""
    lines = [
        "# Data Retention Policy Report",
        "",
        f"**Generated:** {results['timestamp']}",
        f"**Mode:** {results['mode']}",
        f"**Policy:** {results['policy']}",
        f"**Total findings:** {results['summary']['total_findings']}",
        "",
    ]
    plan = results.get("harvester_plan") or {}
    delete_list = list(plan.get("delete") or []) + list(plan.get("debug_delete") or [])
    if delete_list:
        lines.extend([
            "## Harvester releases to delete",
            "",
            f"Archive: `{plan.get('archive_tarball')}`",
            "",
        ])
        for name in delete_list:
            lines.append(f"- `{name}`")
        lines.append("")
    keep = plan.get("keep") or {}
    if keep:
        lines.extend(["## Harvester releases to keep", ""])
        for name, reasons in keep.items():
            joined = ", ".join(reasons) if isinstance(reasons, list) else str(reasons)
            lines.append(f"- `{name}` ({joined})")
        lines.append("")

    for check_name, check_data in results["checks"].items():
        icon = "✅" if check_data["count"] == 0 else "⚠️"
        lines.append(f"## {icon} {check_name} ({check_data['count']})")
        lines.append("")
        for finding in check_data["findings"]:
            lines.append(f"- `{finding['path']}`: {finding.get('status', '')}")
            if finding.get("note"):
                lines.append(f"  {finding['note']}")
        if not check_data["findings"]:
            lines.append("- No issues found")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply data retention policy")
    parser.add_argument("--json", action="store_true", help="JSON output")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="List Harvester releases that would be packed and deleted (default)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Pack then delete reclaimable Harvester releases; archive eligible Output/runs",
    )
    args = parser.parse_args()

    if args.apply:
        policy = _load_policy()
        harvester_action = apply_harvester_export_retention(policy)
        runs_action = _apply_output_runs_retention(policy)
        results = run_retention_check(mode="apply")
        results["actions"] = [harvester_action, runs_action]
        results["live_lineage_unresolved"] = live_lineage_unresolved_releases()
    else:
        results = run_retention_check(mode="dry-run")

    ensure_dir(OUTPUT_DIR)
    report_path = OUTPUT_DIR / "data_retention_report.md"
    report_path.write_text(generate_report(results), encoding="utf-8")

    json_path = OUTPUT_DIR / "data_retention_report.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(generate_report(results))


if __name__ == "__main__":
    main()
