"""Pricing and transaction streams: parsing, watchdog, reconnects (httpx mock transport)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Callable, Sequence
from decimal import Decimal

import httpx
import pytest
import respx

from fxbot.brokers.backoff import Backoff
from fxbot.brokers.oanda.streaming import OandaPriceStream, OandaTransactionStream, StreamPolicy
from fxbot.domain.errors import BrokerAuthError, BrokerUnavailableError, FeedStaleError
from fxbot.domain.models import Price
from tests.support import ACCOUNT_PATH, PRACTICE, RecordingSleep, fixture_text, practice_client


class LineStream(httpx.AsyncByteStream):
    """Response body that yields lines, then optionally stalls forever."""

    def __init__(self, lines: Sequence[str], *, stall: bool = False) -> None:
        self._lines = lines
        self._stall = stall

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for line in self._lines:
            yield (line + "\n").encode()
        if self._stall:
            await asyncio.Event().wait()


def stream_transport(
    responses: list[Callable[[], httpx.Response]],
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[min(len(seen), len(responses)) - 1]()

    return httpx.MockTransport(handler), seen


POLICY = StreamPolicy(stale_after=0.2, backoff=Backoff(initial=1.0, maximum=30.0))


def price_stream(
    transport: httpx.MockTransport, sleep: RecordingSleep, policy: StreamPolicy = POLICY
) -> OandaPriceStream:
    client = practice_client(respx.Router(base_url=PRACTICE.rest), stream_transport=transport)
    return OandaPriceStream(
        client, ["EUR_USD", "EUR_JPY"], policy=policy, sleep=sleep, rng=random.Random(5)
    )


async def take(iterator: AsyncIterator[Price], count: int) -> list[Price]:
    return [await anext(iterator) for _ in range(count)]


async def test_parses_prices_and_skips_everything_else() -> None:
    lines = fixture_text("pricing_stream.ndjson").splitlines()
    transport, seen = stream_transport(
        [lambda: httpx.Response(200, stream=LineStream(lines, stall=True))]
    )
    sleep = RecordingSleep()
    stream = price_stream(transport, sleep)

    first, second = await take(stream.prices(), 2)

    assert (first.instrument, first.bid, first.ask) == (
        "EUR_JPY",
        Decimal("114.295"),
        Decimal("114.312"),
    )
    # Heartbeat, blank line, unknown type, malformed JSON and an empty book were skipped.
    assert (second.instrument, second.ask, second.tradeable) == ("EUR_USD", Decimal("1.2018"), True)
    assert second.time.year == 2018  # UNIX-format timestamp parsed
    assert stream.last_heartbeat is not None
    request = seen[0]
    assert request.url.host == httpx.URL(PRACTICE.stream).host
    assert request.url.path == f"{ACCOUNT_PATH}/pricing/stream"
    assert request.url.params["instruments"] == "EUR_USD,EUR_JPY"
    assert request.url.params["snapshot"] == "true"
    assert "token" not in str(request.url).lower()


async def test_stall_raises_feed_stale() -> None:
    heartbeat = '{"type":"HEARTBEAT","time":"2016-10-27T08:38:44.327443673Z"}'
    transport, _ = stream_transport(
        [lambda: httpx.Response(200, stream=LineStream([heartbeat], stall=True))]
    )
    stream = price_stream(transport, RecordingSleep())

    with pytest.raises(FeedStaleError, match="nothing received"):
        await anext(stream.prices())


async def test_reconnects_after_disconnect_with_capped_backoff() -> None:
    price = fixture_text("pricing_stream.ndjson").splitlines()[0]
    responses: list[Callable[[], httpx.Response]] = [
        lambda: httpx.Response(200, stream=LineStream([])),  # closed by the server
        lambda: httpx.Response(503),
        lambda: httpx.Response(503),
        lambda: httpx.Response(503),
        lambda: httpx.Response(503),
        lambda: httpx.Response(503),
        lambda: httpx.Response(503),
        lambda: httpx.Response(200, stream=LineStream([price], stall=True)),
    ]
    transport, seen = stream_transport(responses)
    sleep = RecordingSleep()
    stream = price_stream(transport, sleep)

    (received,) = await take(stream.prices(), 1)

    assert received.instrument == "EUR_JPY"
    assert len(seen) == 8 and stream.reconnects == 7
    nominal = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert len(sleep.calls) == len(nominal)
    for delay, cap in zip(sleep.calls, nominal, strict=True):
        assert cap / 2 <= delay <= cap  # jittered, never faster than half the nominal delay
    assert min(sleep.calls) >= 0.5  # never more than two connection attempts a second


async def test_429_waits_at_least_retry_after() -> None:
    price = fixture_text("pricing_stream.ndjson").splitlines()[0]
    transport, _ = stream_transport(
        [
            lambda: httpx.Response(429, headers={"Retry-After": "12"}),
            lambda: httpx.Response(200, stream=LineStream([price], stall=True)),
        ]
    )
    sleep = RecordingSleep()

    await take(price_stream(transport, sleep).prices(), 1)

    assert sleep.calls[0] >= 12


async def test_gives_up_after_max_reconnects() -> None:
    transport, seen = stream_transport([lambda: httpx.Response(500)])
    policy = StreamPolicy(stale_after=0.2, max_reconnects=2)

    with pytest.raises(BrokerUnavailableError, match="gave up"):
        await anext(price_stream(transport, RecordingSleep(), policy).prices())

    assert len(seen) == 3


async def test_auth_failure_is_not_retried() -> None:
    transport, seen = stream_transport([lambda: httpx.Response(401, json={"errorMessage": "x"})])

    with pytest.raises(BrokerAuthError):
        await anext(price_stream(transport, RecordingSleep()).prices())

    assert len(seen) == 1


async def test_transport_errors_reconnect() -> None:
    price = fixture_text("pricing_stream.ndjson").splitlines()[0]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadError("connection reset")
        return httpx.Response(200, stream=LineStream([price], stall=True))

    sleep = RecordingSleep()
    stream = price_stream(httpx.MockTransport(handler), sleep)

    await take(stream.prices(), 1)

    assert calls == 2 and len(sleep.calls) == 1


async def test_transaction_stream() -> None:
    lines = fixture_text("transaction_stream.ndjson").splitlines()
    transport, seen = stream_transport(
        [lambda: httpx.Response(200, stream=LineStream([*lines, '{"id": "x"}'], stall=True))]
    )
    client = practice_client(respx.Router(base_url=PRACTICE.rest), stream_transport=transport)
    stream = OandaTransactionStream(client, policy=POLICY, sleep=RecordingSleep())

    transactions = stream.transactions()
    transaction = await anext(transactions)

    assert (transaction.id, transaction.type) == ("16389", "MARKET_ORDER")
    assert "accountID" not in transaction.payload
    assert stream.last_heartbeat is not None
    assert seen[0].url.path == f"{ACCOUNT_PATH}/transactions/stream"
    with pytest.raises(FeedStaleError):  # the invalid line is skipped, then the stream stalls
        await anext(transactions)
    assert repr(stream) == "OandaTransactionStream()"
