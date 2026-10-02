"""Seeded synthetic FX data: regime-switching prices with bid/ask spreads and weekend gaps.

Used in CI and for paper trading without an account. The generator is deterministic for a
given configuration and seed. Realism features:

- regimes: trend (drift), mean reversion (pull to an anchor) and volatility bursts, in
  segments of random length;
- stochastic volatility and an intraday activity profile;
- no bars while the market is closed (Friday 17:00 to Sunday 17:00 New York), and a price gap
  across each weekend;
- spreads that widen around the 17:00 New York rollover, at the Sunday open and in bursts
  (``spreads.session_multiplier``).

It is a test fixture, not a market model: never draw conclusions about strategy edge from it.
"""

from __future__ import annotations

import asyncio
import zlib
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Final

import numpy as np

from fxbot.brokers.backoff import Sleep
from fxbot.data.replay import candles_until, paced_bars, paced_prices, ticks_from_candle
from fxbot.data.resample import resample
from fxbot.data.spreads import TYPICAL_SPREAD_PIPS, session_multiplier
from fxbot.domain.calendar import (
    bar_close_time,
    bar_open_time,
    ensure_utc,
    is_market_open,
)
from fxbot.domain.clock import Clock
from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.errors import ConfigurationError
from fxbot.domain.instruments import DEFAULT_INSTRUMENTS
from fxbot.domain.models import OHLC, Candle, Instrument, Price

# Typical mid price per instrument; spreads come from ``spreads.TYPICAL_SPREAD_PIPS``.
_PRICES: Final[dict[str, float]] = {
    "EUR_USD": 1.10,
    "GBP_USD": 1.27,
    "USD_JPY": 150.0,
    "AUD_USD": 0.66,
    "USD_CAD": 1.36,
    "NZD_USD": 0.61,
    "USD_CHF": 0.88,
    "EUR_GBP": 0.86,
    "EUR_JPY": 162.0,
    "GBP_JPY": 190.0,
    "EUR_CHF": 0.95,
    "AUD_JPY": 99.0,
}
_SECONDS_PER_YEAR: Final = 252 * 24 * 3600


class SyntheticRegime(StrEnum):
    TREND = "trend"
    MEAN_REVERT = "mean_revert"
    VOL_BURST = "vol_burst"


@dataclass(frozen=True, slots=True)
class SyntheticConfig:
    instrument: str = "EUR_USD"
    granularity: Granularity = Granularity.H1
    start: datetime = datetime(2024, 1, 7, 22, 0, tzinfo=UTC)  # a Sunday open
    bars: int = 2000
    seed: int = 7
    initial_price: float | None = None  # default from the instrument profile
    base_spread_pips: float | None = None
    annual_vol: float = 0.08
    vol_of_vol: float = 0.10
    segment_bars: tuple[int, int] = (60, 240)
    regime_weights: tuple[float, float, float] = (0.4, 0.4, 0.2)  # trend, mean revert, burst
    trend_drift: float = 0.25  # drift per bar, in units of the bar's volatility
    mean_reversion: float = 0.10  # share of the distance to the anchor closed per bar
    burst_multiplier: float = 3.0
    weekend_gap_vol: float = 0.0015  # standard deviation of the weekend gap (log return)


@dataclass(frozen=True, slots=True)
class SyntheticSeries:
    candles: tuple[Candle, ...]
    regimes: tuple[SyntheticRegime, ...]  # regime of each candle
    segments: tuple[tuple[int, int, SyntheticRegime], ...] = field(default=())  # [start, end)


def instrument_seed(seed: int, instrument: str) -> int:
    """Stable per-instrument seed (``hash()`` is randomised per process)."""
    return (seed * 1_000_003 + zlib.crc32(instrument.encode())) % (2**32)


def _bar_times(start: datetime, granularity: Granularity, count: int) -> list[datetime]:
    times: list[datetime] = []
    current = bar_open_time(ensure_utc(start), granularity)
    while len(times) < count:
        if is_market_open(current):
            times.append(current)
        current = bar_close_time(current, granularity)
    return times


def _activity(hour_utc: int) -> float:
    """Relative activity by UTC hour: quiet Asia, busy London/New York overlap."""
    if 7 <= hour_utc < 12:
        return 1.2
    if 12 <= hour_utc < 17:
        return 1.3
    if 17 <= hour_utc < 21:
        return 0.9
    return 0.7


