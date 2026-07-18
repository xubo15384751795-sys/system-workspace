#!/usr/bin/env python3
"""Run the canonical Learning Hub collect -> append -> derive pipeline."""
from __future__ import annotations

from scripts._runtime_io import ROOT

from system_learning.cli import main as hub_main


def main() -> int:
    return hub_main(["run", "--system-root", str(ROOT), "--no-refresh"])


if __name__ == "__main__":
    raise SystemExit(main())
