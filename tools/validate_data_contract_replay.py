#!/usr/bin/env python3
"""Read-only replay of the cross-asset data contract on real release paths.

This is intentionally independent of the provider mode.  ``shadow`` controls
the launchd release observation path; a pre-push must still prove that the
currently checked-in workspace data is safe under the same contract.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]


def _target_paths(root: Path) -> dict[str, Path]:
    return {
        "workspace_mirror": root / "Data" / "panels" / "cross_asset_daily_panel.parquet",
        "latest_release": (
            root
            / "Data"
            / "harvester"
            / "exports"
            / "latest"
            / "data"
            / "cross_asset_daily_panel.parquet"
        ),
    }


def replay_data_contract(
    root: Path = ROOT,
    *,
    expected_symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Replay the contract without writing Data, Output, or cache state."""
    # Imports are delayed so the script can report a useful missing-dependency
    # error and so its path discovery remains harmless in shell diagnostics.
    import pandas as pd
    from harvester.quality.data_contract import validate_cross_asset_panel_contract

    symbols = list(expected_symbols) if expected_symbols is not None else None
    if symbols is None:
        from harvester.cross_asset_panel import resolve_etf_universe

        symbols = resolve_etf_universe(root)

    reports: list[dict[str, Any]] = []
    for name, path in _target_paths(root).items():
        if not path.is_file():
            reports.append(
                {
                    "name": name,
                    "path": str(path),
                    "status": "BLOCK",
                    "violations": ["missing_data_file"],
                    "warnings": [],
                }
            )
            continue
        try:
            frame = pd.read_parquet(path)
            report = validate_cross_asset_panel_contract(
                frame,
                expected_symbols=symbols,
                require_nonempty=True,
                raise_on_error=False,
            )
            report = dict(report)
            report["name"] = name
            report["path"] = str(path)
        except Exception as exc:  # noqa: BLE001 - convert read failures to a gate result
            report = {
                "name": name,
                "path": str(path),
                "status": "BLOCK",
                "violations": [f"read_or_validate_failed:{type(exc).__name__}:{exc}"],
                "warnings": [],
            }
        reports.append(report)

    status = "PASS" if all(report.get("status") != "BLOCK" for report in reports) else "BLOCK"
    return {
        "schema_version": "system.data_contract_replay.v1",
        "status": status,
        "contract_id": "cross_asset_daily_panel.v1",
        "expected_symbol_count": len(symbols),
        "reports": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the complete report as JSON")
    args = parser.parse_args(argv)

    try:
        report = replay_data_contract(ROOT)
    except Exception as exc:  # noqa: BLE001 - the gate must fail closed
        report = {
            "schema_version": "system.data_contract_replay.v1",
            "status": "BLOCK",
            "contract_id": "cross_asset_daily_panel.v1",
            "reports": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    output = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    if args.json:
        print(output)
    elif report["status"] == "PASS":
        print("data contract replay PASS")
        for item in report["reports"]:
            print(f"  PASS {item['name']}: {item['path']}")
    else:
        print(output, file=sys.stderr)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
