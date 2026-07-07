from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pandas as pd

from system_learning.cartography.layer_rules import (
    FORBIDDEN_IMPORT_RULES,
    HARVESTER_FORBIDDEN_TERMS,
    HARVESTER_PATH_TERMS,
    is_deformation_adapter,
    is_provider_warning_path,
    source_scope,
)
from system_learning.cartography.scanner import FileScan

OVERSIZED_FILE_LINES = 800
MODULE_GROWTH_MIN_LOC = 200
MODULE_GROWTH_RATIO = 1.5


def detect_drift(
    scans: list[FileScan],
    module_metrics: pd.DataFrame,
    dependency_edges: pd.DataFrame,
    previous_history: pd.DataFrame | None,
) -> tuple[pd.DataFrame, list[dict]]:
    violations: list[dict] = []
    violations.extend(detect_forbidden_imports(scans))
    violations.extend(detect_text_rule_violations(scans))
    violations.extend(detect_oversized_files(scans))
    violations.extend(detect_module_growth(module_metrics, previous_history))
    events = [system_event_from_violation(item) for item in violations]
    return pd.DataFrame(violations), events


def detect_forbidden_imports(scans: list[FileScan]) -> list[dict]:
    rows = []
    for scan in scans:
        if scan.kind != "python":
            continue
        scope = source_scope(scan.rel_path, scan.module)
        for rule in FORBIDDEN_IMPORT_RULES:
            if scope != rule.source_scope:
                continue
            for imported in scan.imports:
                if any(imported == forbidden or imported.startswith(f"{forbidden}.") for forbidden in rule.forbidden_imports):
                    rows.append(
                        violation(
                            "forbidden_dependency",
                            rule.severity,
                            scan,
                            f"{rule.name}: {scan.module} imports {imported}",
                            {"rule": rule.name, "import": imported},
                        )
                    )
    return rows


def detect_text_rule_violations(scans: list[FileScan]) -> list[dict]:
    rows = []
    for scan in scans:
        if scan.kind != "python":
            continue
        text = scan.path.read_text(encoding="utf-8", errors="replace")
        scope = source_scope(scan.rel_path, scan.module)
        if scope == "deformation" and not is_deformation_adapter(scan.rel_path):
            matches = [term for term in HARVESTER_PATH_TERMS if term in text]
            if matches:
                severity = "low" if context_type(scan) == "test_code" else "high"
                rows.append(
                    violation(
                        "architecture_drift",
                        severity,
                        scan,
                        "Deformation non-adapter module references Harvester raw/processed/corpus paths.",
                        {"matches": matches},
                        boundary_type="data_contract",
                    )
                )
        if scope == "harvester":
            matches = [term for term in HARVESTER_FORBIDDEN_TERMS if term in text]
            if matches:
                rows.append(
                    violation(
                        "architecture_drift",
                        "high",
                        scan,
                        "Harvester contains Deformation proxy or claim-registry terminology.",
                        {"matches": matches},
                        boundary_type="architecture_drift",
                    )
                )
        if is_provider_warning_path(scan.rel_path) and "provider" in text.lower():
            rows.append(
                violation(
                    "architecture_drift",
                    "medium",
                    scan,
                    "New provider-like code under Deformation data adapters/gateway should be reviewed.",
                    {"rule": "deformation_provider_warning"},
                    boundary_type="architecture_drift",
                )
            )
    return rows


def detect_oversized_files(scans: list[FileScan]) -> list[dict]:
    return [
        violation(
            "oversized_file",
            "medium",
            scan,
            f"File exceeds {OVERSIZED_FILE_LINES} lines.",
            {"lines": scan.lines},
            boundary_type="architecture_drift",
        )
        for scan in scans
        if scan.kind == "python" and scan.lines >= OVERSIZED_FILE_LINES
    ]


