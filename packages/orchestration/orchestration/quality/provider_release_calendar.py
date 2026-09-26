"""Declarative provider publication calendars.

The calendar is a schedule oracle, not publication evidence. It can tell the
quality layer that a release should have been available by a decision time,
but it never fills an event's available_at field and never makes a retrieved
value decision-usable by itself. The provider event must still carry an
explicit causal availability timestamp.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from system_runtime.context import RuntimeContext

CALENDAR_RELATIVE_PATH = Path("configs/provider_release_calendar.yaml")

_VALID_MODES = {"shadow", "enforce"}
_VALID_EVIDENCE_STATUS = {"verified"}
_VALID_BUSINESS_CALENDARS = {"US_FEDERAL", "WEEKDAYS"}
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


class ProviderReleaseCalendarError(ValueError):
    """Raised when a provider publication calendar is malformed."""


def load_provider_release_calendar(root: Path | None = None) -> dict[str, Any]:
    """Load and validate the declarative provider publication calendar."""
    root = root or RuntimeContext.current_context().workspace
    path = root / CALENDAR_RELATIVE_PATH
    if not path.is_file():
        raise ProviderReleaseCalendarError(f"provider release calendar missing: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProviderReleaseCalendarError(
            f"provider release calendar is invalid YAML: {path}"
        ) from exc
    validate_provider_release_calendar(payload)
    return payload


def validate_provider_release_calendar(payload: dict[str, Any]) -> None:
    """Validate calendar rules without treating them as observed releases."""
    if not isinstance(payload, dict):
        raise ProviderReleaseCalendarError("provider release calendar must be a mapping")
    if payload.get("schema_version") != "workbench.provider_release_calendar.v1":
        raise ProviderReleaseCalendarError("unsupported provider release calendar schema")
    if str(payload.get("mode") or "shadow").lower() not in _VALID_MODES:
        raise ProviderReleaseCalendarError("provider release calendar mode must be shadow or enforce")
    _validate_timezone(payload.get("default_timezone"), "default_timezone")
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ProviderReleaseCalendarError("provider release calendar requires non-empty rules")

    required = {
        "rule_id",
        "provider_id",
        "series_id",
        "dataset_id",
        "evidence_status",
        "observation_weekday",
        "release_offset_days",
        "release_weekday",
        "release_timezone",
        "release_cutoff_local",
        "nominal_publication_lag",
        "business_calendar_basis",
        "official_evidence_url",
        "evidence_checked_at",
    }
    seen: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise ProviderReleaseCalendarError("provider release calendar rules must be mappings")
        missing = sorted(required - set(rule))
        if missing:
            raise ProviderReleaseCalendarError(f"calendar rule missing fields: {missing}")
        rule_id = str(rule["rule_id"])
        if not rule_id or rule_id in seen:
            raise ProviderReleaseCalendarError(f"duplicate or empty calendar rule_id: {rule_id!r}")
        seen.add(rule_id)
        if rule["evidence_status"] not in _VALID_EVIDENCE_STATUS:
            raise ProviderReleaseCalendarError(
                f"unsupported evidence_status for {rule_id}: {rule['evidence_status']!r}"
            )
        for field in ("provider_id", "dataset_id", "official_evidence_url"):
            if not str(rule[field]).strip():
                raise ProviderReleaseCalendarError(f"calendar rule field is empty: {rule_id}.{field}")
        series_id = str(rule["series_id"])
        if not series_id.strip():
            raise ProviderReleaseCalendarError(f"calendar rule series_id is empty: {rule_id}")
        for field in ("observation_weekday", "release_weekday"):
            value = rule[field]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 6:
                raise ProviderReleaseCalendarError(
                    f"calendar rule {rule_id}.{field} must be an integer from 0 to 6"
                )
        offset = rule["release_offset_days"]
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ProviderReleaseCalendarError(
                f"calendar rule {rule_id}.release_offset_days must be a non-negative integer"
            )
        if (rule["observation_weekday"] + offset) % 7 != rule["release_weekday"]:
            raise ProviderReleaseCalendarError(
                f"calendar rule {rule_id} weekday/offset combination is inconsistent"
            )
        _validate_timezone(rule["release_timezone"], f"{rule_id}.release_timezone")
        _parse_cutoff(rule["release_cutoff_local"], rule_id)
        _parse_duration(rule["nominal_publication_lag"], rule_id)
        basis = str(rule["business_calendar_basis"]).upper()
        if basis not in _VALID_BUSINESS_CALENDARS:
            raise ProviderReleaseCalendarError(
                f"unsupported business calendar for {rule_id}: {rule['business_calendar_basis']!r}"
            )
        try:
            date.fromisoformat(str(rule["evidence_checked_at"]))
        except ValueError as exc:
            raise ProviderReleaseCalendarError(
                f"calendar rule {rule_id}.evidence_checked_at must be an ISO date"
            ) from exc
        aliases = rule.get("provider_aliases", [])
        if not isinstance(aliases, list) or any(not str(item).strip() for item in aliases):
            raise ProviderReleaseCalendarError(
                f"calendar rule {rule_id}.provider_aliases must be a list of non-empty strings"
            )
        release_dates = rule.get("official_release_dates", [])
        if not isinstance(release_dates, list):
            raise ProviderReleaseCalendarError(
                f"calendar rule {rule_id}.official_release_dates must be a list"
            )
        parsed_release_dates: list[date] = []
        for value in release_dates:
            try:
                parsed_release_dates.append(date.fromisoformat(str(value)))
            except ValueError as exc:
                raise ProviderReleaseCalendarError(
                    f"calendar rule {rule_id} has invalid official release date: {value!r}"
                ) from exc
        if parsed_release_dates != sorted(set(parsed_release_dates)):
            raise ProviderReleaseCalendarError(
                f"calendar rule {rule_id}.official_release_dates must be sorted and unique"
            )


def resolve_provider_release_calendar(
    provider_id: str,
    *,
    series_id: str = "",
    dataset_id: str = "",
    observation_date: date | str | datetime | None = None,
    calendar: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Resolve the most specific calendar rule for a provider event."""
    root = root or RuntimeContext.current_context().workspace
    payload = calendar or load_provider_release_calendar(root)
    validate_provider_release_calendar(payload)
    provider = str(provider_id)
    candidates = []
    for rule in payload["rules"]:
        provider_matches = rule["provider_id"] == provider or provider in {
            str(item) for item in rule.get("provider_aliases", [])
        }
        if (
            provider_matches
            and rule["dataset_id"] in {dataset_id, "*"}
            and rule["series_id"] in {series_id, "*"}
        ):
            candidates.append(rule)
    if not candidates:
        return None
    parsed_observation = _parse_date(observation_date)
    if parsed_observation is not None:
        weekday_matches = [
            rule
            for rule in candidates
            if int(rule["observation_weekday"]) == parsed_observation.weekday()
        ]
        if weekday_matches:
            candidates = weekday_matches
    candidates.sort(
        key=lambda rule: (
            rule["dataset_id"] != "*",
            rule["series_id"] != "*",
            rule["provider_id"] == provider,
        ),
        reverse=True,
    )
    return dict(candidates[0])


