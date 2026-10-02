"""Broker server time → UTC.

Some platforms (MetaTrader 5) stamp bars, ticks and deals in the broker's *server* wall
clock, not UTC. Converting needs an explicit policy per broker; nothing here assumes UTC.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fxbot.domain.calendar import DAY_START_NY, NEW_YORK, ensure_utc

_EPOCH: Final = datetime(1970, 1, 1)


class ServerTimePolicy(Protocol):
    def to_utc(self, server_time: datetime) -> datetime:
        """Convert a naive server wall-clock time to tz-aware UTC."""
        ...

    def from_utc(self, utc_time: datetime) -> datetime:
        """Convert a UTC time to the naive server wall clock (for requests by time range)."""
        ...


def _require_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        raise ValueError("server time must be naive wall-clock time; convert it with a policy")
    return value


@dataclass(frozen=True, slots=True)
class FixedOffsetServerTime:
    """Server clock at a constant offset from UTC (``hours=0`` for brokers that use UTC)."""

    hours: float

    def to_utc(self, server_time: datetime) -> datetime:
        return (_require_naive(server_time) - timedelta(hours=self.hours)).replace(tzinfo=UTC)

    def from_utc(self, utc_time: datetime) -> datetime:
        return ensure_utc(utc_time).replace(tzinfo=None) + timedelta(hours=self.hours)


@dataclass(frozen=True, slots=True)
class ZoneServerTime:
    """Server clock that follows an IANA time zone, e.g. ``Europe/Athens``."""

    zone: str

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown time zone {self.zone!r}") from None

    def to_utc(self, server_time: datetime) -> datetime:
        return _require_naive(server_time).replace(tzinfo=ZoneInfo(self.zone)).astimezone(UTC)

    def from_utc(self, utc_time: datetime) -> datetime:
        return ensure_utc(utc_time).astimezone(ZoneInfo(self.zone)).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class NewYorkCloseServerTime:
    """Server midnight is 17:00 New York all year (the common MT5 "GMT+2/+3, US DST" clock).

    Equivalent to New York time shifted by ``hours_ahead_of_new_york`` (7 by default), so
    daily bars open at server 00:00 and the week has five full daily bars.
    """

    hours_ahead_of_new_york: int = 7

    def to_utc(self, server_time: datetime) -> datetime:
        local_ny = _require_naive(server_time) - timedelta(hours=self.hours_ahead_of_new_york)
        return local_ny.replace(tzinfo=NEW_YORK).astimezone(UTC)

    def from_utc(self, utc_time: datetime) -> datetime:
        local_ny = ensure_utc(utc_time).astimezone(NEW_YORK).replace(tzinfo=None)
        return local_ny + timedelta(hours=self.hours_ahead_of_new_york)


def infer_new_york_shift(week_open_times: Iterable[datetime]) -> NewYorkCloseServerTime | None:
    """Detect "server = New York + k hours" from each week's first bar (server wall time).

    The FX week opens on Sunday 17:00 New York. If the first bar of every week is the same
    number of whole hours after that, across US and EU daylight-saving changes, the server
    clock follows New York (research 08 §A.10). Otherwise there is no such rule: ``None``.
    """
    shifts: set[float] = set()
    for opened in week_open_times:
        opened = _require_naive(opened)
        days_since_sunday = (opened.weekday() + 1) % 7
        sunday_open = datetime.combine(
            opened.date() - timedelta(days=days_since_sunday), DAY_START_NY
        )
        if sunday_open > opened:
            sunday_open -= timedelta(days=7)
        shifts.add((opened - sunday_open).total_seconds() / 3600)
    if len(shifts) != 1:
        return None
    shift = shifts.pop()
    return NewYorkCloseServerTime(int(shift)) if shift.is_integer() and 0 <= shift < 24 else None


def from_server_epoch(seconds: int | float, policy: ServerTimePolicy) -> datetime:
    """MT5-style timestamps: seconds since 1970 *in the server's wall clock*, not UTC."""
    return policy.to_utc(_EPOCH + timedelta(seconds=seconds))


_FIXED: Final = re.compile(r"^(?:utc)?([+-]\d{1,2}(?:\.\d+)?)$", re.IGNORECASE)


def parse_server_time_policy(spec: str) -> ServerTimePolicy:
    """Parse ``utc``, ``utc+2`` / ``+2``, ``ny-close`` or an IANA zone like ``Europe/Athens``."""
    text = spec.strip()
    if text.lower() == "utc":
        return FixedOffsetServerTime(0)
    if text.lower() == "ny-close":
        return NewYorkCloseServerTime()
    if match := _FIXED.match(text):
        return FixedOffsetServerTime(float(match.group(1)))
    return ZoneServerTime(text)
