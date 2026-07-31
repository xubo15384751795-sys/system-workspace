"""Governance freeze — machine-checkable enforcement of system_constitution.yaml.

v2 additions:
- File hash integrity (baseline_hashes)
- review_after date enforcement
- approved_additions budget
- Pending commit detection
"""
from __future__ import annotations

import fnmatch
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _runtime_io import ROOT  # noqa: E402
from _runtime_io import load_yaml as _load_yaml

MANIFEST_PATH = ROOT / "governance" / "governance_freeze_manifest.yaml"
TIERS_PATH = ROOT / "governance" / "governance_tiers.yaml"


def _ignored(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _file_hash(path: Path) -> str:
    """SHA256[:16] of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def check_governance_freeze(root: Path = ROOT) -> dict[str, Any]:
    manifest = _load_yaml(root / MANIFEST_PATH.relative_to(ROOT))
    tiers = _load_yaml(root / TIERS_PATH.relative_to(ROOT))

    baseline = set(manifest.get("baseline_root_files", []))
    approved_items = manifest.get("approved_additions", [])
    approved = {item["file"] for item in approved_items if item.get("file")}
    allowed = baseline | approved
    ignore_patterns = list(manifest.get("ignore_patterns", []))

    violations: list[dict[str, str]] = []
    unapproved_new: list[str] = []
    hash_mismatches: list[dict[str, str]] = []

    gov_dir = root / "governance"

    # ── Check 1: Unapproved files ──────────────────────────────
    for path in sorted(gov_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if _ignored(name, ignore_patterns):
            continue
        if name not in allowed:
            unapproved_new.append(name)
            violations.append(
                {
                    "id": "unapproved_governance_file",
                    "severity": "high",
                    "message": (
                        f"Governance file '{name}' is not in freeze baseline or approved_additions. "
                        "Add to governance_freeze_manifest.yaml with explicit approval or revert."
                    ),
                }
            )

    # ── Check 2: Attention-shape budget ────────────────────────
    # File volume is not governance weight. A machine-shaped rule must have a
    # real code/test consumer; a label alone is not enforcement.
    work_support = tiers.get("work_support", {}).get("files", []) or []
    budget = int(manifest.get("work_support_budget", {}).get("max_files", 17))
    inventory = tiers.get("shape_inventory", {}) or {}
    attention = tiers.get("attention_budget", {}) or {}
    governed_root_files = {
        path.name for path in gov_dir.iterdir()
        if path.is_file() and not _ignored(path.name, ignore_patterns)
    }
    classified_files = set(inventory)
    unclassified_shapes = sorted(governed_root_files - classified_files)
    stale_shape_entries = sorted(classified_files - governed_root_files)
    if unclassified_shapes:
        violations.append(
            {
                "id": "governance_shape_unclassified",
                "severity": "high",
                "message": "Governance files lack an attention shape: " + ", ".join(unclassified_shapes),
            }
        )
    if stale_shape_entries:
        violations.append(
            {
                "id": "governance_shape_stale_entry",
                "severity": "medium",
                "message": "Shape inventory entries do not exist: " + ", ".join(stale_shape_entries),
            }
        )

    procedural = sorted(
        name for name, metadata in inventory.items()
        if (metadata or {}).get("shape") == "procedural_rule"
    )
    procedural_budget = int(attention.get("max_procedural_rule_files", 5))
    if len(procedural) > procedural_budget:
        violations.append(
            {
                "id": "procedural_rule_budget_exceeded",
                "severity": "high",
                "message": f"procedural rule files {len(procedural)}/{procedural_budget}",
            }
        )

    always_read = list(attention.get("always_read_files", []) or [])
    always_file_budget = int(attention.get("max_always_read_files", 1))
    always_line_budget = int(attention.get("max_always_read_rule_lines", 80))
    always_lines = 0
    missing_always: list[str] = []
    for relative in always_read:
        path = root / str(relative)
        if not path.is_file():
            missing_always.append(str(relative))
        else:
            always_lines += sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
    if missing_always or len(always_read) > always_file_budget or always_lines > always_line_budget:
        violations.append(
            {
                "id": "always_read_attention_budget_exceeded",
                "severity": "high",
                "message": (
                    f"always-read files {len(always_read)}/{always_file_budget}, "
                    f"lines {always_lines}/{always_line_budget}, missing={missing_always}"
                ),
            }
        )

    unbacked_machine_files: list[str] = []
    if (root / "scripts").is_dir() or (root / "tests").is_dir():
        from scripts.build_governance_drag_report import _machine_consumer_evidence

        machine_names = {
            name for name, metadata in inventory.items()
            if (metadata or {}).get("shape") in {"executable_invariant", "feedback_loop"}
        }
        consumer_evidence = _machine_consumer_evidence(root, machine_names)
        unbacked_machine_files = sorted(
            name for name in machine_names if not consumer_evidence.get(name)
        )
        if unbacked_machine_files:
            violations.append(
                {
                    "id": "machine_governance_without_consumer",
                    "severity": "high",
                    "message": "Machine-shaped governance has no code/test consumer: " + ", ".join(unbacked_machine_files),
                }
            )

    # ── Check 3: Freeze active ─────────────────────────────────
    constitution = _load_yaml(root / "governance" / "system_constitution.yaml")
    freeze = constitution.get("governance_freeze", {}) or {}
    if not freeze.get("active", False):
        violations.append(
            {
                "id": "freeze_not_active",
                "severity": "medium",
                "message": "governance_freeze.active is not true in system_constitution.yaml",
            }
        )

    # ── Check 4: review_after date enforcement ──────────────────
    review_after_str = freeze.get("review_after") or manifest.get("review_after")
    if review_after_str:
        try:
            review_after = datetime.strptime(str(review_after_str), "%Y-%m-%d").replace(tzinfo=UTC)
            now = datetime.now(UTC)
            if now > review_after:
                violations.append(
                    {
                        "id": "freeze_review_expired",
                        "severity": "high",
                        "message": (
                            f"Governance freeze review_after date ({review_after_str}) has passed. "
                            "Review and renew the freeze or formally lift it."
                        ),
                    }
                )
        except ValueError:
            violations.append(
                {
                    "id": "freeze_review_invalid_date",
                    "severity": "medium",
                    "message": f"Invalid review_after date format: {review_after_str}",
                }
            )

    # ── Check 5: File hash integrity ───────────────────────────
    baseline_hashes = manifest.get("baseline_hashes", {})
    blocking_hash_files = set(manifest.get("blocking_hash_files", []) or [])
    if baseline_hashes:
        for name, expected_hash in baseline_hashes.items():
            path = gov_dir / name
            if not path.exists():
                hash_mismatches.append({"file": name, "expected": expected_hash, "actual": "MISSING"})
                violations.append(
                    {
                        "id": "baseline_file_missing",
                        "severity": "high",
                        "message": (
                            f"Baseline governance file '{name}' is missing (expected hash {expected_hash}). "
                            "Missing baseline files are blocking. Restore the file or explicitly revise the baseline."
                        ),
                    }
                )
            else:
                actual_hash = _file_hash(path)
                if actual_hash != expected_hash:
                    severity = "high" if name in blocking_hash_files else "medium"
                    hash_mismatches.append({"file": name, "expected": expected_hash, "actual": actual_hash})
                    violations.append(
                        {
                            "id": "baseline_file_modified",
                            "severity": severity,
                            "message": (
                                f"Baseline governance file '{name}' content changed since freeze "
                                f"(expected {expected_hash}, got {actual_hash}). "
                                f"Severity is {severity}. "
                                "Update baseline_hashes in manifest with explicit approval or revert."
                            ),
                        }
                    )

    # ── Check 6: Pending commits in approved_additions ──────────
    pending_commits = [
        item for item in approved_items if item.get("commit") == "pending"
    ]
    for item in pending_commits:
        violations.append(
            {
                "id": "pending_commit_attribution",
                "severity": "medium",
                "message": (
                    f"Approved addition '{item['file']}' has commit='pending'. "
                    "Assign a real commit hash."
                ),
            }
        )

    # ── Check 7: Approved additions budget ──────────────────────
    additions_budget = int(
        manifest.get("approved_additions_budget", {}).get("max_files", 10)
    )
    if len(approved_items) > additions_budget:
        violations.append(
            {
                "id": "approved_additions_budget_exceeded",
                "severity": "high",
                "message": (
                    f"approved_additions count ({len(approved_items)}) exceeds budget ({additions_budget}). "
                    "Consolidate or remove less critical additions."
                ),
            }
        )

    high = [v for v in violations if v.get("severity") == "high"]
    return {
        "valid": len(high) == 0,
        "baseline_count": len(baseline),
        "approved_additions_count": len(approved),
        "unapproved_new_files": unapproved_new,
        "hash_mismatches": hash_mismatches,
        "work_support_count": len(work_support),
        "work_support_budget": budget,
        "procedural_rule_count": len(procedural),
        "always_read_rule_lines": always_lines,
        "unbacked_machine_files": unbacked_machine_files,
        "violations": violations,
    }
