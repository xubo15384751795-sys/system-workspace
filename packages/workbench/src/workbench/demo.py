"""wb-demo — generate test data and run the full Workbench pipeline.

Usage:
  wb-demo              Run full demo
  wb-demo --quick      Skip matplotlib chart generation (faster)
  wb-demo --no-html    Skip HTML rendering
  wb-demo --dir PATH   Use PATH as workspace root (default: auto-detect)

Generates synthetic Harvester release data, runs validation + freshness +
dashboard + current-card, and prints a summary.  No real Harvester or
Deformation Framework needed.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from workbench.paths import workbench_root, workspace_root

DEMO_RELEASE_ID = "demo_20260510"
DEMO_CREATED_AT = "2026-05-10T08:00:00Z"
DEMO_PROVIDER_ID = "demo_provider"

# ── Synthetic data ──────────────────────────────────────────────────────

EVIDENCE_COLUMNS = ["date", "series_id", "source_id", "source_series_id",
                    "value", "unit", "frequency", "vintage_date", "quality_flag"]

SYNTHETIC_DATA: list[dict[str, str]] = [
    {"date": "2026-04-27", "series_id": "VIXCLS", "source_id": "cboe", "source_series_id": "VIXCLS",
     "value": "18.42", "unit": "index", "frequency": "business_daily", "vintage_date": "2026-04-28", "quality_flag": "observed"},
    {"date": "2026-04-28", "series_id": "VIXCLS", "source_id": "cboe", "source_series_id": "VIXCLS",
     "value": "17.85", "unit": "index", "frequency": "business_daily", "vintage_date": "2026-04-29", "quality_flag": "observed"},
    {"date": "2026-04-29", "series_id": "VIXCLS", "source_id": "cboe", "source_series_id": "VIXCLS",
     "value": "16.90", "unit": "index", "frequency": "business_daily", "vintage_date": "2026-04-30", "quality_flag": "observed"},
    {"date": "2026-04-30", "series_id": "VIXCLS", "source_id": "cboe", "source_series_id": "VIXCLS",
     "value": "17.31", "unit": "index", "frequency": "business_daily", "vintage_date": "2026-05-01", "quality_flag": "observed"},
    {"date": "2026-05-01", "series_id": "VIXCLS", "source_id": "cboe", "source_series_id": "VIXCLS",
     "value": "17.10", "unit": "index", "frequency": "business_daily", "vintage_date": "2026-05-02", "quality_flag": "observed"},
    {"date": "2026-03-25", "series_id": "NFCI", "source_id": "fred_chicago_fed", "source_series_id": "NFCI",
     "value": "-0.38", "unit": "index", "frequency": "weekly", "vintage_date": "2026-03-27", "quality_flag": "observed"},
    {"date": "2026-04-01", "series_id": "NFCI", "source_id": "fred_chicago_fed", "source_series_id": "NFCI",
     "value": "-0.42", "unit": "index", "frequency": "weekly", "vintage_date": "2026-04-03", "quality_flag": "observed"},
    {"date": "2026-04-08", "series_id": "NFCI", "source_id": "fred_chicago_fed", "source_series_id": "NFCI",
     "value": "-0.39", "unit": "index", "frequency": "weekly", "vintage_date": "2026-04-10", "quality_flag": "observed"},
    {"date": "2026-04-15", "series_id": "NFCI", "source_id": "fred_chicago_fed", "source_series_id": "NFCI",
     "value": "-0.45", "unit": "index", "frequency": "weekly", "vintage_date": "2026-04-17", "quality_flag": "observed"},
    {"date": "2026-04-22", "series_id": "NFCI", "source_id": "fred_chicago_fed", "source_series_id": "NFCI",
     "value": "-0.50", "unit": "index", "frequency": "weekly", "vintage_date": "2026-04-24", "quality_flag": "observed"},
    {"date": "2026-04-29", "series_id": "NFCI", "source_id": "fred_chicago_fed", "source_series_id": "NFCI",
     "value": "-0.52", "unit": "index", "frequency": "weekly", "vintage_date": "2026-05-01", "quality_flag": "observed"},
]

FRESHNESS_POLICY = {
    "frequency_thresholds": {
        "weekly": {"fresh_lag_days": 10, "acceptable_lag_days": 21},
        "business_daily": {"fresh_lag_days": 3, "acceptable_lag_days": 10},
        "unknown": {"fresh_lag_days": 30, "acceptable_lag_days": 90},
    },
    "indicators": {
        "VIXCLS": {"frequency": "business_daily", "required": True},
        "NFCI": {"frequency": "weekly", "required": True},
    },
    "gate_defaults": {
        "stale_required_severity": "warn",
        "missing_required_severity": "block",
        "retired_used_severity": "block",
    },
}

PROVIDER_RELEASE = {
    "schema_version": "workbench.data_provider_release.v1",
    "provider_id": DEMO_PROVIDER_ID,
    "release_id": DEMO_RELEASE_ID,
    "created_at": DEMO_CREATED_AT,
    "status": "finalized",
    "artifacts": [
        {"path": "data/evidence_panel.csv", "role": "evidence_panel", "format": "csv", "sha256": "demo_sha256"},
        {"path": "source_registry.json", "role": "source_registry", "format": "json", "sha256": "demo_sha256"},
        {"path": "provenance.jsonl", "role": "provenance", "format": "jsonl", "sha256": "demo_sha256"},
    ],
    "provider_payload": {"demo": True},
}

SOURCE_REGISTRY = {
    "provider_id": DEMO_PROVIDER_ID,
    "created_at": DEMO_CREATED_AT,
    "sources": [
        {
            "source_id": "cboe",
            "provider": "CBOE (via demo)",
            "homepage": "https://www.cboe.com/",
            "kind": "public_file",
            "series": [{
                "source_series_id": "VIXCLS",
                "name": "CBOE Volatility Index: VIX",
                "role": "benchmark_series",
                "unit": "index", "frequency": "business_daily",
                "url": "https://fred.stlouisfed.org/series/VIXCLS",
            }],
        },
        {
            "source_id": "fred_chicago_fed",
            "provider": "Federal Reserve Bank of Chicago (via demo)",
            "homepage": "https://www.chicagofed.org/",
            "kind": "public_file",
            "series": [{
                "source_series_id": "NFCI",
                "name": "Chicago Fed National Financial Conditions Index",
                "role": "benchmark_series",
                "unit": "index", "frequency": "weekly",
                "url": "https://fred.stlouisfed.org/series/NFCI",
            }],
        },
    ],
}

CATALOG = {
    "created_at": DEMO_CREATED_AT,
    "files": [
        {"role": "benchmark_panel", "path": "data/evidence_panel.csv"},
    ],
}


# ── Workspace setup ─────────────────────────────────────────────────────

def create_demo_workspace(root: Path) -> Path:
    """Generate synthetic Harvester release data under *root*/Data/.

    Returns the release directory path.
    """
    release = root / "Data" / "harvester" / "exports" / DEMO_RELEASE_ID
    data_dir = release / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Provider release manifest
    (release / "provider_release.json").write_text(
        json.dumps(PROVIDER_RELEASE, indent=2), encoding="utf-8")

    # Source registry
    (release / "source_registry.json").write_text(
        json.dumps(SOURCE_REGISTRY, indent=2), encoding="utf-8")

    # Provenance
    prov_path = release / "provenance.jsonl"
    with prov_path.open("w", encoding="utf-8") as f:
        for row in SYNTHETIC_DATA:
            f.write(json.dumps({
                "source": row["source_id"],
                "series_id": row["series_id"],
                "fetched_at": DEMO_CREATED_AT,
            }, ensure_ascii=False) + "\n")

    # Evidence panel CSV
    csv_path = data_dir / "evidence_panel.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVIDENCE_COLUMNS)
        writer.writeheader()
        writer.writerows(SYNTHETIC_DATA)

    # Catalog
    (release / "catalog.json").write_text(
        json.dumps(CATALOG, indent=2), encoding="utf-8")

    # Symlink Data/harvester/exports/latest -> this release
    latest = root / "Data" / "harvester" / "exports" / "latest"
    latest.parent.mkdir(parents=True, exist_ok=True)
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(DEMO_RELEASE_ID)

    return release


def create_freshness_policy(root: Path) -> Path:
    """Write the demo freshness policy under *root*/configs/.

    Returns the policy path.
    """
    import yaml
    policy_dir = root / "configs"
    policy_dir.mkdir(parents=True, exist_ok=True)
    path = policy_dir / "freshness_policy.yaml"
    path.write_text(yaml.dump(FRESHNESS_POLICY), encoding="utf-8")
    return path


def ensure_contracts(root: Path, wb_root: Path) -> None:
    """Copy contract schemas into the demo workspace if missing."""
    target = root / "contracts"
    if not target.exists():
        src = wb_root / "contracts"
        if src.exists():
            shutil.copytree(src, target)


def create_output_dirs(root: Path) -> None:
    """Ensure Output/ directory structure exists."""
    dirs = [
        root / "Output" / "current",
        root / "Output" / "workbench" / "benchmark_evidence",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


# ── Pipeline steps ──────────────────────────────────────────────────────

def run_validation(root: Path, release: Path) -> dict[str, Any]:
    """Step 1: contract validation."""
    from workbench.contract_validator import validate_provider_release

    try:
        validate_provider_release(release / "provider_release.json")
        return {"status": "PASS", "detail": "Provider release contract is valid."}
    except Exception as exc:
        return {"status": "FAIL", "detail": str(exc)}


def run_freshness(root: Path, release: Path) -> dict[str, Any]:
    """Step 2: freshness manifest."""
    from workbench.freshness import build_release_freshness_manifest

    try:
        manifest = build_release_freshness_manifest(release)
        indicators = len(manifest.get("indicators", []))
        validity = manifest.get("model_input_validity", "unknown")
        return {
            "status": "PASS",
            "indicators": indicators,
            "model_input_validity": validity,
            "detail": f"Freshness manifest built: {indicators} indicators, validity={validity}",
        }
    except Exception as exc:
        return {"status": "FAIL", "detail": str(exc)}


def run_dashboard(root: Path) -> dict[str, Any]:
    """Step 3: evidence dashboard."""
    from workbench.evidence_dashboard import build

    try:
        result = build()
        return {
            "status": "PASS",
            "json": str(result["json"].relative_to(root)),
            "markdown": str(result["markdown"].relative_to(root)),
            "html": str(result["html"].relative_to(root)),
            "detail": f"Dashboard generated: {result['markdown'].name}, {result['html'].name}",
        }
    except Exception as exc:
        return {"status": "FAIL", "detail": str(exc)}


# ── Patcher (monkeypatches module-level path constants) ─────────────────

def _patch_paths(root: Path, monkeypatch: Any) -> None:
    """Redirect path constants to the demo workspace."""
    import workbench.contract_validator as _cv
    import workbench.evidence_dashboard as _ed
    import workbench.freshness as _fresh

    output = root / "Output"
    data = root / "Data"

    for mod, attrs in [
        (_cv, {"ROOT": root, "CONTRACTS": root / "contracts" / "workbench"}),
        (_fresh, {
            "ROOT": root,
            "POLICY_PATH": root / "configs" / "freshness_policy.yaml",
            "HARVESTER_LATEST": data / "harvester" / "exports" / "latest",
            "CURRENT": output / "current",
            "NEUTRAL_PRESSURE_SNAPSHOT": output / "current" / "neutral_pressure_snapshot.json",
        }),
        (_ed, {
            "ROOT": root,
            "OUTPUT": output,
            "WORKBENCH": output / "workbench" / "benchmark_evidence",
            "CURRENT": output / "current",
            "HARVESTER_LATEST": data / "harvester" / "exports" / "latest",
        }),
    ]:
        for attr, val in attrs.items():
            setattr(mod, attr, val)


# ── Main ─────────────────────────────────────────────────────────────────

def run_demo(
    root: Path,
    wb_root: Path,
    *,
    quick: bool = False,
    no_html: bool = False,
) -> int:
    """Run the full demo pipeline in the given workspace."""
    print(f"\n{'='*60}")
    print("  Workbench Demo Pipeline")
    print(f"{'='*60}\n")

    # Phase 0: Setup
    print("▶ Phase 0: Generating synthetic test data...")
    ensure_contracts(root, wb_root)
    create_freshness_policy(root)
    create_output_dirs(root)
    release = create_demo_workspace(root)
    print(f"   Release: {release.relative_to(root)}")
    print("   Series:  VIXCLS (business_daily), NFCI (weekly)")
    print(f"   Rows:    {len(SYNTHETIC_DATA)}\n")

    # Patch paths to point at the demo workspace
    _patch_paths(root, None)

    # Phase 1: Validate
    print("▶ Phase 1: Contract validation...")
    v = run_validation(root, release)
    print(f"   Result: {v['status']}")
    if v["status"] != "PASS":
        print(f"   Error:  {v['detail']}")
        return 1
    print(f"   Detail: {v['detail']}\n")

    # Phase 2: Freshness
    print("▶ Phase 2: Freshness analysis...")
    f = run_freshness(root, release)
    print(f"   Result: {f['status']}")
    print(f"   Indicators: {f.get('indicators', 'n/a')}")
    print(f"   Model input validity: {f.get('model_input_validity', 'n/a')}\n")

    # Phase 3: Dashboard
    print("▶ Phase 3: Evidence dashboard...")
    d = run_dashboard(root)
    print(f"   Result: {d['status']}")
    if d["status"] == "PASS":
        print(f"   JSON:  Output/{d['json']}")
        print(f"   MD:    Output/{d['markdown']}")
        print(f"   HTML:  Output/{d['html']}")
    else:
        print(f"   Error: {d['detail']}\n")

    # Summary
    print(f"{'='*60}")
    print("  Demo Complete")
    print(f"{'='*60}")
    print(f"  Workspace: {root}")
    steps = [v, f, d]
    passed = sum(1 for s in steps if s["status"] == "PASS")
    total = len(steps)
    print(f"  Pipeline:  {passed}/{total} steps passed")
    print()
    print("  Dashboard commands:")
    print(f"    cat Output/{d.get('markdown', '<dashboard>')}")
    print(f"    open Output/{d.get('html', '<dashboard>')}")
    print()

    return 0 if passed == total else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="wb-demo — generate test data and run the full Workbench pipeline",
    )
    parser.add_argument("--quick", action="store_true",
                        help="Skip matplotlib chart generation")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip HTML rendering")
    parser.add_argument("--dir", type=Path, default=None,
                        help="Workspace root directory (default: auto-detect)")
    args = parser.parse_args()

    if args.dir:
        root = Path(args.dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = workspace_root()

    wb_root = workbench_root()
    return run_demo(root, wb_root, quick=args.quick, no_html=args.no_html)


if __name__ == "__main__":
    sys.exit(main())
