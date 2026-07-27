#!/usr/bin/env python3
"""Check Output/current/ artifact freshness against constitution rules.

Reads freshness_rules.max_age_hours from governance/system_constitution.yaml
and checks each artifact in Output/current/ against its allowed age.

Authority: governance/system_constitution.yaml → freshness_rules

Usage:
    python3 scripts/check_output_freshness.py
    python3 scripts/check_output_freshness.py --json
    python3 scripts/check_output_freshness.py --require-artifacts
    python3 scripts/check_output_freshness.py --ci-clean-checkout

Exit codes:
    0 — all artifacts fresh, or clean-checkout N/A
    1 — stale, missing (require mode), or validation error
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

# Critical current artifacts that scheduled depth checks must see.
REQUIRED_ARTIFACTS = (
    "framework_output.json",
    "signal_card.md",
    "signal_consensus.json",
    "work_brief.md",
    "promotion_gate.json",
    "system_index.json",
)

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


def _missing_required_artifacts(output_current: Path) -> list[str]:
    missing = [name for name in REQUIRED_ARTIFACTS if not (output_current / name).exists()]
    readme_ok = (output_current / "00_READ_ME_FIRST.md").exists() or (
        output_current / "readme.md"
    ).exists()
    if not readme_ok:
        missing.append("00_READ_ME_FIRST.md|readme.md")
    return missing


def run_freshness_check(root: Path) -> list[dict]:
    """Run the full freshness check on Output/current/."""
    constitution = load_yaml(CONSTITUTION_PATH)
    if not constitution:
        return [{"severity": "ERROR", "status": "ERROR", "message": "Cannot load constitution"}]

    output_current = root / "Output" / "current"
    if not output_current.exists():
        return [
            {
                "severity": "ERROR",
                "status": "MISSING_DIR",
                "message": "Output/current/ does not exist",
            }
        ]

    max_age_map = get_freshness_rules(constitution)
    now = time.time()
    findings = []

    for item in sorted(output_current.iterdir()):
        # Skip directories and hidden files
        if item.is_dir() or item.name.startswith("."):
            continue

        # Determine max age for this artifact
        category = ARTIFACT_CATEGORY_MAP.get(item.name)
        if category:
            max_age = max_age_map.get(category, DEFAULT_MAX_AGE_HOURS)
        else:
            max_age = DEFAULT_MAX_AGE_HOURS

        if item.is_symlink():
            finding = check_symlink_freshness(item, max_age, now)
        else:
            finding = check_artifact_freshness(item, max_age, now)

        if finding:
            finding["severity"] = "WARN"
            findings.append(finding)

    return findings


def _verdict_for(
    findings: list[dict],
    *,
    require_artifacts: bool,
    ci_clean_checkout: bool,
    missing_required: list[str],
) -> tuple[str, int]:
    """Return (verdict, exit_code). Never labels clean-checkout absence as PASS."""
    if any(f.get("status") == "ERROR" and "constitution" in f.get("message", "") for f in findings):
        return "FAIL", 1

    missing_dir = any(f.get("status") == "MISSING_DIR" for f in findings)
    if missing_dir or missing_required:
        if require_artifacts:
            return "FAIL", 1
        if ci_clean_checkout:
            return "NOT_APPLICABLE", 0
        # Default (legacy local): missing dir is not a hard fail, but not PASS either
        if missing_dir and not any(f.get("status") == "STALE" for f in findings):
            return "WARN", 0
        if missing_required:
            return "FAIL", 1

    if any(f.get("status") == "STALE" for f in findings):
        return "FAIL", 1
    if any(f.get("status") in {"MISSING", "BROKEN_SYMLINK", "ERROR"} for f in findings):
        if require_artifacts:
            return "FAIL", 1
        if ci_clean_checkout:
            return "FAIL", 1
    return "PASS", 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--require-artifacts",
        action="store_true",
        help="Fail when Output/current or required artifacts are missing (Nightly/Weekly).",
    )
    mode.add_argument(
        "--ci-clean-checkout",
        action="store_true",
        help="Missing current artifacts → NOT_APPLICABLE (not PASS).",
    )
    args = parser.parse_args()

    findings = run_freshness_check(ROOT)
    output_current = ROOT / "Output" / "current"
    missing_required: list[str] = []
    if output_current.exists():
        missing_required = _missing_required_artifacts(output_current)
        if missing_required and (args.require_artifacts or args.ci_clean_checkout):
            for name in missing_required:
                findings.append(
                    {
                        "severity": "ERROR",
                        "status": "MISSING",
                        "file": name,
                        "message": f"Required artifact missing: {name}",
                    }
                )

    verdict, exit_code = _verdict_for(
        findings,
        require_artifacts=args.require_artifacts,
        ci_clean_checkout=args.ci_clean_checkout,
        missing_required=missing_required if (args.require_artifacts or args.ci_clean_checkout) else [],
    )

    # Clean checkout with no current tree at all.
    if (
        args.ci_clean_checkout
        and any(f.get("status") == "MISSING_DIR" for f in findings)
        and not any(f.get("status") == "STALE" for f in findings)
    ):
        verdict, exit_code = "NOT_APPLICABLE", 0

    if args.json or args.ci_clean_checkout or args.require_artifacts:
        report = {
            "check": "output_freshness",
            "verdict": verdict,
            "findings": findings,
            "missing_required": missing_required,
            # Retain legacy key for callers that still read status=
            "status": verdict,
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
        print(f"verdict: {verdict}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