def evaluate_provider_release_calendar(
    event: dict[str, Any],
    *,
    decision_time: datetime,
    calendar: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return expected schedule evidence for one event.

    expected_available_at is deliberately separate from the event's explicit
    available_at. A schedule that has elapsed makes missing causal evidence
    more visible; it does not manufacture that evidence.
    """
    root = root or RuntimeContext.current_context().workspace
    provider = str(event.get("provider_id") or event.get("provider") or "")
    series_id = str(event.get("series_id") or "")
    dataset_id = str(event.get("dataset_id") or "")
    result: dict[str, Any] = {
        "schema_version": "provider_release_calendar_result.v1",
        "mode": str((calendar or {}).get("mode") or "shadow"),
        "provider_id": provider,
        "series_id": series_id,
        "dataset_id": dataset_id,
        "status": "unconfigured",
        "rule_id": None,
        "evidence_status": None,
        "expected_release_at": None,
        "expected_available_at": None,
        "release_due": False,
        "resolution": None,
        "reason": "no_matching_provider_release_calendar",
        "official_evidence_url": None,
        "evidence_checked_at": None,
    }
    payload = calendar or load_provider_release_calendar(root)
    validate_provider_release_calendar(payload)
    result["mode"] = str(payload.get("mode") or "shadow")
    observation_date = _parse_date(event.get("observation_date"))
    rule = resolve_provider_release_calendar(
        provider,
        series_id=series_id,
        dataset_id=dataset_id,
        observation_date=observation_date,
        calendar=payload,
        root=root,
    )
    if rule is None:
        return result

    result.update(
        {
            "rule_id": rule["rule_id"],
            "evidence_status": rule["evidence_status"],
            "official_evidence_url": rule["official_evidence_url"],
            "evidence_checked_at": rule["evidence_checked_at"],
        }
    )
    if observation_date is None:
        result["status"] = "invalid"
        result["reason"] = "missing_observation_date"
        return result
    if observation_date.weekday() != rule["observation_weekday"]:
        result["status"] = "invalid"
        result["reason"] = "observation_weekday_mismatch"
        return result

    try:
        release_date, resolution = _resolve_release_date(observation_date, rule)
        release_at = _release_timestamp(release_date, rule)
    except ProviderReleaseCalendarError as exc:
        result["status"] = "stale" if "schedule_stale" in str(exc) else "invalid"
        result["reason"] = str(exc)
        return result

    lag = _parse_duration(rule["nominal_publication_lag"], rule["rule_id"])
    available_at = release_at + lag
    parsed_decision = _parse_timestamp(decision_time)
    if parsed_decision is None:
        raise ProviderReleaseCalendarError("decision_time must be timezone-aware")
    result.update(
        {
            "status": "verified",
            "expected_release_at": _timestamp(release_at),
            "expected_available_at": _timestamp(available_at),
            "release_due": available_at <= parsed_decision,
            "resolution": resolution,
            "reason": "verified_schedule",
            "observation_date": observation_date.isoformat(),
        }
    )
    return result


def _resolve_release_date(observation_date: date, rule: dict[str, Any]) -> tuple[date, str]:
    nominal = observation_date + timedelta(days=int(rule["release_offset_days"]))
    official_dates = [date.fromisoformat(str(value)) for value in rule.get("official_release_dates", [])]
    if official_dates:
        candidates = [value for value in official_dates if value >= nominal]
        if not candidates:
            raise ProviderReleaseCalendarError(
                f"schedule_stale:no official release date covers {nominal.isoformat()}"
            )
        return candidates[0], "official_release_date"
    release_date = nominal
    if not _is_business_day(release_date, str(rule["business_calendar_basis"]).upper()):
        release_date = _roll_forward_business_day(
            release_date, str(rule["business_calendar_basis"]).upper()
        )
        return release_date, "holiday_roll_forward"
    return release_date, "weekday_pattern"


def _release_timestamp(release_date: date, rule: dict[str, Any]) -> datetime:
    hour, minute = _parse_cutoff(rule["release_cutoff_local"], str(rule["rule_id"]))
    try:
        timezone = ZoneInfo(str(rule["release_timezone"]))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ProviderReleaseCalendarError(
            f"invalid release timezone: {rule['rule_id']}"
        ) from exc
    return datetime.combine(release_date, time(hour, minute), tzinfo=timezone).astimezone(UTC)


def _parse_cutoff(value: Any, rule_id: str) -> tuple[int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ProviderReleaseCalendarError(f"invalid release cutoff: {rule_id}")
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _parse_duration(value: Any, rule_id: str) -> timedelta:
    match = _DURATION_RE.fullmatch(str(value))
    if match is None or not any(match.group(name) for name in ("days", "hours", "minutes", "seconds")):
        raise ProviderReleaseCalendarError(f"invalid publication lag: {rule_id}")
    return timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours") or 0),
        minutes=int(match.group("minutes") or 0),
        seconds=int(match.group("seconds") or 0),
    )


def _validate_timezone(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProviderReleaseCalendarError(f"{field} must be a timezone")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ProviderReleaseCalendarError(f"{field} is not a valid timezone") from exc


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _is_business_day(value: date, basis: str) -> bool:
    if value.weekday() >= 5:
        return False
    if basis == "WEEKDAYS":
        return True
    return value not in _us_federal_holidays(value.year)


def _roll_forward_business_day(value: date, basis: str) -> date:
    candidate = value
    while not _is_business_day(candidate, basis):
        candidate += timedelta(days=1)
    return candidate


def _us_federal_holidays(year: int) -> set[date]:
    """Return the standard federal holiday dates with observed weekdays."""
    holidays = {
        _observed_fixed(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed_fixed(year, 6, 19),  # Juneteenth
        _observed_fixed(year, 7, 4),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _observed_fixed(year, 11, 11),  # Veterans Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed(year, 12, 25),  # Christmas
    }
    return holidays


def _observed_fixed(year: int, month: int, day: int) -> date:
    actual = date(year, month, day)
    if actual.weekday() == 5:
        return actual - timedelta(days=1)
    if actual.weekday() == 6:
        return actual + timedelta(days=1)
    return actual


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (ordinal - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


__all__ = [
    "ProviderReleaseCalendarError",
    "evaluate_provider_release_calendar",
    "load_provider_release_calendar",
    "resolve_provider_release_calendar",
    "validate_provider_release_calendar",
]
