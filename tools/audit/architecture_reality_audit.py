#!/usr/bin/env python3
"""Architecture Reality Audit — automated governance drift detection.

Checks that governance declarations match code reality.
See: governance/architecture_reality_decisions.md §10

Usage:
    python3 scripts/commands/weekly/architecture_reality_audit.py
    python3 scripts/commands/weekly/architecture_reality_audit.py --json
    python3 scripts/commands/weekly/architecture_reality_audit.py --strict  # exit 1 on any finding

Output:
    Output/system_learning/latest/architecture_reality_audit.md
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from verity.runtime._constants import TIMEOUT_SHORT  # noqa: E402
from verity.runtime.runtime_io import ROOT, ensure_dir, surface_dir  # noqa: E402
from verity.runtime.runtime_io import load_yaml as _load_yaml

logger = logging.getLogger(__name__)

FRAMEWORK_SRC = ROOT / "packages" / "framework_v1_archive" / "src"
CAPABILITY_REGISTRY = ROOT / "governance" / "capability_registry.yaml"
DAILY_PIPELINE_REGISTRY = ROOT / "governance" / "daily_pipeline_registry.yaml"
MODULES_MD = ROOT / "MODULES.md"
OUTPUT_DIR = surface_dir("system_learning") / "latest"


def _report_output_dir() -> Path:
    """Report directory, isolated from the checkout on ephemeral CI runners.

    GitHub Actions runs this audit inside a fresh checkout where the
    clean-checkout boundary contract (scripts/commands/ci/clean_checkout_boundary.py)
    forbids materializing ``Output/`` content; reports land in a temporary
    directory there instead of the workspace surface.
    """
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        return Path(tempfile.mkdtemp(prefix="architecture-reality-audit-"))
    return OUTPUT_DIR


def _framework_self_check_heartbeat() -> dict[str, Any]:
    """Invoke Framework's public self-check; central control only aggregates."""
    result = subprocess.run(
        [sys.executable, "-m", "src.validation.architecture_self_check", "--json"],
        cwd=ROOT / "packages" / "framework_v1_archive",
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SHORT,
    )
    if result.returncode not in {0, 1}:
        issue = {"issue": "Framework self-check unavailable", "stderr": result.stderr[-300:]}
        return {
            "checks": {
                "framework_http_imports": [issue],
                "framework_api_keys": [],
                "unmarked_http_in_framework": [],
            }
        }
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        issue = {"issue": "Framework self-check returned invalid heartbeat"}
        return {
            "checks": {
                "framework_http_imports": [issue],
                "framework_api_keys": [],
                "unmarked_http_in_framework": [],
            }
        }


_LIVE_OPERATOR_ROOTS = (
    ROOT / "scripts",
    ROOT / "verity",
    ROOT / "tools",
    ROOT / "packages" / "workbench" / "src",
    ROOT / "packages" / "learning_hub" / "src",
    ROOT / "packages" / "orchestration",
    ROOT / "system_runtime",
    ROOT / "system_cli",
)
_SKIP_PARTS = {"__pycache__", "tests", "build", "dist"}


def _iter_live_operator_python() -> list[Path]:
    files: list[Path] = []
    for root in _LIVE_OPERATOR_ROOTS:
        if not root.exists():
            continue
        for py_file in root.rglob("*.py"):
            if any(part in _SKIP_PARTS or part.endswith(".egg-info") for part in py_file.parts):
                continue
            files.append(py_file)
    return files


def _scan_root_provider_acquisition() -> list[dict[str, str]]:
    """Live operator trees must not directly import provider clients such as OpenBB."""
    forbidden = {"openbb", "yfinance", "pandas_datareader"}
    findings = []
    for py_file in _iter_live_operator_python():
        try:
            source = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Skip scripts marked ARCHIVE_CANDIDATE — they are already flagged for removal
        if "ARCHIVE_CANDIDATE" in source[:500]:
            continue
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden or any(alias.name.startswith(f"{f}.") for f in forbidden):
                        module = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module in forbidden or any(node.module.startswith(f"{f}.") for f in forbidden)):
                    module = node.module
            if module:
                findings.append({
                    "file": str(py_file.relative_to(ROOT)),
                    "line": str(node.lineno),
                    "import": module,
                    "rule": "Provider acquisition must run through Harvester, not root scripts.",
                })
    return findings


