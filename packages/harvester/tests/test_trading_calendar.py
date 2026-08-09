from datetime import UTC, date, datetime

from harvester.trading_calendar import (
    is_us_equity_session,
    latest_completed_us_equity_session,
    previous_us_equity_session,
    us_equity_sessions_between,
)


def test_weekends_and_regular_exchange_holidays_are_closed() -> None:
    assert not is_us_equity_session(date(2026, 8, 8))  # Saturday
    assert not is_us_equity_session(date(2026, 8, 9))  # Sunday
    assert not is_us_equity_session(date(2026, 4, 3))  # Good Friday
    assert not is_us_equity_session(date(2026, 7, 3))  # July 4 observed
    assert is_us_equity_session(date(2026, 7, 6))


def test_previous_session_skips_weekend_and_holiday() -> None:
    assert previous_us_equity_session(date(2026, 8, 9)) == date(2026, 8, 7)
    assert previous_us_equity_session(date(2026, 7, 6)) == date(2026, 7, 2)


def test_session_lag_counts_sessions_not_calendar_days() -> None:
    assert us_equity_sessions_between(date(2026, 7, 2), date(2026, 7, 6)) == 1
    assert us_equity_sessions_between(date(2026, 8, 7), date(2026, 8, 9)) == 0


def test_latest_completed_session_is_timezone_and_close_aware() -> None:
    # 10:30 New York on Monday: the Monday session is still in progress.
    before_close = datetime(2026, 8, 3, 14, 30, tzinfo=UTC)
    assert latest_completed_us_equity_session(before_close) == date(2026, 7, 31)

    # 18:30 New York: Monday is complete.
    after_close = datetime(2026, 8, 3, 22, 30, tzinfo=UTC)
    assert latest_completed_us_equity_session(after_close) == date(2026, 8, 3)
