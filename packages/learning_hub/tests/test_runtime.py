from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from system_learning.analyzers.derive import build_ledgers
from system_learning.ledger.append import append_system_events
from system_learning.ledger.store import write_derived_ledgers
from system_learning.runtime.context import new_run_context
from system_learning.runtime.manifest import read_last_run_id
from system_learning.runtime.paths import HubPaths
from system_learning.runtime.pipeline import PipelinePlan, execute_pipeline


def test_run_context_stamps_all_ledgers(tmp_path: Path) -> None:
    events = [
        {
            "event_id": "evt-1",
            "timestamp": "2026-04-26T00:00:00Z",
            "subsystem": "harvester",
            "event_type": "provider_health_issue",
            "severity": "high",
            "payload": {},
            "source_report_path": "/tmp/x.json",
            "requires_manual_review": True,
        }
    ]
    context = new_run_context(mode="test", run_id="hub-test-run-001")
    ledgers = build_ledgers(events)
    ledger_dir = tmp_path / "ledgers"
    append_system_events(ledger_dir, events, context.run_id)
    write_derived_ledgers(ledger_dir, ledgers, context.run_id)

    for name in ("violation_ledger", "event_edges", "improvement_queue", "subsystem_health"):
        frame = pd.read_parquet(ledger_dir / f"{name}.parquet")
        assert (frame["generated_by_run"] == context.run_id).all()


def test_execute_pipeline_writes_manifest_and_summary_run_block(tmp_path: Path) -> None:
    system_root = tmp_path / "System"
    events_path = (
        system_root
        / "Output"
        / "system_learning"
        / "events"
        / "ml_test_evt.json"
    )
    events_path.parent.mkdir(parents=True)
    events_path.write_text(
        json.dumps(
            {
                "event_id": "evt-1",
                "timestamp": "2026-05-01T00:00:00Z",
                "subsystem": "harvester",
                "event_type": "provider_health_issue",
                "severity": "medium",
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    paths = HubPaths.resolve(system_root)
    context = new_run_context(mode="full", run_id="hub-pipeline-001")
    result = execute_pipeline(
        context,
        paths,
        PipelinePlan(run_cartography=False, run_ml_integrity=False, write_manifest=True),
    )

    assert result.manifest_path is not None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["run"]["run_id"] == "hub-pipeline-001"
    assert "append.events" in manifest["steps"]

    summary = json.loads((paths.report_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["run"]["run_id"] == "hub-pipeline-001"
    assert read_last_run_id(paths.runs_dir) == "hub-pipeline-001"


def test_rebuild_ledger_skips_collect(tmp_path: Path) -> None:
    system_root = tmp_path / "System"
    paths = HubPaths.resolve(system_root)
    paths.ledger_dir.mkdir(parents=True, exist_ok=True)

    events = [
        {
            "event_id": "evt-1",
            "timestamp": "2026-05-01T00:00:00Z",
            "subsystem": "deformation",
            "event_type": "benchmark_error",
            "severity": "high",
            "payload": {"m": 1},
            "requires_manual_review": False,
        }
    ]
    append_system_events(paths.ledger_dir, events, "seed-run")

    context = new_run_context(mode="rebuild-ledger", run_id="hub-rebuild-001")
    result = execute_pipeline(
        context,
        paths,
        PipelinePlan(collect_events=False, write_reports=False, write_manifest=False),
    )

    assert "append.events.skip" in result.steps_completed
    assert len(result.ledgers["system_event_ledger"]) == 1
    frame = pd.read_parquet(paths.ledger_dir / "improvement_queue.parquet")
    assert frame.loc[0, "generated_by_run"] == "hub-rebuild-001"
