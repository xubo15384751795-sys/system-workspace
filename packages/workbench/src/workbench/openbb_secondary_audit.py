from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Any


SCHEMA_VERSION = "workbench.openbb_secondary_audit.v1"
EVENT_TYPE = "openbb_secondary_audit"


@dataclass(frozen=True)
class AuditInputs:
    openbb_run_dir: Path
    deformation_run_dir: Path
    output_dir: Path
    events_dir: Path


def run_audit(inputs: AuditInputs) -> dict[str, Any]:
    openbb_manifest_path = inputs.openbb_run_dir / "run_manifest.json"
    deformation_model_run_path = _first_existing(
        inputs.deformation_run_dir / "model_run.json",
        inputs.deformation_run_dir / "run_manifest.json",
    )
    deformation_framework_output_path = _first_existing(
        inputs.deformation_run_dir / "framework_output.json",
        inputs.deformation_run_dir / "reports" / "dashboard_snapshot.json",
    )

    openbb_manifest = _read_json(openbb_manifest_path)
    deformation_model_run = _read_json(deformation_model_run_path) if deformation_model_run_path else {}
    deformation_framework_output = (
        _read_json(deformation_framework_output_path) if deformation_framework_output_path else {}
    )
    quality_report = _read_optional_json(_resolve_output_path(inputs.openbb_run_dir, openbb_manifest, "quality"))

    generated_at = _utc_now()
    openbb_run_id = str(openbb_manifest.get("run_id") or inputs.openbb_run_dir.name)
    deformation_run_id = str(
        deformation_model_run.get("run_id")
        or deformation_framework_output.get("run_id")
        or inputs.deformation_run_dir.name
    )
    compared_series = _compared_series(openbb_manifest, quality_report)
    findings = _findings(openbb_manifest, deformation_model_run, deformation_framework_output, quality_report)
    verdict = _verdict(findings)
    recommended_action = _recommended_action(verdict, findings)
    audit_id = _stable_id([openbb_run_id, deformation_run_id, generated_at, verdict])
    event_id = _stable_id(["learning-event", audit_id])

    audit = {
        "schema_version": SCHEMA_VERSION,
        "audit_id": audit_id,
        "generated_at": generated_at,
        "audit_mode": "observe_only",
        "openbb_probe_run_id": openbb_run_id,
        "deformation_run_id": deformation_run_id,
        "compared_series": compared_series,
        "verdict": verdict,
        "findings": findings,
        "recommended_action": recommended_action,
        "learning_hub_event_id": event_id,
        "source_paths": {
            "openbb_run_manifest": str(openbb_manifest_path),
            "deformation_model_run": str(deformation_model_run_path or ""),
            "deformation_framework_output": str(deformation_framework_output_path or ""),
            "openbb_quality_report": str(_resolve_output_path(inputs.openbb_run_dir, openbb_manifest, "quality") or ""),
        },
        "non_interference": {
            "deformation_input_written": False,
            "harvester_release_written": False,
            "openbb_imported_by_deformation": False,
            "allowed_outputs": [
                "Output/workbench/openbb_secondary_audits",
                "Output/system_learning/events",
            ],
        },
    }

    _write_audit(inputs.output_dir, audit)
    _append_event(inputs.events_dir, _learning_event(audit, event_id))
    return audit


