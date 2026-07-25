#!/usr/bin/env python3
"""Judgment Promotion Gate — thin wrapper.

See packages/workbench/src/workbench/judgment/promotion_gate.py for core logic.
"""
from __future__ import annotations

import argparse
import json

from workbench.judgment.promotion_gate import run_promotion_gate, write_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run judgment promotion gate.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--date", default=None, help="Override date for lookup.")
    args = parser.parse_args()

    report = run_promotion_gate(args.date)
    write_outputs(report)

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
