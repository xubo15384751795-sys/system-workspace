#!/usr/bin/env python3
"""Freshness Validator — check artifact freshness and temporal ordering.

This script validates that key artifacts are fresh and in correct
temporal order. Stale artifacts cannot be displayed as ✅.

Usage:
    python3 scripts/freshness_validator.py
    python3 scripts/freshness_validator.py --json

Output:
    Output/quality/freshness_report.json
    Output/quality/freshness_report.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from verity.runtime.runtime_io import (
    ROOT,
    current_dir,
    ensure_dir,
    output_root_dir,
    surface_dir,
)

OUTPUT_DIR = output_root_dir()
CURRENT = current_dir()
QUALITY_DIR = surface_dir("quality")

# Phase 1.2: artifact mtime budgets derived from configs/freshness_policy.yaml
# (single source of truth), not hardcoded. Each artifact maps to its owning
# step's cadence (daily/weekly); the budget = acceptable_lag_days * 24 hours.
# This replaces the old hardcoded MAX_AGE_HOURS dict.
_POLICY_PATH = ROOT / "configs" / "freshness_policy.yaml"

# Map artifact name -> cadence. learning_summary is weekly (8d TTL); the rest
# of the current-readout chain is daily. System_index/readme/signal are daily
# display artifacts (24h = 1 day, the fresh_lag threshold for daily).
_ARTIFACT_CADENCE = {
    "harvester": "daily",
    "structural_replay": "daily",
    "framework_output": "daily",
    "judgment": "daily",
    "promotion_gate": "daily",
    "trade_decision": "daily",
    "risk_gate": "daily",
    "learning_summary": "weekly",  # weekly cadence (daily_run_sequence.yaml)
    "system_index": "daily",
    "readme_first": "daily",
    "signal_card": "daily",
    "signal_consensus": "daily",
    "work_brief": "daily",
}


def _load_max_age_hours_from_policy() -> dict[str, int]:
    """Derive per-artifact max-age-hours from freshness_policy.yaml.

    budget = frequency_thresholds[cadence].acceptable_lag_days * 24.
    Falls back to the policy's daily threshold if the cadence is unknown.
    """
    try:
        policy = yaml.safe_load(_POLICY_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        policy = {}
    thresholds = policy.get("frequency_thresholds", {}) or {}
    daily = (thresholds.get("daily") or {}).get("acceptable_lag_days", 10)
    weekly = (thresholds.get("weekly") or {}).get("acceptable_lag_days", 21)
    budgets: dict[str, int] = {}
    for name, cadence in _ARTIFACT_CADENCE.items():
        if cadence == "weekly":
            budgets[name] = int(weekly) * 24
        else:
            budgets[name] = int(daily) * 24
    return budgets


MAX_AGE_HOURS = _load_max_age_hours_from_policy()

def _load_content_freshness_registry(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    """Compile content clocks from the canonical pipeline registry.

    Keeping these paths in Python recreated the exact "monitor path table drift"
    failure mode this validator is meant to prevent.
    """
    registry_path = root / "governance" / "daily_pipeline_registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    rows = registry.get("content_freshness", {}) or {}
    return {str(name): dict(config) for name, config in rows.items() if isinstance(config, dict)}


# Backward-compatible import surface for callers/tests; source of truth is YAML.
CONTENT_FRESHNESS = _load_content_freshness_registry()

# The "current outputs" chain — these must all be from the same run
CURRENT_OUTPUT_CHAIN = [
    "readme_first",
    "signal_card",
    "signal_consensus",
    "work_brief",
    "system_index",
]


def _chain_current() -> Path:
    """Current readout dir for closure/freshness checks (patchable via OUTPUT_DIR in tests)."""
    override = os.environ.get("CURRENT_OUTPUT_DIR")
    if override:
        return Path(override)
    return OUTPUT_DIR / "current"


def _weekly_freshness_due(now: datetime) -> bool:
    """Return whether weekly artifacts are expected in this run.

    Daily runs deliberately skip weekly producers except on Monday (the same
    cadence used by ``daily_run.should_run_step``).  A missing/stale weekly
    artifact on an ordinary daily run is therefore an advisory condition, not
    evidence that the current daily generation is incomplete.  Operators can
    force the weekly contract for an ad-hoc validation with
    ``SYSTEM_FORCE_WEEKLY=1``.
    """
    return now.weekday() == 0 or os.environ.get("SYSTEM_FORCE_WEEKLY") == "1"

# Evidence release TTL — see governance/architecture_reality_decisions.md §4
# See: configs/freshness_policy.yaml evidence_release section
EVIDENCE_RELEASE_TTL_HOURS = 3 * 24  # 3 days = 72 hours

CARRY_FORWARD_ARTIFACT = "harvester_carry_forward"
CARRY_FORWARD_MAX_SERIES = 2
CARRY_FORWARD_MAX_TRADING_DAYS = 5


def evaluate_harvester_carry_forward(
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read carry-forward series from latest provenance and score lag.

    More than two carried series, or any series more than five trading days
    behind, is STALE. This check is WARN-only: it never raises FAIL, and
    PublishAdmission must treat that WARN as diagnostic publish rather than
    an integrity block.
    """
    workspace = Path(root or ROOT)
    clock = now or datetime.now(UTC)
    as_of = clock.date() if clock.tzinfo is None else clock.astimezone(UTC).date()
    release = workspace / "Data" / "harvester" / "exports" / "latest"
    provenance_path = release / "provenance" / "benchmark_panel.provenance.json"
    panel_path = release / "data" / "benchmark_panel.parquet"
    catalog_path = release / "catalog.json"
    result: dict[str, Any] = {
        "name": CARRY_FORWARD_ARTIFACT,
        "check_type": "carry_forward",
        "path": str(provenance_path),
        "status": "FRESH",
        "series": [],
        "count": 0,
        "max_trading_days_behind": 0,
        "exceeds": False,
        "max_series": CARRY_FORWARD_MAX_SERIES,
        "max_trading_days": CARRY_FORWARD_MAX_TRADING_DAYS,
        "age_hours": None,
        "max_age_hours": None,
    }
    if catalog_path.is_file():
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            catalog = {}
        as_of_raw = catalog.get("as_of_date") or catalog.get("as_of")
        if as_of_raw:
            try:
                as_of = date.fromisoformat(str(as_of_raw)[:10])
            except ValueError:
                pass
    if not provenance_path.is_file() or not panel_path.is_file():
        return result
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return result
    outcome = provenance.get("provider_outcome")
    if not isinstance(outcome, Mapping):
        return result
    failed = [str(item) for item in outcome.get("failed_series") or [] if str(item).strip()]
    if not failed:
        return result
    try:
        import pandas as pd

        wanted = [column for column in ("date", "series_id", "source_series_id")]
        panel = pd.read_parquet(panel_path, columns=wanted)
    except Exception:
        return result
    if "date" not in panel.columns:
        return result
    series_id = panel["series_id"].astype(str) if "series_id" in panel.columns else None
    source_id = (
        panel["source_series_id"].astype(str) if "source_series_id" in panel.columns else None
    )
    dates = pd.to_datetime(panel["date"], errors="coerce")
    rows: list[dict[str, Any]] = []
    for sid in failed:
        mask = False
        if source_id is not None:
            mask = source_id == sid
        if series_id is not None:
            ends = series_id.str.endswith(":" + sid) | (series_id == sid)
            mask = ends if mask is False else (mask | ends)
        if mask is False:
            continue
        selected = dates[mask]
        if selected.empty or selected.notna().sum() == 0:
            continue
        max_date = selected.max().date()
        behind = trading_days_behind(max_date, as_of)
        rows.append(
            {
                "series_id": sid,
                "max_date": max_date.isoformat(),
                "trading_days_behind": int(behind),
            }
        )
    rows.sort(key=lambda item: (-int(item["trading_days_behind"]), item["series_id"]))
    max_behind = max((int(item["trading_days_behind"]) for item in rows), default=0)
    exceeds = len(rows) > CARRY_FORWARD_MAX_SERIES or max_behind > CARRY_FORWARD_MAX_TRADING_DAYS
    result.update(
        {
            "status": "STALE" if exceeds else "FRESH",
            "series": rows,
            "count": len(rows),
            "max_trading_days_behind": max_behind,
            "exceeds": exceeds,
            "as_of": as_of.isoformat(),
        }
    )
    return result