def _scan_root_harness_import_hacks() -> list[dict[str, str]]:
    """Root scripts must use public harness entrypoints, not Workbench internals."""
    findings = []
    pattern = re.compile(
        r"HARNESS_SRC|sys\.path\.insert\(.*Workbench.*agents|from\s+harness\.|from\s+tools\.task_router"
    )
    for py_file in _iter_live_operator_python():
        if py_file.resolve() == Path(__file__).resolve():
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if pattern.search(line):
                findings.append({
                    "file": str(py_file.relative_to(ROOT)),
                    "line": str(lineno),
                    "match": line.strip(),
                    "rule": "Root scripts must call Agent Routing through a public CLI/API.",
                })
    return findings


def _check_daily_pipeline_registry() -> list[dict[str, str]]:
    """Every daily_run step should have an explicit registry entry."""
    registry = _load_yaml(DAILY_PIPELINE_REGISTRY).get("steps", {})
    if not registry:
        return [{"missing": str(DAILY_PIPELINE_REGISTRY.relative_to(ROOT))}]

    daily_run = ROOT / "verity" / "cli" / "daily_run.py"
    try:
        source = daily_run.read_text(encoding="utf-8")
    except OSError:
        return [{"missing": str(daily_run.relative_to(ROOT))}]

    found = sorted(set(re.findall(r'run_step\("([^"]+)"', source)))
    missing = [name for name in found if name not in registry]
    return [{"step": name, "rule": "daily_run step missing from governance/daily_pipeline_registry.yaml"} for name in missing]


def _check_daily_pipeline_compatibility_steps() -> list[dict[str, str]]:
    """Surface compatibility/deprecated steps still used by the daily pipeline."""
    registry = _load_yaml(DAILY_PIPELINE_REGISTRY).get("steps", {})
    findings = []
    for step, spec in registry.items():
        if spec.get("status") in {"compatibility", "blocked"}:
            findings.append({
                "step": step,
                "status": str(spec.get("status")),
                "owner": str(spec.get("owner", "")),
                "blocker": str(spec.get("blocker", "")),
            })
    return findings


def _check_forbidden_exec_open() -> list[dict[str, str]]:
    """Scan live operator trees for exec(open(...).read()) — a security red line."""
    findings = []
    for py_file in _iter_live_operator_python():
        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        in_docstring = False
        for lineno, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            # Track docstring state
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            if stripped.startswith("#"):
                continue
            # Skip string comparisons (the audit check itself)
            if '"exec(' in stripped or "'exec(" in stripped:
                continue
            if "exec(open(" in stripped or "exec(open (" in stripped:
                findings.append({
                    "script": str(py_file.relative_to(ROOT)),
                    "line": str(lineno),
                    "code": stripped[:120],
                })
    return findings


def _check_legacy_display_in_current() -> list[dict[str, str]]:
    """Check that Output/current does not contain legacy deformation display files."""
    legacy_names = {
        "latest_report.html",
        "latest_dashboard.json",
        "latest_screenshot.png",
    }
    # Also check for latest_run directory or symlink
    current = surface_dir("current")
    findings = []
    if not current.exists():
        return findings
    for item in current.iterdir():
        if item.name in legacy_names:
            findings.append({
                "file": str(item.relative_to(ROOT)),
                "type": "directory" if item.is_dir() else "symlink" if item.is_symlink() else "file",
                "action": "move_to_Output/archive/legacy_display/",
            })
        if item.name == "latest_run" and (item.is_symlink() or item.is_dir()):
            findings.append({
                "file": str(item.relative_to(ROOT)),
                "type": "symlink" if item.is_symlink() else "directory",
                "action": "move_to_Output/archive/legacy_display/",
            })
    return findings


