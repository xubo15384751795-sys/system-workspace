"""Contract tests for the read-only minimum operational monitor."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from system_runtime.feedback_lifecycle import make_transition_event
from system_runtime.minimum_monitoring import (
    _publication,
    evaluate_minimum_monitoring,
    notification_dedup_key,
)


def _copy_provider_policy(root: Path) -> None:
    policy_dir = root / "configs"
    policy_dir.mkdir(parents=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[1]
        / "configs"
        / "provider_release_policy.yaml",
        policy_dir / "provider_release_policy.yaml",
    )


def test_monitor_does_not_turn_missing_evidence_into_pass(tmp_path: Path) -> None:
    result = evaluate_minimum_monitoring(tmp_path)
    assert result["overall_status"] == "INCOMPLETE"


def test_monitor_cli_is_nonzero_until_all_checks_pass(monkeypatch, tmp_path: Path) -> None:
    import system_runtime.minimum_monitoring as monitoring

    monkeypatch.setattr(
        monitoring,
        "evaluate_minimum_monitoring",
        lambda *args, **kwargs: {"overall_status": "BLOCKED", "checks": {}},
    )
    assert monitoring._main(["--root", str(tmp_path)]) == 1

    monkeypatch.setattr(
        monitoring,
        "evaluate_minimum_monitoring",
        lambda *args, **kwargs: {"overall_status": "PASS", "checks": {}},
    )
    assert monitoring._main(["--root", str(tmp_path)]) == 0


def test_environmentally_blocked_provider_never_unlocks_decision(tmp_path: Path) -> None:
    _copy_provider_policy(tmp_path)
    manifest_dir = (
        tmp_path
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "manifests"
    )
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "cross_asset_daily_panel.manifest.json").write_text(
        json.dumps(
            {
                "provider_outcome": {"status": "environmentally_blocked"},
                "release_id": "release_environment_blocked",
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path)
    check = result["checks"]["provider_failure"]
    assert check["status"] == "BLOCKED"
    assert check["reason_code"] == "ENVIRONMENTALLY_BLOCKED"
    assert check["status_policy"]["decision"] == "DENY"
    assert check["status_policy"]["watch_zero"] == "DIAGNOSTIC_ONLY"


def test_diagnostic_provider_route_never_unlocks_decision(tmp_path: Path) -> None:
    _copy_provider_policy(tmp_path)
    manifest_dir = (
        tmp_path
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "manifests"
    )
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "cross_asset_daily_panel.manifest.json").write_text(
        json.dumps(
            {
                "provider_outcome": {
                    "status": "refreshed",
                    "route_policy": {
                        "route_class": "diagnostic_fallback",
                        "diagnostic_only": True,
                        "promotion_allowed": False,
                        "decision_usable": False,
                        "reason": "yfinance_route_is_diagnostic_only",
                    },
                },
                "release_id": "release_diagnostic_route",
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path)
    check = result["checks"]["provider_failure"]
    assert check["status"] == "BLOCKED"
    assert check["reason_code"] == "DIAGNOSTIC_ONLY_PROVIDER_ROUTE"


def test_notification_dedup_and_lineage_are_checked(tmp_path: Path) -> None:
    output = tmp_path / "Output"
    run_id = "daily_test_run"
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_outcome.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "publish_status": "COMMITTED",
                "admission_verdict": "PASS",
                "authority_mode": "authoritative",
                "generation_id": run_id,
                "release_id": "release_test",
            }
        ),
        encoding="utf-8",
    )
    alert = {
        "status": "success",
        "run_id": run_id,
        "release_id": "release_test",
        "generation_id": "generation_test",
        "provider_status": "refreshed",
        "warnings": [],
        "failed_steps": [],
        "outcome": {
            "run_id": run_id,
            "publish_status": "COMMITTED",
            "admission_verdict": "PASS",
            "authority_mode": "authoritative",
            "generation_id": "generation_test",
            "release_id": "release_test",
        },
    }
    alert["notification_dedup_key"] = notification_dedup_key(
        run_id=run_id,
        status="success",
        failed_steps=[],
        warnings=[],
        outcome=alert["outcome"],
        provider_status=alert["provider_status"],
    )
    (output / "state" / "alerts").mkdir(parents=True)
    (output / "state" / "alerts" / "latest_alert.json").write_text(
        json.dumps(alert), encoding="utf-8"
    )
    (output / "current").mkdir(parents=True)
    (output / "current" / "latest_run_id.txt").write_text(run_id + "\n", encoding="utf-8")
    generation = output / "generations" / run_id
    generation.mkdir(parents=True)
    (generation / "admission.json").write_text(
        json.dumps(
            {
                "publish_integrity_verdict": "PASS",
                "diagnostic_publish_verdict": "PASS",
                "decision_authority_verdict": "ALLOW",
                "generation_id": run_id,
                "release_id": "release_test",
            }
        ),
        encoding="utf-8",
    )
    (generation / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "authority": "ALLOW",
                "status": "accepted",
                "release_id": "release_test",
            }
        ),
        encoding="utf-8",
    )
    (output / "live").symlink_to(Path("generations") / run_id, target_is_directory=True)
    (tmp_path / "Data" / "harvester" / "exports" / "latest" / "manifests").mkdir(parents=True)
    (tmp_path / "Data" / "harvester" / "exports" / "latest" / "manifests" / "cross_asset_daily_panel.manifest.json").write_text(
        json.dumps({"status": "refreshed", "release_id": "release_test"}),
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path, run_id=run_id)
    assert result["checks"]["notification_dedup"]["status"] == "PASS"
    assert result["checks"]["publish_authority_verdict"]["status"] == "PASS"
    assert result["checks"]["alert_to_run_release_generation_lineage"]["status"] == "BLOCKED"


def test_publication_reader_carries_shadow_lineage_without_using_it_for_status(tmp_path: Path) -> None:
    output = tmp_path / "Output"
    run_id = "run-canonical-reader"
    run_dir = output / "runs" / run_id
    generation = output / "generations" / run_id
    run_dir.mkdir(parents=True)
    generation.mkdir(parents=True)
    (output / "live").symlink_to(generation, target_is_directory=True)
    (run_dir / "run_outcome.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "generation_id": run_id,
                "publish_status": "COMMITTED",
                "admission_verdict": "PASS",
                "authority_mode": "authoritative",
            }
        ),
        encoding="utf-8",
    )
    lineage = {
        "schema_version": "system.canonical_lineage_reader.v1",
        "authority": "shadow_only",
        "promotion_allowed": False,
        "status": "MATCH",
        "entry_count": 1,
        "entries": [],
    }
    (generation / "admission.json").write_text(
        json.dumps(
            {
                "generation_id": run_id,
                "publish_integrity_verdict": "PASS",
                "diagnostic_publish_verdict": "PASS",
                "decision_authority_verdict": "ALLOW",
                "canonical_lineage": lineage,
            }
        ),
        encoding="utf-8",
    )
    (generation / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "authority": "ALLOW"}),
        encoding="utf-8",
    )

    publication = _publication(tmp_path, output, run_id)

    assert publication["status"] == "PASS"
    assert publication["canonical_lineage"] == lineage


def test_publication_blocks_mixed_run_and_generation_lineage(tmp_path: Path) -> None:
    output = tmp_path / "Output"
    run_id = "run_a"
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_outcome.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "publish_status": "COMMITTED",
                "admission_verdict": "PASS",
                "authority_mode": "authoritative",
                "generation_id": run_id,
            }
        ),
        encoding="utf-8",
    )
    generation = output / "generations" / "run_b"
    generation.mkdir(parents=True)
    (generation / "admission.json").write_text(
        json.dumps(
            {
                "publish_integrity_verdict": "PASS",
                "diagnostic_publish_verdict": "PASS",
                "decision_authority_verdict": "ALLOW",
                "generation_id": "run_b",
            }
        ),
        encoding="utf-8",
    )
    (generation / "manifest.json").write_text(
        json.dumps({"run_id": "run_b", "authority": "ALLOW"}),
        encoding="utf-8",
    )
    (output / "live").symlink_to(Path("generations") / "run_b", target_is_directory=True)

    result = evaluate_minimum_monitoring(tmp_path, run_id=run_id)
    publication = result["checks"]["publish_authority_verdict"]
    assert publication["status"] == "BLOCKED"
    assert publication["reason_code"] == "PUBLISH_LINEAGE_MISMATCH"


def test_committed_outcome_without_live_generation_is_blocked(tmp_path: Path) -> None:
    output = tmp_path / "Output"
    run_id = "committed_without_generation"
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_outcome.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "publish_status": "COMMITTED",
                "admission_verdict": "PASS",
                "authority_mode": "authoritative",
                "generation_id": run_id,
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path, run_id=run_id)
    publication = result["checks"]["publish_authority_verdict"]
    assert publication["status"] == "BLOCKED"
    assert publication["reason_code"] == "PUBLISH_LINEAGE_MISMATCH"
    assert "live generation missing or unreadable" in publication["lineage_violations"]


def test_publication_does_not_promote_diagnostic_only_to_decision_pass(tmp_path: Path) -> None:
    output = tmp_path / "Output"
    run_id = "diagnostic_run"
    run_dir = output / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_outcome.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "publish_status": "COMMITTED",
                "admission_verdict": "PASS",
                "authority_mode": "diagnostic",
                "generation_id": run_id,
            }
        ),
        encoding="utf-8",
    )
    generation = output / "generations" / run_id
    generation.mkdir(parents=True)
    (generation / "admission.json").write_text(
        json.dumps(
            {
                "publish_integrity_verdict": "PASS",
                "diagnostic_publish_verdict": "PASS",
                "decision_authority_verdict": "DIAGNOSTIC_ONLY",
                "generation_id": run_id,
            }
        ),
        encoding="utf-8",
    )
    (generation / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "authority": "DIAGNOSTIC_ONLY"}),
        encoding="utf-8",
    )
    (output / "live").symlink_to(Path("generations") / run_id, target_is_directory=True)

    result = evaluate_minimum_monitoring(tmp_path, run_id=run_id)
    publication = result["checks"]["publish_authority_verdict"]
    assert publication["status"] == "BLOCKED"
    assert publication["reason_code"] == "DECISION_AUTHORITY_BLOCKED"
    assert publication["publish_integrity_verdict"] == "PASS"
    assert publication["diagnostic_publish_verdict"] == "PASS"
    assert publication["decision_authority_verdict"] == "DIAGNOSTIC_ONLY"


def test_provider_monitor_reads_structured_provider_outcome(tmp_path: Path) -> None:
    _copy_provider_policy(tmp_path)
    manifest_dir = tmp_path / "Data" / "harvester" / "exports" / "latest" / "manifests"
    manifest_dir.mkdir(parents=True)
    manifest = manifest_dir / "cross_asset_daily_panel.manifest.json"

    manifest.write_text(
        json.dumps(
            {
                "release_id": "release_test",
                "provider_outcome": {
                    "status": "refreshed",
                    "provider": "yfinance",
                    "requested_count": 2,
                    "succeeded_count": 2,
                    "failed_count": 0,
                    "retrieved_at": "2026-08-12T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path)
    provider = result["checks"]["provider_failure"]
    assert provider["status"] == "PASS"
    assert provider["reason_code"] == "PROVIDER_RELEASE_AVAILABLE"
    assert provider["provider_status"] == "refreshed"
    assert provider["status_policy"]["decision"] == "ALLOW"


def test_provider_monitor_blocks_reused_after_provider_failure(tmp_path: Path) -> None:
    _copy_provider_policy(tmp_path)
    manifest_dir = tmp_path / "Data" / "harvester" / "exports" / "latest" / "manifests"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "cross_asset_daily_panel.manifest.json").write_text(
        json.dumps(
            {
                "release_id": "release_test",
                "provider_outcome": {
                    "status": "reused_after_provider_failure",
                    "provider": "yfinance",
                    "requested_count": 2,
                    "succeeded_count": 0,
                    "failed_count": 2,
                    "retrieved_at": "2026-08-12T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path)
    provider = result["checks"]["provider_failure"]
    assert provider["status"] == "BLOCKED"
    assert provider["reason_code"] == "REUSED_AFTER_PROVIDER_FAILURE"
    assert provider["status_policy"]["decision"] == "DENY"


def test_provider_monitor_requires_benchmark_outcome_in_complete_release(tmp_path: Path) -> None:
    _copy_provider_policy(tmp_path)
    manifest_dir = tmp_path / "Data" / "harvester" / "exports" / "latest" / "manifests"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "cross_asset_daily_panel.manifest.json").write_text(
        json.dumps(
            {
                "release_id": "release_test",
                "provider_outcome": {"status": "refreshed"},
            }
        ),
        encoding="utf-8",
    )
    (manifest_dir.parent / "catalog.json").write_text(
        json.dumps(
            {
                "datasets": [
                    {"dataset_id": "benchmark_panel"},
                    {"dataset_id": "cross_asset_daily_panel"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path)
    provider = result["checks"]["provider_failure"]
    assert provider["status"] == "BLOCKED"
    assert provider["reason_code"] == "MULTIPLE_PROVIDER_OUTCOMES"
    assert {item["dataset_id"] for item in provider["datasets"]} == {
        "benchmark_panel",
        "cross_asset_daily_panel",
    }


def test_provider_monitor_fails_closed_on_invalid_status_matrix(tmp_path: Path) -> None:
    _copy_provider_policy(tmp_path)
    policy_path = tmp_path / "configs" / "provider_release_policy.yaml"
    policy_path.write_text(
        policy_path.read_text(encoding="utf-8").replace(
            "    diagnostic: ALLOW", "    diagnostic: INVALID", 1
        ),
        encoding="utf-8",
    )
    manifest_dir = tmp_path / "Data" / "harvester" / "exports" / "latest" / "manifests"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "cross_asset_daily_panel.manifest.json").write_text(
        json.dumps(
            {
                "release_id": "release_test",
                "provider_outcome": {"status": "refreshed"},
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path)
    provider = result["checks"]["provider_failure"]
    assert provider["status"] == "BLOCKED"
    assert provider["reason_code"] == "PROVIDER_STATUS_POLICY_INVALID"
    assert provider["status_policy"] is None


def test_feedback_monitor_applies_provider_status_matrix(tmp_path: Path) -> None:
    _copy_provider_policy(tmp_path)
    feedback_dir = tmp_path / "Data" / "feedback_samples"
    feedback_dir.mkdir(parents=True)
    sample_id = "sample-reused-after-failure"
    lifecycle_events = [
        make_transition_event(
            sample_id=sample_id,
            from_state=None,
            to_state="candidate",
            owner="fixture",
            occurred_at="2026-08-12T00:00:00Z",
            evidence=["fixture"],
        ),
        make_transition_event(
            sample_id=sample_id,
            from_state="candidate",
            to_state="eligible",
            owner="fixture",
            occurred_at="2026-08-12T00:01:00Z",
            evidence=["review"],
        ),
    ]
    (feedback_dir / "sample_manifest.jsonl").write_text(
        json.dumps(
            {
                "sample_id": sample_id,
                "lifecycle_state": "eligible",
                "eligibility": "eligible",
                "allowed_to_affect_core_judgment": False,
                "golden": False,
                "calibration_set": False,
                "lifecycle_events": lifecycle_events,
                "provider_status": "reused_after_provider_failure",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate_minimum_monitoring(tmp_path)
    feedback = result["checks"]["feedback_sample_eligibility"]
    assert feedback["status"] == "BLOCKED"
    assert any(item.endswith(":provider_feedback_deny") for item in feedback["violations"])
