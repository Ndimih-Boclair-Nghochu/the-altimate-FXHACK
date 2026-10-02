"""``OandaFeed``: candles from the REST candles endpoint, live quotes from the pricing stream.

Decision bars come only from the candles endpoint (``price=BA``, ``smooth=false``, complete
candles), polled just after each bar boundary. They are never aggregated from stream ticks:
the stream sends at most four quotes a second per instrument, so tick-built bars would not
match the candles that backtests use. Stream quotes are for monitoring, staleness and spread
checks, and paper fills.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Final

from fxbot.brokers.backoff import Sleep
from fxbot.brokers.oanda.client import OandaClient
from fxbot.brokers.oanda.streaming import OandaPriceStream, StreamPolicy
from fxbot.brokers.oanda.wire import format_time, parse_candle, parse_price
from fxbot.data.resample import (
    BASE_GRANULARITY,
    DERIVED_GRANULARITIES,
    base_window,
    resample_window,
)
from fxbot.domain.calendar import bar_close_time, bar_open_time, ensure_utc, is_market_open
from fxbot.domain.clock import Clock
from fxbot.domain.enums import Granularity
from fxbot.domain.errors import DataIntegrityError
from fxbot.domain.models import Candle, Price
from fxbot.logging import get_logger

log = get_logger(__name__)

MAX_PAGE_SIZE: Final = 5000


class OandaFeed:
    def __init__(
        self,
        client: OandaClient,
        *,
        clock: Clock,
        sleep: Sleep = asyncio.sleep,
        stream_policy: StreamPolicy | None = None,
        page_size: int = MAX_PAGE_SIZE,
        poll_delay: float = 3.0,
        poll_retry_delay: float = 2.0,
        poll_attempts: int = 5,
        owns_client: bool = False,
    ) -> None:
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        self._client = client
        self._clock = clock
        self._sleep = sleep
        self._stream_policy = stream_policy or StreamPolicy()
        self._page_size = page_size
        self._poll_delay = poll_delay
        self._poll_retry_delay = poll_retry_delay
        self._poll_attempts = max(1, poll_attempts)
        self._owns_client = owns_client

    def __repr__(self) -> str:
        return f"OandaFeed(client={self._client!r})"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ candles

    async def get_candles(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Candle]:
        """Complete candles; H2 and coarser are built from H1 with the 17:00 New York alignment."""
        if granularity not in DERIVED_GRANULARITIES:
            return await self._native_candles(instrument, granularity, start, end)
        base_start, base_end = base_window(ensure_utc(start), end, granularity)
        base = await self._native_candles(instrument, BASE_GRANULARITY, base_start, base_end)
        return resample_window(base, granularity, start, end, as_of=self._clock.now())

    async def _native_candles(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime,
        end: datetime | None,
    ) -> list[Candle]:
        candles: list[Candle] = []
        async for page in self.iter_candle_pages(instrument, granularity, start, end):
            candles.extend(page)
        return candles

    async def iter_candle_pages(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime,
        end: datetime | None = None,
        *,
        include_first: bool = True,
    ) -> AsyncIterator[list[Candle]]:
        """Pages of complete candles from ``start`` (exclusive if ``include_first`` is False).

        Only granularities up to H1 are requested from OANDA; coarser bars are built from H1.
        """
        if granularity in DERIVED_GRANULARITIES:
            raise ValueError(f"{granularity.value} bars are built from H1, not downloaded")
        start = ensure_utc(start)
        end = ensure_utc(end) if end is not None else None
        cursor, include = start, include_first
        while True:
            body = await self._client.candles(
                instrument,
                {
                    "price": "BA",
                    "granularity": granularity.value,
                    "smooth": "false",
                    "from": format_time(cursor),
                    "count": str(self._page_size),
                    "includeFirst": "true" if include else "false",
                },
            )
            raw = body.get("candles") or []
            candles = [parse_candle(item, instrument, granularity) for item in raw]
            _check_ascending(candles, after=None if include else cursor)
            page = [
                c
                for c in candles
                if c.complete and c.time >= start and (end is None or c.time < end)
            ]
            if page:
                yield page
            if len(raw) < self._page_size or not candles:
                return
            last = candles[-1]
            if not last.complete or (end is not None and last.time >= end):
                return
            cursor, include = last.time, False

    async def bars(
        self,
        instruments: Sequence[str],
        granularity: Granularity,
        since: datetime | None = None,
    ) -> AsyncIterator[Candle]:
        """Poll the candles endpoint just after each bar boundary and yield new closed bars."""
        last: dict[str, datetime | None] = {
            name: ensure_utc(since) if since is not None else None for name in instruments
        }
        while True:
            now = self._clock.now()
            closing_open = bar_open_time(now, granularity)
            closes_at = bar_close_time(closing_open, granularity)
            await self._sleep((closes_at - now).total_seconds() + self._poll_delay)
            if not is_market_open(closing_open):
                continue
            for name in instruments:
                for candle in await self._fetch_closed(name, granularity, last[name], closing_open):
                    last[name] = candle.time
                    yield candle

    async def _fetch_closed(
        self,
        instrument: str,
        granularity: Granularity,
        after: datetime | None,
        expected_open: datetime,
    ) -> list[Candle]:
        candles: list[Candle] = []
        for attempt in range(self._poll_attempts):
            start = after if after is not None else expected_open
            candles = [
                c
                for c in await self.get_candles(instrument, granularity, start)
                if after is None or c.time > after
            ]
            if any(c.time >= expected_open for c in candles):
                return candles
            if attempt < self._poll_attempts - 1:
                await self._sleep(self._poll_retry_delay)
        log.info(
            "closed bar not available yet",
            instrument=instrument,
            granularity=granularity.value,
            bar=expected_open.isoformat(),
        )
        return candles

    # ------------------------------------------------------------------ prices

    async def latest_prices(self, instruments: Sequence[str]) -> list[Price]:
        body = await self._client.pricing(instruments)
        prices = [parse_price(item) for item in body.get("prices") or []]
        return [price for price in prices if price is not None]

    def stream_prices(self, instruments: Sequence[str]) -> AsyncIterator[Price]:
        stream = OandaPriceStream(
            self._client, instruments, policy=self._stream_policy, sleep=self._sleep
        )
        return stream.prices()


def _check_ascending(candles: Sequence[Candle], *, after: datetime | None) -> None:
    previous = after
    for candle in candles:
        if previous is not None and candle.time <= previous:
            raise DataIntegrityError(
                f"candles for {candle.instrument} are not strictly increasing in time"
            )
        previous = candle.time
