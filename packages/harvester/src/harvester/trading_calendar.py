"""Small, dependency-free US equity session calendar.

The daily Harvester may be scheduled in any local timezone but acquires
US-listed market data. Using the scheduler's calendar date as a market-data
as-of date therefore creates empty or partial releases on weekends, exchange
holidays, and before the US close. This module keeps the automatic path
conservative without adding a runtime dependency on a third-party calendar
package. Explicit historical dates remain the caller's responsibility and are
not rejected by ``run_daily_release``.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo


_US_EASTERN = ZoneInfo("America/New_York")
_US_CLOSE_BUFFER = time(16, 30)


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (ordinal - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    last = first_next - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed_fixed(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:  # Saturday -> Friday
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:  # Sunday -> Monday
        return holiday + timedelta(days=1)
    return holiday


def _easter_sunday(year: int) -> date:
    """Return Gregorian Easter Sunday using the Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=None)
def us_equity_holidays(year: int) -> frozenset[date]:
    """Return regular full-day US equity-market closures for ``year``."""
    holidays = {
        _observed_fixed(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed_fixed(year, 7, 4),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving Day
        _observed_fixed(year, 12, 25),  # Christmas Day
    }
    # Juneteenth became a regular NYSE closure in 2022.
    if year >= 2022:
        holidays.add(_observed_fixed(year, 6, 19))
    return frozenset(holidays)


def is_us_equity_session(day: date) -> bool:
    """Whether ``day`` is a regular full-day US equity trading session."""
    if day.weekday() >= 5:
        return False
    # Include the next year because Jan 1 can be observed on Dec 31.
    return (
        day not in us_equity_holidays(day.year - 1)
        and day not in us_equity_holidays(day.year)
        and day not in us_equity_holidays(day.year + 1)
    )


def previous_us_equity_session(day: date) -> date:
    """Return the last US equity session strictly before ``day``."""
    candidate = day - timedelta(days=1)
    while not is_us_equity_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def latest_completed_us_equity_session(
    now_utc: datetime | None = None,
    *,
    close_buffer: time = _US_CLOSE_BUFFER,
) -> date:
    """Return the latest US equity session whose regular close has passed.

    The scheduler runs on the operator's local clock, while the data belongs
    to US-listed markets. Resolving the as-of session in America/New_York
    prevents a local evening run from labeling an in-progress US session as a
    completed release. The 30-minute buffer avoids writing a release while
    end-of-day files are still settling.
    """
    current = now_utc or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    eastern = current.astimezone(_US_EASTERN)
    candidate = eastern.date()
    if not is_us_equity_session(candidate) or eastern.time() < close_buffer:
        return previous_us_equity_session(candidate)
    return candidate


def us_equity_sessions_between(start: date, end: date) -> int:
    """Count sessions strictly after ``start`` and through ``end``."""
    if end <= start:
        return 0
    count = 0
    candidate = start + timedelta(days=1)
    while candidate <= end:
        if is_us_equity_session(candidate):
            count += 1
        candidate += timedelta(days=1)
    return count


__all__ = [
    "is_us_equity_session",
    "latest_completed_us_equity_session",
    "previous_us_equity_session",
    "us_equity_sessions_between",
    "us_equity_holidays",
]
