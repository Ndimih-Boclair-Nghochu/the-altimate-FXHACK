"""One behavioural contract for every ``Broker`` adapter (paper, OANDA, and later MT5).

Each adapter is wrapped in a harness that can set the market quote; the tests then only use
the ``Broker`` protocol. Idempotency checks adapt to ``capabilities.client_id_support``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fxbot.brokers.base import Broker, BrokerCapabilities, ClientIdSupport
from fxbot.brokers.oanda.adapter import OandaBroker
from fxbot.brokers.paper import PaperBroker, PaperConfig
from fxbot.domain.clock import SimClock
from fxbot.domain.enums import FillReason, OrderStatus, Side
from fxbot.domain.models import OrderRequest, Price
from tests.fake_oanda import FakeOandaServer
from tests.support import practice_client

NOW = datetime(2024, 3, 4, 12, 0, tzinfo=UTC)


@dataclass
class Harness:
    broker: Broker
    set_quote: Callable[[str, str, str], None]
    submissions: Callable[[], int]


def _paper(support: ClientIdSupport) -> Harness:
    broker = PaperBroker(clock=SimClock(NOW), config=PaperConfig(client_id_support=support))

    def set_quote(instrument: str, bid: str, ask: str) -> None:
        broker.on_price(Price(instrument=instrument, time=NOW, bid=Decimal(bid), ask=Decimal(ask)))

    def submissions() -> int:
        return sum(1 for t in broker._state.transactions if t.type == "MARKET_ORDER")

    return Harness(broker, set_quote, submissions)


@pytest.fixture(params=["paper", "paper-comment-ids", "oanda"])
async def harness(request: pytest.FixtureRequest) -> AsyncIterator[Harness]:
    if request.param == "paper":
        yield _paper(ClientIdSupport.NATIVE)
        return
    if request.param == "paper-comment-ids":
        yield _paper(ClientIdSupport.COMMENT)
        return
    server = FakeOandaServer()
    broker = OandaBroker(practice_client(server.router()))
    server.set_price("EUR_USD", "1.10000", "1.10010")
    await broker.connect()
    yield Harness(broker, server.set_price, lambda: server.order_posts)
    await broker.aclose()


def buy(client_id: str = "afx-contract-1") -> OrderRequest:
    return OrderRequest(
        client_id=client_id,
        instrument="EUR_USD",
        side=Side.BUY,
        units=Decimal(1000),
        stop_loss=Decimal("1.09500"),
        take_profit=Decimal("1.11000"),
        price_bound=Decimal("1.10050"),
        strategy_id="contract",
        signal_id="sig-1",
    )


async def test_capabilities_are_exposed(harness: Harness) -> None:
    capabilities = harness.broker.capabilities

    assert isinstance(capabilities, BrokerCapabilities)
    assert capabilities.supports_sl_on_fill
    assert capabilities.client_id_support in set(ClientIdSupport)
    assert capabilities.candle_price_sides
    assert harness.broker.name


async def test_submit_fill_close_and_transactions(harness: Harness) -> None:
    broker = harness.broker
    harness.set_quote("EUR_USD", "1.10000", "1.10010")
    start = await broker.get_transactions_since(None)

    result = await broker.submit_order(buy())

    assert result.status is OrderStatus.FILLED
    assert result.fill is not None
    assert result.fill.side is Side.BUY
    assert result.fill.units == 1000
    assert result.fill.price >= Decimal("1.10010")  # bought at the ask (plus any slippage)
    assert result.fill.reason is FillReason.ENTRY
    (trade,) = await broker.get_open_trades()
    assert trade.id == result.fill.trade_id
    assert trade.client_id == "afx-contract-1"
    assert trade.is_ours

    harness.set_quote("EUR_USD", "1.10200", "1.10210")
    close = await broker.close_trade(trade.id)

    assert close.trade_id == trade.id
    assert close.side is Side.SELL
    assert close.realized_pl > 0
    assert await broker.get_open_trades() == []
    page = await broker.get_transactions_since(start.last_id)
    assert any(t.id == result.fill.transaction_id for t in page.items)
    assert any(t.id == close.transaction_id for t in page.items)


async def test_every_fill_has_a_stop(harness: Harness) -> None:
    harness.set_quote("EUR_USD", "1.10000", "1.10010")

    await harness.broker.submit_order(buy())

    (trade,) = await harness.broker.get_open_trades()
    assert trade.stop_loss == Decimal("1.09500")
    assert trade.take_profit == Decimal("1.11000")


async def test_same_client_id_twice_opens_one_trade(harness: Harness) -> None:
    if harness.broker.capabilities.client_id_support is ClientIdSupport.NONE:
        pytest.skip("broker cannot find orders by client id")  # pragma: no cover
    harness.set_quote("EUR_USD", "1.10000", "1.10010")

    first = await harness.broker.submit_order(buy())
    second = await harness.broker.submit_order(buy())

    assert second.status is OrderStatus.FILLED
    assert second.fill is not None and first.fill is not None
    assert second.fill.trade_id == first.fill.trade_id
    assert len(await harness.broker.get_open_trades()) == 1
    assert harness.submissions() == 1
    found = await harness.broker.find_order("afx-contract-1")
    assert found is not None and found.status is OrderStatus.FILLED


async def test_unknown_client_id_is_not_found(harness: Harness) -> None:
    assert await harness.broker.find_order("afx-never-sent") is None


async def test_fill_beyond_price_bound_is_cancelled(harness: Harness) -> None:
    harness.set_quote("EUR_USD", "1.10100", "1.10110")  # ask moved above the bound

    result = await harness.broker.submit_order(buy())

    assert result.status is OrderStatus.CANCELLED
    assert result.reason == "BOUNDS_VIOLATION"
    assert await harness.broker.get_open_trades() == []


async def test_modify_exits_and_close_all(harness: Harness) -> None:
    harness.set_quote("EUR_USD", "1.10000", "1.10010")
    await harness.broker.submit_order(buy())
    await harness.broker.submit_order(buy("afx-contract-2"))
    trade = (await harness.broker.get_open_trades())[0]

    await harness.broker.modify_trade_exits(trade.id, stop_loss=Decimal("1.09800"))

    updated = next(t for t in await harness.broker.get_open_trades() if t.id == trade.id)
    assert updated.stop_loss == Decimal("1.09800")
    fills = await harness.broker.close_all()
    assert len(fills) == 2
    assert await harness.broker.get_open_trades() == []
    assert await harness.broker.get_positions() == []


async def test_account_summary(harness: Harness) -> None:
    harness.set_quote("EUR_USD", "1.10000", "1.10010")
    account = await harness.broker.get_account()

    assert account.currency == "USD"
    assert account.nav == account.balance
    assert "1234567" not in account.masked_id
