"""OandaFeed: decision bars from the candles endpoint (H4 and D built from H1), and quotes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from fxbot.brokers.oanda.feed import OandaFeed
from fxbot.domain.calendar import is_market_open
from fxbot.domain.clock import SimClock
from fxbot.domain.enums import Granularity
from tests.support import ACCOUNT_PATH, PRACTICE, RecordingSleep, fixture, practice_client

MONDAY = datetime(2024, 3, 4, tzinfo=UTC)


def h1_candle(time: datetime, *, complete: bool = True) -> dict[str, object]:
    hour = time.hour
    price = f"1.{10000 + hour:05d}"
    return {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "bid": {"o": price, "h": f"1.{10100 + hour:05d}", "l": "1.09000", "c": price},
        "ask": {"o": price, "h": f"1.{10101 + hour:05d}", "l": "1.09001", "c": price},
        "volume": 1,
        "complete": complete,
    }


def candles_endpoint(router: respx.Router, clock: SimClock) -> respx.Route:
    """Serves complete H1 candles up to the clock, like the real endpoint."""

    def respond(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params["granularity"] == "H1"
        start = datetime.fromisoformat(params["from"].replace("Z", "+00:00"))
        include = params["includeFirst"] == "true"
        times: list[datetime] = []
        current = start if include else start + timedelta(hours=1)
        while current + timedelta(hours=1) <= clock.now() and len(times) < int(params["count"]):
            if is_market_open(current):
                times.append(current)
            current += timedelta(hours=1)
        return httpx.Response(200, json={"candles": [h1_candle(t) for t in times]})

    return router.get("/v3/instruments/EUR_USD/candles").mock(side_effect=respond)


async def test_h4_candles_are_built_from_h1_with_new_york_alignment() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    clock = SimClock(MONDAY + timedelta(hours=12))
    route = candles_endpoint(router, clock)
    feed = OandaFeed(practice_client(router), clock=clock)

    bars = await feed.get_candles("EUR_USD", Granularity.H4, MONDAY)

    # March 4 is in winter time: New York 17:00 = 22:00 UTC, so H4 opens at 02, 06, 10 UTC.
    assert [b.time.hour for b in bars] == [2, 6]  # 10:00-14:00 has not ended yet
    assert all(call.request.url.params["granularity"] == "H1" for call in route.calls)
    first = bars[0]
    assert first.granularity is Granularity.H4
    assert first.bid.open.to_eng_string() == "1.10002"  # open of the 02:00 H1 bar
    assert first.bid.close.to_eng_string() == "1.10005"  # close of the 05:00 H1 bar
    assert first.bid.high.to_eng_string() == "1.10105"


async def test_bars_poll_after_each_boundary() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    clock = SimClock(MONDAY + timedelta(hours=10, minutes=30))
    candles_endpoint(router, clock)
    sleep = RecordingSleep(clock)
    feed = OandaFeed(practice_client(router), clock=clock, sleep=sleep, poll_delay=3.0)

    bars = feed.bars(["EUR_USD"], Granularity.H1, since=MONDAY + timedelta(hours=9))
    first = await anext(bars)
    second = await anext(bars)

    assert first.time == MONDAY + timedelta(hours=10)
    assert second.time == MONDAY + timedelta(hours=11)
    assert sleep.calls[0] == pytest.approx(30 * 60 + 3.0)  # until 11:00 plus the poll delay


async def test_bars_skip_the_weekend() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    friday = datetime(2024, 3, 8, 21, 30, tzinfo=UTC)  # 16:30 New York
    clock = SimClock(friday)
    route = candles_endpoint(router, clock)
    sleep = RecordingSleep(clock)
    feed = OandaFeed(practice_client(router), clock=clock, sleep=sleep, poll_attempts=1)
    bars = feed.bars(["EUR_USD"], Granularity.H1, since=datetime(2024, 3, 8, 20, tzinfo=UTC))

    friday_last = await anext(bars)
    calls = route.call_count
    sunday_first = await anext(bars)

    assert friday_last.time == datetime(2024, 3, 8, 21, tzinfo=UTC)
    # US daylight saving started on Sunday 10 March: the week opens at 17:00 EDT = 21:00 UTC.
    assert sunday_first.time == datetime(2024, 3, 10, 21, tzinfo=UTC)
    assert route.call_count == calls + 1  # no requests while the market was closed


async def test_missing_bar_is_retried_then_given_up() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    clock = SimClock(MONDAY + timedelta(hours=10, minutes=30))
    route = router.get("/v3/instruments/EUR_USD/candles").respond(json={"candles": []})
    sleep = RecordingSleep(clock)
    feed = OandaFeed(
        practice_client(router), clock=clock, sleep=sleep, poll_attempts=3, poll_retry_delay=2.0
    )

    candles = await feed._fetch_closed(
        "EUR_USD", Granularity.H1, None, MONDAY + timedelta(hours=10)
    )

    assert candles == []
    assert route.call_count == 3 and sleep.calls == [2.0, 2.0]


async def test_latest_prices_and_stream() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    router.get(f"{ACCOUNT_PATH}/pricing").respond(json=fixture("pricing.json"))
    feed = OandaFeed(practice_client(router), clock=SimClock(MONDAY), owns_client=True)

    (price,) = await feed.latest_prices(["EUR_USD"])

    assert price.instrument == "EUR_USD"
    assert repr(feed).startswith("OandaFeed(")
    stream = feed.stream_prices(["EUR_USD"])
    assert hasattr(stream, "__anext__")
    await feed.aclose()


def test_page_size_is_bounded() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    with pytest.raises(ValueError, match="page_size"):
        OandaFeed(practice_client(router), clock=SimClock(MONDAY), page_size=5001)


async def test_coarse_granularities_are_never_downloaded() -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    feed = OandaFeed(practice_client(router), clock=SimClock(MONDAY))

    with pytest.raises(ValueError, match="built from H1"):
        await anext(feed.iter_candle_pages("EUR_USD", Granularity.D, MONDAY))
