"""Submit an experiment to the experimental submission registry.

Usage:
    python scripts/submit_experiment.py \\
        --id my_experiment_001 \\
        --type exploration \\
        --owner scripts/my_script.py \\
        --reason "Testing new proxy for K dimension" \\
        --paths "scripts/my_script.py,tests/test_my_script.py"

This adds an entry to governance/experimental_submission_registry.yaml
with required fields pre-filled and status=open.
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from _runtime_io import ROOT, load_yaml
REGISTRY_PATH = ROOT / "governance" / "experimental_submission_registry.yaml"


def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return load_yaml(REGISTRY_PATH) or {}
    return {"schema_version": "experimental_submission.v1", "submissions": []}


def _save_registry(data: dict) -> None:
    REGISTRY_PATH.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def submit_experiment(
    submission_id: str,
    submission_type: str,
    owner: str,
    reason: str,
    affected_paths: list[str],
    evidence_paths: list[str] | None = None,
    rule_deviation: str = "",
    retire_days: int = 14,
) -> dict:
    """Add a submission to the registry."""
    registry = _load_registry()
    submissions = registry.get("submissions", []) or []

    # Check for duplicate ID
    existing_ids = {s.get("submission_id") for s in submissions}
    if submission_id in existing_ids:
        raise ValueError(f"Submission '{submission_id}' already exists")

    now = datetime.now(UTC)
    retire_after = (now + timedelta(days=retire_days)).strftime("%Y-%m-%d")

    entry = {
        "submission_id": submission_id,
        "submitted_by": owner,
        "owner": owner,
        "status": "open",
        "submission_type": submission_type,
        "current_priority": "low",
        "rule_deviation": rule_deviation or "none",
        "affected_paths": affected_paths,
        "evidence_paths": evidence_paths or affected_paths,
        "review_deadline": (now + timedelta(days=7)).strftime("%Y-%m-%d"),
        "reviewer": "",
        "decision": "",
        "decision_reason": "",
        "rollback_plan": f"revert {', '.join(affected_paths)}",
        "retire_after": retire_after,
        "submitted_at": now.strftime("%Y-%m-%d"),
    }

    submissions.append(entry)
    registry["submissions"] = submissions
    _save_registry(registry)

    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit experiment to registry")
    parser.add_argument("--id", required=True, help="Unique submission ID")
    parser.add_argument(
        "--type", default="exploration", choices=["exploration", "topology_change"],
        help="Submission type",
    )
    parser.add_argument("--owner", required=True, help="Owner script or module path")
    parser.add_argument("--reason", required=True, help="Why this experiment exists")
    parser.add_argument(
        "--paths", required=True,
        help="Comma-separated affected file paths",
    )
    parser.add_argument(
        "--evidence", default=None,
        help="Comma-separated evidence paths (defaults to --paths)",
    )
    parser.add_argument("--deviation", default="", help="Rule deviation description")
    parser.add_argument("--retire-days", type=int, default=14, help="Days until auto-archive")

    args = parser.parse_args()

    affected = [p.strip() for p in args.paths.split(",") if p.strip()]
    evidence = (
        [p.strip() for p in args.evidence.split(",") if p.strip()]
        if args.evidence else None
    )

    try:
        entry = submit_experiment(
            submission_id=args.id,
            submission_type=args.type,
            owner=args.owner,
            reason=args.reason,
            affected_paths=affected,
            evidence_paths=evidence,
            rule_deviation=args.deviation,
            retire_days=args.retire_days,
        )
        print(f"✅ Submitted: {entry['submission_id']}")
        print(f"   Status: {entry['status']}")
        print(f"   Retire after: {entry['retire_after']}")
        print(f"   Registry: {REGISTRY_PATH}")
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