def get_file_mtime(path: Path) -> datetime | None:
    """Get file modification time."""
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def check_artifact_freshness(
    name: str,
    path: Path,
    max_age_hours: int,
    now: datetime,
) -> dict[str, Any]:
    """Check if an artifact is fresh."""
    mtime = get_file_mtime(path)
    if mtime is None:
        return {
            "name": name,
            "path": str(path),
            "status": "MISSING",
            "age_hours": None,
            "max_age_hours": max_age_hours,
        }

    age_hours = (now - mtime).total_seconds() / 3600
    is_fresh = age_hours <= max_age_hours

    return {
        "name": name,
        "path": str(path),
        "status": "FRESH" if is_fresh else "STALE",
        "age_hours": round(age_hours, 1),
        "max_age_hours": max_age_hours,
        "last_modified": mtime.isoformat(),
    }


def trading_days_behind(content_max: date, as_of: date) -> int:
    """Backward-compatible adapter to the canonical exchange-session engine."""
    from orchestration.quality.calendar_engine import sessions_behind

    return sessions_behind(content_max, as_of)


def check_content_freshness(
    name: str,
    path: Path,
    date_column: str,
    max_trading_days_behind: int,
    now: datetime,
) -> dict[str, Any]:
    """Adapter to the canonical orchestration content-clock evaluator."""
    try:
        from orchestration.quality.content_freshness import (
            evaluate_content_clock,
            freshness_result_digest,
        )

        result = evaluate_content_clock(
            name,
            {
                "path": str(path),
                "date_column": date_column,
                "max_trading_days_behind": max_trading_days_behind,
            },
            root=ROOT,
            as_of=(now.date() if now.tzinfo is None else now.astimezone(UTC).date()),
        )
    except Exception as exc:  # noqa: BLE001 — evaluator outage is not a PASS
        error_result = {
            "name": name,
            "path": str(path),
            "check_type": "content",
            "status": "MISSING",
            "date_column": date_column,
            "max_date": None,
            "trading_days_behind": None,
            "max_trading_days_behind": max_trading_days_behind,
            "engine": "unavailable",
            "error": f"quality_evaluator:{exc}",
        }
        from orchestration.quality.content_freshness import freshness_result_digest

        error_result["result_digest"] = freshness_result_digest(error_result)
        return error_result

    canonical_digest = freshness_result_digest(result)

    status_map = {
        "fresh": "FRESH",
        "stale": "STALE",
        "missing": "MISSING",
        "unreadable": "MISSING",
        "schema_fail": "MISSING",
        "empty": "MISSING",
    }
    return {
        "name": name,
        "path": str(path),
        "check_type": "content",
        "status": status_map.get(str(result.get("status")), "MISSING"),
        "date_column": date_column,
        "max_date": result.get("latest_date"),
        "trading_days_behind": result.get("lag_days"),
        "max_trading_days_behind": max_trading_days_behind,
        "age_hours": None,
        "max_age_hours": None,
        "engine": result.get("engine", "pandera"),
        "error": "; ".join(result.get("errors", [])) if result.get("errors") else None,
        "result_digest": canonical_digest,
    }


