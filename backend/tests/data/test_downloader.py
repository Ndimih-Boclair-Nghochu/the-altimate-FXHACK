from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import respx

from fxbot.brokers.oanda.feed import OandaFeed
from fxbot.data.candle_store import CandleStore
from fxbot.data.downloader import HistoricalDownloader, oanda_dataset
from fxbot.domain.clock import SimClock
from fxbot.domain.enums import Granularity
from tests.support import PRACTICE, practice_client

START = datetime(2024, 3, 4, tzinfo=UTC)
DATASET = oanda_dataset("practice", "EUR_USD", Granularity.H1)


def candle_json(time: datetime, *, complete: bool = True) -> dict[str, object]:
    return {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "bid": {"o": "1.10000", "h": "1.10100", "l": "1.09900", "c": "1.10050"},
        "ask": {"o": "1.10010", "h": "1.10110", "l": "1.09910", "c": "1.10060"},
        "volume": 3,
        "complete": complete,
    }


def endpoint(router: respx.Router, available_hours: int) -> respx.Route:
    """Hours [0, available_hours) are complete; the next one is still forming."""

    def respond(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert params["price"] == "BA"
        cursor = datetime.fromisoformat(params["from"].replace("Z", "+00:00"))
        first = cursor if params["includeFirst"] == "true" else cursor + timedelta(hours=1)
        hour = int((first - START).total_seconds() // 3600)
        items = [
            candle_json(START + timedelta(hours=h))
            for h in range(hour, min(hour + int(params["count"]), available_hours))
        ]
        if len(items) < int(params["count"]):
            items.append(candle_json(START + timedelta(hours=available_hours), complete=False))
        return httpx.Response(200, json={"candles": items})

    return router.get("/v3/instruments/EUR_USD/candles").mock(side_effect=respond)


async def test_downloads_complete_candles_page_by_page(store: CandleStore) -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    route = endpoint(router, available_hours=10)
    feed = OandaFeed(
        practice_client(router), clock=SimClock(START + timedelta(days=1)), page_size=4
    )

    report = await HistoricalDownloader(feed, store).download(
        "EUR_USD", Granularity.H1, START, dataset=DATASET
    )

    assert report.stored == 10 and report.resumed_from is None
    assert (report.first, report.last) == (START, START + timedelta(hours=9))
    stored = await store.get_candles("EUR_USD", Granularity.H1)
    assert len(stored) == 10 and all(c.complete for c in stored)  # the forming bar was dropped
    assert route.call_count == 3
    (provenance,) = await store.datasets("EUR_USD", Granularity.H1)
    assert provenance.price_side == "BA" and provenance.source == "oanda-practice"


async def test_resumes_from_the_last_stored_candle(store: CandleStore) -> None:
    router = respx.Router(base_url=PRACTICE.rest)
    endpoint(router, available_hours=6)
    feed = OandaFeed(practice_client(router), clock=SimClock(START + timedelta(days=1)))
    downloader = HistoricalDownloader(feed, store)
    await downloader.download("EUR_USD", Granularity.H1, START, dataset=DATASET)

    router2 = respx.Router(base_url=PRACTICE.rest)
    route = endpoint(router2, available_hours=9)
    feed2 = OandaFeed(practice_client(router2), clock=SimClock(START + timedelta(days=1)))
    report = await HistoricalDownloader(feed2, store).download(
        "EUR_USD", Granularity.H1, START, dataset=DATASET
    )

    params = route.calls.last.request.url.params
    assert params["includeFirst"] == "false"
    assert params["from"].startswith("2024-03-04T05:00:00")
    assert report.resumed_from == START + timedelta(hours=5)
    assert report.stored == 3
    assert len(await store.get_candles("EUR_USD", Granularity.H1)) == 9
    assert repr(downloader) == "HistoricalDownloader()"