def _regime_segments(
    count: int, config: SyntheticConfig, rng: np.random.Generator
) -> list[tuple[int, int, SyntheticRegime, int]]:
    regimes = list(SyntheticRegime)
    weights = np.asarray(config.regime_weights, dtype=float)
    weights = weights / weights.sum()
    low, high = config.segment_bars
    segments: list[tuple[int, int, SyntheticRegime, int]] = []
    position, previous = 0, -1
    while position < count:
        choice = int(rng.choice(len(regimes), p=weights))
        if choice == previous:  # avoid merging consecutive segments of the same regime
            choice = int(rng.choice(len(regimes), p=weights))
        length = int(rng.integers(low, high + 1))
        direction = 1 if rng.random() < 0.5 else -1
        end = min(count, position + length)
        segments.append((position, end, regimes[choice], direction))
        position, previous = end, choice
    return segments


def _quantize(values: np.ndarray, places: int) -> list[Decimal]:
    return [Decimal(f"{value:.{places}f}") for value in values]


def generate(config: SyntheticConfig) -> SyntheticSeries:
    instrument: Instrument | None = DEFAULT_INSTRUMENTS.get(config.instrument)
    if instrument is None:
        raise ConfigurationError(f"no synthetic profile for {config.instrument}")
    if config.bars <= 0:
        return SyntheticSeries(candles=(), regimes=())
    price0 = config.initial_price or _PRICES.get(config.instrument, 1.0)
    spread_pips = config.base_spread_pips or float(TYPICAL_SPREAD_PIPS.get(config.instrument, 2))
    rng = np.random.default_rng(instrument_seed(config.seed, config.instrument))

    times = _bar_times(config.start, config.granularity, config.bars)
    n = len(times)
    bar_sigma = config.annual_vol * np.sqrt(config.granularity.seconds / _SECONDS_PER_YEAR)
    segments = _regime_segments(n, config, rng)

    regime_of = np.empty(n, dtype=object)
    direction = np.zeros(n)
    for begin, end, regime, sign in segments:
        regime_of[begin:end] = regime
        direction[begin:end] = sign

    # Stochastic volatility: AR(1) log-volatility around 0, times activity and bursts.
    log_vol = np.zeros(n)
    shocks = rng.standard_normal(n)
    for i in range(1, n):
        log_vol[i] = 0.98 * log_vol[i - 1] + config.vol_of_vol * shocks[i]
    activity = np.array([_activity(t.hour) for t in times])
    burst = np.array(
        [config.burst_multiplier if r is SyntheticRegime.VOL_BURST else 1.0 for r in regime_of]
    )
    sigma = bar_sigma * np.exp(log_vol) * activity * burst

    noise = rng.standard_normal(n)
    gap_noise = rng.standard_normal(n)
    wick_up = np.abs(rng.standard_normal(n))
    wick_down = np.abs(rng.standard_normal(n))
    spread_noise = rng.lognormal(0.0, 0.15, size=(n, 2))

    x_open = np.empty(n)
    x_close = np.empty(n)
    x = float(np.log(price0))
    anchor = x
    segment_starts = {begin for begin, _, _, _ in segments}
    for i in range(n):
        gapped = i > 0 and bar_close_time(times[i - 1], config.granularity) != times[i]
        if gapped:
            x += config.weekend_gap_vol * gap_noise[i]
        if i in segment_starts:
            anchor = x
        x_open[i] = x
        regime = regime_of[i]
        if regime is SyntheticRegime.TREND:
            step = direction[i] * config.trend_drift * sigma[i] + sigma[i] * noise[i]
        elif regime is SyntheticRegime.MEAN_REVERT:
            step = -config.mean_reversion * (x - anchor) + sigma[i] * noise[i]
        else:
            step = sigma[i] * noise[i]
        x += step
        x_close[i] = x

    x_high = np.maximum(x_open, x_close) + 0.5 * sigma * wick_up
    x_low = np.minimum(x_open, x_close) - 0.5 * sigma * wick_down
    mid_open, mid_close = np.exp(x_open), np.exp(x_close)
    mid_high, mid_low = np.exp(x_high), np.exp(x_low)

    pip = float(instrument.pip_size)
    spread_open = (
        np.array(
            [
                spread_pips * pip * float(session_multiplier(t)) * (1.5 if b > 1 else 1.0)
                for t, b in zip(times, burst, strict=True)
            ]
        )
        * spread_noise[:, 0]
    )
    spread_close = (
        np.array(
            [
                spread_pips
                * pip
                * float(
                    session_multiplier(bar_close_time(t, config.granularity) - timedelta(seconds=1))
                )
                * (1.5 if b > 1 else 1.0)
                for t, b in zip(times, burst, strict=True)
            ]
        )
        * spread_noise[:, 1]
    )
    spread_mid = (spread_open + spread_close) / 2

    bid_open, ask_open = mid_open - spread_open / 2, mid_open + spread_open / 2
    bid_close, ask_close = mid_close - spread_close / 2, mid_close + spread_close / 2
    bid_high = np.maximum.reduce([mid_high - spread_mid / 2, bid_open, bid_close])
    bid_low = np.minimum.reduce([mid_low - spread_mid / 2, bid_open, bid_close])
    ask_high = np.maximum.reduce([mid_high + spread_mid / 2, ask_open, ask_close])
    ask_low = np.minimum.reduce([mid_low + spread_mid / 2, ask_open, ask_close])

    places = instrument.display_precision
    columns = [
        _quantize(values, places)
        for values in (
            bid_open,
            bid_high,
            bid_low,
            bid_close,
            ask_open,
            ask_high,
            ask_low,
            ask_close,
        )
    ]
    hours = config.granularity.seconds / 3600
    volume = rng.poisson(lam=np.maximum(1.0, 800 * hours * activity * np.exp(log_vol) * burst))

    candles = tuple(
        Candle(
            instrument=config.instrument,
            granularity=config.granularity,
            time=times[i],
            bid=OHLC(
                open=columns[0][i], high=columns[1][i], low=columns[2][i], close=columns[3][i]
            ),
            ask=OHLC(
                open=columns[4][i], high=columns[5][i], low=columns[6][i], close=columns[7][i]
            ),
            volume=int(volume[i]),
            complete=True,
            ask_source=AskSource.SYNTHETIC,
        )
        for i in range(n)
    )
    return SyntheticSeries(
        candles=candles,
        regimes=tuple(regime_of.tolist()),
        segments=tuple((begin, end, regime) for begin, end, regime, _ in segments),
    )


