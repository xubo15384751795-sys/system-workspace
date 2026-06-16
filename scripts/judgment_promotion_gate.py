#!/usr/bin/env python3
"""Judgment Promotion Gate — thin wrapper.

See Workbench/src/workbench/judgment/promotion_gate.py for core logic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.judgment.promotion_gate import run_promotion_gate, write_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run judgment promotion gate.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date for lookup.")
    args = parser.parse_args()

    report = run_promotion_gate(args.date)
    paths = write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Promotion gate: {report['overall_status']}")
        print(f"Claim ceiling: {report['claim_ceiling']}")
        if report["blocking_reasons"]:
            print(f"Blocked by: {', '.join(report['blocked_gates'])}")
        print(f"Allowed: {', '.join(report['allowed_language'])}")
        if report["forbidden_language"]:
            print(f"Forbidden: {', '.join(report['forbidden_language'])}")


if __name__ == "__main__":
    main()
