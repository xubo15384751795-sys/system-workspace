#!/usr/bin/env python3
"""Check Output/current/ artifact freshness against constitution rules.

Reads freshness_rules.max_age_hours from governance/system_constitution.yaml
and checks each artifact in Output/current/ against its allowed age.

Authority: governance/system_constitution.yaml → freshness_rules

Usage:
    python3 scripts/check_output_freshness.py
    python3 scripts/check_output_freshness.py --json

Exit codes:
    0 — all artifacts fresh
    1 — one or more critical artifacts are stale
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path



from scripts._runtime_io import ROOT, load_yaml  # noqa: E402

CONSTITUTION_PATH = ROOT / "governance" / "system_constitution.yaml"
OUTPUT_CURRENT = ROOT / "Output" / "current"

# Map artifact filenames to freshness_rules.max_age_hours keys.
# Files not in this map use the default max age.
ARTIFACT_CATEGORY_MAP = {
    "00_READ_ME_FIRST.md": "readme",
    "readme.md": "readme",
    "framework_output.json": "framework_output",
    "signal_card.md": "signal_card",
    "signal_consensus.json": "signal_consensus",
    "work_brief.md": "work_brief",
    "promotion_gate.json": "promotion_gate",
    "system_index.json": "system_index",
}

DEFAULT_MAX_AGE_HOURS = 48


def get_freshness_rules(constitution: dict) -> dict[str, int]:
    """Extract max_age_hours from constitution freshness_rules."""
    rules = constitution.get("freshness_rules", {})
    return rules.get("max_age_hours", {})


def check_artifact_freshness(
    filepath: Path,
    max_age_hours: int,
    now: float,
) -> dict | None:
    """Check if a single artifact is within its freshness window."""
    try:
        mtime = filepath.stat().st_mtime
    except OSError:
        return {
            "file": filepath.name,
            "status": "MISSING",
            "message": f"Cannot stat {filepath.name}",
        }

    age_hours = (now - mtime) / 3600
    if age_hours > max_age_hours:
        return {
            "file": filepath.name,
            "status": "STALE",
            "age_hours": round(age_hours, 1),
            "max_age_hours": max_age_hours,
            "message": (
                f"{filepath.name} is {round(age_hours, 1)}h old "
                f"(max {max_age_hours}h)"
            ),
        }
    return None


def check_symlink_freshness(
    symlink: Path,
    max_age_hours: int,
    now: float,
) -> dict | None:
    """Check if a symlink target is fresh."""
    try:
        target = symlink.resolve()
        if not target.exists():
            return {
                "file": symlink.name,
                "status": "BROKEN_SYMLINK",
                "message": f"Symlink {symlink.name} points to missing target",
            }
        return check_artifact_freshness(target, max_age_hours, now)
    except OSError:
        return {
            "file": symlink.name,
            "status": "ERROR",
            "message": f"Cannot resolve symlink {symlink.name}",
        }


def run_freshness_check(root: Path) -> list[dict]:
    """Run the full freshness check on Output/current/."""
    constitution = load_yaml(CONSTITUTION_PATH)
    if not constitution:
        return [{"severity": "ERROR", "message": "Cannot load constitution"}]

    if not OUTPUT_CURRENT.exists():
        return [{"severity": "WARN", "message": "Output/current/ does not exist"}]

    max_age_map = get_freshness_rules(constitution)
    now = time.time()
    findings = []

    for item in sorted(OUTPUT_CURRENT.iterdir()):
        # Skip directories and hidden files
        if item.is_dir() or item.name.startswith("."):
            continue

        # Determine max age for this artifact
        category = ARTIFACT_CATEGORY_MAP.get(item.name)
        if category:
            max_age = max_age_map.get(category, DEFAULT_MAX_AGE_HOURS)
        else:
            # Use the shortest default for uncategorized files
            max_age = DEFAULT_MAX_AGE_HOURS

        if item.is_symlink():
            finding = check_symlink_freshness(item, max_age, now)
        else:
            finding = check_artifact_freshness(item, max_age, now)

        if finding:
            finding["severity"] = "WARN"
            findings.append(finding)

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    findings = run_freshness_check(ROOT)

    if args.json:
        report = {
            "check": "output_freshness",
            "findings": findings,
            "status": "FAIL" if any(f.get("status") == "STALE" for f in findings) else "PASS",
        }
        print(json.dumps(report, indent=2))
    else:
        stale = [f for f in findings if f.get("status") == "STALE"]
        if stale:
            print(f"WARNING: {len(stale)} stale artifact(s) in Output/current/:")
            for f in stale:
                print(f"  {f['message']}")
        other = [f for f in findings if f.get("status") != "STALE"]
        if other:
            for f in other:
                print(f"  [{f.get('severity', 'INFO')}] {f['message']}")

    return 1 if any(f.get("status") == "STALE" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
