"""Read-only minimum operational monitoring contract for the default path.

The monitor reports evidence; it never changes a pointer, grants authority, or
turns a missing artifact into PASS.  It is intentionally small and explicit so
WS5/M8 can consume one structured result for provider failure, publication and
authority, Learning Hub watermark, notification deduplication, lineage, and
feedback eligibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from system_runtime.feedback_lifecycle import (
    validate_golden_adjudication,
    validate_lifecycle_events,
)
from system_runtime.provider_status import (
    PROVIDER_STATUSES,
    ProviderStatusPolicyError,
    provider_status_policy,
)

MONITOR_IDS = (
    "provider_failure",
    "publish_authority_verdict",
    "learning_hub_source_watermark",
    "notification_dedup",
    "alert_to_run_release_generation_lineage",
    "feedback_sample_eligibility",
)
_UNSAFE_FEEDBACK_DECISIONS = frozenset(
    {"WATCH", "WATCH_ONLY", "ACTIVE_WATCH", "RESEARCH_REVIEW"}
)
_UNSAFE_FEEDBACK_STATES = frozenset({"DEGRADED", "INSUFFICIENT_COVERAGE"})


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def notification_dedup_key(
    *,
    run_id: str,
    status: str,
    failed_steps: list[str],
    warnings: list[str],
    outcome: dict[str, Any] | None,
    provider_status: str | None = None,
) -> str:
    """Return a stable key for one root-cause alert state.

    Run/release/generation identities are deliberately excluded.  They belong
    in the alert lineage, but including them would make every repeated daily
    observation look like a new incident and defeat notification deduplication.
    """
    payload = {
        "status": status,
        "failed_steps": sorted(str(item) for item in failed_steps),
        "warnings": sorted(str(item) for item in warnings),
        "outcome": {
            key: (outcome or {}).get(key)
            for key in (
                "admission_verdict",
                "publish_status",
                "authority_mode",
                "reason_codes",
                "provider_status",
                "provider_cache_within_grace",
            )
        },
    }
    if provider_status:
        payload["provider_status"] = str(provider_status).strip().lower()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def release_identity(root: Path) -> dict[str, Any]:
    candidates = [
        root
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "catalog.json",
        root
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "manifests"
        / "cross_asset_daily_panel.manifest.json",
    ]
    for path in candidates:
        payload = _read_json(path)
        if not payload:
            continue
        release_id = (
            payload.get("release_id")
            or payload.get("release")
            or payload.get("release_name")
            or payload.get("vintage")
        )
        if release_id:
            return {"release_id": str(release_id), "path": str(path)}
    return {"release_id": None, "path": None}


def _provider_failure_for_manifest(
    root: Path,
    manifest: Path,
    dataset_id: str,
) -> dict[str, Any]:
    payload = _read_json(manifest)
    if not payload:
        return {
            "dataset_id": dataset_id,
            "status": "MISSING",
            "reason_code": "MISSING_PROVIDER_MANIFEST",
            "manifest": str(manifest),
        }
    provider_outcome = payload.get("provider_outcome")
    if not isinstance(provider_outcome, dict):
        provider_outcome = {}
    provider_status = payload.get("provider_status")
    if not isinstance(provider_status, dict):
        provider_status = {}
    all_failed = bool(
        payload.get("all_providers_failed")
        or provider_status.get("all_failed")
        or provider_outcome.get("status")
        in {"provider_failed_no_acceptable_fallback", "all_failed"}
        or payload.get("status") == "failed"
    )
    status = str(
        provider_outcome.get("status")
        or provider_status.get("status")
        or payload.get("status")
        or "unknown"
    ).lower()
    status_policy: dict[str, str] | None = None
    if status in PROVIDER_STATUSES:
        try:
            status_policy = provider_status_policy(status, root=root)
        except ProviderStatusPolicyError as exc:
            return {
                "status": "BLOCKED",
                "reason_code": "PROVIDER_STATUS_POLICY_INVALID",
                "provider_status": status,
                "status_policy": None,
                "policy_error": str(exc),
                "release_id": release_identity(root).get("release_id"),
                "manifest": str(manifest),
            }
    if all_failed:
        verdict = "FAIL"
        reason = "ALL_PROVIDERS_FAILED"
    elif status == "reused_after_provider_failure":
        verdict = "BLOCKED"
        reason = "REUSED_AFTER_PROVIDER_FAILURE"
    elif status == "provider_failed_no_acceptable_fallback":
        verdict = "FAIL"
        reason = "PROVIDER_FAILED_NO_ACCEPTABLE_FALLBACK"
    elif status in {"partial_provider_success", "reused_same_content"}:
        verdict = "WARN"
        reason = "DEGRADED_PROVIDER_OUTCOME"
    elif status == "no_release_expected":
        verdict = "PASS"
        reason = "NO_RELEASE_EXPECTED"
    elif status == "environmentally_blocked":
        verdict = "BLOCKED"
        reason = "ENVIRONMENTALLY_BLOCKED"
    elif status in {"refreshed", "success", "accepted", "finalized"}:
        verdict = "PASS"
        reason = "PROVIDER_RELEASE_AVAILABLE"
    else:
        verdict = "BLOCKED"
        reason = "UNKNOWN_PROVIDER_OUTCOME"
    return {
        "dataset_id": dataset_id,
        "status": verdict,
        "reason_code": reason,
        "provider_status": status,
        "status_policy": status_policy,
        "release_id": release_identity(root).get("release_id"),
        "manifest": str(manifest),
    }


def _provider_failure(root: Path) -> dict[str, Any]:
    """Evaluate every provider-backed dataset in a complete latest release."""
    manifests_root = (
        root / "Data" / "harvester" / "exports" / "latest" / "manifests"
    )
    manifest_specs = [
        (
            "cross_asset_daily_panel",
            manifests_root / "cross_asset_daily_panel.manifest.json",
        )
    ]
    catalog = _read_json(root / "Data" / "harvester" / "exports" / "latest" / "catalog.json")
    dataset_ids = {
        str(item.get("dataset_id"))
        for item in catalog.get("datasets", [])
        if isinstance(item, dict) and item.get("dataset_id")
    }
    benchmark_manifest = manifests_root / "benchmark_panel.manifest.json"
    if "benchmark_panel" in dataset_ids or benchmark_manifest.exists():
        manifest_specs.insert(0, ("benchmark_panel", benchmark_manifest))

    outcomes = [
        _provider_failure_for_manifest(root, manifest, dataset_id)
        for dataset_id, manifest in manifest_specs
    ]
    if len(outcomes) == 1:
        return outcomes[0]

    severity = {"PASS": 0, "WARN": 1, "INCOMPLETE": 2, "MISSING": 2, "BLOCKED": 2, "FAIL": 3}
    worst = max(outcomes, key=lambda value: severity.get(str(value.get("status")), 2))
    combined = dict(worst)
    reason_codes = sorted({str(value.get("reason_code")) for value in outcomes})
    provider_statuses = sorted({str(value.get("provider_status")) for value in outcomes})
    combined["datasets"] = outcomes
    combined["reason_codes"] = reason_codes
    combined["provider_statuses"] = provider_statuses
    if len(reason_codes) > 1:
        combined["reason_code"] = "MULTIPLE_PROVIDER_OUTCOMES"
    if len(provider_statuses) > 1:
        combined["provider_status"] = "mixed"
        combined["status_policy"] = None
    if combined["status"] in {"MISSING", "INCOMPLETE"}:
        combined["status"] = "BLOCKED"
    return combined


def _run_id_from_pointers(output: Path) -> str | None:
    for pointer in (
        output / "live" / "latest_run_id.txt",
        output / "current" / "latest_run_id.txt",
    ):
        if pointer.is_file():
            value = pointer.read_text(encoding="utf-8").strip()
            if value:
                return value
    return None


def _normalize_authority(value: Any) -> str | None:
    """Normalize run-level and admission-level authority vocabularies."""
    if value is None:
        return None
    normalized = str(value).strip()
    aliases = {
        "authoritative": "ALLOW",
        "allow": "ALLOW",
        "diagnostic": "DIAGNOSTIC_ONLY",
        "diagnostic_only": "DIAGNOSTIC_ONLY",
        "block": "BLOCK",
        "blocked": "BLOCK",
    }
    return aliases.get(normalized.lower(), normalized.upper())


def _publication(root: Path, output: Path, run_id: str | None) -> dict[str, Any]:
    resolved_run_id = run_id or _run_id_from_pointers(output)
    run_outcome = (
        _read_json(output / "runs" / resolved_run_id / "run_outcome.json")
        if resolved_run_id
        else {}
    )
    live = output / "live"
    generation = live.resolve(strict=False) if live.is_symlink() else None
    admission = _read_json(generation / "admission.json") if generation else {}
    manifest = _read_json(generation / "manifest.json") if generation else {}

    if not run_outcome and not admission and not manifest:
        return {
            "status": "MISSING",
            "reason_code": "MISSING_PUBLISH_EVIDENCE",
            "run_id": resolved_run_id,
        }

    # A committed outcome is not sufficient on its own.  The outcome, the
    # admission token, the generation manifest, and the selected pointer must
    # identify one run; otherwise an old PASS can be paired with a different
    # live generation.
    id_sources = {
        "requested_run_id": resolved_run_id,
        "run_outcome_run_id": run_outcome.get("run_id"),
        "run_outcome_generation_id": run_outcome.get("generation_id"),
        "manifest_run_id": manifest.get("run_id"),
        "admission_generation_id": admission.get("generation_id"),
    }
    present_ids = {
        name: str(value)
        for name, value in id_sources.items()
        if value not in (None, "")
    }
    lineage_violations: list[str] = []
    if run_outcome and not id_sources["run_outcome_run_id"]:
        lineage_violations.append("run_outcome: run_id missing")
    if admission and not id_sources["admission_generation_id"]:
        lineage_violations.append("admission: generation_id missing")
    if manifest and not id_sources["manifest_run_id"]:
        lineage_violations.append("manifest: run_id missing")
    unique_ids = set(present_ids.values())
    if len(unique_ids) > 1:
        lineage_violations.append(f"run/generation ids disagree: {present_ids}")
    if resolved_run_id:
        mismatched = {
            name: value
            for name, value in present_ids.items()
            if name != "requested_run_id" and value != str(resolved_run_id)
        }
        if mismatched:
            lineage_violations.append(
                f"run/generation ids do not match selected run: {mismatched}"
            )
    expected_release_id = release_identity(root).get("release_id")
    if expected_release_id:
        release_sources = {
            "run_outcome": run_outcome.get("release_id"),
            "admission": admission.get("release_id"),
            "manifest": manifest.get("release_id"),
        }
        for source, value in release_sources.items():
            if value in (None, ""):
                lineage_violations.append(f"{source}: release_id missing")
            elif str(value) != str(expected_release_id):
                lineage_violations.append(
                    f"{source}: release_id={value!r} != selected={expected_release_id!r}"
                )
        artifact_release_ids = admission.get("artifact_release_ids") or manifest.get(
            "artifact_release_ids", {}
        )
        if isinstance(artifact_release_ids, dict):
            for artifact, value in artifact_release_ids.items():
                if str(value) != str(expected_release_id):
                    lineage_violations.append(
                        f"{artifact}: release_id={value!r} != selected={expected_release_id!r}"
                    )
    if generation is None or not generation.is_dir():
        lineage_violations.append("live generation missing or unreadable")
    if generation is not None and not admission:
        lineage_violations.append("generation admission.json missing or unreadable")
    if generation is not None and not manifest:
        lineage_violations.append("generation manifest.json missing or unreadable")

    publish_status = run_outcome.get("publish_status")
    integrity_verdict = (
        admission.get("publish_integrity_verdict")
        or admission.get("integrity_verdict")
        or ("PASS" if run_outcome.get("admission_verdict") == "PASS" else None)
    )
    diagnostic_verdict = (
        admission.get("diagnostic_publish_verdict")
        or admission.get("diagnostic_verdict")
        or ("PASS" if publish_status == "COMMITTED" else None)
    )
    authority = _normalize_authority(
        admission.get("decision_authority_verdict")
        or admission.get("authority_verdict")
        or run_outcome.get("authority_mode")
    )
    manifest_authority = _normalize_authority(manifest.get("authority"))
    if authority and manifest_authority and authority != manifest_authority:
        lineage_violations.append(
            f"authority mismatch: admission={authority} manifest={manifest_authority}"
        )
    authority = authority or manifest_authority
    if admission:
        publish_status = publish_status or (
            "COMMITTED" if integrity_verdict == "PASS" else None
        )
    generation_id = (
        manifest.get("run_id")
        or admission.get("generation_id")
        or run_outcome.get("generation_id")
    )
    canonical_lineage = admission.get("canonical_lineage")
    if not isinstance(canonical_lineage, dict):
        canonical_lineage = None
    integrity_pass = publish_status == "COMMITTED" and integrity_verdict == "PASS"
    diagnostic_pass = diagnostic_verdict == "PASS"
    decision_allowed = authority == "ALLOW"
    if lineage_violations:
        status = "BLOCKED"
        reason_code = "PUBLISH_LINEAGE_MISMATCH"
    elif not integrity_pass:
        status = "BLOCKED"
        reason_code = "PUBLISH_INTEGRITY_BLOCKED"
    elif not diagnostic_pass:
        status = "BLOCKED"
        reason_code = "DIAGNOSTIC_PUBLISH_BLOCKED"
    elif not decision_allowed:
        status = "BLOCKED"
        reason_code = "DECISION_AUTHORITY_BLOCKED"
    else:
        status = "PASS"
        reason_code = "PUBLISH_AUTHORITY_RECORDED"
    return {
        "status": status,
        "reason_code": reason_code,
        "run_id": resolved_run_id or next(iter(unique_ids), None),
        "publish_status": publish_status,
        "admission_verdict": integrity_verdict,
        "publish_integrity_verdict": integrity_verdict,
        "diagnostic_publish_verdict": diagnostic_verdict,
        "decision_authority_verdict": authority,
        "authority": authority,
        "release_id": expected_release_id,
        "generation_id": generation_id,
        # SYS-21 reader dual-read context; never used to derive status.
        "canonical_lineage": canonical_lineage,
        "lineage_violations": lineage_violations,
    }


def _learning_hub_watermark(root: Path) -> dict[str, Any]:
    ledger = root / "Data" / "system_learning" / "ledgers" / "system_event_ledger.parquet"
    source_paths: list[Path] = []
    for pattern in (
        "Output/system_learning/runtime/records_*.jsonl",
        "Output/system_learning/events/*.jsonl",
        "Output/system_learning/routing_decisions/*.yaml",
        ".cursor/checkpoints/*.md",
        "governance/open_threads.yaml",
    ):
        source_paths.extend(path for path in root.glob(pattern) if path.is_file())
    newest = max(source_paths, key=lambda path: path.stat().st_mtime) if source_paths else None
    if newest is None:
        return {"status": "MISSING", "reason_code": "MISSING_HUB_SOURCE"}
    if not ledger.is_file():
        return {"status": "MISSING", "reason_code": "MISSING_HUB_LEDGER", "source": str(newest)}
    lag_hours = (ledger.stat().st_mtime - newest.stat().st_mtime) / 3600
    return {
        "status": "PASS" if lag_hours >= 0 else "FAIL",
        "reason_code": "HUB_WATERMARK_CURRENT" if lag_hours >= 0 else "SOURCE_AHEAD_OF_LEDGER",
        "ledger_minus_source_hours": round(lag_hours, 2),
        "source": str(newest),
        "ledger": str(ledger),
    }


def _notification_dedup(output: Path) -> dict[str, Any]:
    path = output / "alerts" / "latest_alert.json"
    alert = _read_json(path)
    if not alert:
        return {"status": "MISSING", "reason_code": "MISSING_ALERT"}
    outcome = alert.get("outcome") if isinstance(alert.get("outcome"), dict) else None
    run_id = str(alert.get("run_id") or (outcome or {}).get("run_id") or "")
    key = alert.get("notification_dedup_key")
    expected = notification_dedup_key(
        run_id=run_id,
        status=str(alert.get("status") or ""),
        failed_steps=[str(item.get("step")) for item in alert.get("failed_steps", []) if isinstance(item, dict)],
        warnings=[str(item) for item in alert.get("warnings", [])],
        outcome=outcome,
        provider_status=str(alert.get("provider_status") or "") or None,
    )
    return {
        "status": "PASS" if run_id and key == expected else "BLOCKED",
        "reason_code": "NOTIFICATION_DEDUP_KEY_VALID" if run_id and key == expected else "INVALID_NOTIFICATION_DEDUP_KEY",
        "run_id": run_id,
        "alert": str(path),
    }


def _lineage(root: Path, output: Path, run_id: str | None) -> dict[str, Any]:
    alert = _read_json(output / "alerts" / "latest_alert.json")
    publication = _publication(root, output, run_id)
    release = release_identity(root)
    if not alert or not publication.get("run_id"):
        return {"status": "MISSING", "reason_code": "MISSING_ALERT_OR_RUN"}
    alert_run = alert.get("run_id") or (alert.get("outcome") or {}).get("run_id")
    alert_generation = alert.get("generation_id")
    generation_id = publication.get("generation_id")
    release_id = release.get("release_id")
    checks = {
        "run_id": bool(alert_run and alert_run == publication.get("run_id")),
        "release_id": bool(alert.get("release_id") and release_id and alert.get("release_id") == release_id),
        "generation_id": bool(
            generation_id
            and alert_generation
            and alert_generation == generation_id
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "reason_code": "ALERT_LINEAGE_COMPLETE" if all(checks.values()) else "ALERT_LINEAGE_INCOMPLETE",
        "checks": checks,
        "run_id": alert_run,
        "release_id": release_id,
        "generation_id": generation_id,
        "canonical_lineage": publication.get("canonical_lineage"),
    }


def _feedback_eligibility(root: Path) -> dict[str, Any]:
    path = root / "Data" / "feedback_samples" / "sample_manifest.jsonl"
    if not path.is_file():
        return {"status": "MISSING", "reason_code": "MISSING_FEEDBACK_MANIFEST"}
    samples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return {"status": "BLOCKED", "reason_code": "INVALID_FEEDBACK_RECORD"}
        if isinstance(value, dict):
            samples.append(value)
    if not samples:
        return {"status": "MISSING", "reason_code": "EMPTY_FEEDBACK_MANIFEST"}
    violations: list[str] = []
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "unknown")
        lifecycle_state = str(sample.get("lifecycle_state") or "") or None
        for violation in validate_lifecycle_events(
            sample_id,
            sample.get("lifecycle_events"),
            current_state=lifecycle_state,
        ):
            violations.append(f"{sample_id}:{violation}")
        # Cross-run reuse and future leakage invalidate the sample itself,
        # regardless of whether it has reached an eligible/calibration state.
        # Keep this outside the eligibility branch so candidate records cannot
        # hide contaminated provenance behind an ineligible label.
        if sample.get("cross_run") or sample.get("future_leak"):
            violations.append(f"{sample_id}:cross_run_or_future_leak")
        if "eligibility" not in sample or "lifecycle_state" not in sample:
            violations.append(f"{sample_id}:missing_eligibility")
            continue
        eligibility = str(sample.get("eligibility") or "").lower()
        if sample.get("allowed_to_affect_core_judgment") is True:
            violations.append(f"{sample_id}:core_judgment_authority_granted")
        if sample.get("golden") is True:
            adjudication = sample.get("golden_adjudication")
            if not adjudication:
                violations.append(f"{sample_id}:golden_without_adjudication")
            else:
                for violation in validate_golden_adjudication(adjudication):
                    violations.append(f"{sample_id}:golden_{violation}")
        if sample.get("calibration_set") is True and (
            eligibility != "calibration_set" or lifecycle_state != "calibration_set"
        ):
            violations.append(f"{sample_id}:calibration_state_mismatch")
        if eligibility in {"eligible", "calibration_set"}:
            # accepted is a lifecycle state, not a golden-set grant.  It may
            # remain calibration-eligible while awaiting separate calibration
            # admission and golden adjudication.
            if eligibility == "eligible" and lifecycle_state not in {
                "eligible",
                "reviewed",
                "accepted",
            }:
                violations.append(f"{sample_id}:invalid_lifecycle")
            if eligibility == "calibration_set" and lifecycle_state != "calibration_set":
                violations.append(f"{sample_id}:invalid_calibration_lifecycle")
            provider_outcome = sample.get("provider_outcome")
            provider_status = str(
                sample.get("provider_status")
                or (provider_outcome.get("status") if isinstance(provider_outcome, dict) else "")
                or ""
            ).strip().lower()
            if not provider_status:
                violations.append(f"{sample_id}:missing_provider_status_policy")
            else:
                try:
                    feedback_policy = provider_status_policy(provider_status, root=root)
                except ProviderStatusPolicyError:
                    violations.append(f"{sample_id}:invalid_provider_status_policy")
                else:
                    if feedback_policy["feedback"] != "ELIGIBLE_AFTER_REVIEW":
                        violations.append(
                            f"{sample_id}:provider_feedback_{feedback_policy['feedback'].lower()}"
                        )
            decision = str(sample.get("decision", "")).upper()
            sizing_mode = str(sample.get("sizing_mode", "")).upper()
            sample_validity = str(sample.get("sample_validity", "")).upper()
            if (
                sample.get("degraded")
                or decision in _UNSAFE_FEEDBACK_DECISIONS
                or sizing_mode == "HOLD_DEGRADED"
                or sample_validity in _UNSAFE_FEEDBACK_STATES
                or str(sample.get("authority_mode", "")).upper()
                in {"DIAGNOSTIC", "DIAGNOSTIC_ONLY"}
            ):
                violations.append(f"{sample_id}:unsafe_state")
        elif eligibility not in {"ineligible", "candidate", "deferred", "rejected"}:
            violations.append(f"{sample_id}:unknown_eligibility")
    return {
        "status": "PASS" if not violations else "BLOCKED",
        "reason_code": "FEEDBACK_ELIGIBILITY_EXPLICIT" if not violations else "FEEDBACK_ELIGIBILITY_VIOLATION",
        "sample_count": len(samples),
        "violations": violations[:20],
    }


def evaluate_minimum_monitoring(
    root: Path,
    *,
    output_root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate minimum operational monitors without writing any artifact."""
    output = output_root or root / "Output"
    checks = {
        "provider_failure": _provider_failure(root),
        "publish_authority_verdict": _publication(root, output, run_id),
        "learning_hub_source_watermark": _learning_hub_watermark(root),
        "notification_dedup": _notification_dedup(output),
        "alert_to_run_release_generation_lineage": _lineage(root, output, run_id),
        "feedback_sample_eligibility": _feedback_eligibility(root),
    }
    statuses = [str(value.get("status")) for value in checks.values()]
    if all(status == "PASS" for status in statuses):
        overall = "PASS"
    elif any(status in {"FAIL", "BLOCKED"} for status in statuses):
        overall = "BLOCKED"
    else:
        overall = "INCOMPLETE"
    return {
        "schema_version": "system.minimum_monitoring.v1",
        "checked_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "checks": checks,
        "monitor_ids": list(MONITOR_IDS),
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only minimum operational monitoring")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    result = evaluate_minimum_monitoring(args.root, output_root=args.output_root, run_id=args.run_id)
    print(json.dumps(result, indent=2))
    # Monitoring is a gate, not a report-only side channel: only a complete
    # PASS may be treated as successful by a shell/CI caller.  The evaluator
    # remains read-only and continues to expose the detailed status payload.
    return 0 if result.get("overall_status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "MONITOR_IDS",
    "evaluate_minimum_monitoring",
    "notification_dedup_key",
    "release_identity",
]
