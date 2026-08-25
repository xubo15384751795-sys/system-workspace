#!/usr/bin/env python3
"""Compare two isolated daily run bundles without executing or publishing.

The command is intended for the native/current observation window.  It reads
two completed run bundles and their generation candidates, then requires
matching steps.jsonl semantics, canonical lineage, input/release/vintage
identity, and published-surface bytes (with only declared JSON ephemera
ignored).  Missing evidence is not green, and promotion is always disabled.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from orchestration.run_parity import compare_daily_run_bundles
from scripts._runtime_io import ROOT

DEFAULT_REPORT = ROOT / "Output" / "health" / "native_current_dual_run_parity.json"


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, indent=2, sort_keys=True)
            temporary.write("\n")
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-run", type=Path, required=True)
    parser.add_argument("--native-run", type=Path, required=True)
    parser.add_argument("--legacy-generation", type=Path)
    parser.add_argument("--native-generation", type=Path)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = compare_daily_run_bundles(
        args.legacy_run,
        args.native_run,
        legacy_generation=args.legacy_generation,
        native_generation=args.native_generation,
    )
    output_path = args.report if args.report.is_absolute() else ROOT / args.report
    _write_json_atomically(output_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