def resolve_freshness_gate(explicit: str | None = None) -> str:
    """Return ``midrun`` or ``publish``.

    Mid-run (candidate redirect) must not hard-fail on an incomplete chain.
    The publish boundary re-runs with ``publish`` after the chain is closed.
    """
    if explicit in ("midrun", "publish"):
        return explicit
    env = (os.environ.get("FRESHNESS_GATE") or "").strip().lower()
    if env in ("midrun", "publish"):
        return env
    if os.environ.get("CURRENT_OUTPUT_DIR"):
        return "midrun"
    return "publish"


def check_closure_chain(
    now: datetime,
    *,
    gate: str | None = None,
) -> list[dict[str, Any]]:
    """Check that all current outputs are from the same run (closure chain).

    If any current output is significantly older than the others, it means
    a partial refresh happened — the chain is not closed.

    The "current output chain" consists of: readme_first, signal_card,
    work_brief, system_index. These should all be generated within a
    short window (< 5 minutes) of each other during a full pipeline run.

    Under ``gate=midrun``, gaps are ADVISORY_EXPECTED so the in-pipeline step
    cannot deadlock publish. ``gate=publish`` hard-fails the same gaps.
    """
    issues = []
    chain_paths = {
        "readme_first": _chain_current() / "00_READ_ME_FIRST.md",
        "signal_card": _chain_current() / "signal_card.json",
        "signal_consensus": _chain_current() / "signal_consensus.json",
        "work_brief": _chain_current() / "work_brief.json",
        "system_index": ROOT / "Data" / "system_index" / "latest.json",
    }

    # Collect mtimes for all chain members that exist
    mtimes: dict[str, datetime] = {}
    for name, path in chain_paths.items():
        mtime = get_file_mtime(path)
        if mtime is not None:
            mtimes[name] = mtime

    if len(mtimes) < 2:
        return issues  # Can't check chain with < 2 artifacts

    # Check if any artifact is more than 5 minutes older than the newest
    # This indicates a partial refresh (the chain is not closed)
    newest_name = max(mtimes, key=lambda k: mtimes[k])
    newest_time = mtimes[newest_name]
    # 30-minute tolerance: accounts for re-runs that update some artifacts
    # but not all within the same pipeline session
    max_gap_minutes = 30
    resolved_gate = resolve_freshness_gate(gate)
    advisory = resolved_gate == "midrun"

    for name, mtime in mtimes.items():
        gap_minutes = (newest_time - mtime).total_seconds() / 60
        if gap_minutes > max_gap_minutes:
            issues.append({
                "rule": f"closure chain: {name} is {gap_minutes:.0f}min older than {newest_name}",
                "earlier": name,
                "earlier_time": mtime.isoformat(),
                "later": newest_name,
                "later_time": newest_time.isoformat(),
                "status": "ADVISORY_EXPECTED" if advisory else "CLOSURE_VIOLATION",
                "hint": (
                    "Mid-run candidate: closure is enforced at the publish boundary."
                    if advisory
                    else (
                        f"Partial refresh detected: {name} was not updated in the same run "
                        f"as {newest_name}. Re-run the full pipeline to close the chain, "
                        f"or run: python3 scripts/build_{name}.py"
                    )
                ),
            })

    return issues


