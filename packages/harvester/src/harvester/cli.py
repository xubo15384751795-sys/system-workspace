from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# Load .env from project root and user home if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Project-level .env
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
    # User-level .env
    load_dotenv(Path.home() / ".hermes" / ".env", override=False)
except ImportError:
    pass

from harvester.core.catalog import load_catalog
from harvester.core.exporter import default_exports_root, finalize_release, list_releases
from harvester.core.manifest import load_manifest
from harvester.official import stage_complete_release
from harvester.ops import monitor_latest, next_release_id, run_daily_release, run_preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harvester")
    parser.add_argument(
        "--exports-root",
        type=Path,
        default=default_exports_root(),
        help="Exports root. Defaults to <repo>/data/exports.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_manifest = subparsers.add_parser("validate-manifest")
    validate_manifest.add_argument("path", type=Path)

    validate_catalog = subparsers.add_parser("validate-catalog")
    validate_catalog.add_argument("release_dir", type=Path)

    stage_complete = subparsers.add_parser("stage-complete-release")
    stage_complete.add_argument("release_id")
    stage_complete.add_argument("--as-of-date", default="")
    stage_complete.add_argument("--vintage-date", default="")
    stage_complete.add_argument(
        "--providers",
        default="",
        help="Comma-separated provider list. Defaults to the configured official providers.",
    )
    stage_complete.add_argument("--no-cache", action="store_true")
    stage_complete.add_argument("--no-external", action="store_true")
    stage_complete.add_argument("--notes", default="")

    finalize = subparsers.add_parser("finalize-release")
    finalize.add_argument("release_id")
    finalize.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Validate without writing catalog/latest by default. Use --no-dry-run to finalize.",
    )

    subparsers.add_parser("list-releases")

    next_release = subparsers.add_parser("next-release-id")
    next_release.add_argument("--date", default="")

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--providers", default="")

    daily = subparsers.add_parser("daily-release")
    daily.add_argument("--release-id", default="")
    daily.add_argument("--as-of-date", default="")
    daily.add_argument("--vintage-date", default="")
    daily.add_argument("--providers", default="")
    daily.add_argument("--no-cache", action="store_true")
    daily.add_argument("--no-external", action="store_true")
    daily.add_argument("--no-preflight", action="store_true")
    daily.add_argument("--notes", default="")

    monitor = subparsers.add_parser("monitor")
    monitor.add_argument("--max-age-days", type=int, default=3)

    args = parser.parse_args(argv)
    if args.command == "validate-manifest":
        load_manifest(args.path)
        print(f"valid manifest: {args.path}")
        return 0
    if args.command == "validate-catalog":
        load_catalog(args.release_dir)
        print(f"valid catalog: {args.release_dir / 'catalog.json'}")
        return 0
    if args.command == "stage-complete-release":
        providers = [p.strip() for p in args.providers.split(",") if p.strip()] or None
        result = stage_complete_release(
            release_id=args.release_id,
            as_of_date=args.as_of_date,
            vintage_date=args.vintage_date or args.as_of_date,
            exports_root=str(args.exports_root),
            providers=providers,
            cache=not args.no_cache,
            include_external=not args.no_external,
            notes=args.notes,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "finalize-release":
        result = finalize_release(args.release_id, exports_root=args.exports_root, dry_run=args.dry_run)
        print(
            json.dumps(
                {
                    "release_id": result.release_id,
                    "release_dir": str(result.release_dir),
                    "dry_run": result.dry_run,
                    "verified_datasets": result.verified_datasets,
                    "latest_path": str(result.latest_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "list-releases":
        for release_id in list_releases(args.exports_root):
            print(release_id)
        return 0
    if args.command == "next-release-id":
        release_date = None
        if args.date:
            from datetime import date
            release_date = date.fromisoformat(args.date)
        print(next_release_id(args.exports_root, release_date=release_date))
        return 0
    if args.command == "preflight":
        providers = [p.strip() for p in args.providers.split(",") if p.strip()] or None
        result = run_preflight(exports_root=args.exports_root, providers=providers)
        print(json.dumps({
            "passed": result.passed,
            "blockers": result.blockers,
            "checks": [check.__dict__ for check in result.checks],
        }, indent=2, sort_keys=True))
        return 0 if result.passed else 1
    if args.command == "daily-release":
        providers = [p.strip() for p in args.providers.split(",") if p.strip()] or None
        result = run_daily_release(
            release_id=args.release_id,
            as_of_date=args.as_of_date,
            vintage_date=args.vintage_date,
            exports_root=args.exports_root,
            providers=providers,
            cache=not args.no_cache,
            include_external=not args.no_external,
            notes=args.notes,
            preflight=not args.no_preflight,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("status") == "finalized" else 1
    if args.command == "monitor":
        result = monitor_latest(exports_root=args.exports_root, max_age_days=args.max_age_days)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("status") == "healthy" else 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
