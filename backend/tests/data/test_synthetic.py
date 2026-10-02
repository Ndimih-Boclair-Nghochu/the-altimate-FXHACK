from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from fxbot.data.spreads import hour_of_week
from fxbot.data.synthetic import (
    SyntheticConfig,
    SyntheticFeed,
    SyntheticRegime,
    SyntheticSeries,
    generate,
)
from fxbot.domain.calendar import NEW_YORK, is_market_open
from fxbot.domain.clock import SimClock
from fxbot.domain.enums import AskSource, Granularity
from fxbot.domain.errors import ConfigurationError
from tests.support import RecordingSleep

CONFIG = SyntheticConfig(bars=3000, seed=11)


@pytest.fixture(scope="module")
def series() -> SyntheticSeries:
    return generate(CONFIG)


def test_same_seed_gives_identical_series(series: SyntheticSeries) -> None:
    assert generate(CONFIG) == series
    assert generate(replace(CONFIG, seed=12)).candles != series.candles
    assert generate(replace(CONFIG, instrument="USD_JPY")).candles[0].bid.open > 100


def test_ohlc_and_spread_invariants(series: SyntheticSeries) -> None:
    for candle in series.candles:  # also enforced by the model; asserted here for clarity
        for side in (candle.bid, candle.ask):
            assert side.low <= min(side.open, side.close) <= max(side.open, side.close) <= side.high
        assert candle.bid.open <= candle.ask.open and candle.bid.close <= candle.ask.close
        assert candle.bid.high <= candle.ask.high and candle.bid.low <= candle.ask.low
        assert candle.ask_source is AskSource.SYNTHETIC
        assert candle.bid.open == candle.bid.open.quantize(Decimal("0.00001"))  # quantized


def test_no_bars_while_the_market_is_closed_and_weekend_gaps(series: SyntheticSeries) -> None:
    candles = series.candles
    assert all(is_market_open(c.time) for c in candles)
    weekend_opens = [
        i
        for i in range(1, len(candles))
        if candles[i].time - candles[i - 1].time > timedelta(hours=1)
    ]
    assert len(weekend_opens) >= 15
    gaps = [abs(candles[i].mid.open - candles[i - 1].mid.close) for i in weekend_opens]
    assert sum(1 for g in gaps if g > 0) >= len(gaps) * 0.8  # prices jump across weekends
    continuous = [
        abs(candles[i].mid.open - candles[i - 1].mid.close)
        for i in range(1, 200)
        if i not in weekend_opens
    ]
    assert max(continuous) < max(gaps)


def test_regime_segments_are_distinguishable(series: SyntheticSeries) -> None:
    closes = np.array([float(c.mid.close) for c in series.candles])
    opens = np.array([float(c.mid.open) for c in series.candles])
    efficiency: dict[SyntheticRegime, list[float]] = {r: [] for r in SyntheticRegime}
    volatility: dict[SyntheticRegime, list[float]] = {r: [] for r in SyntheticRegime}
    for begin, end, regime in series.segments:
        if end - begin < 40:
            continue
        returns = np.log(closes[begin:end] / opens[begin:end])
        efficiency[regime].append(abs(returns.sum()) / np.abs(returns).sum())
        volatility[regime].append(float(returns.std()))

    assert all(efficiency.values()), "each regime appears in the sample"
    median_er = {r: statistics.median(v) for r, v in efficiency.items()}
    median_vol = {r: statistics.median(v) for r, v in volatility.items()}
    assert median_er[SyntheticRegime.TREND] > 3 * median_er[SyntheticRegime.MEAN_REVERT]
    assert median_vol[SyntheticRegime.VOL_BURST] > 2 * median_vol[SyntheticRegime.MEAN_REVERT]
    assert len(series.regimes) == len(series.candles)


def test_spreads_widen_at_the_new_york_rollover(series: SyntheticSeries) -> None:
    by_hour: dict[int, list[float]] = {}
    for candle in series.candles:
        local_hour = candle.time.astimezone(NEW_YORK).hour
        by_hour.setdefault(local_hour, []).append(float(candle.spread_open))
    rollover = statistics.median(by_hour[17])
    london = statistics.median(by_hour[4])
    assert rollover > 2.5 * london
    assert 0.8e-4 < london < 2.5e-4  # around 1.3 pips for EUR/USD
    assert hour_of_week(series.candles[0].time) == 6 * 24 + 17  # Sunday 17:00 New York


def test_unknown_instrument_and_empty_series() -> None:
    with pytest.raises(ConfigurationError):
        generate(replace(CONFIG, instrument="XAU_USD"))
    assert generate(replace(CONFIG, bars=0)).candles == ()


async def test_feed_releases_bars_as_the_clock_passes() -> None:
    start = datetime(2024, 1, 7, 22, tzinfo=UTC)
    clock = SimClock(start + timedelta(hours=10))
    sleep = RecordingSleep(clock)
    feed = SyntheticFeed(
        ["EUR_USD", "GBP_USD"],
        clock=clock,
        base=replace(CONFIG, start=start, bars=100),
        sleep=sleep,
    )

    history = await feed.get_candles("EUR_USD", Granularity.H1, start)
    assert len(history) == 10  # nothing from the future
    h4 = await feed.get_candles("EUR_USD", Granularity.H4, start)
    assert [c.time.hour for c in h4] == [22, 2]

    bars = feed.bars(["EUR_USD", "GBP_USD"], Granularity.H1, since=history[-1].time)
    first, second, third = [await anext(bars) for _ in range(3)]
    assert {first.instrument, second.instrument} == {"EUR_USD", "GBP_USD"}
    assert first.time == second.time == start + timedelta(hours=10)
    assert third.time == start + timedelta(hours=11)
    assert clock.now() >= third.close_time

    prices = feed.stream_prices(["EUR_USD"])
    tick = await anext(prices)
    assert tick.time >= third.close_time - timedelta(hours=1)
    assert "EUR_USD" in repr(feed)
    with pytest.raises(ConfigurationError):
        await feed.get_candles("USD_CAD", Granularity.H1, start)
    with pytest.raises(ConfigurationError):
        await feed.get_candles("EUR_USD", Granularity.M5, start)
    await feed.aclose()
