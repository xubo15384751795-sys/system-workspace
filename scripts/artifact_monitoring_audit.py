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
MONITORING_CLASSES = {
    "authoritative",
    "decision_adjacent_shadow",
    "research",
    "manual_on_demand",
    "archived_retire",
}
DEFAULT_REQUIRED_COVERAGE_CLASSES = {"authoritative", "decision_adjacent_shadow"}
DEBT_BASELINE_REL = "governance/monitoring_coverage_debt_baseline.yaml"


def load_registry(root: Path) -> dict[str, Any]:
    path = root / "governance" / "daily_pipeline_registry.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_debt_baseline(root: Path) -> dict[str, Any]:
    """Load accepted required_coverage_gap paths (empty if missing)."""
    path = root / DEBT_BASELINE_REL
    if not path.is_file():
        return {
            "schema_version": "monitoring_coverage_debt_baseline.v1",
            "paths": [],
            "missing": True,
        }
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {
            "schema_version": "monitoring_coverage_debt_baseline.v1",
            "paths": [],
            "missing": True,
            "error": "unreadable",
        }
    paths = [str(p) for p in (raw.get("paths") or []) if str(p).strip()]
    return {
        "schema_version": str(raw.get("schema_version") or "monitoring_coverage_debt_baseline.v1"),
        "as_of": raw.get("as_of"),
        "review_by": raw.get("review_by"),
        "owner": raw.get("owner"),
        "paths": paths,
        "missing": False,
    }


def diff_coverage_gaps_against_baseline(
    gaps: list[dict[str, Any]],
    baseline_paths: list[str],
) -> dict[str, Any]:
    """Split required gaps into baselined / new / cleared."""
    current = {str(g.get("path")) for g in gaps if g.get("path")}
    accepted = set(baseline_paths)
    new_paths = sorted(current - accepted)
    cleared_paths = sorted(accepted - current)
    baselined = sorted(current & accepted)
    by_path = {str(g.get("path")): g for g in gaps if g.get("path")}
    return {
        "baseline_path_count": len(accepted),
        "current_gap_count": len(current),
        "baselined_count": len(baselined),
        "new_gap_count": len(new_paths),
        "cleared_count": len(cleared_paths),
        "new_gaps": [by_path[p] for p in new_paths if p in by_path],
        "cleared_paths": cleared_paths,
        "baselined_paths": baselined,
    }


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


def monitoring_classification_config(registry: dict[str, Any]) -> dict[str, Any]:
    config = registry.get("monitoring_classification", {}) or {}
    required = {
        str(item)
        for item in (config.get("required_coverage_classes") or sorted(DEFAULT_REQUIRED_COVERAGE_CLASSES))
    }
    rules = [dict(rule) for rule in (config.get("rules") or []) if isinstance(rule, dict)]
    return {"required_coverage_classes": required, "rules": rules}


def classify_monitoring_path(path: str, registry: dict[str, Any]) -> dict[str, Any]:
    """Assign a P0-4 monitoring class + owner. First matching rule wins."""
    config = monitoring_classification_config(registry)
    for rule in config["rules"]:
        pattern = str(rule.get("pattern") or "")
        if not pattern or not matches_pattern(path, pattern):
            continue
        klass = str(rule.get("class") or "unclassified")
        owner = rule.get("owner")
        return {
            "path": path,
            "class": klass if klass in MONITORING_CLASSES else "unclassified",
            "owner": str(owner) if owner else None,
            "matched_rule": pattern,
        }
    return {
        "path": path,
        "class": "unclassified",
        "owner": None,
        "matched_rule": None,
    }


