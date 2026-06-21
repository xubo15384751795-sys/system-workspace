#!/usr/bin/env python3
"""Governance drag report — read-only complexity metrics.

Computes 8 indicators of system complexity drag:
  1. daily_active_step_count     — steps running every day
  2. root_script_count           — scripts/ root-level .py files
  3. governance_file_count       — governance/*.yaml active files
  4. registry_entry_count        — entries in module_authority_registry
  5. script_without_test_count   — scripts with no corresponding test
  6. orphan_output_count         — Output/ dirs with stale/unknown provenance
  7. hash_reconcile_commits_last_10  — freeze hash reconcile commits in last 10
  8. governance_commits_ratio_last_10 — fraction of last 10 commits that are governance

Outputs:
    Output/system_learning/latest/governance_drag_report.json

This is a read-only diagnostic. It never blocks, never modifies, never promotes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _workspace_imports import add_scripts  # noqa: E402
add_scripts()

from _daily_run_sequence import load_daily_run_sequence, weekly_step_ids  # noqa: E402
from _runtime_io import ROOT, ensure_dir, load_yaml  # noqa: E402

OUTPUT_PATH = ROOT / "Output" / "system_learning" / "latest" / "governance_drag_report.json"

# --- helpers ---------------------------------------------------------------

def _count_daily_steps() -> int:
    """Count steps without schedule: weekly."""
    steps = load_daily_run_sequence()
    weekly = weekly_step_ids()
    return sum(1 for s in steps if s.get("id") and s["id"] not in weekly)


def _count_root_scripts(root: Path) -> int:
    """Count .py files directly under scripts/ (excluding __init__)."""
    scripts_dir = root / "scripts"
    if not scripts_dir.is_dir():
        return 0
    return sum(
        1 for f in scripts_dir.iterdir()
        if f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
    )


def _count_governance_yamls(root: Path) -> int:
    """Count active (non-archive) governance YAML files."""
    gov_dir = root / "governance"
    if not gov_dir.is_dir():
        return 0
    return sum(
        1 for f in gov_dir.iterdir()
        if f.is_file() and f.suffix in (".yaml", ".yml")
    )


def _count_registry_entries(root: Path) -> int:
    """Count entries in authority_registry.yaml (modules section)."""
    reg_path = root / "governance" / "authority_registry.yaml"
    if not reg_path.exists():
        return 0
    data = load_yaml(reg_path)
    # authority_registry has modules as dict keys; older format had list
    modules = data.get("modules", {})
    if isinstance(modules, dict):
        return len(modules)
    entries = data.get("entries") or []
    return len(entries) if isinstance(entries, list) else 0


def _count_scripts_without_tests(root: Path) -> int:
    """Estimate scripts with no corresponding test file.

    Heuristic: for each scripts/*.py, check if tests/test_<stem>*.py exists.
    This is approximate — some tests cover concepts, not scripts.
    """
    scripts_dir = root / "scripts"
    tests_dir = root / "tests"
    if not scripts_dir.is_dir() or not tests_dir.is_dir():
        return 0

    test_names = {f.stem for f in tests_dir.iterdir() if f.is_file() and f.suffix == ".py"}
    # Also check tests/governance/
    gov_tests = tests_dir / "governance"
    if gov_tests.is_dir():
        test_names.update(f.stem for f in gov_tests.iterdir() if f.is_file() and f.suffix == ".py")

    untested = 0
    for script in scripts_dir.iterdir():
        if not script.is_file() or script.suffix != ".py" or script.name == "__init__.py":
            continue
        if script.name.startswith("_"):
            continue  # private modules tested indirectly
        stem = script.stem
        # Check if any test file matches
        has_test = any(
            t == f"test_{stem}" or t.startswith(f"test_{stem}_") or t.endswith(f"_{stem}")
            for t in test_names
        )
        if not has_test:
            untested += 1
    return untested


def _count_orphan_outputs(root: Path) -> int:
    """Count Output/ subdirectories that look stale or orphaned.

    Heuristic: directories under Output/ that haven't been modified in 30+ days
    and aren't in the known-good set.
    """
    output_dir = root / "Output"
    if not output_dir.is_dir():
        return 0

    known_good = {
        "current", "runs", "runtime_events", "alerts", "archive",
        "system_learning", "validation", "quality",
    }

    import time
    now = time.time()
    stale_threshold = 30 * 24 * 3600  # 30 days
    orphans = 0
    for d in output_dir.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if d.name in known_good:
            continue
        # Check mtime of directory
        age = now - d.stat().st_mtime
        if age > stale_threshold:
            orphans += 1
    return orphans


def _git_log_last_n(root: Path, n: int = 10) -> list[str]:
    """Get last N commit messages."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-{n}", "--no-decorate"],
            capture_output=True, text=True, timeout=10, cwd=str(root),
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()
    except Exception:
        pass
    return []


def _count_hash_reconcile_commits(root: Path) -> int:
    """Count freeze hash reconcile commits in last 10."""
    lines = _git_log_last_n(root, 10)
    keywords = {"hash", "reconcile", "freeze", "governance_freeze"}
    count = 0
    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in keywords):
            count += 1
    return count


def _governance_commits_ratio(root: Path) -> float:
    """Fraction of last 10 commits that are governance-related."""
    lines = _git_log_last_n(root, 10)
    if not lines:
        return 0.0
    gov_keywords = {
        "governance", "freeze", "registry", "audit", "authority",
        "constitution", "reconcile", "boundary", "policy", "redundancy",
    }
    gov_count = sum(
        1 for line in lines
        if any(kw in line.lower() for kw in gov_keywords)
    )
    return round(gov_count / len(lines), 2)


# --- net contribution formula ----------------------------------------------

def _compute_net_contribution(metrics: dict[str, Any]) -> dict[str, Any]:
    """Compute a simple drag score from the 8 metrics.

    Each metric is normalized to a 0-10 scale where higher = more drag.
    Total drag is the sum (max 80).
    """
    # Thresholds for scoring (linear scale 0-10)
    score = {}

    # 1. daily_active_step_count: 20=0, 40=10
    score["daily_step_drag"] = min(10, max(0, (metrics["daily_active_step_count"] - 20) / 2))

    # 2. root_script_count: 60=0, 120=10
    score["root_script_drag"] = min(10, max(0, (metrics["root_script_count"] - 60) / 6))

    # 3. governance_file_count: 15=0, 35=10
    score["governance_file_drag"] = min(10, max(0, (metrics["governance_file_count"] - 15) / 2))

    # 4. registry_entry_count: 10=0, 30=10
    score["registry_drag"] = min(10, max(0, (metrics["registry_entry_count"] - 10) / 2))

    # 5. script_without_test_count: 30=0, 70=10
    score["untested_drag"] = min(10, max(0, (metrics["script_without_test_count"] - 30) / 4))

    # 6. orphan_output_count: 0=0, 10=10
    score["orphan_drag"] = min(10, max(0, metrics["orphan_output_count"]))

    # 7. hash_reconcile_commits_last_10: 0=0, 5=10
    score["hash_reconcile_drag"] = min(10, max(0, metrics["hash_reconcile_commits_last_10"] * 2))

    # 8. governance_commits_ratio_last_10: 0.2=0, 0.7=10
    ratio = metrics["governance_commits_ratio_last_10"]
    score["governance_ratio_drag"] = min(10, max(0, (ratio - 0.2) * 20))

    total = round(sum(score.values()), 1)
    severity = "LOW" if total < 20 else "MEDIUM" if total < 40 else "HIGH" if total < 60 else "CRITICAL"

    return {
        "component_scores": score,
        "total_drag_score": total,
        "max_possible": 80,
        "severity": severity,
    }


# --- main ------------------------------------------------------------------

def build_report(root: Path = ROOT) -> dict[str, Any]:
    """Build the governance drag report."""
    metrics = {
        "daily_active_step_count": _count_daily_steps(),
        "root_script_count": _count_root_scripts(root),
        "governance_file_count": _count_governance_yamls(root),
        "registry_entry_count": _count_registry_entries(root),
        "script_without_test_count": _count_scripts_without_tests(root),
        "orphan_output_count": _count_orphan_outputs(root),
        "hash_reconcile_commits_last_10": _count_hash_reconcile_commits(root),
        "governance_commits_ratio_last_10": _governance_commits_ratio(root),
    }

    drag = _compute_net_contribution(metrics)

    report = {
        "schema": "governance_drag_report.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "metrics": metrics,
        "drag_assessment": drag,
        "recommendations": _recommendations(metrics, drag),
    }
    return report


def _recommendations(metrics: dict[str, Any], drag: dict[str, Any]) -> list[str]:
    """Generate human-readable recommendations."""
    recs = []
    scores = drag["component_scores"]

    if scores["daily_step_drag"] > 5:
        recs.append(
            f"Daily pipeline has {metrics['daily_active_step_count']} active steps — "
            "consider moving validation/reporting steps to weekly."
        )
    if scores["root_script_drag"] > 5:
        recs.append(
            f"{metrics['root_script_count']} root scripts — "
            "archive orphaned scripts to scripts/archive/."
        )
    if scores["governance_file_drag"] > 5:
        recs.append(
            f"{metrics['governance_file_count']} governance YAMLs — "
            "consolidate or archive redundant governance files."
        )
    if scores["untested_drag"] > 5:
        recs.append(
            f"{metrics['script_without_test_count']} scripts without tests — "
            "prioritize tests for signal-blocking scripts, archive the rest."
        )
    if scores["hash_reconcile_drag"] > 3:
        recs.append(
            "High hash-reconcile commit ratio — "
            "consider making freeze hash checks advisory, not blocking."
        )
    if scores["governance_ratio_drag"] > 5:
        recs.append(
            f"{int(metrics['governance_commits_ratio_last_10']*100)}% of recent commits are governance — "
            "governance is consuming development bandwidth."
        )
    if not recs:
        recs.append("System complexity is within healthy bounds.")
    return recs


def main() -> None:
    report = build_report()
    ensure_dir(OUTPUT_PATH.parent)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Also write a summary to stdout
    drag = report["drag_assessment"]
    print(f"Governance Drag Score: {drag['total_drag_score']}/{drag['max_possible']} ({drag['severity']})")
    for name, val in drag["component_scores"].items():
        bar = "█" * int(val) + "░" * (10 - int(val))
        print(f"  {name:30s} [{bar}] {val:.0f}/10")
    if report["recommendations"]:
        print("\nRecommendations:")
        for r in report["recommendations"]:
            print(f"  → {r}")


if __name__ == "__main__":
    main()
