"""Governance freeze — machine-checkable enforcement of system_constitution.yaml.

Admission is shape classification, not freeze-allowlist membership.
File-count additions budget is advisory inventory. Hash blocking is limited
to authority-lock files.
"""
from __future__ import annotations

import fnmatch
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT  # noqa: E402
from verity.runtime.runtime_io import load_yaml as _load_yaml

MANIFEST_PATH = ROOT / "governance" / "governance_freeze_manifest.yaml"
TIERS_PATH = ROOT / "governance" / "governance_tiers.yaml"


def _ignored(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _file_hash(path: Path) -> str:
    """SHA256[:16] of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _machine_consumer_evidence(root: Path, names: set[str]) -> dict[str, list[str]]:
    """Find code, tests, hooks, or CI that actually consume a governance file."""
    evidence = {name: [] for name in names}
    search_roots = ("scripts", "packages", "system_runtime", "system_cli", "tests", ".github", "tools", "verity")
    candidates: list[Path] = []
    for relative in search_roots:
        base = root / relative
        if base.is_dir():
            candidates.extend(path for path in base.rglob("*") if path.is_file())
    candidates.extend(
        path for path in (root / "pyproject.toml", root / "Makefile", root / "Justfile")
        if path.is_file()
    )
    allowed_suffixes = {".py", ".sh", ".yaml", ".yml", ".toml"}
    for path in candidates:
        if path.suffix not in allowed_suffixes and path.name not in {"Makefile", "Justfile"}:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for name in names:
            if name in content:
                evidence[name].append(str(path.relative_to(root)))
    return {name: sorted(paths) for name, paths in evidence.items()}


def check_governance_freeze(root: Path = ROOT) -> dict[str, Any]:
    manifest = _load_yaml(root / MANIFEST_PATH.relative_to(ROOT))
    tiers = _load_yaml(root / TIERS_PATH.relative_to(ROOT))

    baseline = set(manifest.get("baseline_root_files", []))
    approved_items = manifest.get("approved_additions", [])
    approved = {item["file"] for item in approved_items if item.get("file")}
    ignore_patterns = list(manifest.get("ignore_patterns", []))

    violations: list[dict[str, str]] = []
    hash_mismatches: list[dict[str, str]] = []

    gov_dir = root / "governance"

    # ── Check 1: Attention-shape admission ─────────────────────
    # File volume is not governance weight. A root file is admitted when it
    # is classified; a machine-shaped rule must have a real code/test consumer.
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
    # CLI/test alias: admission failure is missing classification, not freeze listing.
    unapproved_new = unclassified_shapes
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

    # ── Check 2: Freeze active ─────────────────────────────────
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

    # ── Check 3: review_after date enforcement ──────────────────
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

    # ── Check 4: File hash integrity ───────────────────────────
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

    # ── Check 5: Pending commits in approved_additions ──────────
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

    # ── Check 6: Approved additions ledger (advisory) ───────────
    additions_budget = int(
        manifest.get("approved_additions_budget", {}).get("max_files", 10)
    )
    if len(approved_items) > additions_budget:
        violations.append(
            {
                "id": "approved_additions_budget_exceeded",
                "severity": "medium",
                "message": (
                    f"approved_additions ledger count ({len(approved_items)}) exceeds "
                    f"historical inventory cap ({additions_budget}). "
                    "This is advisory; admission is shape_inventory plus consumers."
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
