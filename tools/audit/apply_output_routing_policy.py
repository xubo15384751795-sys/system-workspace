"""Apply output routing policy — dry-run executor.

Reads governance/output_routing_policy.yaml and checks each rule against
the actual Output/ directory.  Generates a report of violations.

Usage:
    python3 scripts/apply_output_routing_policy.py              # dry-run report
    python3 scripts/apply_output_routing_policy.py --json       # JSON output
    python3 scripts/apply_output_routing_policy.py --apply      # actually move files (future)

This script is the executor for governance/output_routing_policy.yaml.
First version: dry-run only (report).  --apply will be added in a future version.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT, ensure_dir, load_yaml, surface_dir

POLICY_PATH = ROOT / "governance" / "output_routing_policy.yaml"
OUTPUT_DIR = surface_dir("system_learning") / "latest"
ARCHIVE_ROOT = ROOT / "Output" / "archive" / "output_routing_cleanup"
ACTIVE_SANDBOX_DEPENDENCIES = {"structural_replay_v2"}


def _load_policy() -> dict[str, Any]:
    return load_yaml(POLICY_PATH)


def _check_current_artifacts(policy: dict) -> list[dict[str, str]]:
    """Check Output/current/ against allowed_artifacts list."""
    findings = []
    current_config = policy.get("groups", {}).get("current", {})
    allowed = set(current_config.get("allowed_artifacts", []))
    if not allowed:
        return findings

    current_dir = surface_dir("current")
    if not current_dir.exists():
        return findings

    for item in current_dir.iterdir():
        if item.name not in allowed and not item.name.startswith("."):
            findings.append({
                "path": str(item.relative_to(ROOT)),
                "status": "unregistered_in_current",
                "type": "directory" if item.is_dir() else "symlink" if item.is_symlink() else "file",
                "note": "Not in output_routing_policy.groups.current.allowed_artifacts",
            })
    return findings


def _check_sandbox_ttl(policy: dict) -> list[dict[str, str]]:
    """Check for sandbox artifacts older than TTL."""
    findings = []
    sandbox_config = policy.get("groups", {}).get("sandbox", {})
    ttl_days = sandbox_config.get("default_ttl_days", 7)

    sandbox_dir = ROOT / "Output" / "state" / "sandbox"
    if not sandbox_dir.exists():
        return findings

    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    for item in sandbox_dir.iterdir():
        if item.name in ACTIVE_SANDBOX_DEPENDENCIES:
            continue
        if item.is_dir():
            mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=UTC)
            if mtime < cutoff:
                findings.append({
                    "path": str(item.relative_to(ROOT)),
                    "status": "sandbox_expired",
                    "age_days": str((datetime.now(UTC) - mtime).days),
                    "note": f"Older than {ttl_days} day TTL — move to archive",
                })
    return findings


def _check_research_ttl(policy: dict) -> list[dict[str, str]]:
    """Check for research artifacts older than TTL."""
    findings = []
    research_config = policy.get("groups", {}).get("research", {})
    ttl_days = research_config.get("default_ttl_days", 30)

    research_dir = ROOT / "Output" / "research"
    if not research_dir.exists():
        return findings

    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    for item in research_dir.iterdir():
        if item.is_dir():
            mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=UTC)
            if mtime < cutoff:
                findings.append({
                    "path": str(item.relative_to(ROOT)),
                    "status": "research_candidate_for_archive",
                    "age_days": str((datetime.now(UTC) - mtime).days),
                    "note": f"Older than {ttl_days} day TTL — consider archiving",
                })
    return findings


def _check_root_entries(policy: dict) -> list[dict[str, str]]:
    """Output/ top-level names must match policy.root_entries."""
    allowed = set(policy.get("root_entries") or [])
    if not allowed:
        return []
    output = ROOT / "Output"
    if not output.exists():
        return []
    present = {p.name for p in output.iterdir() if not p.name.startswith(".")}
    extra = sorted(present - allowed)
    missing = sorted(allowed - present)
    findings = []
    for name in extra:
        findings.append({
            "path": f"Output/{name}",
            "status": "unregistered_root_entry",
            "note": "Not in output_routing_policy.root_entries",
        })
    for name in missing:
        findings.append({
            "path": f"Output/{name}",
            "status": "missing_root_entry",
            "note": "Declared in root_entries but absent on disk",
        })
    live = output / "live"
    if live.is_symlink():
        target = os.readlink(live)
        if target.startswith("/") or "/Users/" in target:
            findings.append({
                "path": "Output/live",
                "status": "live_symlink_not_relative",
                "note": f"readlink={target!r}; expected generations/<run_id>",
            })
    return findings


def _check_legacy_display(policy: dict) -> list[dict[str, str]]:
    """Check for legacy display symlinks in Output/current."""
    findings = []
    legacy_names = {
        "latest_report.html",
        "latest_dashboard.json",
        "latest_screenshot.png",
        "latest_run",
    }

    current_dir = surface_dir("current")
    if not current_dir.exists():
        return findings

    for item in current_dir.iterdir():
        if item.name in legacy_names:
            findings.append({
                "path": str(item.relative_to(ROOT)),
                "status": "legacy_display_in_current",
                "type": "symlink" if item.is_symlink() else "file",
                "note": "Legacy display symlinks must not exist in Output/current/",
            })
    return findings


def _check_deformation_runs(policy: dict) -> list[dict[str, str]]:
    """Check deformation_runs for old latest symlinks."""
    findings = []
    runs_dir = ROOT / "Output" / "archive" / "legacy_2026H1" / "deformation_runs"
    if not runs_dir.exists():
        return findings

    for item in runs_dir.iterdir():
        if item.name == "latest" and item.is_symlink():
            target = item.resolve()
            if target.exists():
                mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC)
                age_days = (datetime.now(UTC) - mtime).days
                if age_days > 30:
                    findings.append({
                        "path": str(item.relative_to(ROOT)),
                        "status": "old_latest_symlink",
                        "age_days": str(age_days),
                        "note": "Old latest symlink in deformation_runs",
                    })
    return findings


def run_routing_check() -> dict[str, Any]:
    """Run all output routing checks."""
    policy = _load_policy()

    checks = {
        "current_artifacts": _check_current_artifacts(policy),
        "sandbox_ttl": _check_sandbox_ttl(policy),
        "research_ttl": _check_research_ttl(policy),
        "legacy_display": _check_legacy_display(policy),
        "deformation_runs": _check_deformation_runs(policy),
        "root_entries": _check_root_entries(policy),
    }

    total_findings = sum(len(v) for v in checks.values())

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "cadence": "weekly",
        "source_run_id": os.environ.get("ZCODE_BUNDLE_RUN_ID"),
        "policy": str(POLICY_PATH.relative_to(ROOT)),
        "mode": "dry-run",
        "checks": {k: {"count": len(v), "findings": v} for k, v in checks.items()},
        "summary": {
            "total_findings": total_findings,
            "overall_status": "CLEAN" if total_findings == 0 else "FINDINGS",
        },
    }


def _unique_target(base: Path) -> Path:
    if not base.exists() and not base.is_symlink():
        return base
    for index in range(1, 1000):
        candidate = base.with_name(f"{base.name}_{index}")
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise RuntimeError(f"Could not find unique archive target for {base}")


def apply_routing_cleanup(results: dict[str, Any]) -> dict[str, Any]:
    """Archive expired routing artifacts without deleting payloads."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = ARCHIVE_ROOT / run_id
    ensure_dir(archive_dir)

    actions: list[dict[str, str]] = []
    for finding in results["checks"]["sandbox_ttl"]["findings"]:
        source = ROOT / finding["path"]
        if not source.exists():
            continue
        target = _unique_target(archive_dir / "sandbox" / source.name)
        ensure_dir(target.parent)
        shutil.move(str(source), str(target))
        actions.append({
            "action": "archived_sandbox",
            "source": str(source.relative_to(ROOT)),
            "target": str(target.relative_to(ROOT)),
        })

    for finding in results["checks"]["deformation_runs"]["findings"]:
        source = ROOT / finding["path"]
        if not source.is_symlink():
            continue
        target = _unique_target(archive_dir / "deformation_runs" / f"{source.name}.symlink.txt")
        ensure_dir(target.parent)
        target.write_text(f"{source} -> {source.readlink()}\n", encoding="utf-8")
        source.unlink()
        actions.append({
            "action": "archived_symlink_record",
            "source": str(source.relative_to(ROOT)),
            "target": str(target.relative_to(ROOT)),
        })

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "archive_dir": str(archive_dir.relative_to(ROOT)),
        "actions": actions,
    }
    (archive_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def generate_report(results: dict[str, str]) -> str:
    """Generate markdown report."""
    lines = [
        "# Output Routing Policy Report",
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
    parser = argparse.ArgumentParser(description="Apply output routing policy")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--apply", action="store_true", help="Actually move files (not yet implemented)")
    args = parser.parse_args()

    if args.apply:
        initial = run_routing_check()
        manifest = apply_routing_cleanup(initial)
        results = run_routing_check()
        results["mode"] = "apply"
        results["applied"] = manifest
    else:
        results = run_routing_check()

    ensure_dir(OUTPUT_DIR)
    report_path = OUTPUT_DIR / "output_routing_report.md"
    report_path.write_text(generate_report(results), encoding="utf-8")

    json_path = OUTPUT_DIR / "output_routing_report.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(generate_report(results))


if __name__ == "__main__":
    main()
