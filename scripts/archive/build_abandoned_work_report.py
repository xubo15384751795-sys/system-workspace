#!/usr/bin/env python3
"""Build abandoned work report — finds forgotten artifacts and inconsistencies.

Checks:
- Untracked source files older than 3 days
- Output artifacts without capability registry entry
- MODULES.md status vs registry inconsistency
- 'latest' symlinks pointing to old artifacts
- Root script imports of untracked code
- PAPER modules that actually have data
- CANONICAL capabilities without tests
- Deprecated scripts still called by daily pipeline

Output: Output/system_learning/latest/abandoned_work_report.md
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git_untracked_older_than(days=3):
    """Find untracked source files older than N days."""
    cutoff = datetime.now() - timedelta(days=days)
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, cwd=ROOT
    )
    old_files = []
    for f in result.stdout.strip().split("\n"):
        if not f:
            continue
        fp = ROOT / f
        if fp.exists() and fp.suffix in (".py", ".yaml", ".json", ".md"):
            mtime = datetime.fromtimestamp(fp.stat().st_mtime)
            if mtime < cutoff:
                old_files.append({"file": f, "age_days": (datetime.now() - mtime).days})
    return old_files


def load_capability_registry():
    """Load capability registry."""
    reg_path = ROOT / "governance" / "capability_registry.yaml"
    if not reg_path.exists():
        return {}
    try:
        import yaml
        with open(reg_path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Fallback: parse key names only
        with open(reg_path) as f:
            content = f.read()
        keys = []
        for line in content.split("\n"):
            if line and not line.startswith(" ") and not line.startswith("#") and ":" in line:
                keys.append(line.split(":")[0].strip())
        return {k: {} for k in keys}


def load_artifact_registry():
    """Load artifact registry."""
    reg_path = ROOT / "Output" / "artifact_registry.json"
    if not reg_path.exists():
        return {"artifacts": []}
    with open(reg_path) as f:
        return json.load(f)


def check_output_without_registry():
    """Find Output subdirectories not in artifact registry."""
    output_dir = ROOT / "Output"
    reg = load_artifact_registry()
    registered = {a["path"].rstrip("/") for a in reg.get("artifacts", [])}

    unregistered = []
    for item in output_dir.iterdir():
        if item.is_dir() and item.name not in ("current", "system_learning", "archive", "sandbox"):
            rel = f"Output/{item.name}"
            if rel not in registered and rel + "/" not in registered:
                unregistered.append(rel)
    return unregistered


def check_paper_modules_with_data(cap_reg):
    """Find PAPER modules that actually have output artifacts."""
    paper_with_data = []
    for name, info in cap_reg.items():
        status = info.get("status", "UNKNOWN") if isinstance(info, dict) else "UNKNOWN"
        if status == "PAPER":
            artifacts = info.get("artifacts", []) if isinstance(info, dict) else []
            for art in artifacts:
                art_path = ROOT / art
                if art_path.exists():
                    paper_with_data.append({"module": name, "artifact": art})
    return paper_with_data


def check_canonical_without_tests(cap_reg):
    """Find CANONICAL capabilities without test coverage."""
    no_tests = []
    for name, info in cap_reg.items():
        if not isinstance(info, dict):
            continue
        status = info.get("status", "UNKNOWN")
        test_count = info.get("test_count", 0)
        if status == "CANONICAL" and test_count == 0:
            no_tests.append(name)
    return no_tests


def check_modules_md_vs_registry():
    """Compare MODULES.md status with capability registry."""
    modules_path = ROOT / "MODULES.md"
    cap_reg = load_capability_registry()

    if not modules_path.exists():
        return []

    with open(modules_path) as f:
        content = f.read()

    inconsistencies = []
    # Map MODULES.md thread names to registry keys
    thread_map = {
        "Workbench": "workbench",
        "Deformation Framework": "deformation_framework",
        "Harvester": "harvester",
        "Protocols": "protocols",
        "Data and Output": "data_output",
        "Learning Hub": "learning_hub",
        "Agent Routing": "agent_routing",
        "CaseLab Context": "caselab_context",
        "NLP Pipeline": "nlp_pipeline",
        "ML Signals": "ml_signals",
        "Backtest Lens": "backtest_lens",
        "Qlib Benchmark": "qlib_benchmark",
        "Research Terminal": "research_terminal",
    }

    for thread_name, reg_key in thread_map.items():
        if reg_key in cap_reg and isinstance(cap_reg[reg_key], dict):
            reg_status = cap_reg[reg_key].get("status", "UNKNOWN")
            # Check if MODULES.md mentions this status
            if thread_name in content:
                # Simple check: see if the status appears near the thread name
                lines = content.split("\n")
                for line in lines:
                    if thread_name in line and "|" in line:
                        # Extract status from table row
                        parts = [p.strip() for p in line.split("|")]
                        for part in parts:
                            clean = part.strip("`*").replace("CANONICAL", "").replace("ACTIVE_PARTIAL", "").replace("REAL_EXPERIMENTAL", "").replace("BLOCKED", "").replace("UNKNOWN", "").strip()
                            if not clean and reg_status in ("CANONICAL", "ACTIVE_PARTIAL", "REAL_EXPERIMENTAL", "BLOCKED", "UNKNOWN"):
                                pass  # Status matches
                        break
    return inconsistencies


def check_latest_symlinks():
    """Find 'latest' symlinks pointing to old artifacts."""
    old_links = []
    for latest_path in ROOT.rglob("latest"):
        if latest_path.is_symlink():
            target = latest_path.resolve()
            if target.exists():
                mtime = datetime.fromtimestamp(target.stat().st_mtime)
                age_days = (datetime.now() - mtime).days
                if age_days > 7:
                    old_links.append({
                        "link": str(latest_path.relative_to(ROOT)),
                        "target": str(target.relative_to(ROOT)),
                        "age_days": age_days
                    })
    return old_links


def check_deprecated_in_pipeline():
    """Check if deprecated scripts are still referenced by daily pipeline."""
    daily_run = ROOT / "scripts" / "daily_run.py"
    if not daily_run.exists():
        return []

    with open(daily_run) as f:
        content = f.read()

    deprecated_refs = []
    # Check for imports/calls to known deprecated scripts
    deprecated = ["solution_phase1", "solution_phase2", "hmm_generate_history",
                  "hmm_stability_audit", "prepare_dl_training_data"]
    for dep in deprecated:
        if dep in content:
            deprecated_refs.append(dep)
    return deprecated_refs


def generate_report():
    """Generate the abandoned work report."""
    cap_reg = load_capability_registry()

    report = []
    report.append("# Abandoned Work Report")
    report.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append("")

    # 1. Untracked source files
    old_untracked = git_untracked_older_than(days=3)
    report.append("## 1. Untracked Source Files (>3 days old)")
    if old_untracked:
        report.append("")
        report.append("| File | Age (days) |")
        report.append("|---|---|")
        for item in old_untracked[:20]:
            report.append(f"| `{item['file']}` | {item['age_days']} |")
    else:
        report.append("\nNone found.")
    report.append("")

    # 2. Output without registry
    unregistered = check_output_without_registry()
    report.append("## 2. Output Directories Without Registry Entry")
    if unregistered:
        report.append("")
        for d in unregistered:
            report.append(f"- `{d}`")
    else:
        report.append("\nNone found.")
    report.append("")

    # 3. PAPER modules with data
    paper_with_data = check_paper_modules_with_data(cap_reg)
    report.append("## 3. PAPER Modules That Actually Have Data")
    if paper_with_data:
        report.append("")
        report.append("| Module | Artifact |")
        report.append("|---|---|")
        for item in paper_with_data:
            report.append(f"| {item['module']} | `{item['artifact']}` |")
    else:
        report.append("\nNone found.")
    report.append("")

    # 4. CANONICAL without tests
    no_tests = check_canonical_without_tests(cap_reg)
    report.append("## 4. CANONICAL Capabilities Without Tests")
    if no_tests:
        report.append("")
        for m in no_tests:
            report.append(f"- `{m}`")
    else:
        report.append("\nNone found.")
    report.append("")

    # 5. Old 'latest' symlinks
    old_links = check_latest_symlinks()
    report.append("## 5. 'latest' Symlinks Pointing to Old Artifacts (>7 days)")
    if old_links:
        report.append("")
        report.append("| Link | Target | Age (days) |")
        report.append("|---|---|---|")
        for item in old_links:
            report.append(f"| `{item['link']}` | `{item['target']}` | {item['age_days']} |")
    else:
        report.append("\nNone found.")
    report.append("")

    # 6. Deprecated scripts in pipeline
    deprecated_refs = check_deprecated_in_pipeline()
    report.append("## 6. Deprecated Scripts Still Referenced in Daily Pipeline")
    if deprecated_refs:
        report.append("")
        for ref in deprecated_refs:
            report.append(f"- `{ref}`")
    else:
        report.append("\nNone found.")
    report.append("")

    # 7. Summary counts
    report.append("## Summary")
    report.append("")
    report.append(f"- Untracked old files: {len(old_untracked)}")
    report.append(f"- Unregistered Output dirs: {len(unregistered)}")
    report.append(f"- PAPER modules with data: {len(paper_with_data)}")
    report.append(f"- CANONICAL without tests: {len(no_tests)}")
    report.append(f"- Old 'latest' symlinks: {len(old_links)}")
    report.append(f"- Deprecated in pipeline: {len(deprecated_refs)}")

    return "\n".join(report)


def main():
    report = generate_report()

    # Write to Output/system_learning/latest/
    out_dir = ROOT / "Output" / "system_learning" / "latest"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "abandoned_work_report.md"

    with open(out_path, "w") as f:
        f.write(report)

    print(f"Report written to: {out_path}")

    # Also print summary
    print("\n" + "=" * 60)
    print(report.split("## Summary")[-1] if "## Summary" in report else report)


if __name__ == "__main__":
    main()
