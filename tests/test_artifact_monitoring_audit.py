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
    classify_blind_spots,
    classify_monitoring_path,
    learning_hub_source_lag,
    monitoring_blind_spots,
    monitoring_contract_violations,
    monitoring_matrix,
    non_daily_content_checks,
    non_daily_contract_violations,
    required_coverage_gaps,
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


def test_live_registry_has_no_non_daily_ttl_schedule_violations() -> None:
    """P0-4 wave 1: weekly TTL must not be shorter than weekly cadence."""
    registry = yaml.safe_load(
        (ROOT / "governance" / "daily_pipeline_registry.yaml").read_text(encoding="utf-8")
    )
    findings = non_daily_contract_violations(registry or {})
    assert findings == []


def test_content_clock_ignores_fresh_mtime_when_payload_is_stale(tmp_path: Path) -> None:
    """P0-4: mtime and content clock are separate; fresh touch cannot hide stale payload."""
    registry = _write_registry(
        tmp_path,
        {
            "weekly_report": {
                "status": "active",
                "schedule": "weekly",
                "ttl_hours": 168,
                "produces": ["Output/current/weekly_report.json"],
            }
        },
    )
    artifact = tmp_path / "Output" / "current" / "weekly_report.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"generated_at":"2026-01-01T00:00:00Z"}', encoding="utf-8")
    os.utime(artifact, None)  # fresh mtime

    checks = non_daily_content_checks(
        tmp_path,
        registry,
        now=datetime(2026, 7, 17, tzinfo=UTC),
    )

    assert len(checks) == 1
    assert checks[0]["status"] == "STALE_CONTENT"
    assert checks[0]["content_age_hours"] is not None
    assert checks[0]["content_age_hours"] > 168


def test_blind_spots_are_classified_with_owner(tmp_path: Path) -> None:
    """P0-4 wave 2: uncovered artifacts get class + owner from registry rules."""
    registry = {
        "steps": {
            "covered": {
                "status": "active",
                "schedule": "weekly",
                "ttl_hours": 168,
                "produces": ["Output/current/covered.json"],
            }
        },
        "monitoring_classification": {
            "required_coverage_classes": ["authoritative", "decision_adjacent_shadow"],
            "rules": [
                {
                    "pattern": "Output/current/*",
                    "class": "authoritative",
                    "owner": "Workbench",
                },
                {
                    "pattern": "Output/sandbox/*",
                    "class": "research",
                    "owner": "Workbench",
                },
            ],
        },
    }
    path = tmp_path / "governance" / "daily_pipeline_registry.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

    current = tmp_path / "Output" / "current"
    sandbox = tmp_path / "Output" / "sandbox"
    current.mkdir(parents=True)
    sandbox.mkdir(parents=True)
    (current / "covered.json").write_text('{"generated_at":"2026-07-17T00:00:00Z"}', encoding="utf-8")
    (current / "blind.json").write_text('{"generated_at":"2026-07-17T00:00:00Z"}', encoding="utf-8")
    (sandbox / "probe.json").write_text('{"generated_at":"2026-07-17T00:00:00Z"}', encoding="utf-8")

    classified = classify_blind_spots(monitoring_blind_spots(tmp_path, registry), registry)
    by_path = {row["path"]: row for row in classified}

    assert by_path["Output/current/blind.json"]["class"] == "authoritative"
    assert by_path["Output/current/blind.json"]["owner"] == "Workbench"
    assert by_path["Output/sandbox/probe.json"]["class"] == "research"
    assert "Output/current/covered.json" not in by_path

    gaps = required_coverage_gaps(classified, registry)
    assert {row["path"] for row in gaps} == {"Output/current/blind.json"}

    report = build_report(tmp_path, now=datetime(2026, 7, 17, tzinfo=UTC))
    assert report["status"] == "FAIL"
    assert report["summary"]["required_coverage_gap_count"] == 1


def test_research_blind_spot_with_owner_is_warn_not_required_gap(tmp_path: Path) -> None:
    registry = {
        "steps": {},
        "monitoring_classification": {
            "required_coverage_classes": ["authoritative", "decision_adjacent_shadow"],
            "rules": [
                {
                    "pattern": "Output/sandbox/*",
                    "class": "research",
                    "owner": "Workbench",
                }
            ],
        },
    }
    path = tmp_path / "governance" / "daily_pipeline_registry.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    sandbox = tmp_path / "Output" / "sandbox"
    sandbox.mkdir(parents=True)
    (sandbox / "probe.json").write_text('{"generated_at":"2026-07-17T00:00:00Z"}', encoding="utf-8")

    report = build_report(tmp_path, now=datetime(2026, 7, 17, tzinfo=UTC))

    assert report["summary"]["required_coverage_gap_count"] == 0
    assert report["summary"]["unresolved_monitoring_blind_spot_count"] == 0
    assert report["status"] == "WARN"


def test_live_registry_classifies_authority_paths() -> None:
    """P0-4 wave 2: live classification rules cover current + sandbox prefixes."""
    registry = yaml.safe_load(
        (ROOT / "governance" / "daily_pipeline_registry.yaml").read_text(encoding="utf-8")
    )
    current = classify_monitoring_path("Output/current/signal_consensus.json", registry or {})
    sandbox = classify_monitoring_path("Output/sandbox/probe.json", registry or {})
    assert current["class"] == "authoritative"
    assert current["owner"]
    assert sandbox["class"] == "research"
    assert sandbox["owner"]
    assert registry["monitoring_classification"]["rules"]


def test_monitoring_contract_covers_static_path_and_requires_target(tmp_path: Path) -> None:
    registry = {
        "steps": {},
        "monitoring_contracts": {
            "static_registry": {
                "path": "Data/system_learning/registries/policy.yaml",
                "class": "decision_adjacent_shadow",
                "owner": "Learning Hub",
                "mode": "version_controlled_input",
            }
        },
    }
    path = tmp_path / "Data" / "system_learning" / "registries" / "policy.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("schema_version: test.v1\n", encoding="utf-8")

    assert monitoring_contract_violations(tmp_path, registry) == []
    assert "Data/system_learning/registries/policy.yaml" not in monitoring_blind_spots(
        tmp_path, registry
    )

    path.unlink()
    violations = monitoring_contract_violations(tmp_path, registry)
    assert violations == [
        {
            "monitor": "static_registry",
            "path": "Data/system_learning/registries/policy.yaml",
            "kind": "missing_monitoring_contract_target",
        }
    ]


def test_pointer_monitor_rejects_broken_symlink(tmp_path: Path) -> None:
    pointer = tmp_path / "Output" / "current" / "latest_run_id.txt"
    pointer.parent.mkdir(parents=True)
    pointer.symlink_to(tmp_path / "missing" / "latest_run_id.txt")
    registry = {
        "steps": {},
        "monitoring_contracts": {
            "current_run_pointer": {
                "path": "Output/current/latest_run_id.txt",
                "class": "authoritative",
                "owner": "PublishTransaction",
                "mode": "pointer_integrity",
            }
        },
    }

    assert monitoring_contract_violations(tmp_path, registry) == [
        {
            "monitor": "current_run_pointer",
            "path": "Output/current/latest_run_id.txt",
            "kind": "broken_monitoring_contract_pointer",
        }
    ]