def _check_manual_sys_path_insert() -> list[dict[str, str]]:
    """Scan all production Python trees for path surgery."""
    scan_roots = [
        ROOT / "scripts",
        ROOT / "verity",
        ROOT / "tools",
        ROOT / "packages",
        ROOT / "caselab_context",
        ROOT / "caselab_runtime",
        ROOT / "research_terminal",
    ]
    allowed_path_surgery = {
        "verity/runtime/_deformation_archive_guard.py",
    }
    findings = []
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for py_file in sorted(scan_root.rglob("*.py")):
            relative = py_file.relative_to(ROOT)
            optional_tooling = (
                relative.parts[:3] == ("packages", "workbench", "agents")
                or relative.parts[:3] == ("packages", "framework", "apps")
            )
            if "tests" in py_file.parts or optional_tooling:
                continue
            if str(relative).replace("\\", "/") in allowed_path_surgery:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(source.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                path_mutation = "sys.path" + ".insert"
                if path_mutation in stripped:
                    findings.append(
                        {
                            "script": str(py_file.relative_to(ROOT)),
                            "line": str(lineno),
                            "code": stripped[:120],
                        }
                    )
    return findings


def _check_legacy_deadline_countdown() -> list[dict[str, str]]:
    """Check deferred_work_register.yaml for legacy items approaching deadline."""
    reg_path = ROOT / "governance" / "deferred_work_register.yaml"
    reg = _load_yaml(reg_path)
    if not reg:
        return []

    findings = []
    today = datetime.now(UTC).date()
    terminal_statuses = frozenset({"completed", "completed_sealed", "cancelled", "archived"})
    for item in reg.get("items", []):
        if str(item.get("status", "")).lower() in terminal_statuses:
            continue
        hard_dl = item.get("hard_deadline")
        if not hard_dl:
            continue
        try:
            deadline = datetime.strptime(str(hard_dl), "%Y-%m-%d").date()
        except ValueError:
            continue
        days_left = (deadline - today).days
        if days_left < 0:
            findings.append({
                "id": item.get("id", "unknown"),
                "status": "OVERDUE",
                "days_overdue": str(-days_left),
                "hard_deadline": str(hard_dl),
            })
        elif days_left <= 14:
            findings.append({
                "id": item.get("id", "unknown"),
                "status": "APPROACHING",
                "days_left": str(days_left),
                "hard_deadline": str(hard_dl),
            })
    return findings


def _check_data_retention_policy_unapplied() -> list[dict[str, str]]:
    """Check if data retention policy exists but has no executor script."""
    policy_path = ROOT / "governance" / "data_retention_policy.yaml"
    executor_path = ROOT / "scripts" / "apply_data_retention_policy.py"
    output_routing_path = ROOT / "scripts" / "apply_output_routing_policy.py"

    findings = []
    if policy_path.exists() and not executor_path.exists():
        findings.append({
            "policy": "governance/data_retention_policy.yaml",
            "missing": "scripts/apply_data_retention_policy.py",
            "note": "Policy exists but no executor script to enforce it",
        })
    routing_policy = ROOT / "governance" / "output_routing_policy.yaml"
    if routing_policy.exists() and not output_routing_path.exists():
        findings.append({
            "policy": "governance/output_routing_policy.yaml",
            "missing": "scripts/apply_output_routing_policy.py",
            "note": "Policy exists but no executor script to enforce it",
        })
    return findings


def _check_symlinks_fresh(output_dir: Path, max_age_days: int = 7) -> list[dict[str, str]]:
    """Check that symlinks in Output/current point to recent artifacts."""
    findings = []
    current = surface_dir("current") if output_dir == ROOT else output_dir / "Output" / "current"
    if not current.exists():
        return findings
    # Legacy Deformation display artifacts — not authoritative current state.
    # Authoritative: framework_output.json + status.json + 00_READ_ME_FIRST.md
    legacy_display_only = {
        "latest_run", "latest_dashboard.json", "latest_report.html", "latest_screenshot.png",
    }
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    for item in current.iterdir():
        if item.is_symlink():
            target = item.resolve()
            classification = "legacy_display_only" if item.name in legacy_display_only else "active"
            if target.exists():
                mtime = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC)
                if mtime < cutoff:
                    findings.append({
                        "symlink": str(item.relative_to(ROOT)),
                        "target": str(target.relative_to(ROOT)),
                        "age_days": str((datetime.now(UTC) - mtime).days),
                        "classification": classification,
                    })
            else:
                findings.append({
                    "symlink": str(item.relative_to(ROOT)),
                    "target": "BROKEN",
                    "age_days": "N/A",
                    "classification": classification,
                })
    return findings


