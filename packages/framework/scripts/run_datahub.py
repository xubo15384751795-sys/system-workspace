from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]

from src.data.gateway import create_data_hub


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified DataHub CLI for free public data providers.")
    parser.add_argument("kind", choices=["series", "events", "filings", "positions", "structural"], help="DataHub method to call.")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--start", required=True, help="Start date, e.g. 2025-01-01")
    parser.add_argument("--end", required=True, help="End date, e.g. 2026-04-22")
    parser.add_argument(
        "--request",
        action="append",
        help='JSON request payload, e.g. \'{"provider":"fred","series_id":"DFF"}\'',
    )
    parser.add_argument(
        "--preset",
        action="append",
        help="Structural preset name, e.g. mismatch_policy_funding_gap_us",
    )
    parser.add_argument("--mock", action="store_true", help="Use mock adapters instead of live public APIs.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    with open(args.config, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    hub = create_data_hub(config=config, use_mock=bool(args.mock))
    if args.kind == "structural":
        preset_names = list(args.preset or [])
        if not preset_names:
            raise SystemExit("--preset is required when kind=structural")
        result = hub.fetch_structural_presets(preset_names, start=args.start, end=args.end)
    else:
        requests = [json.loads(item) for item in (args.request or [])]
        if not requests:
            raise SystemExit("--request is required for series/events/filings/positions")
        method = getattr(hub, f"fetch_{args.kind}")
        result = method(requests, start=args.start, end=args.end)
    print(json.dumps(result.to_dict(), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
