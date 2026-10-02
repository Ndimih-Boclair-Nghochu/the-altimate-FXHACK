"""FX market calendar: UTC handling, the 17:00 New York day boundary and bar alignment.

The FX week runs from Sunday 17:00 to Friday 17:00 New York time. Daily bars, the trading day
and 2h+ intraday bars all align to 17:00 New York (OANDA's ``dailyAlignment=17`` default), so
their UTC boundaries move by an hour with US daylight-saving time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from fxbot.domain.enums import Granularity

NEW_YORK: Final = ZoneInfo("America/New_York")
DAY_START_NY: Final = time(17, 0)

_FRIDAY: Final = 4
_SATURDAY: Final = 5
_SUNDAY: Final = 6
_NY_ALIGNED_INTRADAY: Final = frozenset(
    {Granularity.H2, Granularity.H4, Granularity.H6, Granularity.H8, Granularity.H12}
)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` in UTC. Naive datetimes are rejected: their meaning is ambiguous."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime: an explicit timezone (UTC) is required")
    return value.astimezone(UTC)


def is_market_open(at: datetime) -> bool:
    """False from Friday 17:00 to Sunday 17:00 New York time. Holidays are not modelled."""
    local = ensure_utc(at).astimezone(NEW_YORK)
    weekday, clock = local.weekday(), local.time()
    if weekday == _SATURDAY:
        return False
    if weekday == _FRIDAY:
        return clock < DAY_START_NY
    if weekday == _SUNDAY:
        return clock >= DAY_START_NY
    return True


def trading_day(at: datetime) -> date:
    """The FX trading day ``at`` belongs to (it starts at 17:00 New York the day before)."""
    local = ensure_utc(at).astimezone(NEW_YORK)
    return local.date() + timedelta(days=1) if local.time() >= DAY_START_NY else local.date()


def _day_start_local(local: datetime) -> datetime:
    """Most recent 17:00 New York at or before ``local`` (naive local wall time)."""
    start = datetime.combine(local.date(), DAY_START_NY)
    return start if local >= start else start - timedelta(days=1)


def _from_local(naive_local: datetime) -> datetime:
    return naive_local.replace(tzinfo=NEW_YORK).astimezone(UTC)


def bar_open_time(at: datetime, granularity: Granularity) -> datetime:
    """Open time of the ``granularity`` bar that contains ``at``."""
    at = ensure_utc(at)
    if granularity in (Granularity.D, Granularity.W) or granularity in _NY_ALIGNED_INTRADAY:
        local = at.astimezone(NEW_YORK).replace(tzinfo=None)
        start = _day_start_local(local)
        if granularity is Granularity.D:
            return _from_local(start)
        if granularity is Granularity.W:
            # Weeks align to Friday 17:00 New York (OANDA ``weeklyAlignment=Friday``).
            days_since_friday = (start.weekday() - _FRIDAY) % 7
            return _from_local(start - timedelta(days=days_since_friday))
        step = granularity.seconds
        elapsed = int((local - start).total_seconds()) // step * step
        return _from_local(start + timedelta(seconds=elapsed))
    step = granularity.seconds
    epoch_seconds = int(at.timestamp())
    return datetime.fromtimestamp(epoch_seconds - epoch_seconds % step, tz=UTC)


def bar_close_time(open_time: datetime, granularity: Granularity) -> datetime:
    """Close time (exclusive end) of the bar that opens at ``open_time``."""
    open_time = ensure_utc(open_time)
    if granularity in (Granularity.D, Granularity.W):
        # Add calendar days in New York so DST changes inside the bar are honoured.
        local = open_time.astimezone(NEW_YORK).replace(tzinfo=None)
        days = 1 if granularity is Granularity.D else 7
        return _from_local(local + timedelta(days=days))
    return open_time + granularity.duration
