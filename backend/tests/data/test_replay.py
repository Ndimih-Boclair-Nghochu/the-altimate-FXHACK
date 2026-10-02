from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fxbot.data.candle_store import CandleStore
from fxbot.data.replay import ReplayFeed, candles_until, ticks_from_candle
from fxbot.domain.clock import SimClock
from fxbot.domain.enums import Granularity
from tests.data.conftest import bar, dataset, hourly
from tests.support import RecordingSleep

START = datetime(2024, 3, 5, 2, tzinfo=UTC)  # an H4 boundary (winter)


async def test_replay_never_returns_unfinished_bars(store: CandleStore) -> None:
    await store.upsert(hourly(START, 12), dataset=dataset())
    clock = SimClock(START + timedelta(hours=6, minutes=30))
    feed = ReplayFeed(store, clock=clock, dataset="test:eurusd")

    h1 = await feed.get_candles("EUR_USD", Granularity.H1, START)
    h4 = await feed.get_candles("EUR_USD", Granularity.H4, START)

    # At 08:30 the 02:00..07:00 bars have closed; the 08:00 bar is still forming.
    assert [c.time.hour for c in h1] == [2, 3, 4, 5, 6, 7]
    assert [c.time.hour for c in h4] == [2]
    assert repr(feed) == "ReplayFeed()"


async def test_replay_bars_are_paced_by_the_clock(store: CandleStore) -> None:
    await store.upsert(hourly(START, 12), dataset=dataset())
    clock = SimClock(START + timedelta(hours=1))
    sleep = RecordingSleep(clock)
    feed = ReplayFeed(store, clock=clock, sleep=sleep)

    bars = feed.bars(["EUR_USD"], Granularity.H4, since=START - timedelta(hours=4))
    first = await anext(bars)
    second = await anext(bars)

    assert (first.time, second.time) == (START, START + timedelta(hours=4))
    assert clock.now() == second.close_time
    assert sleep.calls[0] == 3 * 3600


async def test_replay_prices_from_the_current_bar(store: CandleStore) -> None:
    await store.upsert(hourly(START, 4), dataset=dataset())
    clock = SimClock(START + timedelta(hours=1, minutes=20))
    feed = ReplayFeed(store, clock=clock, sleep=RecordingSleep(clock))

    prices = feed.stream_prices(["EUR_USD"])
    first = await anext(prices)

    assert first.time >= START + timedelta(hours=1, minutes=20)
    assert first.time < START + timedelta(hours=2)
    await feed.aclose()


def test_ticks_from_candle_visit_open_extremes_close() -> None:
    rising = bar(START, mid="1.10000")
    ticks = ticks_from_candle(rising)

    assert [t.bid for t in ticks] == [
        rising.bid.open,
        rising.bid.low,
        rising.bid.high,
        rising.bid.close,
    ]
    assert ticks[0].time == START and ticks[-1].time < rising.close_time
    assert candles_until([rising], START + timedelta(minutes=59)) == []
    assert candles_until([rising], rising.close_time) == [rising]
