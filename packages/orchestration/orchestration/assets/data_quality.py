"""Dagster shadow checks for release-bound data quality.

The structural check is blocking because malformed keys/shapes cannot safely
enter a release. Provider-route parity is intentionally non-blocking during
the observed-window phase; it records whether a diagnostic route was used
without pretending that the fallback is certified.
"""
from __future__ import annotations

from typing import Any

from dagster import AssetCheckResult, asset_check

from orchestration.assets.boundary_pilot import harvester_release


def _contract_status(release: dict[str, Any]) -> str:
    contract = release.get("data_contract")
    return str(contract.get("status", "UNKNOWN")).upper() if isinstance(contract, dict) else "UNKNOWN"


@asset_check(
    asset=harvester_release,
    name="cross_asset_structural_contract",
    blocking=True,
    compute_kind="data_quality",
)
def cross_asset_structural_contract(harvester_release: dict[str, Any]) -> AssetCheckResult:
    contract_status = _contract_status(harvester_release)
    integrity = harvester_release.get("integrity")
    duplicate_rows = 0
    if isinstance(integrity, dict):
        duplicate_rows = int(integrity.get("duplicate_rows_removed", 0) or 0)
    passed = contract_status in {"PASS", "WARN"} and duplicate_rows == 0
    return AssetCheckResult(
        passed=passed,
        description="release data has a valid structural contract and no duplicate primary keys",
        metadata={
            "contract_status": contract_status,
            "duplicate_rows_removed": duplicate_rows,
            "release_id": harvester_release.get("release_id", ""),
        },
    )


@asset_check(
    asset=harvester_release,
    name="cross_asset_provider_route_shadow",
    blocking=False,
    compute_kind="data_quality",
)
def cross_asset_provider_route_shadow(harvester_release: dict[str, Any]) -> AssetCheckResult:
    route_policy = harvester_release.get("route_policy")
    diagnostic_only = bool(route_policy.get("diagnostic_only")) if isinstance(route_policy, dict) else False
    return AssetCheckResult(
        passed=not diagnostic_only,
        description="provider route is authoritative, or diagnostic fallback is explicitly visible",
        metadata={
            "diagnostic_only": diagnostic_only,
            "route_class": route_policy.get("route_class", "UNKNOWN") if isinstance(route_policy, dict) else "UNKNOWN",
            "reason": route_policy.get("reason", "") if isinstance(route_policy, dict) else "missing_route_policy",
        },
    )


DATA_QUALITY_CHECKS = (
    cross_asset_structural_contract,
    cross_asset_provider_route_shadow,
)


__all__ = [
    "DATA_QUALITY_CHECKS",
    "cross_asset_provider_route_shadow",
    "cross_asset_structural_contract",
]
