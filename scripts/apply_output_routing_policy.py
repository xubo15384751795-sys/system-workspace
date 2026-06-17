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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "governance" / "output_routing_policy.yaml"
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"


def _load_policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def _check_current_artifacts(policy: dict) -> list[dict[str, str]]:
    """Check Output/current/ against allowed_artifacts list."""
    findings = []
    current_config = policy.get("groups", {}).get("current", {})
    allowed = set(current_config.get("allowed_artifacts", []))
    if not allowed:
        return findings

    current_dir = ROOT / "Output" / "current"
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

    sandbox_dir = ROOT / "Output" / "sandbox"
    if not sandbox_dir.exists():
        return findings

    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    for item in sandbox_dir.iterdir():
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


def _check_legacy_display(policy: dict) -> list[dict[str, str]]:
    """Check for legacy display symlinks in Output/current."""
    findings = []
    legacy_names = {
        "latest_report.html",
        "latest_dashboard.json",
        "latest_screenshot.png",
        "latest_run",
    }

    current_dir = ROOT / "Output" / "current"
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
    runs_dir = ROOT / "Output" / "deformation_runs"
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
        raise SystemExit(
            "ERROR: --apply is not yet implemented. "
            "Use --json or default output for dry-run report."
        )

    results = run_routing_check()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
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
