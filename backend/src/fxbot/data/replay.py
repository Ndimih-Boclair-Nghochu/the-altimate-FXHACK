"""``ReplayFeed``: stored candles released as the clock passes them, plus shared pacing helpers.

Used for paper trading on recorded data and by the synthetic feed. With a ``SimClock`` whose
sleep advances the clock, replays run as fast as the consumer reads.
"""

from __future__ import annotations

import asyncio
import heapq
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from datetime import datetime, timedelta

from fxbot.brokers.backoff import Sleep
from fxbot.data.candle_store import CandleStore
from fxbot.data.resample import (
    BASE_GRANULARITY,
    DERIVED_GRANULARITIES,
    base_window,
    resample,
    resample_window,
)
from fxbot.domain.calendar import ensure_utc
from fxbot.domain.clock import Clock
from fxbot.domain.enums import Granularity
from fxbot.domain.models import Candle, Price


def candles_until(candles: Iterable[Candle], now: datetime) -> list[Candle]:
    """Candles that have closed by ``now`` (no lookahead)."""
    return [c for c in candles if c.close_time <= now]


def ticks_from_candle(candle: Candle) -> list[Price]:
    """Four quotes per bar: open, the two extremes (in a plausible order), close."""
    step = (candle.close_time - candle.time) / 4
    rising = candle.bid.close >= candle.bid.open
    extremes = [(candle.bid.low, candle.ask.low), (candle.bid.high, candle.ask.high)]
    if not rising:
        extremes.reverse()
    points = [
        (candle.time, candle.bid.open, candle.ask.open),
        (candle.time + step, *extremes[0]),
        (candle.time + 2 * step, *extremes[1]),
        (candle.close_time - timedelta(microseconds=1), candle.bid.close, candle.ask.close),
    ]
    return [
        Price(instrument=candle.instrument, time=when, bid=bid, ask=ask)
        for when, bid, ask in points
    ]


async def _wait_until(when: datetime, clock: Clock, sleep: Sleep) -> None:
    delay = (when - clock.now()).total_seconds()
    if delay > 0:
        await sleep(delay)


async def paced_bars(
    series: Sequence[Sequence[Candle]],
    clock: Clock,
    sleep: Sleep,
    *,
    since: datetime | None = None,
) -> AsyncIterator[Candle]:
    """Merge per-instrument series and yield each candle once it has closed."""
    since = ensure_utc(since) if since is not None else None
    for candle in heapq.merge(*series, key=lambda c: (c.close_time, c.instrument)):
        if since is not None and candle.time <= since:
            continue
        await _wait_until(candle.close_time, clock, sleep)
        yield candle


async def paced_prices(
    series: Sequence[Sequence[Candle]],
    clock: Clock,
    sleep: Sleep,
    to_ticks: Callable[[Candle], list[Price]] = ticks_from_candle,
) -> AsyncIterator[Price]:
    """Quotes derived from candles, from the current time on, each at its own time."""
    start = clock.now()
    for candle in heapq.merge(*series, key=lambda c: (c.time, c.instrument)):
        if candle.close_time <= start:
            continue
        for tick in to_ticks(candle):
            if tick.time < start:
                continue
            await _wait_until(tick.time, clock, sleep)
            yield tick


class ReplayFeed:
    """``MarketDataFeed`` over the local candle store."""

    def __init__(
        self,
        store: CandleStore,
        *,
        clock: Clock,
        sleep: Sleep = asyncio.sleep,
        tick_granularity: Granularity = Granularity.H1,
        lookback: timedelta = timedelta(days=30),
        dataset: str | None = None,
    ) -> None:
        self._store = store
        self._dataset = dataset
        self._clock = clock
        self._sleep = sleep
        self._tick_granularity = tick_granularity
        self._lookback = lookback

    def __repr__(self) -> str:
        return "ReplayFeed()"

    async def aclose(self) -> None:
        return None

    async def get_candles(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Candle]:
        now = self._clock.now()
        end = min(ensure_utc(end), now) if end is not None else now
        if granularity in DERIVED_GRANULARITIES:
            base_start, base_end = base_window(ensure_utc(start), end, granularity)
            base = await self._store.get_candles(
                instrument, BASE_GRANULARITY, base_start, base_end, dataset=self._dataset
            )
            return resample_window(base, granularity, start, end, as_of=now)
        candles = await self._store.get_candles(
            instrument, granularity, start, end, dataset=self._dataset
        )
        return candles_until(candles, now)

    async def bars(
        self,
        instruments: Sequence[str],
        granularity: Granularity,
        since: datetime | None = None,
    ) -> AsyncIterator[Candle]:
        start = since if since is not None else self._clock.now() - self._lookback
        series = [await self._series(name, granularity, start) for name in instruments]
        async for candle in paced_bars(series, self._clock, self._sleep, since=since):
            yield candle

    async def _series(
        self, instrument: str, granularity: Granularity, start: datetime
    ) -> list[Candle]:
        """All stored candles from ``start``, future ones included (they are paced later)."""
        if granularity in DERIVED_GRANULARITIES:
            base_start, _ = base_window(ensure_utc(start), None, granularity)
            base = await self._store.get_candles(
                instrument, BASE_GRANULARITY, base_start, dataset=self._dataset
            )
            return [c for c in resample(base, granularity) if c.time >= start]
        return await self._store.get_candles(instrument, granularity, start, dataset=self._dataset)

    async def stream_prices(self, instruments: Sequence[str]) -> AsyncIterator[Price]:
        start = self._clock.now() - self._tick_granularity.duration
        series = [
            await self._store.get_candles(
                name, self._tick_granularity, start, dataset=self._dataset
            )
            for name in instruments
        ]
        async for price in paced_prices(series, self._clock, self._sleep):
            yield price