class SyntheticFeed:
    """``MarketDataFeed`` over pre-generated series, released as the clock passes each bar."""

    def __init__(
        self,
        instruments: Iterable[str],
        *,
        clock: Clock,
        base: SyntheticConfig | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        base = base or SyntheticConfig()
        self._clock = clock
        self._sleep = sleep
        self._base = base.granularity
        self._series = {
            name: generate(replace(base, instrument=name)).candles for name in instruments
        }

    def __repr__(self) -> str:
        return f"SyntheticFeed(instruments={sorted(self._series)!r})"

    async def aclose(self) -> None:
        return None

    def _candles(self, instrument: str, granularity: Granularity) -> Sequence[Candle]:
        try:
            series = self._series[instrument]
        except KeyError:
            raise ConfigurationError(f"synthetic feed has no {instrument}") from None
        if granularity == self._base:
            return series
        if granularity.duration < self._base.duration:
            raise ConfigurationError(f"synthetic feed is generated at {self._base.value}")
        return resample(series, granularity)

    async def get_candles(
        self,
        instrument: str,
        granularity: Granularity,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Candle]:
        start = ensure_utc(start)
        now = self._clock.now()
        end = min(ensure_utc(end), now) if end is not None else now
        return [
            c
            for c in candles_until(self._candles(instrument, granularity), now)
            if start <= c.time < end
        ]

    def bars(
        self,
        instruments: Sequence[str],
        granularity: Granularity,
        since: datetime | None = None,
    ) -> AsyncIterator[Candle]:
        series = [self._candles(name, granularity) for name in instruments]
        return paced_bars(series, self._clock, self._sleep, since=since)

    def stream_prices(self, instruments: Sequence[str]) -> AsyncIterator[Price]:
        series = [self._candles(name, self._base) for name in instruments]
        return paced_prices(series, self._clock, self._sleep, ticks_from_candle)