def _check_legacy_imports_in_main_pipeline() -> list[dict[str, str]]:
    """Check that main pipeline scripts don't import legacy data_sources/data_hub."""
    legacy_modules = {"src.data.data_sources", "src.data.gateway.data_hub"}
    main_scripts = [
        ROOT / "verity" / "cli" / "daily_run.py",
        ROOT / "packages" / "framework_v1_archive" / "scripts" / "structural_replay_v2.py",
        ROOT / "packages" / "workbench" / "src" / "workbench" / "surfaces" / "refresh_output_current.py",
        ROOT / "packages" / "framework_v1_archive" / "scripts" / "bridge_replay_to_current.py",
    ]
    findings = []
    for script in main_scripts:
        if not script.exists():
            continue
        try:
            source = script.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            for legacy in legacy_modules:
                if legacy in line and not line.strip().startswith("#"):
                    findings.append({
                        "script": str(script.relative_to(ROOT)),
                        "line": str(lineno),
                        "imports": legacy,
                    })
    return findings


def _check_active_partial_lifecycle() -> list[dict[str, str]]:
    """Check 17: Track how long modules have been ACTIVE_PARTIAL.

    Modules stuck in ACTIVE_PARTIAL for >60 days without a review_date
    are flagged. >90 days is escalated to BLOCKED severity.
    """
    registry = _load_yaml(CAPABILITY_REGISTRY)
    if not registry:
        return []

    findings: list[dict[str, str]] = []
    today = datetime.now(UTC).date()

    for name, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "ACTIVE_PARTIAL":
            continue

        # Check for explicit review_date in the entry
        review_date_str = entry.get("review_date")
        if review_date_str:
            try:
                review_date = datetime.fromisoformat(str(review_date_str)).date()
                if review_date >= today:
                    continue  # review date not yet reached
            except (ValueError, TypeError):
                logger.warning("Invalid architecture review date: %s", review_date_str, exc_info=True)

        # Try to find when status was set via git log
        try:
            result = subprocess.run(
                [
                    "git", "log", "--format=%aI", "--follow", "-1",
                    "--", str(CAPABILITY_REGISTRY.relative_to(ROOT)),
                ],
                capture_output=True, text=True, cwd=str(ROOT), timeout=TIMEOUT_SHORT,
            )
            if result.returncode == 0 and result.stdout.strip():
                last_modified = datetime.fromisoformat(
                    result.stdout.strip().split("\n")[0]
                ).date()
                age_days = (today - last_modified).days
            else:
                age_days = None
        except (subprocess.TimeoutExpired, OSError, ValueError):
            age_days = None

        if age_days is not None and age_days > 90:
            findings.append({
                "module": name,
                "status": "ACTIVE_PARTIAL",
                "age_days": str(age_days),
                "severity": "BLOCKED",
                "message": (
                    f"{name} has been ACTIVE_PARTIAL for {age_days} days "
                    f"(>90 day threshold). Consider promoting or demoting."
                ),
            })
        elif age_days is not None and age_days > 60:
            findings.append({
                "module": name,
                "status": "ACTIVE_PARTIAL",
                "age_days": str(age_days),
                "severity": "WARN",
                "message": (
                    f"{name} has been ACTIVE_PARTIAL for {age_days} days "
                    f"(>60 day threshold). Review needed."
                ),
            })

    return findings


