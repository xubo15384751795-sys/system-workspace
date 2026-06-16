#!/usr/bin/env python3
"""Architecture Reality Audit — automated governance drift detection.

Checks that governance declarations match code reality.
See: governance/architecture_reality_decisions.md §10

Usage:
    python3 scripts/architecture_reality_audit.py
    python3 scripts/architecture_reality_audit.py --json
    python3 scripts/architecture_reality_audit.py --strict  # exit 1 on any finding

Output:
    Output/system_learning/latest/architecture_reality_audit.md
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FRAMEWORK_SRC = ROOT / "Structural Deformation Research System" / "src"
CAPABILITY_REGISTRY = ROOT / "governance" / "capability_registry.yaml"
DAILY_PIPELINE_REGISTRY = ROOT / "governance" / "daily_pipeline_registry.yaml"
MODULES_MD = ROOT / "MODULES.md"
OUTPUT_DIR = ROOT / "Output" / "system_learning" / "latest"


def _load_capability_registry() -> dict[str, Any]:
    """Load capability_registry.yaml."""
    try:
        import yaml
        return yaml.safe_load(CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict on failure."""
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _scan_for_http_imports(directory: Path) -> list[dict[str, str]]:
    """Scan a directory for HTTP client imports."""
    forbidden = {"requests", "httpx", "aiohttp", "urllib.request", "urllib3"}
    findings = []
    for py_file in directory.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden or any(alias.name.startswith(f + ".") for f in forbidden):
                        module = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module in forbidden or any(node.module.startswith(f + ".") for f in forbidden)):
                    module = node.module
            if module:
                findings.append({
                    "file": str(py_file.relative_to(ROOT)),
                    "line": str(node.lineno),
                    "import": module,
                })
    return findings


def _scan_root_provider_acquisition() -> list[dict[str, str]]:
    """Root scripts must not directly import provider clients such as OpenBB."""
    forbidden = {"openbb", "yfinance", "pandas_datareader"}
    findings = []
    scripts_dir = ROOT / "scripts"
    for py_file in scripts_dir.glob("*.py"):
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
    for py_file in (ROOT / "scripts").glob("*.py"):
        if py_file.name == "architecture_reality_audit.py":
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

    daily_run = ROOT / "scripts" / "daily_run.py"
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


def _scan_for_api_keys(directory: Path) -> list[dict[str, str]]:
    """Scan a directory for API key references."""
    patterns = re.compile(r"(api_key|API_KEY|apikey|APIKEY|secret_key|SECRET_KEY)", re.IGNORECASE)
    findings = []
    for py_file in directory.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            # Skip comments and docstrings
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if patterns.search(line):
                findings.append({
                    "file": str(py_file.relative_to(ROOT)),
                    "line": str(lineno),
                    "match": patterns.search(line).group(0) if patterns.search(line) else "",
                })
    return findings


def _check_symlinks_fresh(output_dir: Path, max_age_days: int = 7) -> list[dict[str, str]]:
    """Check that symlinks in Output/current point to recent artifacts."""
    from datetime import timedelta
    findings = []
    current = output_dir / "Output" / "current"
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
        ROOT / "scripts" / "daily_run.py",
        ROOT / "scripts" / "structural_replay_v2.py",
        ROOT / "scripts" / "refresh_output_current.py",
        ROOT / "scripts" / "bridge_replay_to_current.py",
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


def run_audit() -> dict[str, Any]:
    """Run all architecture reality checks."""
    results: dict[str, Any] = {
        "audit_timestamp": datetime.now(UTC).isoformat(),
        "audit_version": "1.0.0",
        "checks": {},
    }
    findings_count = 0

    # Check 1: Framework HTTP imports
    core_dirs = ["core", "operators", "diagnostics", "dynamics", "interpretation", "proxies", "derivation"]
    http_findings = []
    for dir_name in core_dirs:
        dir_path = FRAMEWORK_SRC / dir_name
        if dir_path.exists():
            http_findings.extend(_scan_for_http_imports(dir_path))
    results["checks"]["framework_http_imports"] = {
        "status": "PASS" if not http_findings else "FAIL",
        "findings": http_findings,
    }
    if http_findings:
        findings_count += len(http_findings)

    # Check 2: Framework API key references
    api_key_findings = []
    for dir_name in core_dirs:
        dir_path = FRAMEWORK_SRC / dir_name
        if dir_path.exists():
            api_key_findings.extend(_scan_for_api_keys(dir_path))
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
        "governance/daily_pipeline_registry.yaml",
        "governance/system_constitution.yaml",
        "governance/module_authority_registry.yaml",
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
    lines.append("*Generated by scripts/architecture_reality_audit.py*")
    lines.append(f"*Authority: governance/architecture_reality_decisions.md §10*")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Architecture Reality Audit")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any findings")
    args = parser.parse_args()

    results = run_audit()

    # Write markdown report
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / "architecture_reality_audit.md"
    report_path.write_text(generate_markdown_report(results), encoding="utf-8")

    # Write JSON
    json_path = OUTPUT_DIR / "architecture_reality_audit.json"
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
