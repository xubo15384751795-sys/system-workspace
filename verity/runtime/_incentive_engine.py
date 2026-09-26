"""Incentive engine — credit scoring, demotion, anti-gaming checks.

Credit improves review priority only. It never grants authority.
"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from system_runtime.paths import output_surface
from verity.runtime._constants import TIMEOUT_MEDIUM, TIMEOUT_STANDARD  # noqa: E402
from verity.runtime.runtime_io import ROOT as WORKSPACE_ROOT
from verity.runtime.runtime_io import load_json as _load_json
from verity.runtime.runtime_io import load_yaml as _load_yaml

logger = logging.getLogger(__name__)

PRIORITY_ORDER = ["low", "registered", "preferred", "canonical"]


def _surface(root: Path, name: str) -> Path:
    return output_surface(root, name) if root == WORKSPACE_ROOT else root / "Output" / name


def _tier_index(tier: str) -> int:
    try:
        return PRIORITY_ORDER.index(tier)
    except ValueError:
        return 0


def collect_runtime_signals(root: Path) -> dict[str, Any]:
    governance = _load_json(_surface(root, "system_learning") / "latest" / "governance_status.json") or {}
    graph = _load_json(_surface(root, "system_learning") / "latest" / "authority_graph.json") or {}
    run_trace = governance.get("run_trace", {})
    gates = governance.get("gates", {})
    incentive = governance.get("incentive", {})

    return {
        "trace_complete": bool(run_trace.get("trace_complete")),
        "can_enter_current": bool(gates.get("can_enter_current")),
        "effective_can_affect_core": bool(gates.get("effective_can_affect_core_judgment")),
        "graph_invariants_valid": bool(graph.get("invariants", {}).get("valid")),
        "graph_drift_count": int(graph.get("metrics", {}).get("drift_count", 0)),
        "core_capable_completed": int(incentive.get("graph_metrics", {}).get("core_capable_completed", 0)),
        "total_in_degree": int(incentive.get("graph_metrics", {}).get("total_in_degree", 0)),
        "credits_active": list(incentive.get("credits_active", [])),
    }


def run_pipeline_baseline_check(root: Path) -> dict[str, bool]:
    """Run pytest on pipeline baseline test files and return pass/fail per layer.

    Maps test file → credit source as defined in pipeline_test_baseline.yaml.
    """
    baseline = _load_yaml(root / "governance" / "pipeline_test_baseline.yaml")
    layers = baseline.get("layers", []) or []

    results: dict[str, bool] = {}
    all_paths: list[str] = []

    for layer in layers:
        name = layer.get("name", "unknown")
        test_file = layer.get("file", "")

        if not test_file:
            results[name] = True
            continue

        path = root / test_file
        if not path.exists():
            results[name] = False
            continue

        all_paths.append(str(path))
        try:
            proc = subprocess.run(
                ["python3", "-m", "pytest", str(path), "-x", "-q", "--tb=no"],
                capture_output=True, text=True, timeout=TIMEOUT_MEDIUM, cwd=str(root),
            )
            results[name] = proc.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            results[name] = False

    # Also check full baseline (all layers together)
    if all_paths:
        try:
            proc = subprocess.run(
                ["python3", "-m", "pytest", *all_paths, "-x", "-q", "--tb=no"],
                capture_output=True, text=True, timeout=TIMEOUT_STANDARD, cwd=str(root),
            )
            results["full_baseline"] = proc.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            results["full_baseline"] = False
    else:
        results["full_baseline"] = all(results.values())

    return results


def _load_drag_penalty(root: Path | None) -> dict[str, Any]:
    """Load governance drag report and compute complexity penalty.

    Returns penalty info. Never blocks — if report missing, penalty is 0.
    """
    if not root:
        return {"penalty": 0, "drag_score": 0, "severity": "UNKNOWN", "source": "no_root"}

    drag_path = _surface(root, "system_learning") / "latest" / "governance_drag_report.json"
    if not drag_path.exists():
        return {"penalty": 0, "drag_score": 0, "severity": "UNKNOWN", "source": "report_missing"}

    try:
        report = _load_json(drag_path)
        drag = report.get("drag_assessment", {})
        total_drag = float(drag.get("total_drag_score", 0))
        severity = drag.get("severity", "UNKNOWN")

        # Penalty formula: 1 point per 10 drag points, rounded down, max 5
        penalty = min(5, int(total_drag / 10))

        return {
            "penalty": penalty,
            "drag_score": total_drag,
            "severity": severity,
            "source": "governance_drag_report",
            "components": drag.get("component_scores", {}),
        }
    except Exception:
        return {"penalty": 0, "drag_score": 0, "severity": "ERROR", "source": "parse_error"}


def compute_credit_score(signals: dict[str, Any], policy: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    sources = policy.get("credit_sources", {}) or {}
    active: list[str] = []
    total = 0

    # Run pipeline baseline check if root provided
    baseline_results: dict[str, bool] = {}
    if root:
        baseline_results = run_pipeline_baseline_check(root)

    mapping = {
        "registration": signals.get("trace_complete"),
        "provenance": signals.get("trace_complete"),
        "consumed_by_module": signals.get("can_enter_current"),
        "graph_in_degree": signals.get("total_in_degree", 0) > 0,
        "graph_core_path": signals.get("core_capable_completed", 0) > 0,
        "stable_consumption": signals.get("effective_can_affect_core"),
        "pipeline_baseline_pass": baseline_results.get("full_baseline", False),
        "harvester_aligned": signals.get("harvester_recent", False),
        "improves_existing_rule": signals.get("graph_drift_count", 0) == 0,
    }

    for source_id, cfg in sources.items():
        if mapping.get(source_id):
            active.append(source_id)
            total += int(cfg.get("review_weight", 0))

    # Complexity penalty — deduct credit for system complexity drag
    drag_info = _load_drag_penalty(root)
    complexity_penalty = drag_info["penalty"]
    net_score = max(0, total - complexity_penalty)

    suggested = "low"
    for source_id in active:
        cfg = sources.get(source_id, {})
        target = str(cfg.get("suggests_review_for", "registered"))
        if _tier_index(target) > _tier_index(suggested):
            suggested = target

    return {
        "total_score": total,
        "complexity_penalty": complexity_penalty,
        "net_score": net_score,
        "drag_info": drag_info,
        "active_sources": active,
        "suggested_tier": suggested,
    }


def apply_demotion(current_tier: str, signals: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    demotion = policy.get("demotion_triggers", []) or []
    tier = current_tier
    reasons: list[str] = []

    for rule in demotion:
        rule_id = str(rule.get("id", ""))
        to_tier = str(rule.get("to", "low"))
        trigger = False

        if rule_id == "gate_blocked_or_watch" and not signals.get("can_enter_current"):
            trigger = True
        elif rule_id == "graph_drift_detected" and signals.get("graph_drift_count", 0) > 0:
            trigger = True
        elif rule_id == "graph_invariants_failed" and not signals.get("graph_invariants_valid", True):
            trigger = True
        elif rule_id == "trace_incomplete" and not signals.get("trace_complete"):
            trigger = True

        if trigger and _tier_index(to_tier) < _tier_index(tier):
            tier = to_tier
            reasons.append(rule_id)

    return {"tier": tier, "demotion_reasons": reasons}


def resolve_priority_tier(
    signals: dict[str, Any],
    policy: dict[str, Any],
    *,
    current_tier: str = "low",
    root: Path | None = None,
) -> dict[str, Any]:
    credit = compute_credit_score(signals, policy, root=root)
    promoted = credit["suggested_tier"]
    if _tier_index(promoted) < _tier_index(current_tier):
        promoted = current_tier
    demoted = apply_demotion(promoted, signals, policy)
    return {
        **credit,
        "current_tier": current_tier,
        "promoted_tier": promoted,
        "final_tier": demoted["tier"],
        "demotion_reasons": demoted["demotion_reasons"],
    }


def validate_submission(submission: dict[str, Any], required_fields: list[str]) -> list[str]:
    return [field for field in required_fields if not submission.get(field)]


def score_submission(
    submission: dict[str, Any],
    policy: dict[str, Any],
    *,
    required_fields: list[str],
) -> dict[str, Any]:
    gaps = validate_submission(submission, required_fields)
    priority = str(submission.get("current_priority", "low"))
    credit_bonus = 0
    if submission.get("evidence_paths"):
        credit_bonus += int(policy.get("credit_sources", {}).get("provenance", {}).get("review_weight", 0))
    if submission.get("submission_type") == "topology_change":
        credit_bonus += 4
    demotion_reasons: list[str] = []
    if gaps:
        demotion_reasons.append("missing_required_fields")
        priority = "low"
    status = str(submission.get("status", ""))
    if status in {"submitted", "open"} and not submission.get("reviewer"):
        demotion_reasons.append("no_reviewer_assigned")
    return {
        "submission_id": submission.get("submission_id"),
        "gaps": gaps,
        "credit_bonus": credit_bonus,
        "effective_priority": priority,
        "demotion_reasons": demotion_reasons,
        "topology_change": submission.get("submission_type") == "topology_change",
    }


def run_anti_gaming_checks(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    # ── Check 1: Scripts without tests ─────────────────────────
    scripts_dir = root / "scripts"
    for script in sorted(scripts_dir.glob("*.py")):
        if script.name.startswith("_") or script.name == "__init__.py":
            continue
        stem = script.stem
        has_test = any((root / "tests").rglob(f"test*{stem}*")) or any(
            (root / "tests").rglob(f"*{stem}*test*")
        )
        if not has_test and script.name not in {"bootstrap", "orchestrate"}:
            findings.append(
                {
                    "id": "script_without_test",
                    "severity": "medium",
                    "message": f"Root script {script.name} has no obvious test coverage",
                }
            )

    # ── Check 2: Experimental without submission ───────────────
    registry = _load_yaml(root / "governance/entrypoint_registry.yaml")
    for entry_id, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("status") == "experimental" and entry.get("allowed_use"):
            findings.append(
                {
                    "id": "experimental_without_submission",
                    "severity": "medium",
                    "message": f"Entry '{entry_id}' is experimental — should have experimental submission or retire_after",
                }
            )

    # ── Check 3: Authority boundary policy ─────────────────────
    ab = policy.get("authority_boundary", {}) or {}
    if ab.get("credit_never_grants_authority") is not True:
        findings.append(
            {
                "id": "credit_grants_authority_policy",
                "severity": "high",
                "message": "incentive_policy authority_boundary.credit_never_grants_authority must be true",
            }
        )

    # ── Check 4: Outputs without consumers ─────────────────────
    # If a script writes to Output/ but nothing reads it, it's noise.
    output_dir = _surface(root, "current")
    if output_dir.exists():
        for artifact in sorted(output_dir.glob("*.json")):
            name = artifact.name
            # Check if any script imports/reads this artifact
            consumed = False
            for script in scripts_dir.glob("*.py"):
                try:
                    content = script.read_text(encoding="utf-8", errors="ignore")
                    if name in content:
                        consumed = True
                        break
                except Exception:
                    continue
            if not consumed:
                findings.append(
                    {
                        "id": "output_without_consumer",
                        "severity": "low",
                        "message": f"Output artifact '{name}' is not referenced by any root script",
                    }
                )

    # ── Check 5: Harvester bypass detection ────────────────────
    # If framework_output.json exists but harvester hasn't run today, flag it.
    fw_path = _surface(root, "current") / "framework_output.json"
    harvester_manifest = root / "Data" / "harvester" / "exports" / "latest" / "manifest.json"
    if fw_path.exists() and harvester_manifest.exists():
        fw_age_hours = (datetime.now(UTC).timestamp() - os.path.getmtime(fw_path)) / 3600
        harvest_age_hours = (datetime.now(UTC).timestamp() - os.path.getmtime(harvester_manifest)) / 3600
        # If framework is recent but harvester is stale (>26h), data may be fabricated
        if fw_age_hours < 2 and harvest_age_hours > 26:
            findings.append(
                {
                    "id": "harvester_bypass_suspected",
                    "severity": "high",
                    "message": (
                        f"framework_output is fresh ({fw_age_hours:.1f}h) but harvester is stale "
                        f"({harvest_age_hours:.1f}h). Data may not be sourced from Harvester."
                    ),
                }
            )

    # ── Check 6: Credit score claiming authority ───────────────
    # Check if any output uses credit_score to justify a decision
    judgment_dir = _surface(root, "judgment")
    if judgment_dir.exists():
        latest = judgment_dir / "latest.json"
        if latest.exists():
            j = _load_json(latest)
            if j and "credit_score" in str(j.get("justification", "")):
                findings.append(
                    {
                        "id": "credit_used_as_authority",
                        "severity": "high",
                        "message": "Judgment justification references credit_score — credit never grants authority",
                    }
                )

    # ── Check 7: Submission registry health ────────────────────
    sub_registry = _load_yaml(root / "governance" / "experimental_submission_registry.yaml")
    submissions = sub_registry.get("submissions", []) or []
    overdue = []
    for sub in submissions:
        retire = sub.get("retire_after")
        if retire:
            try:
                retire_date = datetime.strptime(str(retire), "%Y-%m-%d").replace(tzinfo=UTC)
                if datetime.now(UTC) > retire_date and sub.get("status") not in ("rejected", "archived"):
                    overdue.append(sub.get("submission_id", "?"))
            except ValueError:
                logger.warning("Invalid submission retirement date: %s", retire, exc_info=True)
    if overdue:
        findings.append(
            {
                "id": "submission_overdue",
                "severity": "medium",
                "message": f"Submissions past retire_after: {', '.join(overdue)}",
            }
        )

    high = [f for f in findings if f.get("severity") == "high"]
    return {
        "valid": len(high) == 0,
        "finding_count": len(findings),
        "findings": findings,
    }


def build_incentive_review(root: Path) -> dict[str, Any]:
    policy = _load_yaml(root / "governance/incentive_policy.yaml")
    registry = _load_yaml(root / "governance/experimental_submission_registry.yaml")
    required_fields = list(registry.get("required_fields", []))
    submissions = list(registry.get("submissions", []) or [])

    signals = collect_runtime_signals(root)

    # Check harvester freshness for harvester_aligned signal
    import os
    harvester_manifest = root / "Data" / "harvester" / "exports" / "latest" / "manifest.json"
    if harvester_manifest.exists():
        age_hours = (datetime.now(UTC).timestamp() - os.path.getmtime(harvester_manifest)) / 3600
        signals["harvester_recent"] = age_hours < 26

    priority = resolve_priority_tier(signals, policy, root=root)
    anti_gaming = run_anti_gaming_checks(root, policy)
    baseline_results = run_pipeline_baseline_check(root)

    submission_scores = [
        score_submission(item, policy, required_fields=required_fields) for item in submissions
    ]

    return {
        "schema_version": "incentive_review.v3",
        "generated_at": datetime.now(UTC).isoformat(),
        "authority_boundary": policy.get("authority_boundary", {}),
        "runtime_signals": signals,
        "credit_score": priority,
        "complexity_penalty": priority.get("drag_info", {}),
        "pipeline_baseline": baseline_results,
        "anti_gaming": anti_gaming,
        "submissions": submission_scores,
        "submission_count": len(submissions),
        "note": "Credit improves review priority only. It never grants authority. Complexity drag reduces credit.",
    }