def classify_blind_spots(paths: list[str], registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [classify_monitoring_path(path, registry) for path in paths]


def required_coverage_gaps(
    classified: list[dict[str, Any]],
    registry: dict[str, Any],
) -> list[dict[str, Any]]:
    required = monitoring_classification_config(registry)["required_coverage_classes"]
    return [
        {
            "path": row["path"],
            "class": row["class"],
            "owner": row["owner"],
            "kind": "required_coverage_gap",
        }
        for row in classified
        if row["class"] in required
    ]


def unresolved_blind_spots(classified: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blind spots that lack a valid class or owner."""
    return [
        row
        for row in classified
        if row["class"] == "unclassified" or not row.get("owner")
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
    """Compare Learning Hub ingest sources to the event ledger mtime.

    Only ``Output/system_learning/**`` event/runtime artifacts count toward
    ``SOURCE_AHEAD_OF_LEDGER``. Operator notes (``.cursor/checkpoints``,
    ``governance/open_threads.yaml``) are not ledger ingest inputs — treating
    them as sources made nightly ``--strict`` fail whenever an agent wrote a
    checkpoint.
    """
    ledger = root / "Data" / "system_learning" / "ledgers" / "system_event_ledger.parquet"
    sources = []
    for pattern in (
        "Output/system_learning/runtime/records_*.jsonl",
        "Output/system_learning/events/*.jsonl",
        "Output/system_learning/routing_decisions/*.yaml",
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
    classified = classify_blind_spots(blind_spot_paths, registry)
    coverage_gaps = required_coverage_gaps(classified, registry)
    baseline = load_debt_baseline(root)
    gap_diff = diff_coverage_gaps_against_baseline(coverage_gaps, baseline.get("paths") or [])
    unresolved = unresolved_blind_spots(classified)
    content = non_daily_content_checks(root, registry, now)
    matrix = monitoring_matrix(root, registry)
    source_lag = learning_hub_source_lag(root)
    stale_or_missing = sum(row["status"] in {"MISSING", "STALE_CONTENT"} for row in content)
    no_content_clock = sum(row["status"] == "NO_CONTENT_CLOCK" for row in content)
    classification_fail = bool(coverage_gaps or unresolved)
    report = {
        "schema_version": "artifact_monitoring_audit.v4",
        "generated_at": now.isoformat(),
        "status": "FAIL"
        if contracts
        or stale_or_missing
        or no_content_clock
        or classification_fail
        or source_lag.get("status") in {"MISSING_LEDGER", "SOURCE_AHEAD_OF_LEDGER"}
        else "PASS",
        "weekly_contract_violations": contracts,
        "weekly_content_checks": content,
        "monitoring_blind_spots": blind_spots,
        "monitoring_blind_spot_classifications": classified,
        "required_coverage_gaps": coverage_gaps,
        "coverage_debt_baseline": {
            "path": DEBT_BASELINE_REL,
            "as_of": baseline.get("as_of"),
            "review_by": baseline.get("review_by"),
            "owner": baseline.get("owner"),
            "missing": bool(baseline.get("missing")),
            **{k: gap_diff[k] for k in (
                "baseline_path_count",
                "current_gap_count",
                "baselined_count",
                "new_gap_count",
                "cleared_count",
            )},
        },
        "new_required_coverage_gaps": gap_diff["new_gaps"],
        "cleared_coverage_debt_paths": gap_diff["cleared_paths"],
        "unresolved_monitoring_blind_spots": unresolved,
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
            "required_coverage_gap_count": len(coverage_gaps),
            "new_required_coverage_gap_count": gap_diff["new_gap_count"],
            "cleared_coverage_debt_count": gap_diff["cleared_count"],
            "unresolved_monitoring_blind_spot_count": len(unresolved),
            "classified_monitoring_blind_spot_count": len(classified),
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
        f"- Required coverage gaps (authoritative / decision-adjacent): {summary.get('required_coverage_gap_count', 0)}",
        f"- New gaps vs debt baseline (regression): {summary.get('new_required_coverage_gap_count', 0)}",
        f"- Cleared debt paths since baseline: {summary.get('cleared_coverage_debt_count', 0)}",
        f"- Unresolved (unclassified / ownerless) blind spots: {summary.get('unresolved_monitoring_blind_spot_count', 0)}",
        "",
        "## New coverage gaps (vs baseline)",
        "",
    ]
    new_gaps = report.get("new_required_coverage_gaps") or []
    lines.extend(
        f"- `{row.get('path')}` → `{row.get('class')}` (owner: {row.get('owner') or 'none'})"
        for row in new_gaps[:40]
    )
    if not new_gaps:
        lines.append("- None")
    elif len(new_gaps) > 40:
        lines.append(f"- … {len(new_gaps) - 40} more")
    lines.extend(["", "## Monitoring blind spots", ""])
    lines.extend(
        f"- `{row['family']}`: {row['count']} uncovered artifact(s); examples: "
        + ", ".join(f"`{path}`" for path in row["examples"][:3])
        for row in report["monitoring_blind_spots"]
    )
    if not report["monitoring_blind_spots"]:
        lines.append("- None")
    lines.extend(["", "## Blind spot classifications", ""])
    classifications = report.get("monitoring_blind_spot_classifications") or []
    lines.extend(
        f"- `{row['path']}` → `{row['class']}` (owner: {row.get('owner') or 'none'})"
        for row in classifications[:40]
    )
    if not classifications:
        lines.append("- None")
    elif len(classifications) > 40:
        lines.append(f"- … {len(classifications) - 40} more")
    return "\n".join(lines) + "\n"


def strict_exit_nonzero(report: dict[str, Any]) -> bool:
    """Whether ``--strict`` should fail the pipeline step.

    Report ``status`` may still be FAIL when there are baselined coverage gaps
    or stale on_demand artifacts — that debt is visible in the JSON/MD for the
    supervisor. Nightly ``--strict`` trips only on *actionable* breaks:
    contract violations, ownerless/unclassified blind spots, learning-hub
    source/ledger lag, or **new** required coverage gaps beyond the debt
    baseline.
    """
    if report.get("weekly_contract_violations"):
        return True
    if report.get("unresolved_monitoring_blind_spots"):
        return True
    lag = report.get("learning_hub_source_lag") or {}
    if lag.get("status") in {"MISSING_LEDGER", "SOURCE_AHEAD_OF_LEDGER"}:
        return True
    if report.get("new_required_coverage_gaps"):
        return True
    return False


def write_debt_baseline(root: Path, gaps: list[dict[str, Any]]) -> Path:
    """Snapshot current required gaps into the committed debt baseline."""
    path = root / DEBT_BASELINE_REL
    ensure_dir(path.parent)
    paths = sorted({str(g.get("path")) for g in gaps if g.get("path")})
    doc = {
        "schema_version": "monitoring_coverage_debt_baseline.v1",
        "as_of": datetime.now(UTC).date().isoformat(),
        "review_by": "2026-09-30",
        "owner": "Learning Hub",
        "accountable": "operator",
        "note": (
            "Known required_coverage_gaps accepted as monitoring debt. "
            "artifact_monitoring_audit --strict fails only on gaps NOT listed here "
            "(plus contract/unresolved/ledger breaks). Shrink this list when monitors "
            "are added; do not grow it without a routing decision."
        ),
        "paths": paths,
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help=f"Rewrite {DEBT_BASELINE_REL} from current required_coverage_gaps and exit 0.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    report = build_report(root)
    if args.write_baseline:
        out = write_debt_baseline(root, report.get("required_coverage_gaps") or [])
        print(f"Wrote debt baseline ({report['summary']['required_coverage_gap_count']} paths): {out}")
        return 0
    output_dir = root / "Output" / "system_learning" / "latest"
    ensure_dir(output_dir)
    write_json(output_dir / "monitoring_coverage.json", report)
    (output_dir / "monitoring_coverage.md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Monitoring coverage: {report['status']} {report['summary']}")
        debt = report.get("coverage_debt_baseline") or {}
        print(
            f"Coverage debt: baselined={debt.get('baselined_count', 0)} "
            f"new={debt.get('new_gap_count', 0)} cleared={debt.get('cleared_count', 0)}"
        )
    return 1 if args.strict and strict_exit_nonzero(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
