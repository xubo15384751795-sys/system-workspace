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

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "governance" / "governance_freeze_manifest.yaml"
TIERS_PATH = ROOT / "governance" / "governance_tiers.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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

    # ── Check 2: Work support budget ───────────────────────────
    work_support = tiers.get("work_support", {}).get("files", []) or []
    budget = int(manifest.get("work_support_budget", {}).get("max_files", 17))
    if len(work_support) > budget:
        violations.append(
            {
                "id": "work_support_budget_exceeded",
                "severity": "high",
                "message": (
                    f"work_support file count {len(work_support)} exceeds budget {budget}. "
                    "Merge or archive before adding."
                ),
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
    if baseline_hashes:
        for name, expected_hash in baseline_hashes.items():
            path = gov_dir / name
            if not path.exists():
                hash_mismatches.append({"file": name, "expected": expected_hash, "actual": "MISSING"})
                violations.append(
                    {
                        "id": "baseline_file_missing",
                        "severity": "high",
                        "message": f"Baseline governance file '{name}' is missing (expected hash {expected_hash}).",
                    }
                )
            else:
                actual_hash = _file_hash(path)
                if actual_hash != expected_hash:
                    hash_mismatches.append({"file": name, "expected": expected_hash, "actual": actual_hash})
                    violations.append(
                        {
                            "id": "baseline_file_modified",
                            "severity": "high",
                            "message": (
                                f"Baseline governance file '{name}' content changed since freeze "
                                f"(expected {expected_hash}, got {actual_hash}). "
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
        "violations": violations,
    }
