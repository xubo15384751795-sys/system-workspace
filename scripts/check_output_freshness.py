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

from scripts._runtime_io import ROOT, load_yaml, surface_dir  # noqa: E402

CONSTITUTION_PATH = ROOT / "governance" / "system_constitution.yaml"
OUTPUT_CURRENT = surface_dir("current")

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

# Critical readout-chain artifacts that scheduled depth checks must see.
# Keep the real producer paths here: promotion_gate and system_index are not
# published inside Output/current.
REQUIRED_ARTIFACT_PATHS = {
    "framework_output": ("Output/current/framework_output.json",),
    "signal_card": ("Output/current/signal_card.md",),
    "signal_consensus": ("Output/current/signal_consensus.json",),
    "work_brief": ("Output/current/work_brief.md",),
    "promotion_gate": ("Output/judgment/promotion_gate.json",),
    "system_index": ("Data/system_index/latest.json",),
    "readme_first": (
        "Output/current/00_READ_ME_FIRST.md",
        "Output/current/readme.md",
    ),
}

EXTERNAL_REQUIRED_ARTIFACTS = {
    "promotion_gate",
    "system_index",
}

DEFAULT_MAX_AGE_HOURS = 48
NON_REQUIRED_MONITORING_CLASSES = {
    "research",
    "manual_on_demand",
    "archived_retire",
}


def get_freshness_rules(constitution: dict) -> dict[str, int]:
    """Extract max_age_hours from constitution freshness_rules."""
    rules = constitution.get("freshness_rules", {})
    return rules.get("max_age_hours", {})


def _load_pipeline_registry(root: Path) -> dict:
    return load_yaml(root / "governance" / "daily_pipeline_registry.yaml") or {}


def _registry_ttl_for_current_artifact(
    relative_path: str,
    registry: dict,
) -> int | None:
    """Return the strictest registered producer TTL for a current artifact."""
    from scripts.artifact_monitoring_audit import declared_outputs, matches_pattern

    ttls = [
        int(row["ttl_hours"])
        for row in declared_outputs(registry)
        if matches_pattern(relative_path, row["pattern"])
        and isinstance(row.get("ttl_hours"), (int, float))
        and row["ttl_hours"] > 0
    ]
    return min(ttls) if ttls else None


def _is_required_monitoring_class(relative_path: str, registry: dict) -> bool:
    """Fail closed unless a path is explicitly classified as non-required."""
    from scripts.artifact_monitoring_audit import classify_monitoring_path

    classification = classify_monitoring_path(relative_path, registry)
    return classification["class"] not in NON_REQUIRED_MONITORING_CLASSES


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


def _resolve_required_artifact(root: Path, artifact: str) -> Path | None:
    for relative in REQUIRED_ARTIFACT_PATHS[artifact]:
        candidate = root / relative
        if candidate.exists():
            return candidate
    return None


def _missing_required_artifacts(root: Path) -> list[str]:
    return [
        artifact
        for artifact in REQUIRED_ARTIFACT_PATHS
        if _resolve_required_artifact(root, artifact) is None
    ]


def _external_required_freshness(
    root: Path,
    max_age_map: dict[str, int],
    now: float,
) -> list[dict]:
    """Check required artifacts whose producers publish outside Output/current."""
    findings = []
    for artifact in sorted(EXTERNAL_REQUIRED_ARTIFACTS):
        path = _resolve_required_artifact(root, artifact)
        if path is None:
            continue
        finding = check_artifact_freshness(
            path,
            max_age_map.get(artifact, DEFAULT_MAX_AGE_HOURS),
            now,
        )
        if finding:
            finding["artifact"] = artifact
            finding["severity"] = "WARN"
            findings.append(finding)
    return findings


def run_freshness_check(root: Path) -> list[dict]:
    """Run the full freshness check on Output/current/."""
    constitution = load_yaml(CONSTITUTION_PATH)
    if not constitution:
        return [{"severity": "ERROR", "status": "ERROR", "message": "Cannot load constitution"}]

    output_current = surface_dir("current") if root == ROOT else root / "Output" / "current"
    if not output_current.exists():
        return [
            {
                "severity": "ERROR",
                "status": "MISSING_DIR",
                "message": "Output/current/ does not exist",
            }
        ]

    max_age_map = get_freshness_rules(constitution)
    registry = _load_pipeline_registry(root)
    now = time.time()
    findings = []

    for item in sorted(output_current.iterdir()):
        # Skip directories and hidden files
        if item.is_dir() or item.name.startswith("."):
            continue
        relative_path = item.relative_to(root).as_posix()
        if not _is_required_monitoring_class(relative_path, registry):
            continue

        # Determine max age for this artifact
        category = ARTIFACT_CATEGORY_MAP.get(item.name)
        if category:
            max_age = max_age_map.get(category, DEFAULT_MAX_AGE_HOURS)
        else:
            max_age = (
                _registry_ttl_for_current_artifact(relative_path, registry)
                or DEFAULT_MAX_AGE_HOURS
            )

        if item.is_symlink():
            finding = check_symlink_freshness(item, max_age, now)
        else:
            finding = check_artifact_freshness(item, max_age, now)

        if finding:
            finding["severity"] = "WARN"
            findings.append(finding)

    findings.extend(_external_required_freshness(root, max_age_map, now))
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
    output_current = surface_dir("current")
    missing_required: list[str] = []
    if output_current.exists():
        missing_required = _missing_required_artifacts(ROOT)
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
