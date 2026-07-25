#!/usr/bin/env python3
"""Audit scheduled-artifact freshness contracts and unmonitored Data/Output files."""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts._runtime_io import ROOT, ensure_dir, write_json

DATE_STAMP = re.compile(r"(?:^|[_-])(?:19|20)\d{2}[-_]?[01]\d[-_]?[0-3]\d(?=[_.T-]|$)")
IMMUTABLE_PARTS = {"runs", "releases", "snapshots", "archive", "raw", "history"}
TIME_KEYS = ("generated_at", "completed_at", "recorded_at", "updated_at", "timestamp", "as_of_date", "date")
NON_DAILY_SCHEDULES = {"weekly", "monthly", "quarterly", "manual", "on_demand"}
MINIMUM_CADENCE_HOURS = {"weekly": 168, "monthly": 28 * 24, "quarterly": 90 * 24}


def load_registry(root: Path) -> dict[str, Any]:
    path = root / "governance" / "daily_pipeline_registry.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def active_steps(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(step_id): step
        for step_id, step in (registry.get("steps", {}) or {}).items()
        if isinstance(step, dict) and step.get("status", "active") not in {"archived", "inactive"}
    }


def non_daily_contract_violations(registry: dict[str, Any]) -> list[dict[str, Any]]:
    defaults = registry.get("_defaults", {}) or {}
    findings = []
    for step_id, step in active_steps(registry).items():
        schedule = step.get("schedule", defaults.get("schedule", "daily"))
        if schedule not in NON_DAILY_SCHEDULES:
            continue
        outputs = step.get("produces") or (step.get("contracts", {}) or {}).get("outputs")
        ttl = step.get("ttl_hours", defaults.get("ttl_hours"))
        if not outputs:
            findings.append({"step": step_id, "schedule": schedule, "kind": "non_daily_without_registered_output"})
        if not isinstance(ttl, (int, float)) or ttl <= 0:
            findings.append({"step": step_id, "schedule": schedule, "kind": "non_daily_without_positive_ttl"})
        elif schedule in MINIMUM_CADENCE_HOURS and ttl < MINIMUM_CADENCE_HOURS[schedule]:
            findings.append(
                {
                    "step": step_id,
                    "schedule": schedule,
                    "kind": "ttl_shorter_than_schedule",
                    "ttl_hours": ttl,
                    "minimum_hours": MINIMUM_CADENCE_HOURS[schedule],
                }
            )
    return findings


