#!/usr/bin/env python3
"""Check governance freeze — fail if unapproved governance files exist."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_scripts
add_scripts()

from _governance_freeze import check_governance_freeze  # noqa: E402


def main() -> None:
    report = check_governance_freeze(ROOT)
    if report["unapproved_new_files"]:
        print("Unapproved governance files:")
        for name in report["unapproved_new_files"]:
            print(f"  - {name}")
    if report["violations"]:
        print("Violations:")
        for item in report["violations"]:
            print(f"  [{item['severity']}] {item['message']}")
    if not report["valid"]:
        sys.exit(1)
    print(
        f"Governance freeze OK — "
        f"work_support {report['work_support_count']}/{report['work_support_budget']}"
    )


if __name__ == "__main__":
    main()
