#!/usr/bin/env python3
"""K Measurement Gate — thin wrapper.

See packages/workbench/src/workbench/signals/k_gate.py for core logic.
"""
from __future__ import annotations

import argparse
import json

from workbench.signals.k_gate import run_gate, write_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run K measurement gate.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = run_gate()
    write_outputs(report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"K measurement gate: {report['gate_verdict']}")
        for test_name, test in report["tests"].items():
            print(f"  {test_name}: {test['status']}")


if __name__ == "__main__":
    main()
