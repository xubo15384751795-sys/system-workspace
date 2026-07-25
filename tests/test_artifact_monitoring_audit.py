from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from artifact_monitoring_audit import (  # noqa: E402
    build_report,
    learning_hub_source_lag,
    monitoring_blind_spots,
    monitoring_matrix,
    non_daily_contract_violations,
)


def _write_registry(root: Path, steps: dict) -> dict:
    registry = {"_defaults": {"ttl_hours": 48}, "steps": steps}
    path = root / "governance" / "daily_pipeline_registry.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    return registry


def test_weekly_steps_must_register_outputs_and_ttl(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        {"orphan_weekly": {"status": "active", "schedule": "weekly", "ttl_hours": 0}},
    )

    kinds = {finding["kind"] for finding in non_daily_contract_violations(registry)}

    assert kinds == {"non_daily_without_registered_output", "non_daily_without_positive_ttl"}


def test_manual_and_on_demand_steps_are_bound_to_monitoring_contracts(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        {
            "manual_orphan": {"status": "active", "schedule": "manual"},
            "on_demand_ok": {
                "status": "active",
                "schedule": "on_demand",
                "ttl_hours": 168,
                "produces": ["Output/current/on_demand.json"],
            },
        },
    )

    findings = non_daily_contract_violations(registry)

    assert {row["step"] for row in findings} == {"manual_orphan"}


def test_ttl_cannot_be_shorter_than_the_registered_cadence(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        {
            "impossible_weekly": {
                "status": "active",
                "schedule": "weekly",
                "ttl_hours": 24,
                "produces": ["Output/current/impossible.json"],
            }
        },
    )

    findings = non_daily_contract_violations(registry)

    assert findings == [
        {
            "step": "impossible_weekly",
            "schedule": "weekly",
            "kind": "ttl_shorter_than_schedule",
            "ttl_hours": 24,
            "minimum_hours": 168,
        }
    ]


def test_blind_spot_report_enumerates_uncovered_current_artifact(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        {
            "covered": {
                "status": "active",
                "schedule": "weekly",
                "ttl_hours": 168,
                "produces": ["Output/current/covered.json"],
            }
        },
    )
    current = tmp_path / "Output" / "current"
    current.mkdir(parents=True)
    (current / "covered.json").write_text('{"generated_at":"2026-07-17T00:00:00Z"}', encoding="utf-8")
    (current / "blind.json").write_text('{"generated_at":"2026-07-17T00:00:00Z"}', encoding="utf-8")

    blind = monitoring_blind_spots(tmp_path, registry)

    assert "Output/current/blind.json" in blind
    assert "Output/current/covered.json" not in blind


def test_matrix_names_compiled_monitor_for_non_daily_output(tmp_path: Path) -> None:
    registry = _write_registry(
        tmp_path,
        {
            "covered": {
                "status": "active",
                "schedule": "weekly",
                "ttl_hours": 168,
                "produces": ["Output/current/covered.json"],
            }
        },
    )
    current = tmp_path / "Output" / "current"
    current.mkdir(parents=True)
    (current / "covered.json").write_text('{"generated_at":"2026-07-17T00:00:00Z"}', encoding="utf-8")

    row = next(item for item in monitoring_matrix(tmp_path, registry) if item["artifact"].endswith("covered.json"))

    assert row["covered"] is True
    assert row["monitor_ids"] == ["registry:covered"]


def test_learning_hub_source_newer_than_ledger_is_failure(tmp_path: Path) -> None:
    ledger = tmp_path / "Data" / "system_learning" / "ledgers" / "system_event_ledger.parquet"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("ledger", encoding="utf-8")
    source = tmp_path / "Output" / "system_learning" / "events" / "run_events_2026-07-17.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text("{}\n", encoding="utf-8")
    os.utime(ledger, (1000, 1000))
    os.utime(source, (2000, 2000))

    result = learning_hub_source_lag(tmp_path)

    assert result["status"] == "SOURCE_AHEAD_OF_LEDGER"


def test_report_fails_when_weekly_contract_is_unmonitored(tmp_path: Path) -> None:
    _write_registry(tmp_path, {"orphan": {"status": "active", "schedule": "weekly"}})

    report = build_report(tmp_path, now=datetime(2026, 7, 17, tzinfo=UTC))

    assert report["status"] == "FAIL"
