from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from system_learning.analyzers.derive import build_derived_ledgers
from system_learning.cartography.runner import run_cartography
from system_learning.governance.lifecycle_events import (
    migrate_improvement_queue_to_lifecycle_events,
    proposed_events_for_improvements,
)
from system_learning.ingestion.collectors import collect_events
from system_learning.ledger.append import (
    append_lifecycle_events,
    append_system_events,
    canonical_events,
    materialize_event_snapshot,
    read_lifecycle_ledger,
)
from system_learning.ledger.store import read_existing_improvement_queue, write_derived_ledgers
from system_learning.ml_integrity import run_pollution_check
from system_learning.reports.writer import write_reports
from system_learning.runtime.context import RunContext, filter_events_since
from system_learning.runtime.manifest import write_run_manifest
from system_learning.runtime.paths import HubPaths


@dataclass
class PipelinePlan:
    run_cartography: bool = False
    run_ml_integrity: bool = False
    collect_events: bool = True
    write_reports: bool = True
    write_manifest: bool = True
    events_since: str | None = None


@dataclass
class PipelineResult:
    context: RunContext
    events: list[dict]
    ledgers: dict[str, pd.DataFrame]
    ledger_paths: dict[str, Path] = field(default_factory=dict)
    report_paths: dict[str, Path] = field(default_factory=dict)
    cartography_outputs: dict[str, Path] | None = None
    ml_report: Any | None = None
    steps_completed: list[str] = field(default_factory=list)
    manifest_path: Path | None = None


def execute_pipeline(
    context: RunContext,
    paths: HubPaths,
    plan: PipelinePlan,
) -> PipelineResult:
    """Governance memory pipeline: append events → derive views → materialize reports."""
    result = PipelineResult(context=context, events=[], ledgers={})
    metadata_cache = read_existing_improvement_queue(paths.ledger_dir)

    if plan.run_cartography:
        result.cartography_outputs = run_cartography(
            scan_root=paths.system_root,
            project_root=paths.hub_project_root,
        )
        result.steps_completed.append("scan.cartography")

    if plan.run_ml_integrity:
        result.ml_report = run_pollution_check(
            signals_root=paths.system_root / "Output" / "state" / "ml_signals",
            runs_root=paths.system_root / "Output" / "deformation_runs",
            events_dir=paths.events_dir,
        )
        result.steps_completed.append("scan.ml_integrity")

    if plan.collect_events:
        collected = collect_events(paths.system_root)
        result.events = filter_events_since(collected, plan.events_since)
        append_system_events(paths.ledger_dir, result.events, context.run_id)
        result.steps_completed.append("append.events")
    else:
        result.steps_completed.append("append.events.skip")

    _ensure_lifecycle_bootstrap(paths.ledger_dir, metadata_cache, context.run_id)

    event_df = canonical_events(paths.ledger_dir)
    lifecycle_df = read_lifecycle_ledger(paths.ledger_dir)

    result.ledgers = build_derived_ledgers(event_df, lifecycle_df, metadata_cache=metadata_cache)
    result.steps_completed.extend(["derive.violations", "derive.edges", "derive.improvements", "derive.health"])

    new_proposals = proposed_events_for_improvements(
        result.ledgers["improvement_queue"]["improvement_id"].astype(str).tolist(),
        lifecycle_df,
        recorded_by_run=context.run_id,
    )
    if new_proposals:
        lifecycle_df = append_lifecycle_events(paths.ledger_dir, new_proposals, context.run_id)
        result.ledgers = build_derived_ledgers(event_df, lifecycle_df, metadata_cache=metadata_cache)
        result.steps_completed.append("append.lifecycle.proposed")

    snapshot_path = materialize_event_snapshot(paths.ledger_dir, result.ledgers["system_event_ledger"])
    result.ledger_paths = write_derived_ledgers(paths.ledger_dir, result.ledgers, context.run_id)
    result.ledger_paths["system_event_ledger"] = snapshot_path
    result.steps_completed.append("persist.derived")

    if plan.write_reports:
        result.report_paths = write_reports(paths.report_dir, result.ledgers, context)
        result.steps_completed.append("reports")

    if plan.write_manifest:
        completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        stats = {
            "event_count": int(len(result.ledgers["system_event_ledger"])),
            "events_appended_this_run": len(result.events),
            "edge_count": int(len(result.ledgers.get("event_edges", []))),
            "completed_at": completed_at,
            "ml_passed": None if result.ml_report is None else result.ml_report.passed,
        }
        outputs = {key: str(path) for key, path in result.ledger_paths.items()}
        outputs.update({f"report_{key}": str(path) for key, path in result.report_paths.items()})
        if result.cartography_outputs:
            outputs.update({f"cartography_{key}": str(path) for key, path in result.cartography_outputs.items()})
        result.manifest_path = write_run_manifest(
            paths.runs_dir,
            context,
            steps=result.steps_completed,
            stats=stats,
            outputs=outputs,
        )
        result.steps_completed.append("manifest")

    return result


def _ensure_lifecycle_bootstrap(
    ledger_dir: Path,
    metadata_cache: pd.DataFrame | None,
    run_id: str,
) -> None:
    lifecycle_df = read_lifecycle_ledger(ledger_dir)
    if not lifecycle_df.empty or metadata_cache is None or metadata_cache.empty:
        return
    migrated = migrate_improvement_queue_to_lifecycle_events(metadata_cache, recorded_by_run=run_id)
    if migrated:
        append_lifecycle_events(ledger_dir, migrated, run_id)
