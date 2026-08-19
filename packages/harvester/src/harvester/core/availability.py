"""Explicit observation availability and vintage metadata.

The data value, the observation period, the publication/vintage, and the
retrieval time are different clocks.  This module provides one small
serialisable contract for carrying those clocks through a release.  It never
infers publication availability from retrieval time; an unknown calendar is a
conservative ``UNKNOWN`` state and is not decision-usable.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
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


__all__ = [
    "AVAILABILITY_STATES",
    "CALENDAR_STATES",
    "AvailabilityContractError",
    "build_availability",
    "validate_availability",
]
