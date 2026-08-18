"""Apply data retention policy — dry-run executor.

Reads governance/data_retention_policy.yaml and checks each rule against
the actual Data/ directory.  Generates a report of violations.

WARNING: --apply is NOT yet implemented. Only dry-run mode works.
         Using --apply will print an error and exit.

Usage:
    python3 scripts/apply_data_retention_policy.py              # dry-run report
    python3 scripts/apply_data_retention_policy.py --json       # JSON output
    python3 scripts/apply_data_retention_policy.py --apply      # NOT IMPLEMENTED — exits with error

This script is the executor for governance/data_retention_policy.yaml.
First version: dry-run only (report).  --apply will be added in a future version.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT, ensure_dir, load_yaml, surface_dir

logger = logging.getLogger(__name__)

POLICY_PATH = ROOT / "governance" / "data_retention_policy.yaml"
OUTPUT_DIR = surface_dir("system_learning") / "latest"


def _load_policy() -> dict[str, Any]:
    return load_yaml(POLICY_PATH)


def _dir_size_mb(path: Path) -> float:
    """Estimate directory size in MB."""
    total = 0
    if not path.exists():
        return 0.0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                logger.warning("Unable to stat retained file: %s", f, exc_info=True)
    return total / (1024 * 1024)


def _check_harvester_debug_releases(policy: dict) -> list[dict[str, str]]:
    """Check for debug releases that should be archived."""
    findings = []
    config = policy.get("harvester_exports", {})
    if not config.get("archive_debug_releases"):
        return findings

    exports_dir = ROOT / "Data" / "harvester" / "exports"
    if not exports_dir.exists():
        return findings

    debug_names = set(config.get("current_debug_releases", []))
    for item in exports_dir.iterdir():
        if item.is_dir() and any(d in item.name for d in debug_names):
            findings.append({
                "path": str(item.relative_to(ROOT)),
                "status": "debug_release_should_archive",
                "target": config.get("debug_release_archive_path", "Data/archive/harvester_debug/"),
            })
    return findings


def _check_harvester_release_retention(policy: dict) -> list[dict[str, str]]:
    """Check finalized releases against ``keep_last_n_daily``.

    The policy has declared this rule since 2026-06-17 but nothing evaluated
    it, so exports grew unbounded to 883MB across 146 directories while the
    policy's own ``current_size_mb`` still read 205. Findings are split by
    how safe they are to act on: same-day releases superseded by a later
    ``rN`` are a different proposition from whole days outside the window.

    Reporting only — this never deletes. Releases are finalized evidence and
    removing them is an operator decision.
    """
    findings: list[dict[str, str]] = []
    config = policy.get("harvester_exports", {})
    keep_n = config.get("keep_last_n_daily")
    if not keep_n:
        return findings

    exports_dir = ROOT / "Data" / "harvester" / "exports"
    if not exports_dir.exists():
        return findings

    by_day: dict[str, list[tuple[int, Path]]] = {}
    for item in exports_dir.iterdir():
        if not item.is_dir() or item.is_symlink():
            continue
        match = re.match(r"(\d{4}-\d{2}-\d{2})-r(\d+)$", item.name)
        if match:
            by_day.setdefault(match.group(1), []).append((int(match.group(2)), item))

    if not by_day:
        return findings

    superseded = [
        path
        for releases in by_day.values()
        for _, path in sorted(releases)[:-1]
    ]
    if superseded:
        findings.append({
            "path": "Data/harvester/exports",
            "status": "superseded_same_day_releases",
            "count": str(len(superseded)),
            "size_mb": f"{sum(_dir_size_mb(p) for p in superseded):.1f}",
            "note": (
                "Same-day releases superseded by a later rN. No run bundle "
                "pins a release_id, so none of these are referenced."
            ),
        })

    kept_days = set(sorted(by_day)[-int(keep_n):])
    outside = [p for day, rs in by_day.items() if day not in kept_days for _, p in rs]
    if outside:
        findings.append({
            "path": "Data/harvester/exports",
            "status": "outside_keep_last_n_daily",
            "count": str(len(outside)),
            "days": str(len(by_day) - len(kept_days)),
            "size_mb": f"{sum(_dir_size_mb(p) for p in outside):.1f}",
            "note": f"Older than keep_last_n_daily={keep_n}; excludes monthly checkpoints.",
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


def run_retention_check() -> dict[str, Any]:
    """Run all retention policy checks."""
    policy = _load_policy()

    checks = {
        "harvester_debug_releases": _check_harvester_debug_releases(policy),
        "harvester_release_retention": _check_harvester_release_retention(policy),
        "structural_lab_runtime": _check_structural_lab_runtime(policy),
        "merged_data": _check_merged_data(policy),
        "panels_csv_exports": _check_panels_csv(policy),
        "data_root_size": _check_data_root_size(policy),
    }

    total_findings = sum(len(v) for v in checks.values())

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "policy": str(POLICY_PATH.relative_to(ROOT)),
        "mode": "dry-run",
        "checks": {k: {"count": len(v), "findings": v} for k, v in checks.items()},
        "summary": {
            "total_findings": total_findings,
            "overall_status": "CLEAN" if total_findings == 0 else "FINDINGS",
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
    parser.add_argument("--apply", action="store_true", help="Actually move files (not yet implemented)")
    args = parser.parse_args()

    if args.apply:
        raise SystemExit(
            "ERROR: --apply is not yet implemented. "
            "Use --json or default output for dry-run report."
        )

    results = run_retention_check()

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
