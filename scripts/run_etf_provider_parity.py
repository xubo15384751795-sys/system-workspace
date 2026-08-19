"""Run an explicit Tiingo/Massive ETF parity shadow comparison.

This is never part of the scheduled daily release. It writes evidence only;
the output cannot certify a fallback without an explicit human-review flag.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from harvester.core.etf_parity import (
    ETF_PARITY_SENTINELS,
    build_live_provider_parity_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="60d")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--human-reviewed", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    # Reuse the same mode-600 provider secret loader as the launchd path;
    # callers may still override either key through the environment.
    try:
        from orchestration.provider_secrets import load_provider_secrets

        load_provider_secrets()
    except Exception:
        # Missing optional orchestration dependencies should produce an
        # explicit insufficient-data report rather than a secret/config crash.
        pass
    data_root = root / "Data" / "harvester"
    report = build_live_provider_parity_report(
        data_root=data_root,
        tickers=ETF_PARITY_SENTINELS,
        period=args.period,
        api_keys={
            "tiingo": os.environ.get("TIINGO_API_KEY", ""),
            "massive": os.environ.get("MASSIVE_API_KEY", ""),
        },
        human_reviewed=args.human_reviewed,
    )
    output = args.output or data_root / "provider_parity" / "etf_provider_parity.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
