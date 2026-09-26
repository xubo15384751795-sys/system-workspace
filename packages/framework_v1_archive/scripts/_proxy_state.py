"""Proxy activation state machine (Phase C1).

Each proxy moves through states with evidence at each level. No state may be
skipped by human description. A proxy whose builder throws is BUILD_FAILED,
not "available=False but still canonical_voting" - the K channel degrades or
blocks, downstream cannot use old K, and the capability board must not count
it as delivered.

States (in order):
    DECLARED -> BUILDABLE -> AVAILABLE_ON_RELEASE -> ELIGIBLE_TO_VOTE ->
    INCLUDED_IN_AGGREGATION -> EMITTED -> CONSUMED

Terminal failure state:
    BUILD_FAILED  (builder threw, or output all-NaN / below coverage floor)

This module classifies state from build evidence; the structural_replay
builder loop records it per-proxy in proxy_registry.json.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd


class ProxyState(str, Enum):
    DECLARED = "DECLARED"
    BUILD_FAILED = "BUILD_FAILED"
    BUILDABLE = "BUILDABLE"
    AVAILABLE_ON_RELEASE = "AVAILABLE_ON_RELEASE"
    ELIGIBLE_TO_VOTE = "ELIGIBLE_TO_VOTE"
    INCLUDED_IN_AGGREGATION = "INCLUDED_IN_AGGREGATION"
    EMITTED = "EMITTED"
    CONSUMED = "CONSUMED"


# Minimum non-NaN coverage ratio for a built series to count as AVAILABLE.
DEFAULT_COVERAGE_FLOOR = 0.50


@dataclass
class BuildResult:
    """Outcome of building one proxy for one release."""

    name: str
    value: pd.Series | None
    build_error: str | None = None  # set if the builder raised
    coverage_ratio: float = 0.0  # non-NaN fraction of the series
    eligible_to_vote: bool = False  # canonical policy admits this proxy
    in_roster: bool = False  # included in channel_specs aggregation
    emitted: bool = False  # present in the emitted artifact
    consumed: bool = False  # downstream recorded its fingerprint


def classify_build_result(
    name: str,
    value: pd.Series | None,
    *,
    build_error: str | None = None,
    coverage_floor: float = DEFAULT_COVERAGE_FLOOR,
) -> BuildResult:
    """Classify the state of a proxy from its build output.

    - Builder raised -> BUILD_FAILED (terminal).
    - Builder returned None or all-NaN -> BUILD_FAILED (indistinguishable from
      missing input is now an explicit failure, not silent available=False).
    - Below coverage floor -> BUILD_FAILED.
    - Otherwise -> BUILDABLE (will advance to AVAILABLE_ON_RELEASE / ELIGIBLE
      based on roster inclusion + emission downstream).
    """
    if build_error is not None:
        return BuildResult(name=name, value=None, build_error=build_error, coverage_ratio=0.0)
    if value is None or value.empty:
        return BuildResult(name=name, value=None, build_error="builder returned None/empty")
    coverage = float(value.notna().sum()) / float(len(value)) if len(value) > 0 else 0.0
    if coverage == 0.0:
        return BuildResult(name=name, value=None, build_error="all-NaN output", coverage_ratio=0.0)
    if coverage < coverage_floor:
        return BuildResult(
            name=name, value=None,
            build_error=f"coverage {coverage:.2f} below floor {coverage_floor:.2f}",
            coverage_ratio=coverage,
        )
    return BuildResult(name=name, value=value, coverage_ratio=coverage)


def state_of(result: BuildResult) -> ProxyState:
    """Map a BuildResult to its current ProxyState."""
    if result.build_error is not None:
        return ProxyState.BUILD_FAILED
    if result.consumed:
        return ProxyState.CONSUMED
    if result.emitted:
        return ProxyState.EMITTED
    if result.in_roster:
        return ProxyState.INCLUDED_IN_AGGREGATION
    if result.eligible_to_vote:
        return ProxyState.ELIGIBLE_TO_VOTE
    if result.value is not None:
        return ProxyState.AVAILABLE_ON_RELEASE
    return ProxyState.BUILDABLE


def is_active_for_aggregation(result: BuildResult) -> bool:
    """A proxy may vote in aggregation only if it reached at least
    AVAILABLE_ON_RELEASE (not BUILD_FAILED). The aggregator must skip
    BUILD_FAILED proxies and flag the channel as degraded if the roster
    shrinks below a quorum."""
    return result.build_error is None and result.value is not None


def registry_row_with_state(
    spec: Any,
    result: BuildResult,
) -> dict[str, Any]:
    """Build a proxy_registry.json row carrying the state-machine verdict."""
    state = state_of(result)
    return {
        "name": spec.name,
        "target_variable": spec.target_variable,
        "channel": spec.target_variable,
        "tier": spec.tier,
        "role": spec.tier,
        "freq": spec.freq,
        "raw_series": list(spec.raw_series),
        "raw_family": spec.raw_family,
        "independence_group": spec.independence_group,
        "mechanism": spec.mechanism,
        "transform": spec.transform,
        "allow_derivative_reuse": spec.allow_derivative_reuse,
        "canonical_status": spec.canonical_status,
        "available": is_active_for_aggregation(result),
        "proxy_state": state.value,
        "build_error": result.build_error,
        "coverage_ratio": round(result.coverage_ratio, 4),
        "lifecycle_evidence": {
            "declared": True,
            "buildable": result.build_error is None,
            "available_on_release": result.value is not None,
            "eligible_to_vote": result.eligible_to_vote,
            "included_in_aggregation": result.in_roster,
            "emitted": result.emitted,
            "consumed": result.consumed,
        },
        "note": spec.note,
    }
