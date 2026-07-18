#!/usr/bin/env python3
"""Validate proxy observation catalog against Harvester panels.

Checks that catalogued benchmark_panel series exist in the latest release.
Cross-asset proxies are checked against cross_asset_daily_panel when present.

Usage:
    python3 scripts/validate_proxy_observation_catalog.py
    python3 scripts/validate_proxy_observation_catalog.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import yaml
from scripts._runtime_io import ROOT, ensure_dir, write_json

CATALOG = ROOT / "governance" / "proxy_observation_catalog.yaml"
BENCHMARK = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
CROSS_ASSET = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "cross_asset_daily_panel.parquet"
OUT_JSON = ROOT / "Output" / "quality" / "proxy_catalog_report.json"
OUT_MD = ROOT / "Output" / "quality" / "proxy_catalog_report.md"


def _load_catalog() -> dict[str, Any]:
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}


def _benchmark_ids() -> set[str]:
    if not BENCHMARK.exists():
        return set()
    import pandas as pd

    return set(pd.read_parquet(BENCHMARK)["series_id"].astype(str).unique())


def _cross_asset_symbols() -> set[str]:
    if not CROSS_ASSET.exists():
        path = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
        if not path.exists():
            return set()
        CROSS_ASSET_PATH = path
    else:
        CROSS_ASSET_PATH = CROSS_ASSET
    import pandas as pd

    frame = pd.read_parquet(CROSS_ASSET_PATH)
    if "symbol" in frame.columns:
        return set(frame["symbol"].astype(str).unique())
    return set()


def validate() -> dict[str, Any]:
    catalog = _load_catalog()
    proxies = catalog.get("proxies", {})
    bench = _benchmark_ids()
    etf = _cross_asset_symbols()

    missing: list[dict[str, str]] = []
    present: list[str] = []

    for key, meta in proxies.items():
        if key.startswith("cross_asset:"):
            sym = key.split(":", 1)[1]
            if sym in etf:
                present.append(key)
            else:
                missing.append({"proxy": key, "reason": "symbol not in cross_asset panel"})
        else:
            if key in bench:
                present.append(key)
            else:
                missing.append({"proxy": key, "reason": "series_id not in benchmark_panel"})

    verdict = "PASS" if not missing else "FINDINGS"
    return {
        "schema_version": "proxy_catalog_report.v1",
        "catalog_path": str(CATALOG.relative_to(ROOT)),
        "verdict": verdict,
        "present_count": len(present),
        "missing_count": len(missing),
        "missing": missing,
        "present": present,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate proxy observation catalog.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = validate()
    ensure_dir(OUT_JSON.parent)
    write_json(OUT_JSON, report)
    lines = [
        "# Proxy Catalog Report",
        "",
        f"Verdict: **{report['verdict']}**",
        f"Present: {report['present_count']} | Missing: {report['missing_count']}",
        "",
    ]
    if report["missing"]:
        lines.append("## Missing")
        for item in report["missing"]:
            lines.append(f"- {item['proxy']}: {item['reason']}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Proxy catalog: {report['verdict']} ({report['missing_count']} missing)")
        print(f"Report: {OUT_MD}")

    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
