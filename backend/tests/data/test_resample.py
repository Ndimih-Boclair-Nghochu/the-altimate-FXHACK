"""H1 → H4/D resampling aligned to 17:00 New York (DST-safe, no partial bars)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fxbot.data.frames import candles_to_frame
from fxbot.data.resample import base_window, resample, resample_window
from fxbot.domain.enums import Granularity
from fxbot.domain.errors import DataIntegrityError
from tests.data.conftest import bar, hourly


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("week_start", "first_h4_opens", "daily_open_hour"),
    [
        (utc(2024, 3, 3, 22), [22, 2, 6], 22),  # before US DST: 17:00 New York = 22:00 UTC
        (utc(2024, 3, 10, 21), [21, 1, 5], 21),  # US DST started 10 March
        (utc(2024, 3, 31, 21), [21, 1, 5], 21),  # EU DST (31 March) changes nothing
        (utc(2024, 11, 3, 22), [22, 2, 6], 22),  # US DST ended 3 November
    ],
)
def test_h4_and_daily_align_to_new_york(
    week_start: datetime, first_h4_opens: list[int], daily_open_hour: int
) -> None:
    h1 = hourly(week_start, 24 * 5)

    h4 = resample(h1, Granularity.H4)
    daily = resample(h1, Granularity.D)

    assert [c.time.hour for c in h4[:3]] == first_h4_opens
    assert all(c.time.hour == daily_open_hour for c in daily)
    assert all(c.granularity is Granularity.D for c in daily)
    assert len(daily) == 5 and len(h4) == 30


def test_aggregation_values() -> None:
    start = utc(2024, 3, 5, 2)  # an H4 boundary in winter
    h1 = [
        bar(start + timedelta(hours=i), mid=mid)
        for i, mid in enumerate(["1.1", "1.3", "1.0", "1.2"])
    ]

    (h4,) = resample(h1, Granularity.H4)

    assert h4.time == start
    assert (h4.bid.open, h4.bid.close) == (Decimal("1.1"), Decimal("1.2"))
    assert h4.bid.high == Decimal("1.301") and h4.bid.low == Decimal("0.999")
    assert h4.ask.high == Decimal("1.3011")
    assert h4.volume == 20


def test_a_bar_is_available_only_after_its_end() -> None:
    start = utc(2024, 3, 5, 2)
    h1 = hourly(start, 7)  # 02:00 .. 08:00, so the 06:00 H4 bar is not finished

    assert [c.time.hour for c in resample(h1, Granularity.H4)] == [2]
    assert resample(h1, Granularity.H4, as_of=start + timedelta(hours=3, minutes=59)) == []
    # Once the clock has passed 10:00 the 06:00 bar is final even if hours were missing.
    later = resample(h1, Granularity.H4, as_of=utc(2024, 3, 5, 10))
    assert [c.time.hour for c in later] == [2, 6]


def test_invalid_inputs() -> None:
    h1 = hourly(utc(2024, 3, 5), 4)

    assert resample([], Granularity.H4) == []
    with pytest.raises(ValueError, match="coarser"):
        resample(h1, Granularity.M15)
    with pytest.raises(DataIntegrityError, match="one instrument"):
        resample([*h1, bar(utc(2024, 3, 5, 9), instrument="GBP_USD")], Granularity.H4)
    with pytest.raises(DataIntegrityError, match="increasing"):
        resample(list(reversed(h1)), Granularity.H4)


def test_windows() -> None:
    start, end = utc(2024, 3, 5, 3), utc(2024, 3, 5, 11)
    base_start, base_end = base_window(start, end, Granularity.H4)

    assert base_start == utc(2024, 3, 5, 2)
    assert base_end == utc(2024, 3, 5, 14)
    assert base_window(start, None, Granularity.H4) == (utc(2024, 3, 5, 2), None)
    h1 = hourly(base_start, 12)
    window = resample_window(h1, Granularity.H4, start, end, as_of=utc(2024, 3, 5, 14))
    assert [c.time.hour for c in window] == [6, 10]


def test_candles_to_frame() -> None:
    h1 = hourly(utc(2024, 3, 5), 3)

    frame = candles_to_frame(h1)

    assert list(frame.index) == [c.time for c in h1]
    assert str(frame.index.tz) == "UTC"  # type: ignore[attr-defined]
    assert frame["mid_close"].iloc[0] == pytest.approx(1.10005)
    assert frame["bid_high"].dtype == "float64"
    assert candles_to_frame([]).empty