def _findings(
    openbb_manifest: dict[str, Any],
    deformation_model_run: dict[str, Any],
    deformation_framework_output: dict[str, Any],
    quality_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    if openbb_manifest.get("kind") != "openbb_probe":
        findings.append(_finding("openbb_manifest_kind", "medium", "OpenBB run manifest is not an openbb_probe."))
    if openbb_manifest.get("status") not in {"success", "partial"}:
        findings.append(_finding("openbb_probe_status", "medium", "OpenBB probe did not complete successfully."))
    if not deformation_model_run and not deformation_framework_output:
        findings.append(_finding("deformation_output_missing", "high", "No Deformation protocol output was available."))

    input_validity = str(
        deformation_model_run.get("model_input_validity")
        or deformation_framework_output.get("model_input_validity")
        or ""
    )
    if input_validity == "incomplete":
        findings.append(
            _finding(
                "deformation_input_incomplete",
                "medium",
                "Deformation output declares incomplete model input validity.",
            )
        )

    quality_status = str((quality_report or {}).get("status") or (quality_report or {}).get("verdict") or "")
    if quality_report is None:
        findings.append(_finding("openbb_quality_absent", "low", "OpenBB probe has no machine quality report."))
    elif quality_status.lower() in {"fail", "failed", "error"}:
        findings.append(_finding("openbb_quality_failed", "high", "OpenBB quality report indicates failure."))

    if not findings:
        findings.append(_finding("audit_observed_no_exception", "info", "Observe-only audit found no protocol concern."))
    return findings


def _learning_event(audit: dict[str, Any], event_id: str) -> dict[str, Any]:
    severity = _event_severity(str(audit["verdict"]), audit["findings"])
    return {
        "event_id": event_id,
        "timestamp": audit["generated_at"],
        "subsystem": "workbench",
        "event_type": EVENT_TYPE,
        "severity": severity,
        "source_tool": "workbench.openbb_secondary_audit",
        "context_type": "audit",
        "confidence": "medium",
        "boundary_type": "secondary_audit_observe_only",
        "target_subsystem": "deformation",
        "related_paths": list(audit["source_paths"].values()),
        "governance_mode": "observe_only" if severity in {"info", "low"} else "manual_review_required",
        "run_id": audit["deformation_run_id"],
        "bundle_id": "",
        "payload": audit,
        "recommended_action": audit["recommended_action"],
        "source_report_path": str(_audit_path(audit)),
        "requires_manual_review": severity in {"medium", "high", "critical"},
    }


def _write_audit(output_dir: Path, audit: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{audit['audit_id']}.json"
    path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _append_event(events_dir: Path, event: dict[str, Any]) -> Path:
    events_dir.mkdir(parents=True, exist_ok=True)
    date = str(event["timestamp"])[:10]
    path = events_dir / f"openbb_secondary_audit_{date}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")
    return path


def _audit_path(audit: dict[str, Any]) -> Path:
    return _workspace_root() / "Output" / "workbench" / "openbb_secondary_audits" / f"{audit['audit_id']}.json"


def _compared_series(openbb_manifest: dict[str, Any], quality_report: dict[str, Any] | None) -> list[str]:
    values = [
        openbb_manifest.get("symbol"),
        openbb_manifest.get("series_id"),
        openbb_manifest.get("provider_series_id"),
    ]
    if quality_report:
        quality_series = quality_report.get("compared_series") or quality_report.get("series") or []
        if isinstance(quality_series, str):
            values.append(quality_series)
        else:
            values.extend(quality_series)
    return sorted({str(value) for value in values if value})


def _verdict(findings: list[dict[str, Any]]) -> str:
    severities = {str(item.get("severity")) for item in findings}
    if "critical" in severities or "high" in severities:
        return "fail"
    if "medium" in severities:
        return "warn"
    if "low" in severities:
        return "inconclusive"
    return "pass"


def _event_severity(verdict: str, findings: list[dict[str, Any]]) -> str:
    if verdict == "fail":
        return "high"
    if verdict == "warn":
        return "medium"
    if verdict == "inconclusive":
        return "low"
    if any(item.get("severity") == "info" for item in findings):
        return "info"
    return "low"


def _recommended_action(verdict: str, findings: list[dict[str, Any]]) -> str:
    if verdict == "pass":
        return "No action required; retain audit record for Learning Hub recurrence tracking."
    codes = ", ".join(str(item["code"]) for item in findings if item.get("severity") != "info")
    return f"Review observe-only OpenBB secondary audit findings before changing any production input path: {codes}."


def _finding(code: str, severity: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message}


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    return _read_json(path)


def _resolve_output_path(run_dir: Path, manifest: dict[str, Any], key: str) -> Path | None:
    output_paths = manifest.get("output_paths") or {}
    rel = output_paths.get(key)
    if not rel:
        return None
    path = run_dir / str(rel)
    try:
        path.resolve().relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"OpenBB output path escapes run directory: {rel}") from exc
    return path


def _stable_id(parts: list[Any]) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an observe-only OpenBB secondary audit.")
    parser.add_argument("--openbb-run-dir", type=Path, required=True)
    parser.add_argument("--deformation-run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("Output/workbench/openbb_secondary_audits"))
    parser.add_argument("--events-dir", type=Path, default=Path("Output/system_learning/events"))
    args = parser.parse_args(argv)

    audit = run_audit(
        AuditInputs(
            openbb_run_dir=args.openbb_run_dir,
            deformation_run_dir=args.deformation_run_dir,
            output_dir=args.output_dir,
            events_dir=args.events_dir,
        )
    )
    print(json.dumps({"audit_id": audit["audit_id"], "verdict": audit["verdict"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