def check_temporal_ordering(now: datetime, *, mode: str = "standard") -> list[dict[str, Any]]:
    """Check that artifacts are in correct temporal order."""
    issues = []

    # Define expected ordering — the full pipeline chain
    ordering_rules = [
        # Full-chain rules — quick mode marks these as ADVISORY_EXPECTED
        {
            "earlier": ("judgment", OUTPUT_DIR / "judgment" / "latest.json"),
            "later": ("promotion_gate", OUTPUT_DIR / "judgment" / "promotion_gate.json"),
            "rule": "promotion_gate must be after judgment",
            "chain": "full",
        },
        {
            "earlier": ("promotion_gate", OUTPUT_DIR / "judgment" / "promotion_gate.json"),
            "later": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "rule": "trade_decision must be after promotion_gate",
            "chain": "full",
        },
        {
            "earlier": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "later": ("risk_gate", OUTPUT_DIR / "trade_decision" / "risk_gate.json"),
            "rule": "risk_gate must be after trade_decision",
            "chain": "full",
        },
        {
            "earlier": ("risk_gate", OUTPUT_DIR / "trade_decision" / "risk_gate.json"),
            "later": ("record_trade_decision", OUTPUT_DIR / "trade_ledger" / "latest.md"),
            "rule": "record_trade_decision must be after risk_gate",
            "chain": "full",
        },
        {
            "earlier": ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json"),
            "later": ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json"),
            "rule": "learning_summary must be after trade_decision",
            "chain": "full",
        },
        {
            "earlier": ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json"),
            "later": ("system_index", ROOT / "Data" / "system_index" / "latest.json"),
            "rule": "system_index must be after learning_summary",
            "chain": "full",
        },
        {
            "earlier": ("system_index", ROOT / "Data" / "system_index" / "latest.json"),
            "later": ("readme_first", CURRENT / "00_READ_ME_FIRST.md"),
            "rule": "readme_first must be after system_index",
            "chain": "full",
        },
        # Current-output rules — always hard FAIL
        {
            "earlier": ("readme_first", CURRENT / "00_READ_ME_FIRST.md"),
            "later": ("signal_card", CURRENT / "signal_card.json"),
            "rule": "signal_card must be after readme_first",
            "chain": "current",
        },
        {
            "earlier": ("signal_card", CURRENT / "signal_card.json"),
            "later": ("signal_consensus", CURRENT / "signal_consensus.json"),
            "rule": "signal_consensus must be after signal_card",
            "chain": "current",
        },
        {
            "earlier": ("signal_consensus", CURRENT / "signal_consensus.json"),
            "later": ("work_brief", CURRENT / "work_brief.json"),
            "rule": "work_brief must be after signal_consensus",
            "chain": "current",
        },
    ]

    for rule in ordering_rules:
        earlier_name, earlier_path = rule["earlier"]
        later_name, later_path = rule["later"]

        earlier_time = get_file_mtime(earlier_path)
        later_time = get_file_mtime(later_path)

        if earlier_time and later_time:
            # Skip ordering check if files are from different days (weekly vs daily steps)
            if earlier_time.date() != now.date() or later_time.date() != now.date():
                continue

            # Skip if both files were modified within 30 minutes of each other
            # (same pipeline run, minor ordering from re-runs or parallel steps)
            delta = abs((later_time - earlier_time).total_seconds())
            if delta < 1800:
                continue

            if later_time < earlier_time:
                chain = rule.get("chain", "full")
                weekly_mix = (
                    _ARTIFACT_CADENCE.get(earlier_name) == "weekly"
                    or _ARTIFACT_CADENCE.get(later_name) == "weekly"
                )
                # Cross-day / weekly-vs-daily ordering issues are advisory.
                # Same-day refresh must not hard-FAIL solely because a weekly
                # learning_summary was not regenerated after trade_decision.
                is_advisory = (
                    (mode == "quick" and chain == "full")
                    or earlier_time.date() != later_time.date()
                    or weekly_mix
                )
                issues.append({
                    "rule": rule["rule"],
                    "earlier": earlier_name,
                    "earlier_time": earlier_time.isoformat(),
                    "later": later_name,
                    "later_time": later_time.isoformat(),
                    "status": "ADVISORY_EXPECTED" if is_advisory else "VIOLATION",
                    "hint": (
                        f"Ordering violation: {later_name} is older than {earlier_name}. "
                        f"Re-run the owning step (weekly artifacts: force-weekly daily path)."
                    ),
                })

    return issues


