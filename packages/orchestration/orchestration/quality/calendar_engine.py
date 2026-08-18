"""Exchange-session calculations for content freshness.

Pandera validates table shape; this module owns session semantics.  Keeping
the calendar boundary here prevents schema validation code from silently
turning a calendar or holiday question into a weekday approximation.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import pandas as pd

DEFAULT_CALENDAR = "XNYS"


class CalendarEngineError(RuntimeError):
    """Raised when the configured calendar cannot answer a session query."""


@lru_cache(maxsize=8)
def _get_calendar(calendar_name: str):
    try:
        import exchange_calendars as xcals
    except ImportError as exc:  # pragma: no cover - dependency contract
        raise CalendarEngineError(
            "exchange-calendars is required for session-aware freshness evaluation"
        ) from exc

    try:
        return xcals.get_calendar(calendar_name)
    except Exception as exc:  # noqa: BLE001 - normalize library errors
        raise CalendarEngineError(f"unknown exchange calendar: {calendar_name}") from exc


def sessions_behind(
    content_max: date,
    as_of: date,
    *,
    calendar_name: str = DEFAULT_CALENDAR,
) -> int:
    """Return sessions strictly after ``content_max`` through ``as_of``.

    ``as_of`` is rolled to the latest session on or before that date, so
    weekends and exchange holidays do not create false staleness.  A calendar
    coverage or import failure raises instead of silently passing a rule.
    """
    calendar = _get_calendar(calendar_name)
    try:
        expected = calendar.date_to_session(pd.Timestamp(as_of), direction="previous").date()
        if content_max >= expected:
            return 0
        start = pd.Timestamp(content_max + timedelta(days=1))
        end = pd.Timestamp(expected)
        return int(len(calendar.sessions_in_range(start, end)))
    except Exception as exc:  # noqa: BLE001 - normalize calendar boundaries
        raise CalendarEngineError(
            f"calendar query failed: calendar={calendar_name} content_max={content_max} as_of={as_of}"
        ) from exc


def session_bounds(
    session_date: date,
    *,
    calendar_name: str = DEFAULT_CALENDAR,
) -> tuple[datetime, datetime]:
    """Return the exchange session open/close as UTC-aware datetimes.

    The exchange calendar, rather than a weekday or fixed-hours approximation,
    owns early-close and holiday semantics.  Callers may convert the returned
    instants to a provider's release timezone without changing the session
    identity.
    """
    calendar = _get_calendar(calendar_name)
    timestamp = pd.Timestamp(session_date)
    try:
        if not calendar.is_session(timestamp):
            raise CalendarEngineError(
                f"date is not an exchange session: calendar={calendar_name} date={session_date}"
            )
        opened = calendar.session_open(timestamp).to_pydatetime().astimezone(UTC)
        closed = calendar.session_close(timestamp).to_pydatetime().astimezone(UTC)
        return opened, closed
    except CalendarEngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize calendar boundaries
        raise CalendarEngineError(
            f"session bounds unavailable: calendar={calendar_name} date={session_date}"
        ) from exc
