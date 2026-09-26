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
from typing import Any, Mapping

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACE_PATH = ROOT / "PACE.md"
DECISION_PREFIX = "governance/routing_decisions/"
REQUIRED_PROBE_FIELDS = {
    "scope",
    "preregistered_expectation",
    "observation_window",
    "rollback",
}
ACTIVE_EPOCH_STATUSES = frozenset({"active", "adopted"})
EPOCH_LAYERS_DEFAULT = ("L3",)


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


def is_pace_decision(path: Path) -> bool:
    """Return whether a routing-decision record carries PACE/Cynefin fields.

    The routing_decisions directory also contains frozen research protocols
    and estate-disposition records. Those records are governance evidence,
    but they are not substitutes for a PACE routing decision.
    """
    if not path.is_file():
        return True
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return isinstance(data, dict) and "cynefin_domain" in data


def _load_decision_mapping(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _decision_files(root: Path) -> list[Path]:
    directory = root / DECISION_PREFIX.rstrip("/")
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix in {".yaml", ".yml"}
    )


def epoch_covers_path(path: str, coverage: Mapping[str, Any]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    excluded = [
        str(item).replace("\\", "/").lstrip("./")
        for item in coverage.get("exclude_paths") or coverage.get("excluded_paths") or []
    ]
    if normalized in excluded:
        return False
    exact = {
        str(item).replace("\\", "/").lstrip("./")
        for item in coverage.get("paths") or []
    }
    if normalized in exact:
        return True
    prefixes = [
        str(item).replace("\\", "/").lstrip("./")
        for item in coverage.get("path_prefixes") or []
    ]
    return any(normalized.startswith(prefix) for prefix in prefixes if prefix)


def load_covering_epoch_decisions(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Return on-disk epoch decisions that cover later L3 commits.

    An epoch decision is an intentional load reduction: one Cynefin-complex
    probe preregisters a bounded L3 scope so later in-scope commits do not
    each need a new routing-decision file. Out-of-scope L3 and all L4 paths
    still require a decision in the same change.
    """
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in _decision_files(root):
        data = _load_decision_mapping(path)
        if data is None:
            continue
        coverage = data.get("epoch_coverage")
        if not isinstance(coverage, dict):
            continue
        if not coverage.get("covers_subsequent_commits"):
            continue
        status = str(data.get("status") or coverage.get("status") or "").strip().lower()
        if status not in ACTIVE_EPOCH_STATUSES:
            continue
        found.append((path, data))
    return found


def check_paths(paths: list[str], root: Path = ROOT) -> list[str]:
    pace = load_pace(root / "PACE.md")
    classified = {path: classify_path(path, pace) for path in paths}
    slow = {path: layer for path, layer in classified.items() if layer in {"L3", "L4"}}
    if not slow:
        return []

    candidate_refs = [
        path for path in paths
        if path.replace("\\", "/").lstrip("./").startswith(DECISION_PREFIX)
        and path.endswith((".yaml", ".yml"))
    ]
    env_ref = os.environ.get("ROUTING_DECISION_REF", "").strip()
    if env_ref:
        candidate_refs.append(env_ref)

    decision_refs = [
        ref
        for ref in candidate_refs
        if is_pace_decision(root / ref.replace("\\", "/").lstrip("./"))
    ]

    if not decision_refs:
        uncovered: dict[str, str] = {}
        covering_epochs: list[Path] = []
        epochs = load_covering_epoch_decisions(root)
        for path, layer in slow.items():
            matched = False
            for epoch_path, data in epochs:
                coverage = data.get("epoch_coverage") or {}
                layers = coverage.get("layers") or list(EPOCH_LAYERS_DEFAULT)
                allowed_layers = {str(item) for item in layers}
                if layer not in allowed_layers:
                    continue
                if epoch_covers_path(path, coverage):
                    covering_epochs.append(epoch_path)
                    matched = True
                    break
            if not matched:
                uncovered[path] = layer
        if not uncovered and covering_epochs:
            errors: list[str] = []
            for epoch_path in sorted(set(covering_epochs)):
                errors.extend(validate_decision(epoch_path))
            return errors
        details = ", ".join(f"{path} ({layer})" for path, layer in sorted(slow.items()))
        return [
            "PACE violation: L3/L4 change has no PACE routing decision "
            "(cynefin_domain required) in the same change: " + details
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


def _changed_paths(root: Path, base_ref: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMR",
            f"{base_ref}...HEAD",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git diff exited {result.returncode}"
        raise ValueError(f"could not resolve PACE base ref {base_ref!r}: {detail}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Changed paths (pre-commit passes these).")
    parser.add_argument(
        "--base-ref",
        help="Compare this Git ref or SHA with HEAD (used by pull-request CI).",
    )
    args = parser.parse_args(argv)
    try:
        if args.paths:
            paths = args.paths
        elif args.base_ref:
            paths = _changed_paths(ROOT, args.base_ref)
        else:
            paths = _staged_paths(ROOT)
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
