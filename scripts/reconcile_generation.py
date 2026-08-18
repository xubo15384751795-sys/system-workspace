#!/usr/bin/env python3
"""Read-only startup reconciliation for the immutable generation topology."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts._runtime_io import ROOT
from system_runtime.publish_transaction import PublishTransaction


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Return non-zero unless a complete active generation is present.",
    )
    parser.add_argument(
        "--fail-on-recovery",
        action="store_true",
        help="Return non-zero only when reconciliation identifies recovery work.",
    )
    args = parser.parse_args(argv)
    state = PublishTransaction.reconcile(args.root.expanduser().resolve())
    print(json.dumps(state, indent=2, ensure_ascii=False))
    if args.require_complete and state.get("status") not in {"complete", "complete_legacy_baseline"}:
        return 1
    if args.fail_on_recovery and state.get("status") == "recovery_required":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
