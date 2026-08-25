"""Dagster asset checks for the full-plan native daily shadow graph.

The native asset itself still records the legacy-compatible step result so the
dual-run comparator can compare ``steps.jsonl``.  These checks expose the same
result to Dagster's event/check model.  They are non-blocking in the stopped
structural shadow graph; callers can request blocking checks only after the
dual-run gate proves that Dagster skip behavior and the legacy blocked rows are
equivalent.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dagster import AssetCheckResult, AssetChecksDefinition, AssetsDefinition, asset_check

_PASS_STATUSES = frozenset({"success", "skipped"})
_FAIL_STATUSES = frozenset({"failed", "error", "timeout", "blocked_upstream"})


def _payload_from_kwargs(kwargs: Mapping[str, Any]) -> Any:
    return next(iter(kwargs.values())) if kwargs else None


def build_native_daily_checks(
    assets: tuple[AssetsDefinition, ...],
    *,
    blocking: bool = False,
) -> tuple[AssetChecksDefinition, ...]:
    """Build one Dagster result check for every native daily asset.

    ``blocking=False`` is the only mode used by the stopped full-plan shadow
    definition.  ``blocking=True`` is intentionally an explicit caller
    choice, because it changes whether Dagster prevents downstream
    materialization and therefore needs a real parity window first.
    """
    def build_check(
        asset_def: AssetsDefinition,
        *,
        step_id: str,
        failure_behavior: str,
    ) -> AssetChecksDefinition:
        @asset_check(
            asset=asset_def,
            name=f"native_daily_result_{step_id}",
            blocking=blocking,
            compute_kind="dagster_native_daily_asset_check",
        )
        def _native_daily_result_check(**kwargs: Any) -> AssetCheckResult:
            payload = _payload_from_kwargs(kwargs)
            status = str(payload.get("status") or "").lower() if isinstance(payload, Mapping) else ""
            passed = status in _PASS_STATUSES and status not in _FAIL_STATUSES
            return AssetCheckResult(
                passed=passed,
                description=(
                    "native daily result is schedulable"
                    if passed
                    else "native daily result requires failure propagation or review"
                ),
                metadata={
                    "step_id": step_id,
                    "failure_behavior": failure_behavior,
                    "status": status or "unknown",
                    "degraded": bool(payload.get("degraded"))
                    if isinstance(payload, Mapping)
                    else False,
                    "blocked_by": list(payload.get("blocked_by") or [])
                    if isinstance(payload, Mapping)
                    else [],
                    "authority": "shadow_only",
                    "check_blocking": blocking,
                    "promotion_allowed": False,
                },
            )

        return _native_daily_result_check

    checks: list[AssetChecksDefinition] = []
    for asset_def in assets:
        step_id = str(asset_def.metadata_by_key[asset_def.key].get("step_id") or asset_def.key.path[-1])
        failure_behavior = str(
            asset_def.metadata_by_key[asset_def.key].get("failure_behavior") or ""
        )
        checks.append(
            build_check(
                asset_def,
                step_id=step_id,
                failure_behavior=failure_behavior,
            )
        )
    return tuple(checks)


__all__ = ["build_native_daily_checks"]
