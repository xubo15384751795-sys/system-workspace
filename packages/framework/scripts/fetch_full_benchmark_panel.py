"""Deprecated Phase A wrapper for benchmark/external acquisition.

This script used to download FRED and external benchmark indicators from inside
Structural Deformation. That active acquisition path is now owned by Structural
Risk Harvester.
"""
from __future__ import annotations

import argparse


MESSAGE = """\
Deprecated: scripts/fetch_full_benchmark_panel.py no longer performs provider acquisition.

External and benchmark data acquisition belongs in Structural Risk Harvester.
Use Harvester acquisition commands to publish admitted evidence, then consume
the resulting release through Deformation's src/data_access/ boundary.

Suggested Harvester command for Phase A external indicators:
  cd /Users/a1/System/Structural\\ Risk\\ Harvester
  python -m harvester fetch-external-indicators --write-templates
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deprecated benchmark acquisition wrapper")
    parser.add_argument("--refresh", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--start", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--out", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--cache-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--external-cache-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--write-templates", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    parse_args()
    raise SystemExit(MESSAGE)


if __name__ == "__main__":
    main()
