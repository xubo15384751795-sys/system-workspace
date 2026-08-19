#!/usr/bin/env python3
"""Mirror the accepted Harvester cross-asset daily panel.

Updates the writable workspace mirror at
`Data/panels/cross_asset_daily_panel.parquet`. Finalized Harvester releases
under `Data/harvester/exports/latest/` are read-only; consumers resolve the
fresher of mirror vs canonical via `_data_paths.resolve_cross_asset_panel_path`
(and k_gate's matching helper). A complete Harvester
`stage_complete_release` writes the immutable canonical release; this consumer
never mutates that release.

Usage:
    python3 scripts/refresh_cross_asset_panel.py
    python3 scripts/refresh_cross_asset_panel.py --days 30

--days is retained for command compatibility; it no longer causes a
second provider request.

Output:
    Data/panels/cross_asset_daily_panel.parquet
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from scripts._runtime_io import ROOT

PANEL_PATH = ROOT / "Data" / "panels" / "cross_asset_daily_panel.parquet"
HARVESTER_PANEL_PATH = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "cross_asset_daily_panel.parquet"
HARVESTER_EXPORTS_ROOT = ROOT / "Data" / "harvester" / "exports"


def _panel_max_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=["date"])
    if frame.empty:
        return None
    return pd.to_datetime(frame["date"]).max()


def _same_day_candidate_outcome() -> dict[str, object] | None:
    """Read the current day's staged/failure evidence, never its data bytes."""
    prefix = datetime.now(UTC).strftime("%Y-%m-%d-r")
    candidates: list[Path] = []
    if HARVESTER_EXPORTS_ROOT.is_dir():
        for release_dir in HARVESTER_EXPORTS_ROOT.iterdir():
            if not release_dir.is_dir() or not release_dir.name.startswith(prefix):
                continue
            if (release_dir / ".finalized").exists():
                continue
            manifest = release_dir / "manifests" / "cross_asset_daily_panel.manifest.json"
            if manifest.is_file():
                candidates.append(manifest)
    for manifest in sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        outcome = payload.get("provider_outcome")
        if isinstance(outcome, dict):
            return dict(outcome)

    # A failure can occur before the cross-asset manifest is emitted.  Keep
    # the fallback state explicit so the consumer never presents an old panel
    # as a fresh success.
    failure_dir = HARVESTER_EXPORTS_ROOT / ".failures"
    failures = sorted(
        failure_dir.glob(f"{prefix}*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if failure_dir.is_dir() else []
    if failures:
        return {
            "status": "reused_after_provider_failure",
            "provider": "harvester.release",
            "requested_count": 0,
            "succeeded_count": 0,
            "failed_count": 0,
            "failed_series": [],
            "fallback_reason": "same_day_harvester_release_failed",
            "error": failures[0].name,
        }
    return None


def _harvester_build(*, fetch_period: str) -> tuple[pd.DataFrame, dict[str, object]]:
    # ``fetch_period`` remains a compatibility argument for callers and CLI
    # scripts.  Acquisition is owned by the preceding Harvester release step;
    # this function intentionally performs no provider/network call.
    from harvester.cross_asset_panel import (  # noqa: I001
        load_latest_release_panel,
        sync_panel_to_workspace,
    )

    del fetch_period
    panel, outcome = load_latest_release_panel(workspace=ROOT)
    candidate_outcome = _same_day_candidate_outcome()
    if candidate_outcome is not None:
        outcome = dict(candidate_outcome)
        # A staged-but-unfinalized release is not an accepted source.  Even if
        # its provider call succeeded, this step must not label the previous
        # finalized bytes as fresh.
        if outcome.get("status") in {"refreshed", "accepted", "finalized"}:
            outcome["source_status"] = outcome.get("status")
            outcome["status"] = "reused_after_provider_failure"
            outcome["fallback_reason"] = "same_day_release_not_finalized"
    if not panel.empty and "date" in panel.columns:
        latest = pd.to_datetime(panel["date"], errors="coerce").max()
        if pd.notna(latest):
            try:
                grace_days = max(
                    0,
                    int(os.environ.get("ETF_PANEL_CACHE_GRACE_DAYS", "3")),
                )
            except ValueError:
                grace_days = 3
            age_days = (datetime.now(UTC).date() - latest.date()).days
            outcome["cache_age_days"] = age_days
            outcome["cache_within_grace"] = age_days <= grace_days
    sync_panel_to_workspace(panel, ROOT)
    return panel, outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=5, help="Days to fetch from yfinance")
    args = parser.parse_args()

    prior_max = _panel_max_date(PANEL_PATH) or _panel_max_date(HARVESTER_PANEL_PATH)
    period = f"{args.days}d"
    print(f"Refreshing cross-asset panel via Harvester builder ({period})...")
    merged, provider_outcome = _harvester_build(fetch_period=period)
    print(f"Provider outcome: {provider_outcome}")

    if merged.empty:
        raise SystemExit("No panel data produced")

    new_max = pd.to_datetime(merged["date"]).max()
    spy = merged[merged["symbol"] == "SPY"]
    print(f"Updated mirror: {len(merged)} rows, through {new_max.date()} -> {PANEL_PATH}")
    if HARVESTER_PANEL_PATH.exists():
        canon_max = _panel_max_date(HARVESTER_PANEL_PATH)
        print(
            f"Harvester canonical (read-only): through "
            f"{canon_max.date() if canon_max is not None else 'n/a'}"
        )
    if not spy.empty:
        print(f"SPY: through {spy['date'].max().date()}, latest return_1d={spy['return_1d'].iloc[-1]:.4f}")

    if prior_max is not None and new_max <= prior_max:
        print(
            f"WARNING: panel did not advance (still through {new_max.date()}); "
            "check yfinance rate limits / fetch errors"
        )

    status = str(provider_outcome.get("status", "unknown"))
    availability = provider_outcome.get("availability")
    route_policy = provider_outcome.get("route_policy")
    causally_usable = bool(
        isinstance(availability, dict)
        and availability.get("decision_usable") is True
    )
    route_diagnostic_only = bool(
        isinstance(route_policy, dict) and route_policy.get("diagnostic_only")
    )
    degraded = (
        status not in {"refreshed", "accepted", "finalized"}
        or not causally_usable
        or route_diagnostic_only
    )
    if degraded:
        reason = (
            availability.get("reason")
            if isinstance(availability, dict) and availability.get("reason")
            else "provider outcome not decision-usable"
        )
        print(f"Provider outcome is degraded: {status}; {reason}")
    print(
        "SYSTEM_STEP_OUTCOME="
        + json.dumps(
            {
                "status": "degraded" if degraded else "success",
                "provider_outcome": provider_outcome,
                "route_policy": route_policy,
                "source": "harvester_finalized_release",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
