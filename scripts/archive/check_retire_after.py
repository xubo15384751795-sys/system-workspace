#!/usr/bin/env python3
"""Check for entrypoints past their retire_after date.

Reads governance/entrypoint_registry.yaml and flags any entry whose
retire_after date has passed but status is still active/experimental.

Usage:
    python3 scripts/check_retire_after.py
    python3 scripts/check_retire_after.py --json

Exit codes:
    0 — no violations
    1 — one or more entrypoints past retire_after date
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from _workspace_imports import add_scripts  # noqa: E402

add_scripts()

from _runtime_io import ROOT, load_yaml  # noqa: E402

REGISTRY_PATH = ROOT / "governance" / "entrypoint_registry.yaml"


def check_retire_after() -> list[dict[str, str]]:
    """Return list of entrypoints past their retire_after date."""
    registry = load_yaml(REGISTRY_PATH)
    if not registry:
        return []

    today = date.today()
    violations: list[dict[str, str]] = []

    for name, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        retire = entry.get("retire_after")
        if not retire:
            continue
        try:
            retire_date = date.fromisoformat(str(retire))
        except (ValueError, TypeError):
            continue
        if retire_date < today:
            violations.append({
                "entrypoint": name,
                "retire_after": str(retire),
                "status": entry.get("status", "unknown"),
                "script": entry.get("script", ""),
            })

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    violations = check_retire_after()

    if args.json:
        print(json.dumps(violations, indent=2))
    else:
        if violations:
            print(f"WARNING: {len(violations)} entrypoint(s) past retire_after date:")
            for v in violations:
                print(f"  {v['entrypoint']}: retired after {v['retire_after']}, status={v['status']}")
        else:
            print("OK: No entrypoints past retire_after date.")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
