"""Canonical observation construction owned by the Harvester boundary."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from harvester.core.availability import build_availability
from system_runtime.canonical_ids import build_observation


def canonical_official_observations(
    panel: pd.DataFrame,
    *,
    release_id: str,
    vintage_date: str,
    source_snapshot_sha256: str,
    provider_outcome: dict[str, Any] | None,
    canonical_prefix: str = "OFFICIAL",
    producer: str = "harvester.official",
) -> list[dict[str, Any]]:
    """Build canonical observations for the long official panel."""
    outcome = provider_outcome if isinstance(provider_outcome, dict) else {}
    failed_series = {str(item) for item in outcome.get("failed_series", [])}
    reused_status = {
        "reused_after_provider_failure",
        "provider_failed_no_acceptable_fallback",
        "environmentally_blocked",
    }
    series_attempts = outcome.get("series_attempts")
    if not isinstance(series_attempts, dict):
        series_attempts = {}
    availability_meta = outcome.get("availability")
    if not isinstance(availability_meta, dict):
        availability_meta = {
            "state": "UNKNOWN",
            "calendar_status": "UNCONFIGURED",
            "available_at": None,
            "retrieved_at": outcome.get("retrieved_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "decision_usable": False,
            "reason": "publication_calendar_or_available_at_not_evidenced",
        }
    required = {"date", "value"}
    if panel.empty or not required.issubset(panel.columns):
        return []

    records: list[dict[str, Any]] = []
    ordered = panel.sort_values(
        [column for column in ("series_id", "source_series_id", "date") if column in panel.columns]
    )
    for row in ordered.to_dict(orient="records"):
        observed = pd.to_datetime(row.get("date"), errors="coerce")
        if pd.isna(observed):
            continue
        raw_value = row.get("value")
        value: float | None
        if raw_value is None or pd.isna(raw_value):
            value = None
        else:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = None
        series_id = str(row.get("series_id") or row.get("source_series_id") or "").strip()
        source_series_id = str(row.get("source_series_id") or series_id).strip()
        if not series_id:
            continue
        quality_flag = row.get("quality_flag")
        quality_text = str(quality_flag or "").lower()
        if value is None:
            status = "MISSING"
        elif source_series_id in failed_series or outcome.get("status") in reused_status:
            status = "STALE"
        elif quality_text in {"2", "error", "missing", "source_down"} or quality_flag == 2:
            status = "STALE"
        else:
            status = str(availability_meta.get("state") or "UNKNOWN").upper()
            if status not in {
                "AVAILABLE", "STALE", "DELAYED", "MISSING", "NOT_APPLICABLE",
                "SOURCE_DOWN", "SCHEMA_CHANGED", "DISCONTINUED", "UNKNOWN",
            }:
                status = "UNKNOWN"
        attempts = series_attempts.get(source_series_id, [])
        selected_attempt = None
        if isinstance(attempts, list):
            selected_attempt = next(
                (item for item in reversed(attempts) if isinstance(item, dict) and item.get("outcome") == "success"),
                next((item for item in reversed(attempts) if isinstance(item, dict)), None),
            )
        provenance: dict[str, Any] = {
            "captured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "producer": producer,
            "run_id": release_id,
            "method": "registry_provider_observation",
            "quality_flag": quality_flag,
            "derivation": "MODELED" if str(row.get("source_id") or "").lower() == "derived" else "OBSERVED",
        }
        if isinstance(selected_attempt, dict):
            if selected_attempt.get("provider_attempt_id"):
                provenance["provider_attempt_id"] = selected_attempt["provider_attempt_id"]
            if selected_attempt.get("source_tier") is not None:
                provenance["source_tier"] = selected_attempt["source_tier"]
            if selected_attempt.get("failure_class"):
                provenance["failure_class"] = selected_attempt["failure_class"]
        source_signatures = outcome.get("series_source_signatures")
        source_signature = (
            source_signatures.get(source_series_id)
            if isinstance(source_signatures, dict)
            else None
        )
        if isinstance(source_signature, dict):
            provenance["source_signature"] = source_signature
        route_policy = outcome.get("route_policy")
        if isinstance(route_policy, dict):
            provenance["route_policy"] = route_policy
        availability = build_availability(
            state=status,
            observation_date=observed.date().isoformat(),
            source_vintage_at=str(row.get("vintage_date") or vintage_date),
            retrieved_at=str(availability_meta.get("retrieved_at") or outcome.get("retrieved_at")),
            published_at=availability_meta.get("published_at"),
            available_at=availability_meta.get("available_at"),
            calendar_status=str(availability_meta.get("calendar_status") or "UNCONFIGURED"),
            release_timezone=availability_meta.get("release_timezone"),
            release_cutoff_local=availability_meta.get("release_cutoff_local"),
            decision_usable=bool(availability_meta.get("decision_usable", False)),
            reason=str(availability_meta.get("reason") or ""),
        )
        records.append(
            build_observation(
                canonical_series_id=f"{canonical_prefix}:{series_id}",
                observed_at=observed.date().isoformat(),
                vintage_at=str(row.get("vintage_date") or vintage_date),
                value=value,
                source_id=str(row.get("source_id") or outcome.get("provider") or "harvester.registry"),
                unit=str(row.get("unit") or "") or None,
                status=status,
                scope={
                    "series_id": series_id,
                    "source_series_id": source_series_id,
                    "release_id": release_id,
                },
                source_snapshot_sha256=source_snapshot_sha256,
                availability=availability,
                provenance=provenance,
            )
        )
    return records


def panel_identity_set(panel: pd.DataFrame) -> set[str]:
    """Return canonical and provider-native identifiers visible in a panel."""
    identifiers: set[str] = set()
    if panel.empty:
        return identifiers
    if "series_id" in panel:
        for value in panel["series_id"].dropna().astype(str):
            identifiers.add(value)
            if ":" in value:
                identifiers.add(value.split(":", 1)[1])
    if "source_series_id" in panel:
        identifiers.update(panel["source_series_id"].dropna().astype(str))
    return identifiers


_canonical_official_observations = canonical_official_observations


__all__ = ["canonical_official_observations", "panel_identity_set"]
