from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from system_runtime.paths import output_surface
from workbench.paths import workspace_root as _workspace_root

ROOT = _workspace_root()
POLICY_PATH = ROOT / "configs" / "freshness_policy.yaml"
HARVESTER_LATEST = ROOT / "Data" / "harvester" / "exports" / "latest"
DEFORMATION_LATEST = ROOT / "Output" / "deformation_runs" / "latest"
CURRENT = output_surface(ROOT, "current")

STATUSES = {"fresh", "acceptable_lag", "stale", "missing", "retired_or_unavailable"}

# A content clock cannot prove that the bytes were acquired successfully.  A
# release-level provider outcome is therefore an independent freshness gate.
# In particular, reusing an old panel after a provider outage must never look
# like a fresh release merely because the carried-forward rows are recent
# relative to the release timestamp.
_PROVIDER_BLOCKING_STATUSES = frozenset(
    {
        "unknown",
        "all_failed",
        "provider_failed_no_acceptable_fallback",
        "reused_after_provider_failure",
        "environmentally_blocked",
    }
)
_PROVIDER_WARNING_STATUSES = frozenset(
    {"partial_provider_success", "reused_same_content"}
)
_PROVIDER_PASS_STATUSES = frozenset(
    {"refreshed", "success", "accepted", "finalized", "no_release_expected"}
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, raising on missing or invalid."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return {str(key): value for key, value in payload.items()}


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Freshness policy must be a mapping: {path}")
    return {str(key): value for key, value in payload.items()}


def parse_timestamp(value: Any) -> pd.Timestamp | None:
    if value in {None, ""}:
        return None
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        return None
    return pd.Timestamp(stamp)


def parse_date(value: Any) -> pd.Timestamp | None:
    if value in {None, ""}:
        return None
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return None
    return pd.Timestamp(stamp).normalize()


def classify_lag(lag_days: int | None, frequency: str, policy: dict[str, Any]) -> str:
    if lag_days is None:
        return "missing"
    thresholds = policy.get("frequency_thresholds", {}).get(frequency) or policy.get("frequency_thresholds", {}).get("unknown", {})
    if lag_days <= int(thresholds.get("fresh_lag_days", 10)):
        return "fresh"
    if lag_days <= int(thresholds.get("acceptable_lag_days", 30)):
        return "acceptable_lag"
    return "stale"


def _validate_panel_shape_with_pandera(panel: pd.DataFrame) -> None:
    """Optional Pandera shape check for long-format evidence panels.

    Governance lag thresholds stay in freshness_policy.yaml; this only verifies
    the table columns used by lag classifiers. Missing Pandera is a no-op.
    """
    # Prefer date; tolerate catalogs that use observation_date.
    columns: list[str] = []
    if "date" in panel.columns:
        columns.append("date")
    elif "observation_date" in panel.columns:
        columns.append("observation_date")
    if "value" in panel.columns:
        columns.append("value")
    if not columns:
        return
    try:
        import pandera.pandas as pa
    except ImportError:
        return
    schema = pa.DataFrameSchema(
        {name: pa.Column(nullable=True) for name in columns},
        strict=False,
        coerce=False,
    )
    schema.validate(panel, lazy=True)


def series_matches(panel: pd.DataFrame, canonical_id: str) -> pd.Series:
    """Match canonical IDs against full IDs and provider-native IDs.

    Harvester panels can carry canonical slots such as CBOE:MOVE while keeping
    source_series_id as the provider-native symbol, for example VXTLT.
    """
    if panel.empty:
        return pd.Series(False, index=panel.index)
    mask = pd.Series(False, index=panel.index)
    if "series_id" in panel:
        series = panel["series_id"].astype(str)
        mask = mask | series.eq(canonical_id) | series.str.split(":", n=1).str[-1].eq(canonical_id)
    if "source_series_id" in panel:
        mask = mask | panel["source_series_id"].astype(str).eq(canonical_id)
    return mask


def build_release_freshness_manifest(
    release_dir: Path | None = None,
    *,
    policy_path: Path = POLICY_PATH,
    run_generated_at: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    release = (release_dir or HARVESTER_LATEST).resolve()
    policy = load_policy(policy_path)
    catalog = read_json(release / "catalog.json")
    panel_path, evidence_created_at = _resolve_panel_from_catalog(release, catalog)
    panel = pd.read_parquet(panel_path)
    _validate_panel_shape_with_pandera(panel)
    provider_outcomes = _resolve_provider_outcomes(release, catalog)
    indicators = []
    for series_id in policy.get("indicators", {}):
        indicators.append(_indicator_freshness(series_id, panel, policy, evidence_created_at))

    model_input_validity = _model_input_validity(indicators)
    provider_gate = _provider_gate(provider_outcomes)
    manifest = {
        "schema_version": "workbench.freshness_manifest.v1",
        "generated_at": utc_now(),
        "policy_path": str(policy_path.relative_to(ROOT)),
        "evidence_release_id": release.name,
        "run_id": run_id,
        "date_semantics": {
            "observation_date": "Indicator observation date from the frozen evidence panel.",
            "vintage_date": "Data vintage date recorded in the frozen evidence panel.",
            "evidence_created_at": "Harvester release/catalog creation timestamp.",
            "run_generated_at": "Model run package generation timestamp when available.",
        },
        "evidence_created_at": evidence_created_at,
        "run_generated_at": run_generated_at,
        "model_input_validity": model_input_validity,
        "provider_outcomes": provider_outcomes,
        "provider_gate": provider_gate,
        "gate_result": _gate_result(
            indicators,
            policy,
            model_input_validity,
            provider_outcomes=provider_outcomes,
        ),
        "indicators": indicators,
    }
    return manifest


def _resolve_provider_outcomes(
    release: Path,
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    """Read provider outcomes without deriving acquisition success from dates.

    Complete Harvester releases expose benchmark and cross-asset datasets
    whose provider outcomes are decision-relevant.  If either manifest lacks
    the outcome, return an explicit ``unknown`` record so freshness cannot
    report PASS from carried-forward bytes.  Lightweight historical fixtures
    that do not contain the cross-asset manifest remain date-only fixtures.
    """
    records: list[dict[str, Any]] = []
    datasets = catalog.get("datasets") if isinstance(catalog.get("datasets"), list) else []
    dataset_entries = [item for item in datasets if isinstance(item, dict)]
    if not dataset_entries:
        dataset_entries = [
            item
            for item in catalog.get("files", [])
            if isinstance(item, dict) and item.get("dataset_id")
        ]
    if not any(
        str(item.get("dataset_id") or "") == "cross_asset_daily_panel"
        for item in dataset_entries
    ):
        cross_asset_manifest = release / "manifests" / "cross_asset_daily_panel.manifest.json"
        if cross_asset_manifest.exists():
            dataset_entries.append(
                {
                    "dataset_id": "cross_asset_daily_panel",
                    "manifest_path": "manifests/cross_asset_daily_panel.manifest.json",
                }
            )

    complete_release = any(
        str(item.get("dataset_id") or "") == "cross_asset_daily_panel"
        for item in dataset_entries
    )
    required_provider_datasets = {"cross_asset_daily_panel"}
    if complete_release:
        required_provider_datasets.add("benchmark_panel")

    for entry in dataset_entries:
        dataset_id = str(entry.get("dataset_id") or "")
        manifest_ref = entry.get("manifest_path")
        if not dataset_id or not isinstance(manifest_ref, str):
            continue
        manifest_path = release / manifest_ref
        payload = read_json(manifest_path) if manifest_path.is_file() else {}
        outcome = payload.get("provider_outcome")
        if isinstance(outcome, dict) and outcome.get("status"):
            records.append(
                {
                    "dataset_id": dataset_id,
                    "status": str(outcome["status"]).strip().lower(),
                    "source": str(manifest_path.relative_to(release)),
                    "details": outcome,
                }
            )
        elif dataset_id in required_provider_datasets:
            records.append(
                {
                    "dataset_id": dataset_id,
                    "status": "unknown",
                    "reason_code": "UNKNOWN_PROVIDER_OUTCOME",
                    "source": str(manifest_path.relative_to(release)),
                }
            )

    # Bundle-style or release-level provider evidence may live directly in the
    # catalog.  Keep it in the same gate rather than creating a second rule.
    catalog_outcome = catalog.get("provider_outcome")
    if isinstance(catalog_outcome, dict) and catalog_outcome.get("status"):
        records.append(
            {
                "dataset_id": str(catalog.get("release_id") or "release"),
                "status": str(catalog_outcome["status"]).strip().lower(),
                "source": "catalog.json",
                "details": catalog_outcome,
            }
        )
    return records


def _provider_gate(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    for outcome in outcomes:
        status = str(outcome.get("status") or "unknown").strip().lower()
        dataset_id = str(outcome.get("dataset_id") or "release")
        message = f"{dataset_id} provider outcome is {status}"
        if status in _PROVIDER_BLOCKING_STATUSES or status not in (
            _PROVIDER_PASS_STATUSES | _PROVIDER_WARNING_STATUSES
        ):
            blockers.append(message)
        elif status in _PROVIDER_WARNING_STATUSES:
            warnings.append(message)
    status = "BLOCKED" if blockers else "WARN" if warnings else "PASS"
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "outcomes": outcomes,
    }


def _resolve_panel_from_catalog(release: Path, catalog: dict[str, Any]) -> tuple[Path, str | None]:
    """Locate the benchmark panel file regardless of catalog mode.

    Bundle-mode catalogs expose ``files[].role == "benchmark_panel"``.
    Dataset-mode catalogs expose ``datasets[].dataset_id`` with the
    canonical long-format panel published as ``official_panel`` (preferred)
    or ``benchmark_panel`` (legacy alias).  Wide-format dataset ids such as
    ``benchmark_panel_weekly`` are intentionally not selected here — freshness
    classification operates on the long-format observation schema.
    """
    if "files" in catalog:
        entry = next(
            (item for item in catalog.get("files", []) if item.get("role") == "benchmark_panel"),
            None,
        )
        if entry is None:
            raise FileNotFoundError(f"No benchmark_panel in {release / 'catalog.json'}")
        return release / entry["path"], catalog.get("created_at") or catalog.get("bundle_id")

    if "datasets" in catalog:
        for dataset_id in ("official_panel", "benchmark_panel"):
            entry = next(
                (item for item in catalog.get("datasets", []) if item.get("dataset_id") == dataset_id),
                None,
            )
            if entry is not None:
                evidence_created_at = catalog.get("finalized_at") or catalog.get("created_at")
                return release / entry["data_path"], evidence_created_at
        available = sorted(d.get("dataset_id", "") for d in catalog.get("datasets", []))
        raise FileNotFoundError(
            "dataset-mode catalog does not expose official_panel or benchmark_panel; "
            f"available: {available} (release={release})"
        )

    raise FileNotFoundError(f"unknown catalog mode for {release / 'catalog.json'}")


def write_release_freshness_manifest(release_dir: Path | None = None, **kwargs: Any) -> Path:
    release = (release_dir or HARVESTER_LATEST).resolve()
    manifest = build_release_freshness_manifest(release, **kwargs)
    path = release / "freshness_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def write_model_run_freshness_manifest(run_dir: Path | None = None, release_dir: Path | None = None) -> Path:
    run = (run_dir or DEFORMATION_LATEST).resolve()
    manifest = read_json(run / "run_manifest.json")
    release = (release_dir or (ROOT / "Data" / "harvester" / "exports" / str(manifest.get("harvester_release")))).resolve()
    freshness = build_release_freshness_manifest(
        release,
        run_generated_at=manifest.get("generated_at"),
        run_id=manifest.get("run_id"),
    )
    path = run / "freshness_manifest.json"
    path.write_text(json.dumps(freshness, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    manifest["freshness_manifest_path"] = "freshness_manifest.json"
    manifest["model_input_validity"] = freshness["model_input_validity"]
    manifest["freshness_gate_result"] = freshness["gate_result"]
    (run / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    _write_report_banner(run, freshness)
    return path


def _indicator_freshness(
    series_id: str,
    panel: pd.DataFrame,
    policy: dict[str, Any],
    evidence_created_at: str | None,
) -> dict[str, Any]:
    indicator_policy = policy.get("indicators", {}).get(series_id, {})
    frequency = str(indicator_policy.get("frequency") or "unknown")
    calendar_name = str(indicator_policy.get("calendar") or "").strip() or None
    required = bool(indicator_policy.get("required", False))
    override = indicator_policy.get("status_override")
    evidence_ts = parse_timestamp(evidence_created_at)
    part = panel[series_matches(panel, series_id)].copy()

    base: dict[str, Any] = {
        "series_id": series_id,
        "required": required,
        "frequency": frequency,
        "observation_date": None,
        "vintage_date": None,
        "evidence_created_at": evidence_created_at,
        "lag_days": None,
        "lag_basis": "exchange_session" if calendar_name else "calendar_day",
        "calendar": calendar_name,
        "freshness_status": "missing",
        "missing_reason": None,
        "retired_reason": None,
        "used_in_current_diagnostics": False,
        "current_diagnostics_allowed": bool(indicator_policy.get("current_diagnostics_allowed", True)),
        "gate_severity": None,
    }

    if override == "retired_or_unavailable":
        base.update(
            {
                "freshness_status": "retired_or_unavailable",
                "retired_reason": indicator_policy.get("retired_reason"),
                "retired_effective_date": indicator_policy.get("retired_effective_date"),
                "current_diagnostics_allowed": False,
                "gate_severity": "none" if not required else policy.get("gate_defaults", {}).get("retired_used_severity", "block"),
            }
        )
        if not part.empty:
            latest = _latest_observation(part)
            base.update(_latest_dates(latest, evidence_ts))
        return base

    if part.empty:
        base["missing_reason"] = indicator_policy.get("missing_reason") or "Indicator is not present in the admitted evidence panel."
        base["gate_severity"] = _indicator_gate_severity("missing", indicator_policy, policy, required)
        return base

    latest = _latest_observation(part)
    base.update(_latest_dates(latest, evidence_ts, calendar_name=calendar_name))
    status = classify_lag(base["lag_days"], frequency, policy)
    base["freshness_status"] = status
    base["gate_severity"] = _indicator_gate_severity(status, indicator_policy, policy, required)
    return base


def _latest_observation(part: pd.DataFrame) -> pd.Series:
    part = part.copy()
    part["date"] = pd.to_datetime(part["date"], errors="coerce")
    part = part.dropna(subset=["date", "value"]).sort_values("date")
    return part.iloc[-1] if not part.empty else pd.Series(dtype=object)


def _session_lag_days(content_date: date, as_of: date, calendar_name: str) -> int:
    """Count exchange sessions between an observation and evidence timestamp.

    ``scripts.freshness_validator`` already uses exchange-calendars for the
    governed content clock.  Release-level freshness must use the same clock
    for indicators whose publication cadence is tied to a market calendar;
    otherwise a Friday-to-Monday/weekend gap is counted as if it were a data
    outage.  A configured calendar is fail-closed if the dependency or query
    is unavailable rather than silently falling back to weekdays.
    """
    try:
        import exchange_calendars as xcals

        calendar = xcals.get_calendar(calendar_name)
        expected = calendar.date_to_session(pd.Timestamp(as_of), direction="previous").date()
        if content_date >= expected:
            return 0
        start = pd.Timestamp(content_date + timedelta(days=1))
        end = pd.Timestamp(expected)
        return int(len(calendar.sessions_in_range(start, end)))
    except Exception as exc:  # noqa: BLE001 - normalize calendar failures
        raise RuntimeError(
            f"exchange-session freshness unavailable: calendar={calendar_name} "
            f"content_max={content_date} as_of={as_of}"
        ) from exc


def _latest_dates(
    latest: pd.Series,
    evidence_ts: pd.Timestamp | None,
    *,
    calendar_name: str | None = None,
) -> dict[str, Any]:
    observation = parse_date(latest.get("date"))
    vintage = parse_date(latest.get("vintage_date"))
    lag_days = None
    if evidence_ts is not None and observation is not None:
        evidence_date = evidence_ts.normalize().tz_localize(None).date()
        observation_date = observation.date()
        if calendar_name:
            lag_days = _session_lag_days(observation_date, evidence_date, calendar_name)
        else:
            lag_days = int((evidence_ts.normalize().tz_localize(None) - observation).days)
    return {
        "observation_date": observation.date().isoformat() if observation is not None else None,
        "vintage_date": vintage.date().isoformat() if vintage is not None else None,
        "lag_days": lag_days,
    }


def _indicator_gate_severity(status: str, indicator_policy: dict[str, Any], policy: dict[str, Any], required: bool) -> str:
    if not required:
        return "none"
    defaults = policy.get("gate_defaults", {})
    if status == "stale":
        return str(indicator_policy.get("stale_required_severity") or defaults.get("stale_required_severity") or "warn")
    if status == "missing":
        return str(indicator_policy.get("missing_required_severity") or defaults.get("missing_required_severity") or "warn")
    return "none"


def _model_input_validity(indicators: list[dict[str, Any]]) -> str:
    required = [item for item in indicators if item.get("required")]
    if any(item["freshness_status"] == "missing" for item in required):
        return "incomplete"
    if any(item["freshness_status"] == "stale" for item in required):
        return "degraded"
    if any(item["freshness_status"] == "acceptable_lag" for item in required):
        return "usable_with_lag"
    return "usable"


def _gate_result(
    indicators: list[dict[str, Any]],
    policy: dict[str, Any],
    model_input_validity: str,
    *,
    provider_outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    blockers: list[str] = []
    for item in indicators:
        status = item["freshness_status"]
        severity = item.get("gate_severity")
        if item.get("required") and status in {"stale", "missing"}:
            message = f"{item['series_id']} is required but {status}"
            (blockers if severity == "block" else warnings).append(message)
        if status == "retired_or_unavailable" and item.get("used_in_current_diagnostics"):
            blockers.append(f"{item['series_id']} is retired_or_unavailable but marked as used in current diagnostics")
    provider_gate = _provider_gate(provider_outcomes or [])
    blockers.extend(provider_gate["blockers"])
    warnings.extend(provider_gate["warnings"])
    return {
        "promotion_allowed": not blockers,
        "canonical_promotion_severity": "block" if blockers else "warn" if warnings else "pass",
        "model_input_validity": model_input_validity,
        "provider_gate": provider_gate,
        "warnings": warnings,
        "blockers": blockers,
    }


def banner_lines(freshness: dict[str, Any]) -> list[str]:
    counts: dict[str, int] = {status: 0 for status in sorted(STATUSES)}
    for item in freshness.get("indicators", []):
        counts[item.get("freshness_status", "missing")] = counts.get(item.get("freshness_status", "missing"), 0) + 1
    gate = freshness.get("gate_result", {})
    return [
        "Data recency: batch/vintage evidence, not real-time.",
        f"Evidence created at: {freshness.get('evidence_created_at') or 'unknown'}",
        f"Run generated at: {freshness.get('run_generated_at') or 'unknown'}",
        f"Model input validity: {freshness.get('model_input_validity')}",
        "Freshness counts: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()) if value),
        f"Promotion gate: {gate.get('canonical_promotion_severity', 'unknown')}",
    ]


def _write_report_banner(run: Path, freshness: dict[str, Any]) -> None:
    summary = run / "reports" / "executive_summary.md"
    if summary.exists():
        text = summary.read_text(encoding="utf-8")
        if "## Data Recency" not in text:
            block = "\n".join(["", "## Data Recency", *[f"- {line}" for line in banner_lines(freshness)], ""])
            summary.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    report = run / "reports" / "report.html"
    if report.exists():
        text = report.read_text(encoding="utf-8")
        if "Data Recency" not in text:
            lis = "".join(f"<li>{line}</li>" for line in banner_lines(freshness))
            section = f"<section><h2>Data Recency</h2><ul>{lis}</ul></section>"
            text = text.replace("</div>\n</body>", f"{section}\n  </div>\n</body>")
            report.write_text(text, encoding="utf-8")