def build_freshness_report(
    now: datetime,
    *,
    mode: str = "standard",
    gate: str | None = None,
) -> dict[str, Any]:
    """Build complete freshness report."""
    resolved_gate = resolve_freshness_gate(gate)
    # Check artifact freshness
    artifacts = [
        ("harvester", ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json", MAX_AGE_HOURS["harvester"]),
        ("framework_output", CURRENT / "framework_output.json", MAX_AGE_HOURS["framework_output"]),
        ("judgment", OUTPUT_DIR / "judgment" / "latest.json", MAX_AGE_HOURS["judgment"]),
        ("promotion_gate", OUTPUT_DIR / "judgment" / "promotion_gate.json", MAX_AGE_HOURS["promotion_gate"]),
        ("trade_decision", OUTPUT_DIR / "trade_decision" / "latest.json", MAX_AGE_HOURS["trade_decision"]),
        ("risk_gate", OUTPUT_DIR / "trade_decision" / "risk_gate.json", MAX_AGE_HOURS["risk_gate"]),
        ("learning_summary", OUTPUT_DIR / "system_learning" / "latest" / "comprehensive_summary.json", MAX_AGE_HOURS["learning_summary"]),
        ("system_index", ROOT / "Data" / "system_index" / "latest.json", MAX_AGE_HOURS["system_index"]),
        ("readme_first", CURRENT / "00_READ_ME_FIRST.md", MAX_AGE_HOURS["readme_first"]),
        ("signal_card", CURRENT / "signal_card.json", MAX_AGE_HOURS["signal_card"]),
        ("signal_consensus", CURRENT / "signal_consensus.json", MAX_AGE_HOURS["signal_consensus"]),
        ("work_brief", CURRENT / "work_brief.json", MAX_AGE_HOURS["work_brief"]),
    ]

    freshness_checks = [check_artifact_freshness(name, path, max_age, now) for name, path, max_age in artifacts]

    # Content freshness — payload max(date), not file mtime
    content_checks: list[dict[str, Any]] = []
    for name, cfg in CONTENT_FRESHNESS.items():
        content_checks.append(
            check_content_freshness(
                name,
                ROOT / cfg["path"],
                cfg["date_column"],
                int(cfg["max_trading_days_behind"]),
                now,
            )
        )
    freshness_checks.extend(content_checks)

    carry_forward = evaluate_harvester_carry_forward(root=ROOT, now=now)
    freshness_checks.append(carry_forward)

    # Check evidence release freshness (3-day TTL)
    # See: governance/architecture_reality_decisions.md §4
    evidence_release = ROOT / "Data" / "harvester" / "exports" / "latest"
    if evidence_release.exists():
        er_check = check_artifact_freshness(
            "evidence_release", evidence_release, EVIDENCE_RELEASE_TTL_HOURS, now
        )
        freshness_checks.append(er_check)

    # Check temporal ordering
    ordering_issues = check_temporal_ordering(now, mode=mode)

    # Check closure chain — all current outputs must be from the same run
    closure_issues = check_closure_chain(now, gate=resolved_gate)

    # Determine overall verdict
    weekly_due = _weekly_freshness_due(now)
    schedule_advisory = {
        a["name"]
        for a in freshness_checks
        if not weekly_due
        and _ARTIFACT_CADENCE.get(str(a.get("name"))) == "weekly"
        and a.get("status") in {"STALE", "MISSING"}
    }
    stale_artifacts = [
        a for a in freshness_checks if a["status"] == "STALE" and a["name"] not in schedule_advisory
    ]
    missing_artifacts = [
        a for a in freshness_checks if a["status"] == "MISSING" and a["name"] not in schedule_advisory
    ]

    # Only hard violations count toward FAIL; ADVISORY_EXPECTED is informational
    hard_ordering = [i for i in ordering_issues if i["status"] != "ADVISORY_EXPECTED"]
    hard_closure = [i for i in closure_issues if i["status"] != "ADVISORY_EXPECTED"]
    if hard_ordering or hard_closure:
        verdict = "FAIL"
    elif stale_artifacts:
        # Advisory: missingness/carry-forward remain visible. Admission
        # publishes a diagnostic generation; it must not freeze Current.
        verdict = "WARN"
    elif missing_artifacts:
        verdict = "WARN"
    else:
        verdict = "PASS"

    quality_suite: dict[str, Any]
    try:
        from orchestration.quality.content_freshness_suite import (
            run_content_freshness_quality_suite,
            write_quality_validation_artifact,
        )

        quality_suite = run_content_freshness_quality_suite(root=ROOT)
        write_quality_validation_artifact(quality_suite, root=ROOT)
    except Exception as exc:  # noqa: BLE001 — GE is additive; never block report shape
        quality_suite = {
            "engine": "unavailable",
            "evaluator": "orchestration.quality.content_freshness",
            "success": False,
            "status": "EVALUATOR_UNAVAILABLE",
            "error": str(exc),
        }

    if quality_suite.get("success") is not True:
        verdict = "FAIL"

    return {
        "schema_version": "freshness_validator.v3",
        "generated_at": now.isoformat(),
        "gate": resolved_gate,
        "verdict": verdict,
        "stale_artifacts": [a["name"] for a in stale_artifacts],
        "missing_artifacts": [a["name"] for a in missing_artifacts],
        "schedule_advisory_artifacts": sorted(schedule_advisory),
        "weekly_freshness_due": weekly_due,
        "ordering_issues": ordering_issues,
        "closure_chain_issues": closure_issues,
        "content_freshness": content_checks,
        "carry_forward": {
            "series": carry_forward.get("series") or [],
            "count": carry_forward.get("count") or 0,
            "max_trading_days_behind": carry_forward.get("max_trading_days_behind") or 0,
            "exceeds": bool(carry_forward.get("exceeds")),
            "max_series": CARRY_FORWARD_MAX_SERIES,
            "max_trading_days": CARRY_FORWARD_MAX_TRADING_DAYS,
        },
        "artifacts": freshness_checks,
        "quality_content_freshness": quality_suite,
    }


def format_markdown(report: dict[str, Any]) -> str:
    """Format freshness report as markdown."""
    lines = [
        "# Freshness Report",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Verdict:** {report['verdict']}",
        "",
        "---",
        "",
        "## Artifacts",
        "",
        "| Artifact | Status | Age (h) | Max Age (h) |",
        "|---|---|---:|---:|",
    ]

    for artifact in report["artifacts"]:
        status_icon = "✅" if artifact["status"] == "FRESH" else "❌" if artifact["status"] == "STALE" else "⚠️"
        if artifact.get("check_type") == "content":
            behind = artifact.get("trading_days_behind")
            age = f"{behind}d behind" if behind is not None else "N/A"
            max_age = str(artifact.get("max_trading_days_behind", "N/A"))
        elif artifact.get("check_type") == "carry_forward":
            age = f"{artifact.get('count', 0)} series / {artifact.get('max_trading_days_behind', 0)}d"
            max_age = f"{artifact.get('max_series')}/{artifact.get('max_trading_days')}d"
        else:
            age = f"{artifact['age_hours']:.1f}" if artifact["age_hours"] is not None else "N/A"
            max_age = str(artifact["max_age_hours"]) if artifact.get("max_age_hours") is not None else "N/A"
        lines.append(f"| {artifact['name']} | {status_icon} {artifact['status']} | {age} | {max_age} |")

    if report.get("content_freshness"):
        lines += [
            "",
            "## Content Freshness",
            "",
            "| Artifact | Status | max(date) | Days behind | Budget |",
            "|---|---|---|---:|---:|",
        ]
        for item in report["content_freshness"]:
            status_icon = "✅" if item["status"] == "FRESH" else "❌" if item["status"] == "STALE" else "⚠️"
            lines.append(
                f"| {item['name']} | {status_icon} {item['status']} | "
                f"{item.get('max_date') or 'N/A'} | "
                f"{item.get('trading_days_behind') if item.get('trading_days_behind') is not None else 'N/A'} | "
                f"{item.get('max_trading_days_behind', 'N/A')} |"
            )

    carry = report.get("carry_forward") if isinstance(report.get("carry_forward"), dict) else {}
    if carry.get("series"):
        lines += [
            "",
            "## Harvester carry-forward",
            "",
            f"Count {carry.get('count')} (WARN if > {carry.get('max_series')} "
            f"or any series > {carry.get('max_trading_days')} trading days).",
            "",
            "| Series | max(date) | Trading days behind |",
            "|---|---|---:|",
        ]
        for item in carry["series"]:
            lines.append(
                f"| {item.get('series_id')} | {item.get('max_date') or 'N/A'} | "
                f"{item.get('trading_days_behind')} |"
            )

    if report.get("ordering_issues"):
        lines += [
            "",
            "## Ordering Issues",
            "",
        ]
        for issue in report["ordering_issues"]:
            lines.append(f"- ❌ {issue['rule']}")

    if report.get("closure_chain_issues"):
        lines += [
            "",
            "## Closure Chain Violations",
            "",
            "Current outputs are not from the same run. Re-run the full pipeline to close the chain.",
            "",
        ]
        for issue in report["closure_chain_issues"]:
            lines.append(f"- ❌ {issue['rule']}")
            if issue.get("hint"):
                lines.append(f"  - Fix: {issue['hint']}")

    if report["stale_artifacts"]:
        lines += [
            "",
            "## Stale Artifacts",
            "",
        ]
        for name in report["stale_artifacts"]:
            lines.append(f"- {name}")

    if report["missing_artifacts"]:
        lines += [
            "",
            "## Missing Artifacts",
            "",
        ]
        for name in report["missing_artifacts"]:
            lines.append(f"- {name}")

    if report.get("schedule_advisory_artifacts"):
        lines += [
            "",
            "## Schedule Advisory",
            "",
            "These weekly artifacts are not expected on the current daily slot; "
            "they remain visible without blocking daily admission:",
            "",
        ]
        for name in report["schedule_advisory_artifacts"]:
            lines.append(f"- {name}")

    lines += [
        "",
        "---",
        "",
        "*Stale artifacts cannot be displayed as ✅ in system index.*",
    ]

    return "\n".join(lines) + "\n"


def write_outputs(report: dict[str, Any]) -> dict[str, Path]:
    """Write freshness report outputs."""
    ensure_dir(QUALITY_DIR)

    json_path = QUALITY_DIR / "freshness_report.json"
    md_path = QUALITY_DIR / "freshness_report.md"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(format_markdown(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def main() -> int:
    """Run freshness validator.

    Gates:
      - midrun: in-pipeline candidate check. Closure gaps are advisory; always
        exits 0 so downstream steps are not blocked_upstream. Content STALE is
        recorded in the report but not pushed (daily_run aggregates HARD alerts).
      - publish: post-chain / CLI check. Hard FAIL exits 1 for the publish gate.
        Standalone CLI may notify content STALE; daily_run suppresses that and
        merges into one System daily_run alert.
    """
    parser = argparse.ArgumentParser(description="Run freshness validator.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument(
        "--mode", choices=["quick", "standard", "full"], default="standard",
        help="Validation mode: quick marks full-chain ordering as advisory.",
    )
    parser.add_argument(
        "--gate",
        choices=["midrun", "publish"],
        default=None,
        help="midrun=advisory in-pipeline; publish=hard boundary (default by env).",
    )
    parser.add_argument(
        "--notify-content-stale",
        action="store_true",
        help="Push Content freshness STALE (default: only for standalone publish CLI).",
    )
    args = parser.parse_args()

    gate = resolve_freshness_gate(args.gate)
    now = datetime.now(UTC)
    report = build_freshness_report(now, mode=args.mode, gate=gate)
    paths = write_outputs(report)

    content_stale = [
        c for c in report.get("content_freshness", [])
        if c.get("status") == "STALE"
    ]
    # Never push from inside daily_run (bundle id and/or candidate redirect).
    # daily_run aggregates content STALE into one HARD alert. Standalone CLI
    # (operator runs freshness by hand) may still push unless disabled.
    in_pipeline = bool(
        os.environ.get("ZCODE_BUNDLE_RUN_ID") or os.environ.get("CURRENT_OUTPUT_DIR")
    )
    standalone_cli = gate == "publish" and not in_pipeline
    if content_stale and (args.notify_content_stale or standalone_cli):
        from verity.runtime._notify import notify_failure

        details = ", ".join(
            f"{c['name']} max={c.get('max_date')} behind={c.get('trading_days_behind')}d"
            for c in content_stale
        )
        notify_failure(
            "Content freshness STALE",
            details,
        )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Freshness report: {paths['markdown']}")
        print(f"Gate: {gate}")
        print(f"Verdict: {report['verdict']}")
        print(f"Stale: {len(report['stale_artifacts'])}")
        print(f"Missing: {len(report['missing_artifacts'])}")
        print(f"Ordering issues: {len(report['ordering_issues'])}")
        if report.get("content_freshness"):
            for c in report["content_freshness"]:
                print(
                    f"Content {c['name']}: {c['status']} "
                    f"(max={c.get('max_date')}, behind={c.get('trading_days_behind')})"
                )

    # Mid-run is advisory: never fail the pipeline step. Publish gate hard-fails.
    if gate == "midrun":
        return 0
    return 1 if report.get("verdict") == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
