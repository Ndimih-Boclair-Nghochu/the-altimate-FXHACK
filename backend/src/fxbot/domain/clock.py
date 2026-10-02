"""Injected time. Decision code reads the time only from a ``Clock``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from fxbot.domain.calendar import ensure_utc


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, tz-aware UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def __repr__(self) -> str:
        return "SystemClock()"


class SimClock:
    """Manually driven clock for backtests and tests. Time never moves backwards."""

    def __init__(self, start: datetime) -> None:
        self._now = ensure_utc(start)

    def now(self) -> datetime:
        return self._now

    def set(self, when: datetime) -> None:
        when = ensure_utc(when)
        if when < self._now:
            raise ValueError("SimClock cannot move backwards")
        self._now = when

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValueError("SimClock cannot move backwards")
        self._now += delta
        return self._now

    def __repr__(self) -> str:
        return f"SimClock({self._now.isoformat()})"