def run_audit() -> dict[str, Any]:
    """Run all architecture reality checks."""
    results: dict[str, Any] = {
        "audit_timestamp": datetime.now(UTC).isoformat(),
        "cadence": "weekly",
        "source_run_id": os.environ.get("ZCODE_BUNDLE_RUN_ID"),
        "audit_version": "1.0.0",
        "checks": {},
    }
    findings_count = 0

    # Checks 1/2 are owned by Framework; central S3 only aggregates its heartbeat.
    framework_heartbeat = _framework_self_check_heartbeat()
    http_findings = framework_heartbeat["checks"]["framework_http_imports"]
    results["checks"]["framework_http_imports"] = {
        "status": "PASS" if not http_findings else "FAIL",
        "findings": http_findings,
    }
    if http_findings:
        findings_count += len(http_findings)

    # Check 2: Framework API key references
    api_key_findings = framework_heartbeat["checks"]["framework_api_keys"]
    results["checks"]["framework_api_keys"] = {
        "status": "PASS" if not api_key_findings else "FAIL",
        "findings": api_key_findings,
    }
    if api_key_findings:
        findings_count += len(api_key_findings)

    # Check 3: Legacy imports in main pipeline
    legacy_findings = _check_legacy_imports_in_main_pipeline()
    results["checks"]["legacy_imports_in_pipeline"] = {
        "status": "PASS" if not legacy_findings else "WARN",
        "findings": legacy_findings,
    }
    if legacy_findings:
        findings_count += len(legacy_findings)

    # Check 4: Symlink freshness
    symlink_findings = _check_symlinks_fresh(ROOT)
    results["checks"]["symlink_freshness"] = {
        "status": "PASS" if not symlink_findings else "WARN",
        "findings": symlink_findings,
    }
    if symlink_findings:
        findings_count += len(symlink_findings)

    # Check 5: Required governance files exist
    required_files = [
        "governance/capability_registry.yaml",
        "governance/daily_run_sequence.yaml",
        "governance/system_constitution.yaml",
        "governance/authority_registry.yaml",
        "governance/architecture_reality_decisions.md",
        "protocols/evidence_release.schema.json",
    ]
    missing_files = []
    for f in required_files:
        if not (ROOT / f).exists():
            missing_files.append(f)
    results["checks"]["required_governance_files"] = {
        "status": "PASS" if not missing_files else "FAIL",
        "findings": [{"missing": f} for f in missing_files],
    }
    if missing_files:
        findings_count += len(missing_files)

    # Check 6: Evidence release schema exists
    schema_path = ROOT / "protocols" / "evidence_release.schema.json"
    results["checks"]["evidence_release_schema"] = {
        "status": "PASS" if schema_path.exists() else "FAIL",
        "findings": [] if schema_path.exists() else [{"missing": "protocols/evidence_release.schema.json"}],
    }
    if not schema_path.exists():
        findings_count += 1

    # Check 7: Root scripts must not acquire provider data directly
    root_provider_findings = _scan_root_provider_acquisition()
    results["checks"]["root_provider_acquisition"] = {
        "status": "PASS" if not root_provider_findings else "FAIL",
        "findings": root_provider_findings,
    }
    if root_provider_findings:
        findings_count += len(root_provider_findings)

    # Check 8: Root scripts must not import Agent Routing internals directly
    harness_hack_findings = _scan_root_harness_import_hacks()
    results["checks"]["root_harness_import_hacks"] = {
        "status": "PASS" if not harness_hack_findings else "WARN",
        "findings": harness_hack_findings,
    }
    if harness_hack_findings:
        findings_count += len(harness_hack_findings)

    # Check 9: Daily pipeline governance registry coverage
    pipeline_registry_findings = _check_daily_pipeline_registry()
    results["checks"]["daily_pipeline_registry"] = {
        "status": "PASS" if not pipeline_registry_findings else "FAIL",
        "findings": pipeline_registry_findings,
    }
    if pipeline_registry_findings:
        findings_count += len(pipeline_registry_findings)

    # Check 10: Compatibility or blocked steps still in daily pipeline
    compatibility_findings = _check_daily_pipeline_compatibility_steps()
    results["checks"]["daily_pipeline_noncanonical_steps"] = {
        "status": "PASS" if not compatibility_findings else "WARN",
        "findings": compatibility_findings,
    }
    if compatibility_findings:
        findings_count += len(compatibility_findings)

    # Check 11: Forbidden exec(open(...)) in root scripts
    exec_findings = _check_forbidden_exec_open()
    results["checks"]["forbidden_exec_open"] = {
        "status": "PASS" if not exec_findings else "FAIL",
        "findings": exec_findings,
    }
    if exec_findings:
        findings_count += len(exec_findings)

    # Check 12: Legacy display files in Output/current
    legacy_display_findings = _check_legacy_display_in_current()
    results["checks"]["output_current_legacy_display"] = {
        "status": "PASS" if not legacy_display_findings else "FAIL",
        "findings": legacy_display_findings,
    }
    if legacy_display_findings:
        findings_count += len(legacy_display_findings)

    # Check 13: Unmarked HTTP in Framework research files
    unmarked_http_findings = framework_heartbeat["checks"]["unmarked_http_in_framework"]
    results["checks"]["unmarked_http_in_framework"] = {
        "status": "PASS" if not unmarked_http_findings else "WARN",
        "findings": unmarked_http_findings,
    }
    if unmarked_http_findings:
        findings_count += len(unmarked_http_findings)

    # Check 14: Manual sys.path.insert in root scripts
    sys_path_findings = _check_manual_sys_path_insert()
    results["checks"]["manual_sys_path_insert"] = {
        "status": "PASS" if not sys_path_findings else "WARN",
        "findings": sys_path_findings,
    }
    if sys_path_findings:
        findings_count += len(sys_path_findings)

    # Check 15: Legacy deadline countdown
    deadline_findings = _check_legacy_deadline_countdown()
    results["checks"]["legacy_deadline_countdown"] = {
        "status": "PASS" if not deadline_findings else "WARN",
        "findings": deadline_findings,
    }
    if deadline_findings:
        findings_count += len(deadline_findings)

    # Check 16: Data retention policy executor
    retention_findings = _check_data_retention_policy_unapplied()
    results["checks"]["data_retention_policy_unapplied"] = {
        "status": "PASS" if not retention_findings else "WARN",
        "findings": retention_findings,
    }
    if retention_findings:
        findings_count += len(retention_findings)

    # Check 17: ACTIVE_PARTIAL lifecycle tracking
    active_partial_findings = _check_active_partial_lifecycle()
    results["checks"]["active_partial_lifecycle"] = {
        "status": "PASS" if not active_partial_findings else "WARN",
        "findings": active_partial_findings,
    }
    if active_partial_findings:
        findings_count += len(active_partial_findings)

    results["summary"] = {
        "total_findings": findings_count,
        "overall_status": "PASS" if findings_count == 0 else "FINDINGS",
    }
    return results


