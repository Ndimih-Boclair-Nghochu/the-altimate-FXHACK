from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from fxbot.domain.calendar import (
    bar_close_time,
    bar_open_time,
    ensure_utc,
    is_market_open,
    trading_day,
)
from fxbot.domain.clock import SimClock, SystemClock
from fxbot.domain.enums import Granularity


def utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def test_ensure_utc() -> None:
    with pytest.raises(ValueError, match="naive"):
        ensure_utc(datetime(2024, 1, 1))
    assert ensure_utc(datetime(2024, 1, 1, 9, tzinfo=timezone(timedelta(hours=9)))) == utc(
        2024, 1, 1
    )


@pytest.mark.parametrize(
    ("when", "is_open"),
    [
        (utc(2024, 1, 5, 21, 59), True),  # Friday 16:59 New York (EST)
        (utc(2024, 1, 5, 22, 0), False),  # Friday 17:00 New York
        (utc(2024, 1, 6, 12, 0), False),  # Saturday
        (utc(2024, 1, 7, 21, 59), False),  # Sunday 16:59 New York
        (utc(2024, 1, 7, 22, 0), True),  # Sunday 17:00 New York
        (utc(2024, 7, 5, 20, 59), True),  # summer: Friday 16:59 EDT
        (utc(2024, 7, 5, 21, 0), False),
        (utc(2024, 7, 7, 21, 0), True),  # summer: Sunday 17:00 EDT
        (utc(2024, 1, 10, 3, 0), True),  # midweek
    ],
)
def test_market_hours(when: datetime, is_open: bool) -> None:
    assert is_market_open(when) is is_open


def test_trading_day_rolls_at_17_new_york() -> None:
    assert trading_day(utc(2024, 1, 9, 21, 59)) == date(2024, 1, 9)
    assert trading_day(utc(2024, 1, 9, 22, 0)) == date(2024, 1, 10)


@pytest.mark.parametrize(
    ("granularity", "when", "expected"),
    [
        (Granularity.M15, utc(2024, 1, 9, 10, 44), utc(2024, 1, 9, 10, 30)),
        (Granularity.H1, utc(2024, 1, 9, 10, 59, 59), utc(2024, 1, 9, 10)),
        # H4 aligns to 17:00 New York: 22:00 UTC in winter, 21:00 UTC in summer.
        (Granularity.H4, utc(2024, 1, 9, 1, 0), utc(2024, 1, 8, 22)),
        (Granularity.H4, utc(2024, 1, 9, 3, 0), utc(2024, 1, 9, 2)),
        (Granularity.H4, utc(2024, 7, 9, 3, 0), utc(2024, 7, 9, 1)),
        (Granularity.D, utc(2024, 1, 9, 21, 0), utc(2024, 1, 8, 22)),
        (Granularity.D, utc(2024, 7, 9, 21, 0), utc(2024, 7, 9, 21)),
        (Granularity.W, utc(2024, 1, 10, 12, 0), utc(2024, 1, 5, 22)),  # Friday 17:00 New York
    ],
)
def test_bar_open_time(granularity: Granularity, when: datetime, expected: datetime) -> None:
    assert bar_open_time(when, granularity) == expected


def test_daily_bar_spanning_a_dst_change_is_23_hours() -> None:
    saturday_open = utc(2024, 3, 9, 22)  # Saturday 17:00 EST; DST starts Sunday 02:00
    assert bar_close_time(saturday_open, Granularity.D) == utc(2024, 3, 10, 21)
    assert bar_close_time(utc(2024, 3, 5, 22), Granularity.W) == utc(2024, 3, 12, 21)
    assert bar_close_time(utc(2024, 3, 5, 22), Granularity.H4) == utc(2024, 3, 6, 2)


def test_clocks() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC and repr(SystemClock()) == "SystemClock()"

    clock = SimClock(utc(2024, 1, 1))
    assert clock.advance(timedelta(hours=1)) == utc(2024, 1, 1, 1)
    clock.set(utc(2024, 1, 2))
    assert clock.now() == utc(2024, 1, 2)
    assert "2024-01-02" in repr(clock)
    with pytest.raises(ValueError, match="backwards"):
        clock.set(utc(2024, 1, 1))
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(timedelta(seconds=-1))
    with pytest.raises(ValueError, match="naive"):
        SimClock(datetime(2024, 1, 1))
