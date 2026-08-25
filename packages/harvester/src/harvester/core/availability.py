"""Explicit observation availability and vintage metadata.

The data value, the observation period, the publication/vintage, and the
retrieval time are different clocks.  This module provides one small
serialisable contract for carrying those clocks through a release.  It never
infers publication availability from retrieval time; an unknown calendar is a
conservative ``UNKNOWN`` state and is not decision-usable.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from collections.abc import Sequence
from typing import Any, Mapping

AVAILABILITY_STATES = frozenset(
    {
        "AVAILABLE",
        "STALE",
        "DELAYED",
        "MISSING",
        "NOT_APPLICABLE",
        "SOURCE_DOWN",
        "SCHEMA_CHANGED",
        "DISCONTINUED",
        "UNKNOWN",
    }
)
CALENDAR_STATES = frozenset({"CONFIGURED", "UNCONFIGURED"})


class AvailabilityContractError(ValueError):
    """Raised when explicit availability metadata is malformed."""


def _timestamp(value: Any, *, field: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        return value.isoformat()
    elif isinstance(value, str):
        parsed = value
    else:
        raise AvailabilityContractError(f"{field} must be an ISO timestamp/date or null")
    if isinstance(parsed, datetime):
        if parsed.tzinfo is None:
            raise AvailabilityContractError(f"{field} must be timezone-aware")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(parsed)


def _clock(value: Any, *, field: str) -> datetime:
    """Parse a date/timestamp for causal comparisons without guessing retrieval."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise AvailabilityContractError(f"{field} must be an ISO date/timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    else:
        raise AvailabilityContractError(f"{field} must be an ISO date/timestamp")
    if parsed.tzinfo is None:
        raise AvailabilityContractError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def build_availability(
    *,
    state: str,
    observation_date: str | date | datetime | None,
    source_vintage_at: str | date | datetime | None,
    retrieved_at: str | datetime,
    published_at: str | datetime | None = None,
    available_at: str | datetime | None = None,
    calendar_status: str = "UNCONFIGURED",
    release_timezone: str | None = None,
    release_cutoff_local: str | None = None,
    decision_usable: bool | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build a conservative availability record.

    ``decision_usable`` defaults to true only when a publication/availability
    timestamp is explicitly present and the calendar is configured.  A source
    that only reports a successful HTTP retrieval therefore remains UNKNOWN.
    """
    normalized_state = str(state).upper().strip()
    if normalized_state not in AVAILABILITY_STATES:
        raise AvailabilityContractError(f"unsupported availability state: {state!r}")
    normalized_calendar = str(calendar_status).upper().strip()
    if normalized_calendar not in CALENDAR_STATES:
        raise AvailabilityContractError(f"unsupported calendar_status: {calendar_status!r}")
    observation = _timestamp(observation_date, field="observation_date")
    vintage = _timestamp(source_vintage_at, field="source_vintage_at")
    retrieved = _timestamp(retrieved_at, field="retrieved_at")
    published = _timestamp(published_at, field="published_at")
    available = _timestamp(available_at, field="available_at")
    if retrieved is None:
        raise AvailabilityContractError("retrieved_at is required")
    if decision_usable is None:
        decision_usable = bool(
            normalized_calendar == "CONFIGURED"
            and available is not None
            and normalized_state == "AVAILABLE"
        )
    if decision_usable and (available is None or normalized_calendar != "CONFIGURED"):
        raise AvailabilityContractError(
            "decision_usable requires configured calendar and explicit available_at"
        )
    if available and published and available < published:
        raise AvailabilityContractError("available_at cannot precede published_at")
    if available and retrieved and retrieved < available:
        raise AvailabilityContractError("retrieved_at cannot precede available_at")
    return {
        "state": normalized_state,
        "observation_date": observation,
        "source_vintage_at": vintage,
        "published_at": published,
        "available_at": available,
        "retrieved_at": retrieved,
        "calendar_status": normalized_calendar,
        "release_timezone": release_timezone,
        "release_cutoff_local": release_cutoff_local,
        "decision_usable": bool(decision_usable),
        "reason": reason or (
            "explicit_publication_availability"
            if decision_usable
            else "publication_calendar_or_available_at_not_evidenced"
        ),
    }


def validate_availability(value: Mapping[str, Any]) -> None:
    """Validate an availability object produced by :func:`build_availability`."""
    if not isinstance(value, Mapping):
        raise AvailabilityContractError("availability must be an object")
    required = {
        "state",
        "observation_date",
        "source_vintage_at",
        "published_at",
        "available_at",
        "retrieved_at",
        "calendar_status",
        "decision_usable",
    }
    missing = sorted(required - set(value))
    if missing:
        raise AvailabilityContractError(f"availability missing fields: {missing}")
    build_availability(
        state=str(value["state"]),
        observation_date=value.get("observation_date"),
        source_vintage_at=value.get("source_vintage_at"),
        retrieved_at=value["retrieved_at"],
        published_at=value.get("published_at"),
        available_at=value.get("available_at"),
        calendar_status=str(value["calendar_status"]),
        release_timezone=value.get("release_timezone"),
        release_cutoff_local=value.get("release_cutoff_local"),
        decision_usable=bool(value["decision_usable"]),
        reason=value.get("reason"),
    )


def select_latest_vintage_as_of(
    records: Sequence[Mapping[str, Any]],
    *,
    as_of: str | date | datetime,
    key_fields: tuple[str, ...] = ("series_id", "observation_date"),
    vintage_field: str = "source_vintage_at",
) -> list[dict[str, Any]]:
    """Select the latest decision-usable vintage visible at ``as_of``.

    A record is eligible only when its explicit ``available_at`` and source
    vintage are both no later than ``as_of``.  ``retrieved_at`` is never used
    as a proxy for availability.  Missing keys or duplicate visible vintages
    fail closed so a caller cannot silently mix revisions.
    """
    if not key_fields:
        raise AvailabilityContractError("key_fields must not be empty")
    cutoff = _clock(as_of, field="as_of")
    selected: dict[tuple[Any, ...], tuple[datetime, datetime, dict[str, Any]]] = {}

    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, Mapping):
            raise AvailabilityContractError(f"record[{index}] must be an object")
        availability = raw_record.get("availability")
        if not isinstance(availability, Mapping):
            continue
        validate_availability(availability)
        if (
            str(availability.get("state", "")).upper() != "AVAILABLE"
            or not bool(availability.get("decision_usable"))
        ):
            continue
        missing_keys = [field for field in key_fields if field not in raw_record]
        if missing_keys:
            raise AvailabilityContractError(
                f"record[{index}] missing PIT key fields: {missing_keys}"
            )
        key = tuple(raw_record[field] for field in key_fields)
        vintage_value = raw_record.get(vintage_field)
        if vintage_value is None:
            vintage_value = availability.get("source_vintage_at")
        if vintage_value is None:
            raise AvailabilityContractError(
                f"record[{index}] missing vintage field: {vintage_field}"
            )
        vintage = _clock(vintage_value, field=f"record[{index}].{vintage_field}")
        available_value = availability.get("available_at")
        if available_value is None:
            raise AvailabilityContractError(
                f"record[{index}] decision-usable record missing availability.available_at"
            )
        available = _clock(available_value, field=f"record[{index}].availability.available_at")
        if vintage > cutoff or available > cutoff:
            continue
        candidate = dict(raw_record)
        previous = selected.get(key)
        if previous is not None:
            previous_vintage, previous_available, _ = previous
            if (vintage, available) == (previous_vintage, previous_available):
                raise AvailabilityContractError(
                    f"duplicate visible vintage for PIT key {key!r}"
                )
            if (vintage, available) <= (previous_vintage, previous_available):
                continue
        selected[key] = (vintage, available, candidate)

    return [item[2] for item in selected.values()]


__all__ = [
    "AVAILABILITY_STATES",
    "CALENDAR_STATES",
    "AvailabilityContractError",
    "build_availability",
    "select_latest_vintage_as_of",
    "validate_availability",
]
