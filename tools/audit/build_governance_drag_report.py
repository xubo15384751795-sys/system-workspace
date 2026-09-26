#!/usr/bin/env python3
"""Governance drag report — read-only complexity metrics.

Computes 8 indicators of system complexity drag:
  1. daily_active_step_count     — steps running every day
  2. root_script_count           — scripts/ root-level .py files
  3. governance_attention        — shape-6 files + always-read rule surface
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
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestration.daily_run_sequence import (  # noqa: E402
    load_daily_run_sequence,
    weekly_step_ids,
)

from verity.runtime._governance_freeze import _machine_consumer_evidence  # noqa: E402
from verity.runtime.runtime_io import (  # noqa: E402
    ROOT,
    ensure_dir,
    load_yaml,
    surface_dir,
)

logger = logging.getLogger(__name__)

OUTPUT_PATH = surface_dir("system_learning") / "latest" / "governance_drag_report.json"

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
    """Inventory-only count; file volume is not governance weight."""
    gov_dir = root / "governance"
    if not gov_dir.is_dir():
        return 0
    return sum(
        1 for f in gov_dir.iterdir()
        if f.is_file() and f.suffix in (".yaml", ".yml")
    )


def _governance_shape_metrics(root: Path) -> dict[str, Any]:
    """Measure attention shape and reject machine labels without consumers."""
    tiers = load_yaml(root / "governance" / "governance_tiers.yaml")
    inventory = tiers.get("shape_inventory", {}) or {}
    budget = tiers.get("attention_budget", {}) or {}
    gov_dir = root / "governance"
    root_files = {path.name for path in gov_dir.iterdir() if path.is_file() and path.name != ".DS_Store"}
    classified = set(inventory)
    shape_counts: dict[str, int] = {}
    for metadata in inventory.values():
        shape = str((metadata or {}).get("shape", "unclassified"))
        shape_counts[shape] = shape_counts.get(shape, 0) + 1

    procedural = sorted(
        name for name, metadata in inventory.items()
        if (metadata or {}).get("shape") == "procedural_rule"
    )
    machine_names = {
        name for name, metadata in inventory.items()
        if (metadata or {}).get("shape") in {"executable_invariant", "feedback_loop"}
    }
    consumer_evidence = _machine_consumer_evidence(root, machine_names)
    unbacked = sorted(name for name in machine_names if not consumer_evidence.get(name))

    always_read = list(budget.get("always_read_files", []) or [])
    always_lines = 0
    missing_always_read: list[str] = []
    for relative in always_read:
        path = root / str(relative)
        if not path.is_file():
            missing_always_read.append(str(relative))
        else:
            always_lines += sum(1 for _ in path.open(encoding="utf-8", errors="replace"))

    return {
        "governance_root_file_count": len(root_files),
        "shape_counts": shape_counts,
        "machine_or_deviation_file_count": sum(
            shape_counts.get(shape, 0)
            for shape in ("structural_impossibility", "executable_invariant", "feedback_loop")
        ),
        "precedent_file_count": shape_counts.get("precedent", 0),
        "procedural_rule_file_count": len(procedural),
        "procedural_rule_files": procedural,
        "always_read_file_count": len(always_read),
        "always_read_rule_lines": always_lines,
        "missing_always_read_files": missing_always_read,
        "unclassified_governance_files": sorted(root_files - classified),
        "stale_inventory_entries": sorted(classified - root_files),
        "machine_consumer_evidence": consumer_evidence,
        "unbacked_machine_files": unbacked,
        "attention_required_file_count": len(procedural) + len(always_read),
        "attention_budget": {
            "max_procedural_rule_files": int(budget.get("max_procedural_rule_files", 5)),
            "max_always_read_files": int(budget.get("max_always_read_files", 1)),
            "max_always_read_rule_lines": int(budget.get("max_always_read_rule_lines", 80)),
        },
        "sunset_queue": tiers.get("sunset_queue", {}) or {},
    }


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
            ["git", "log", "--oneline", f"-{n}", "--no-decorate"],
            capture_output=True, text=True, timeout=10, cwd=str(root),
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()
    except Exception:
        logger.warning("Unable to read recent git history for governance drag report", exc_info=True)
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

    # 3. Weight follows repeated attention, not file count. An unknown shape or
    # a machine label without a consumer is maximum drag because enforcement is
    # only documentary.
    budget = metrics["attention_budget"]
    if (
        metrics["unclassified_governance_files"]
        or metrics["missing_always_read_files"]
        or metrics["unbacked_machine_files"]
    ):
        attention_drag = 10.0
    else:
        procedural_ratio = metrics["procedural_rule_file_count"] / max(
            1, budget["max_procedural_rule_files"]
        )
        principle_cost = 0.5 if metrics["always_read_file_count"] else 0.0
        attention_drag = 5.0 * procedural_ratio + principle_cost
    score["governance_attention_drag"] = min(10, round(attention_drag, 2))

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
        "governance_yaml_count_inventory_only": _count_governance_yamls(root),
        "registry_entry_count": _count_registry_entries(root),
        "script_without_test_count": _count_scripts_without_tests(root),
        "orphan_output_count": _count_orphan_outputs(root),
        "hash_reconcile_commits_last_10": _count_hash_reconcile_commits(root),
        "governance_commits_ratio_last_10": _governance_commits_ratio(root),
    }
    metrics.update(_governance_shape_metrics(root))

    drag = _compute_net_contribution(metrics)

    report = {
        "schema": "governance_drag_report.v2",
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
    if metrics["unclassified_governance_files"]:
        recs.append(
            "Classify governance files with unknown attention shape: "
            + ", ".join(metrics["unclassified_governance_files"])
        )
    if metrics["unbacked_machine_files"]:
        recs.append(
            "Machine-shaped governance lacks a code/test consumer: "
            + ", ".join(metrics["unbacked_machine_files"])
        )
    if metrics["procedural_rule_file_count"] > metrics["attention_budget"]["max_procedural_rule_files"]:
        recs.append("Convert procedural rules to invariants, loops, precedents, or compact principles.")
    if metrics["always_read_rule_lines"] > metrics["attention_budget"]["max_always_read_rule_lines"]:
        recs.append("Shrink the always-read principle surface below its line budget.")
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
