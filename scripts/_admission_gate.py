"""Pre-consumption admission gate.

Phase A: turns freshness from a post-run report into a *pre-consumption*
authorization. A consumer (refresh_current, paper_portfolio, ...) calls
``admit_for_consumption`` before reading its inputs; if any required public
component is stale or missing, the consumer is blocked rather than silently
degrading.

This thin wrapper reconciles the two freshness systems in the repo:

- ``workbench.freshness.build_release_freshness_manifest`` - policy-driven,
  operates on the frozen Harvester evidence release, gates NFCI/OFR_FSI/
  VIXCLS/... with per-indicator severity (now ``block`` for the public
  components after freshness_policy.yaml step-4). Blind to CISS as a raw
  cache (CISS is in the policy indicators map but its content-date must also
  be checked at the cache file level).
- ``freshness_validator.check_content_freshness`` - file-content level, the
  only place CISS and the raw OFR cache are checked by trading-day budget.

The gate aggregates both: release-level blockers (from workbench.freshness)
plus content-level STALE/MISSING (from check_content_freshness over the
public-component caches and benchmark panel).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._runtime_io import ROOT

# Which content-cache checks matter for the public-stress consumers. These are
# the files whose staleness silently degrades P_public (eq-weight PIT over
# OFR/NFCI/CISS) - the "no silent channel collapse" guardrail.
_PUBLIC_CONTENT_CHECKS = ("ofr_fsi_cache", "ciss_cache", "benchmark_panel")

# Consumers known to depend on fresh public components. Admission is currently
# uniform across these; the consumer name is recorded for the audit trail.
_PUBLIC_DEPENDENT_CONSUMERS = frozenset(
    {"refresh_current", "paper_portfolio", "shadow_outcomes_90d"}
)


# Content checks whose underlying indicator is declared environmentally
# blocked in configs/freshness_policy.yaml. Maps check name -> indicator name.
_CONTENT_CHECK_INDICATORS = {
    "ofr_fsi_cache": "OFR_FSI",
    "ciss_cache": "CISS",
}


@dataclass
class AdmissionDecision:
    """Result of a pre-consumption admission check."""

    consumer: str
    allowed: bool
    blockers: list[str] = field(default_factory=list)
    release_manifest: dict[str, Any] | None = None
    content_checks: list[dict[str, Any]] = field(default_factory=list)
    checked_at: str = ""
    degradations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now(UTC).isoformat()


def _release_level_blockers(release_dir: Path) -> tuple[list[str], dict[str, Any] | None]:
    """Blockers from workbench.freshness over the frozen evidence release."""
    from workbench.freshness import build_release_freshness_manifest  # noqa: E402

    try:
        manifest = build_release_freshness_manifest(release_dir)
    except FileNotFoundError:
        # Release dir or catalog missing - that is itself a blocker.
        return [f"release_missing:{release_dir}"], None
    gate = manifest.get("gate_result", {}) or {}
    blockers = list(gate.get("blockers", []) or [])
    return blockers, manifest


def _content_level_blockers(now: datetime) -> tuple[list[str], list[dict[str, Any]]]:
    """STALE/MISSING content checks over the public-component caches."""
    from scripts.freshness_validator import CONTENT_FRESHNESS, check_content_freshness

    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    for name in _PUBLIC_CONTENT_CHECKS:
        spec = CONTENT_FRESHNESS.get(name)
        if not spec:
            continue
        path = ROOT / spec["path"]
        result = check_content_freshness(
            name=name,
            path=path,
            date_column=spec["date_column"],
            max_trading_days_behind=spec["max_trading_days_behind"],
            now=now,
        )
        checks.append(result)
        status = result.get("status")
        if status in ("STALE", "MISSING"):
            blockers.append(
                f"{name}:{status.lower()} (behind={result.get('trading_days_behind')}d)"
            )
    return blockers, checks


def _environmentally_blocked() -> dict[str, dict[str, Any]]:
    """Sources declared unreachable from this host in freshness_policy.yaml.

    These stop contributing admission blockers, but never stop being reported:
    the caller records them as degradations, and the consumer's own
    fail-closed path (P_public NaN -> HOLD_DEGRADED) still applies.
    """
    import yaml

    path = ROOT / "configs" / "freshness_policy.yaml"
    try:
        policy = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    declared = policy.get("environmentally_blocked") or {}
    return declared if isinstance(declared, dict) else {}


def _split_declared_blockers(
    blockers: list[str],
) -> tuple[list[str], list[str]]:
    """Partition blockers into (still blocking, declared-degraded)."""
    declared = _environmentally_blocked()
    if not declared:
        return blockers, []

    import re

    still_blocking: list[str] = []
    degraded: list[str] = []
    for blocker in blockers:
        # Content-level blockers are "<check_name>:<status> (...)".
        indicator = _CONTENT_CHECK_INDICATORS.get(blocker.split(":", 1)[0])
        if indicator is None:
            # Release-level blockers are free-form sentences that name the
            # indicator, e.g. "OFR_FSI is required but stale".
            indicator = next(
                (n for n in declared if re.search(rf"\b{re.escape(n)}\b", blocker)),
                None,
            )
        if indicator is not None and indicator in declared:
            # YAML folds the reason into one long line; keep the log readable.
            reason = " ".join((declared[indicator].get("reason") or "").split())
            if len(reason) > 90:
                reason = reason[:87].rstrip() + "..."
            degraded.append(f"{blocker} [declared environmentally blocked: {reason}]")
        else:
            still_blocking.append(blocker)
    return still_blocking, degraded


def admit_for_consumption(
    consumer: str,
    *,
    release_dir: Path | None = None,
    now: datetime | None = None,
) -> AdmissionDecision:
    """Authorize a consumer to read its inputs.

    Returns an AdmissionDecision. ``allowed`` is False if any required public
    component is stale or missing at either the release or content-cache
    level. Callers (paper_portfolio) should refuse to proceed (sys.exit) when
    not allowed, so the executor's failure propagation marks descendants
    blocked_upstream.

    Args:
        consumer: Step id of the consumer (e.g. "paper_portfolio"). Recorded
            for the audit trail; admission is uniform across public-dependent
            consumers today.
        release_dir: Harvester evidence release to check. Defaults to the
            ``latest`` symlink target.
        now: Reference time for content-date checks. Defaults to now(UTC).
    """
    resolved_release = release_dir or (ROOT / "Data" / "harvester" / "exports" / "latest")
    resolved_now = now or datetime.now(UTC)

    release_blockers, manifest = _release_level_blockers(resolved_release)
    content_blockers, content_checks = _content_level_blockers(resolved_now)

    all_blockers = release_blockers + content_blockers
    still_blocking, degradations = _split_declared_blockers(all_blockers)
    return AdmissionDecision(
        consumer=consumer,
        allowed=not still_blocking,
        blockers=still_blocking,
        release_manifest=manifest,
        content_checks=content_checks,
        degradations=degradations,
    )


def require_admission(
    consumer: str,
    *,
    release_dir: Path | None = None,
    now: datetime | None = None,
) -> AdmissionDecision:
    """Like admit_for_consumption, but exits non-zero when not allowed.

    Intended as the single-line guard at the top of a consumer's entry point:

        from scripts._admission_gate import require_admission
        require_admission("paper_portfolio")
        # ... proceed with input consumption ...

    On block, logs the blockers and sys.exit(1) so the pipeline runner records
    status="failed" and the executor marks descendants blocked_upstream.
    """
    import logging
    import sys

    decision = admit_for_consumption(consumer, release_dir=release_dir, now=now)
    if decision.degradations:
        # Admitted, but with known-missing components. Surface it at WARNING on
        # every run: a degraded admission must never read as a clean one.
        logging.getLogger(__name__).warning(
            "admission degraded for %s: %s", consumer, "; ".join(decision.degradations)
        )
        print(
            f"WARNING: admission degraded for {consumer}: {decision.degradations}",
            file=sys.stderr,
        )
    if not decision.allowed:
        logging.getLogger(__name__).error(
            "admission blocked for %s: %s", consumer, "; ".join(decision.blockers)
        )
        print(
            f"ERROR: admission blocked for {consumer}: {decision.blockers}",
            file=sys.stderr,
        )
        sys.exit(1)
    return decision