def generate_markdown_report(results: dict[str, Any]) -> str:
    """Generate a markdown report from audit results."""
    lines = [
        "# Architecture Reality Audit Report",
        "",
        f"**Generated:** {results['audit_timestamp']}",
        f"**Overall status:** {results['summary']['overall_status']}",
        f"**Total findings:** {results['summary']['total_findings']}",
        "",
        "---",
        "",
    ]
    for check_name, check_data in results["checks"].items():
        status_icon = "✅" if check_data["status"] == "PASS" else "⚠️" if check_data["status"] == "WARN" else "❌"
        lines.append(f"## {status_icon} {check_name}")
        lines.append("")
        lines.append(f"**Status:** {check_data['status']}")
        lines.append("")
        if check_data["findings"]:
            lines.append("**Findings:**")
            lines.append("")
            for finding in check_data["findings"]:
                lines.append(f"- {json.dumps(finding)}")
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Generated by scripts/commands/weekly/architecture_reality_audit.py*")
    lines.append("*Authority: governance/architecture_reality_decisions.md §10*")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Architecture Reality Audit")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any findings")
    args = parser.parse_args()

    results = run_audit()

    output_dir = _report_output_dir()
    # Write markdown report
    ensure_dir(output_dir)
    report_path = output_dir / "architecture_reality_audit.md"
    report_path.write_text(generate_markdown_report(results), encoding="utf-8")

    # Write JSON
    json_path = output_dir / "architecture_reality_audit.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(f"Architecture Reality Audit: {results['summary']['overall_status']}")
        print(f"Findings: {results['summary']['total_findings']}")
        print(f"Report: {report_path}")

    if args.strict and results["summary"]["total_findings"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