def weekly_contract_violations(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Compatibility alias; enforcement now covers every non-daily cadence."""
    return non_daily_contract_violations(registry)


def declared_outputs(registry: dict[str, Any]) -> list[dict[str, Any]]:
    defaults = registry.get("_defaults", {}) or {}
    rows = []
    for step_id, step in active_steps(registry).items():
        outputs = step.get("produces") or (step.get("contracts", {}) or {}).get("outputs") or []
        for output in outputs:
            rows.append(
                {
                    "step": step_id,
                    "pattern": str(output),
                    "schedule": step.get("schedule", defaults.get("schedule", "daily")),
                    "ttl_hours": step.get("ttl_hours", defaults.get("ttl_hours", 48)),
                }
            )
    return rows


def explicit_content_monitors(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "monitor": str(name),
            "pattern": str(config.get("path", "")),
            "owner_step": config.get("owner_step"),
            "decision_critical": bool(config.get("decision_critical", False)),
        }
        for name, config in (registry.get("content_freshness", {}) or {}).items()
        if isinstance(config, dict) and config.get("path")
    ]


def matches_pattern(relative_path: str, pattern: str) -> bool:
    clean = pattern.rstrip("/")
    if any(char in clean for char in "*?["):
        return fnmatch.fnmatch(relative_path, clean)
    return relative_path == clean or relative_path.startswith(f"{clean}/")


def inventory_candidates(root: Path) -> list[str]:
    candidates = []
    for base_name in ("Data", "Output"):
        base = root / base_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.name.startswith("."):
                continue
            relative = path.relative_to(root)
            if IMMUTABLE_PARTS.intersection(relative.parts) or any(DATE_STAMP.search(part) for part in relative.parts):
                continue
            candidates.append(relative.as_posix())
    return sorted(candidates)


def monitoring_blind_spots(root: Path, registry: dict[str, Any]) -> list[str]:
    patterns = [row["pattern"] for row in declared_outputs(registry)]
    patterns.extend(row["pattern"] for row in explicit_content_monitors(registry))
    return [path for path in inventory_candidates(root) if not any(matches_pattern(path, pattern) for pattern in patterns)]


def monitoring_matrix(root: Path, registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate the artifact x monitor coverage relation for meta-audit."""
    producers = declared_outputs(registry)
    monitors = explicit_content_monitors(registry)
    rows = []
    for path in inventory_candidates(root):
        producer_rows = [row for row in producers if matches_pattern(path, row["pattern"])]
        monitor_rows = [row for row in monitors if matches_pattern(path, row["pattern"])]
        # Non-daily producers are themselves compiled content monitors: their
        # registered TTL is evaluated by non_daily_content_checks below.
        compiled = [row for row in producer_rows if row["schedule"] in NON_DAILY_SCHEDULES]
        rows.append(
            {
                "artifact": path,
                "producer_steps": sorted({row["step"] for row in producer_rows}),
                "monitor_ids": sorted(
                    {str(row["monitor"]) for row in monitor_rows}
                    | {f"registry:{row['step']}" for row in compiled}
                ),
                "covered": bool(monitor_rows or compiled),
            }
        )
    return rows


def blind_spot_families(paths: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for path in paths:
        parts = Path(path).parts
        family = "/".join(parts[:2]) if len(parts) >= 2 else path
        grouped.setdefault(family, []).append(path)
    return [
        {"family": family, "count": len(items), "examples": items[:10]}
        for family, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


def resolve_artifact(root: Path, pattern: str) -> Path | None:
    clean = pattern.rstrip("/")
    matches = [path for path in root.glob(clean) if path.is_file()]
    direct = root / clean
    if direct.is_dir():
        matches.extend(path for path in direct.rglob("*") if path.is_file())
    if direct.is_file():
        matches.append(direct)
    return max(set(matches), key=lambda path: path.stat().st_mtime) if matches else None


def content_timestamp(path: Path) -> datetime | None:
    try:
        if path.suffix == ".json":
            return _timestamp_from_object(json.loads(path.read_text(encoding="utf-8")))
        if path.suffix == ".jsonl":
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for line in reversed(lines[-100:]):
                stamp = _timestamp_from_object(json.loads(line))
                if stamp:
                    return stamp
        if path.suffix == ".parquet":
            frame = pd.read_parquet(path)
            return _timestamp_from_frame(frame)
        if path.suffix == ".csv":
            return _timestamp_from_frame(pd.read_csv(path))
        if path.suffix.lower() in {".yaml", ".yml"}:
            return _timestamp_from_object(yaml.safe_load(path.read_text(encoding="utf-8")))
        if path.suffix.lower() in {".md", ".txt"}:
            text = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:80])
            match = re.search(r"(?im)(?:generated|updated|date|as[-_ ]of)\s*:?\s*\*{0,2}([^\n*]+)", text)
            if match:
                return _parse_timestamp(match.group(1).strip())
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return None


def _timestamp_from_object(value: Any) -> datetime | None:
    if isinstance(value, dict):
        for key in TIME_KEYS:
            if key in value:
                stamp = _parse_timestamp(value[key])
                if stamp:
                    return stamp
        for nested in value.values():
            stamp = _timestamp_from_object(nested)
            if stamp:
                return stamp
    return None


def _timestamp_from_frame(frame: pd.DataFrame) -> datetime | None:
    for key in TIME_KEYS:
        if key in frame.columns and not frame.empty:
            parsed = pd.to_datetime(frame[key], utc=True, errors="coerce").dropna()
            if not parsed.empty:
                return parsed.max().to_pydatetime()
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        stamp = pd.to_datetime(value, utc=True, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.to_pydatetime()


def non_daily_content_checks(root: Path, registry: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    checks = []
    for row in declared_outputs(registry):
        if row["schedule"] not in NON_DAILY_SCHEDULES or row["step"] == "monitoring_coverage_audit":
            continue
        artifact = resolve_artifact(root, row["pattern"])
        if artifact is None:
            status, age = "MISSING", None
        else:
            stamp = content_timestamp(artifact)
            if stamp is None:
                status, age = "NO_CONTENT_CLOCK", None
            else:
                age = round((now - stamp).total_seconds() / 3600, 1)
                status = "STALE_CONTENT" if age > float(row["ttl_hours"]) else "FRESH"
        checks.append({**row, "artifact": str(artifact) if artifact else None, "status": status, "content_age_hours": age})
    return checks


def weekly_content_checks(root: Path, registry: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Compatibility alias; checks now include manual/on-demand/monthly/quarterly."""
    return non_daily_content_checks(root, registry, now)


def learning_hub_source_lag(root: Path) -> dict[str, Any]:
    ledger = root / "Data" / "system_learning" / "ledgers" / "system_event_ledger.parquet"
    sources = []
    for pattern in (
        "Output/system_learning/runtime/records_*.jsonl",
        "Output/system_learning/events/*.jsonl",
        "Output/system_learning/routing_decisions/*.yaml",
        ".cursor/checkpoints/*.md",
        "governance/open_threads.yaml",
    ):
        sources.extend(path for path in root.glob(pattern) if path.is_file())
    newest_source = max(sources, key=lambda path: path.stat().st_mtime) if sources else None
    if newest_source is None:
        return {"status": "NO_SOURCES"}
    if not ledger.is_file():
        return {"status": "MISSING_LEDGER", "newest_source": str(newest_source)}
    lag_hours = (ledger.stat().st_mtime - newest_source.stat().st_mtime) / 3600
    return {
        "status": "PASS" if lag_hours >= 0 else "SOURCE_AHEAD_OF_LEDGER",
        "newest_source": str(newest_source),
        "ledger": str(ledger),
        "ledger_minus_source_hours": round(lag_hours, 2),
    }


def build_report(root: Path, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    registry = load_registry(root)
    contracts = non_daily_contract_violations(registry)
    blind_spot_paths = monitoring_blind_spots(root, registry)
    blind_spots = blind_spot_families(blind_spot_paths)
    content = non_daily_content_checks(root, registry, now)
    matrix = monitoring_matrix(root, registry)
    source_lag = learning_hub_source_lag(root)
    stale_or_missing = sum(row["status"] in {"MISSING", "STALE_CONTENT"} for row in content)
    no_content_clock = sum(row["status"] == "NO_CONTENT_CLOCK" for row in content)
    report = {
        "schema_version": "artifact_monitoring_audit.v2",
        "generated_at": now.isoformat(),
        "status": "FAIL"
        if contracts
        or stale_or_missing
        or no_content_clock
        or source_lag.get("status") in {"MISSING_LEDGER", "SOURCE_AHEAD_OF_LEDGER"}
        else "PASS",
        "weekly_contract_violations": contracts,
        "weekly_content_checks": content,
        "monitoring_blind_spots": blind_spots,
        "artifact_monitoring_matrix": matrix,
        "learning_hub_source_lag": source_lag,
        "summary": {
            "non_daily_contract_violation_count": len(contracts),
            "non_daily_stale_or_missing_count": stale_or_missing,
            "non_daily_no_content_clock_count": no_content_clock,
            # Compatibility keys for existing supervisor consumers.
            "weekly_contract_violation_count": len(contracts),
            "weekly_stale_or_missing_count": stale_or_missing,
            "weekly_no_content_clock_count": no_content_clock,
            "monitoring_blind_spot_count": len(blind_spot_paths),
            "monitoring_blind_spot_family_count": len(blind_spots),
            "monitoring_matrix_row_count": len(matrix),
        },
    }
    if report["status"] == "PASS" and (
        report["summary"]["weekly_stale_or_missing_count"]
        or report["summary"]["weekly_no_content_clock_count"]
        or report["summary"]["monitoring_blind_spot_count"]
    ):
        report["status"] = "WARN"
    return report


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Artifact Monitoring Coverage",
        "",
        f"Generated: {report['generated_at']}",
        f"Status: **{report['status']}**",
        "",
        f"- Non-daily contract violations: {summary['non_daily_contract_violation_count']}",
        f"- Non-daily stale or missing artifacts: {summary['non_daily_stale_or_missing_count']}",
        f"- Non-daily artifacts without a content clock: {summary['non_daily_no_content_clock_count']}",
        f"- Unmonitored current/durable artifacts: {summary['monitoring_blind_spot_count']}",
        "",
        "## Monitoring blind spots",
        "",
    ]
    lines.extend(
        f"- `{row['family']}`: {row['count']} uncovered artifact(s); examples: "
        + ", ".join(f"`{path}`" for path in row["examples"][:3])
        for row in report["monitoring_blind_spots"]
    )
    if not report["monitoring_blind_spots"]:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    report = build_report(root)
    output_dir = root / "Output" / "system_learning" / "latest"
    ensure_dir(output_dir)
    write_json(output_dir / "monitoring_coverage.json", report)
    (output_dir / "monitoring_coverage.md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Monitoring coverage: {report['status']} {report['summary']}")
    return 1 if args.strict and report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
