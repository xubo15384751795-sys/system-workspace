#!/usr/bin/env python3
"""Require a bounded routing decision when a change touches PACE L3/L4.

The default pre-commit mode receives staged filenames. A clean result writes
nothing; deviations go to stderr and return 1.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
PACE_PATH = ROOT / "PACE.md"
DECISION_PREFIX = "governance/routing_decisions/"
REQUIRED_PROBE_FIELDS = {
    "scope",
    "preregistered_expectation",
    "observation_window",
    "rollback",
}


def load_pace(path: Path = PACE_PATH) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing YAML front matter")
    try:
        front_matter = text.split("---\n", 2)[1]
    except IndexError as exc:
        raise ValueError(f"{path}: unterminated YAML front matter") from exc
    data = yaml.safe_load(front_matter)
    if not isinstance(data, dict) or not isinstance(data.get("layers"), dict):
        raise ValueError(f"{path}: invalid layers mapping")
    return data


def classify_path(path: str, pace: dict[str, Any]) -> str | None:
    normalized = path.replace("\\", "/").lstrip("./")
    for layer in ("L4", "L3", "L2", "L1"):
        rule = pace["layers"].get(layer, {})
        if normalized in set(rule.get("paths", [])):
            return layer
        if any(normalized.startswith(prefix) for prefix in rule.get("prefixes", [])):
            return layer
    return None


def validate_decision(path: Path) -> list[str]:
    if not path.is_file():
        return [f"routing decision does not exist: {path}"]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return [f"routing decision must be a mapping: {path}"]

    errors: list[str] = []
    domain = str(data.get("cynefin_domain", "")).strip().lower()
    valid_domains = {"clear", "complicated", "complex", "chaotic"}
    if domain not in valid_domains:
        errors.append(f"{path}: cynefin_domain must be one of {sorted(valid_domains)}")
    if domain == "complex":
        probe = data.get("probe")
        if not isinstance(probe, dict):
            errors.append(f"{path}: complex decision requires probe mapping")
        else:
            missing = sorted(field for field in REQUIRED_PROBE_FIELDS if not probe.get(field))
            if missing:
                errors.append(f"{path}: complex probe missing {', '.join(missing)}")
    return errors


def check_paths(paths: list[str], root: Path = ROOT) -> list[str]:
    pace = load_pace(root / "PACE.md")
    classified = {path: classify_path(path, pace) for path in paths}
    slow = {path: layer for path, layer in classified.items() if layer in {"L3", "L4"}}
    if not slow:
        return []

    decision_refs = [
        path for path in paths
        if path.replace("\\", "/").lstrip("./").startswith(DECISION_PREFIX)
        and path.endswith((".yaml", ".yml"))
    ]
    env_ref = os.environ.get("ROUTING_DECISION_REF", "").strip()
    if env_ref:
        decision_refs.append(env_ref)

    if not decision_refs:
        details = ", ".join(f"{path} ({layer})" for path, layer in sorted(slow.items()))
        return [
            "PACE violation: L3/L4 change has no routing decision in the same change: " + details
        ]

    errors: list[str] = []
    for ref in sorted(set(decision_refs)):
        normalized = ref.replace("\\", "/").lstrip("./")
        errors.extend(validate_decision(root / normalized))
    return errors


def _staged_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Changed paths (pre-commit passes these).")
    args = parser.parse_args(argv)
    paths = args.paths or _staged_paths(ROOT)
    try:
        errors = check_paths(paths, ROOT)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors = [f"PACE check could not run: {exc}"]
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