def detect_module_growth(module_metrics: pd.DataFrame, previous_history: pd.DataFrame | None) -> list[dict]:
    if previous_history is None or previous_history.empty or module_metrics.empty:
        return []
    latest_run = previous_history["run_id"].max() if "run_id" in previous_history.columns else None
    previous = previous_history[previous_history["run_id"] == latest_run] if latest_run else previous_history
    previous = previous[["directory", "loc"]].rename(columns={"loc": "previous_loc"})
    merged = module_metrics.merge(previous, on="directory", how="left")
    rows = []
    for _, row in merged.iterrows():
        previous_loc = row.get("previous_loc")
        if pd.isna(previous_loc) or previous_loc <= 0:
            continue
        growth = int(row["loc"]) - int(previous_loc)
        if growth >= MODULE_GROWTH_MIN_LOC and int(row["loc"]) >= int(previous_loc) * MODULE_GROWTH_RATIO:
            rows.append(
                {
                    "violation_type": "module_growth",
                    "severity": "medium",
                    "path": row["directory"],
                    "module": row["directory"],
                    "message": "Module directory grew abnormally compared with previous history.",
                    "details": {"previous_loc": int(previous_loc), "current_loc": int(row["loc"]), "growth": growth},
                    "source_tool": "codebase_cartographer",
                    "context_type": "production_code",
                    "confidence": "medium",
                    "boundary_type": "architecture_drift",
                    "target_subsystem": target_subsystem(str(row["directory"])),
                    "related_paths": [row["directory"]],
                    "governance_mode": "manual_review_required",
                }
            )
    return rows


def violation(
    kind: str,
    severity: str,
    scan: FileScan,
    message: str,
    details: dict,
    boundary_type: str = "import_boundary",
) -> dict:
    context = context_type(scan)
    confidence = confidence_for(context, severity)
    return {
        "violation_type": kind,
        "severity": severity,
        "path": scan.rel_path,
        "module": scan.module,
        "message": message,
        "details": details,
        "source_tool": "codebase_cartographer",
        "context_type": context,
        "confidence": confidence,
        "boundary_type": boundary_type,
        "target_subsystem": target_subsystem(scan.rel_path),
        "related_paths": [scan.rel_path],
        "governance_mode": governance_mode(severity, confidence),
    }


def system_event_from_violation(item: dict) -> dict:
    event_type = item["violation_type"]
    payload = dict(item)
    raw = json.dumps(payload, sort_keys=True)
    event_id = f"codebase-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"
    return {
        "event_id": event_id,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "subsystem": "codebase_cartographer",
        "event_type": event_type,
        "severity": item["severity"],
        "source_tool": item.get("source_tool", "codebase_cartographer"),
        "context_type": item.get("context_type", "unknown"),
        "confidence": item.get("confidence", "medium"),
        "boundary_type": item.get("boundary_type", ""),
        "target_subsystem": item.get("target_subsystem", ""),
        "related_paths": item.get("related_paths", [item.get("path", "")]),
        "governance_mode": item.get("governance_mode", "observe_only"),
        "run_id": "",
        "bundle_id": "",
        "payload": payload,
        "recommended_action": "Review architecture drift warning and approve any improvement before implementation.",
        "source_report_path": "reports/codebase/latest/architecture_drift.md",
        "requires_manual_review": item.get("governance_mode") in {"manual_review_required", "proposal_required", "blocker"},
    }


def context_type(scan: FileScan) -> str:
    lowered = scan.rel_path.lower()
    if "/tests/" in f"/{lowered}" or Path(lowered).name.startswith("test_"):
        return "test_code"
    if "/archive/" in f"/{lowered}":
        return "archive"
    if "/scripts/" in f"/{lowered}":
        return "script"
    if scan.kind == "docs":
        return "documentation"
    if "generated" in lowered:
        return "generated_file"
    return "production_code"


def confidence_for(context: str, severity: str) -> str:
    if context in {"test_code", "archive", "documentation", "generated_file"}:
        return "low"
    if context == "script" or severity == "medium":
        return "medium"
    return "high"


def governance_mode(severity: str, confidence: str) -> str:
    if severity == "critical":
        return "blocker"
    if severity == "high" and confidence == "high":
        return "proposal_required"
    if severity in {"medium", "high"}:
        return "manual_review_required"
    return "observe_only"


def target_subsystem(path: str) -> str:
    lowered = path.lower()
    if "structural deformation research system" in lowered:
        return "deformation"
    if "structural risk harvester" in lowered:
        return "harvester"
    if "/output/" in f"/{lowered}":
        return "output"
    return ""
