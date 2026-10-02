"""OANDA REST client and adapter against recorded v20 payloads (respx, no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from fxbot.brokers.oanda.adapter import OandaBroker
from fxbot.brokers.oanda.feed import OandaFeed
from fxbot.domain.clock import SimClock
from fxbot.domain.enums import FillReason, Granularity, OrderStatus, Side
from fxbot.domain.errors import (
    BrokerAuthError,
    BrokerRejectedError,
    BrokerUnavailableError,
    DataIntegrityError,
    RateLimitedError,
)
from fxbot.domain.models import OrderRequest
from tests.support import ACCOUNT_PATH, PRACTICE, RecordingSleep, fixture, practice_client

D = Decimal


@pytest.fixture
def router() -> respx.Router:
    return respx.Router(base_url=PRACTICE.rest, assert_all_called=False)


@pytest.fixture
def sleep() -> RecordingSleep:
    return RecordingSleep()


@pytest.fixture
def broker(router: respx.Router, sleep: RecordingSleep) -> OandaBroker:
    router.get(f"{ACCOUNT_PATH}/instruments").respond(json=fixture("instruments.json"))
    return OandaBroker(practice_client(router, sleep=sleep))


def market_order(**overrides: object) -> OrderRequest:
    fields: dict[str, object] = {
        "client_id": "afx-7f3c2a",
        "instrument": "EUR_USD",
        "side": Side.BUY,
        "units": D("12000.9"),
        "stop_loss": D("1.160104"),
        "take_profit": D("1.171496"),
        "price_bound": D("1.164"),
        "strategy_id": "trend_breakout_h4",
        "signal_id": "2024-03-04T12:00Z",
    }
    fields.update(overrides)
    return OrderRequest(**fields)  # type: ignore[arg-type]


def candle_json(
    time: datetime, *, complete: bool = True, mid: str = "1.10000"
) -> dict[str, object]:
    bid = {"o": mid, "h": "1.10100", "l": "1.09900", "c": mid}
    ask = {"o": "1.10010", "h": "1.10110", "l": "1.09910", "c": "1.10010"}
    return {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "bid": bid,
        "ask": ask,
        "volume": 10,
        "complete": complete,
    }


# ------------------------------------------------------------------------- reads


async def test_account_summary(router: respx.Router, broker: OandaBroker) -> None:
    route = router.get(f"{ACCOUNT_PATH}/summary").respond(json=fixture("account_summary.json"))

    account = await broker.get_account()

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"].startswith("Bearer ")
    assert request.headers["Accept-Datetime-Format"] == "RFC3339"
    assert account.currency == "EUR"
    assert account.nav == D("35454.4740")
    assert account.margin_used == D("10581.5000")
    assert account.margin_closeout_percent == D("0.14923")
    assert account.open_trade_count == 2
    assert account.last_transaction_id == "2123"
    assert broker.capabilities.supports_hedging is False


async def test_instruments_parse_precision_and_financing(broker: OandaBroker) -> None:
    instruments = {i.name: i for i in await broker.get_instruments()}

    eur_usd, usd_jpy, gbp_nzd = (
        instruments["EUR_USD"],
        instruments["USD_JPY"],
        instruments["GBP_NZD"],
    )
    assert eur_usd.pip_size == D("0.0001") and eur_usd.display_precision == 5
    assert usd_jpy.pip_size == D("0.01") and usd_jpy.tick_size == D("0.001")
    assert eur_usd.units_step == 1 and eur_usd.max_units == D("100000000")
    assert gbp_nzd.financing is not None
    assert gbp_nzd.financing.long_rate == D("-0.0153")
    assert gbp_nzd.financing.days_charged == (1, 1, 1, 1, 1, 0, 0)


async def test_open_trades_and_positions(router: respx.Router, broker: OandaBroker) -> None:
    router.get(f"{ACCOUNT_PATH}/openTrades").respond(json=fixture("open_trades.json"))
    router.get(f"{ACCOUNT_PATH}/openPositions").respond(json=fixture("open_positions.json"))

    long, short = await broker.get_open_trades()
    eur, jpy = await broker.get_positions()

    assert (long.side, long.units, long.stop_loss, long.take_profit) == (
        Side.BUY,
        D(100),
        D("1.09000"),
        D("1.10500"),
    )
    assert long.client_id == "afx-7f3c2a" and long.is_ours
    assert (short.side, short.units, short.stop_loss) == (Side.SELL, D(500), None)
    assert not short.is_ours
    assert eur.long_units == 100 and eur.net_units == 100
    assert jpy.short_units == 500 and jpy.net_units == -500


async def test_transactions_since_id_strip_private_fields(
    router: respx.Router, broker: OandaBroker
) -> None:
    route = router.get(f"{ACCOUNT_PATH}/transactions/sinceid").respond(
        json=fixture("transactions_sinceid.json")
    )

    page = await broker.get_transactions_since("2123")

    assert route.calls.last.request.url.params["id"] == "2123"
    assert [t.type for t in page.items] == ["MARKET_ORDER", "ORDER_FILL", "DAILY_FINANCING"]
    assert page.last_id == "2126"
    for transaction in page.items:
        assert "accountID" not in transaction.payload
        assert "userID" not in transaction.payload


async def test_candles_paginate_drop_incomplete_and_exclude_first(router: respx.Router) -> None:
    start = datetime(2024, 3, 4, 0, tzinfo=UTC)
    hours = [start + timedelta(hours=i) for i in range(5)]
    pages = [
        {"candles": [candle_json(t) for t in hours[:2]]},
        {"candles": [candle_json(t) for t in hours[2:4]]},
        {"candles": [candle_json(hours[4], complete=False)]},
    ]
    route = router.get("/v3/instruments/EUR_USD/candles").mock(
        side_effect=[httpx.Response(200, json=page) for page in pages]
    )
    clock = SimClock(start + timedelta(hours=5))
    feed = OandaFeed(practice_client(router), clock=clock, page_size=2)

    candles = await feed.get_candles("EUR_USD", Granularity.H1, start)

    assert [c.time for c in candles] == hours[:4]
    first, second, third = (call.request.url.params for call in route.calls)
    assert first["price"] == "BA" and first["smooth"] == "false"
    assert first["includeFirst"] == "true" and first["count"] == "2"
    assert second["includeFirst"] == "false"
    assert second["from"].startswith("2024-03-04T01:00:00")
    assert third["from"].startswith("2024-03-04T03:00:00")
    assert candles[0].ask.close == D("1.10010")


async def test_candles_out_of_order_are_refused(router: respx.Router) -> None:
    start = datetime(2024, 3, 4, 0, tzinfo=UTC)
    router.get("/v3/instruments/EUR_USD/candles").respond(
        json={"candles": [candle_json(start + timedelta(hours=1)), candle_json(start)]}
    )
    feed = OandaFeed(practice_client(router), clock=SimClock(start + timedelta(days=1)))

    with pytest.raises(DataIntegrityError, match="strictly increasing"):
        await feed.get_candles("EUR_USD", Granularity.H1, start)


# ------------------------------------------------------------------------- orders


async def test_market_order_carries_stop_bound_and_client_id(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").respond(404, json={"errorMessage": "no"})
    post = router.post(f"{ACCOUNT_PATH}/orders").respond(201, json=fixture("order_filled.json"))
    trade = fixture("open_trades.json")["trades"][0] | {"id": "23"}
    router.get(f"{ACCOUNT_PATH}/trades/23").respond(json={"trade": trade})

    result = await broker.submit_order(market_order())

    sent = json.loads(post.calls.last.request.content)["order"]
    assert sent == {
        "type": "MARKET",
        "instrument": "EUR_USD",
        "units": "12000",  # rounded down to the unit step
        "timeInForce": "FOK",
        "positionFill": "DEFAULT",
        "priceBound": "1.16400",
        "stopLossOnFill": {"price": "1.16010", "timeInForce": "GTC"},
        "takeProfitOnFill": {"price": "1.17150", "timeInForce": "GTC"},
        "clientExtensions": {
            "id": "afx-7f3c2a",
            "tag": "trend_breakout_h4",
            "comment": "signal=2024-03-04T12:00Z",
        },
        "tradeClientExtensions": {"id": "afx-7f3c2a", "tag": "trend_breakout_h4"},
    }
    assert result.status is OrderStatus.FILLED
    assert result.broker_order_id == "22"
    assert result.fill is not None
    assert (result.fill.trade_id, result.fill.price) == ("23", D("1.16377"))
    assert result.fill.units == 12000
    assert result.fill.half_spread_cost == D("0.0089")
    assert result.last_transaction_id == "24"


async def test_sell_units_are_negative(router: respx.Router, broker: OandaBroker) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").respond(404, json={})
    post = router.post(f"{ACCOUNT_PATH}/orders").respond(
        201, json=fixture("order_cancelled_market_halted.json")
    )
    order = market_order(
        side=Side.SELL, stop_loss=D("1.17"), take_profit=None, price_bound=D("1.15")
    )

    result = await broker.submit_order(order)

    assert json.loads(post.calls.last.request.content)["order"]["units"] == "-12000"
    assert result.status is OrderStatus.CANCELLED
    assert result.reason == "MARKET_HALTED"


async def test_precision_reject_is_not_retried(router: respx.Router, broker: OandaBroker) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").respond(404, json={})
    post = router.post(f"{ACCOUNT_PATH}/orders").respond(
        400, json=fixture("order_rejected_precision.json")
    )

    result = await broker.submit_order(market_order())

    assert post.call_count == 1
    assert result.status is OrderStatus.REJECTED
    assert result.reason == "TAKE_PROFIT_ON_FILL_PRICE_PRECISION_EXCEEDED"


@pytest.mark.parametrize("failure", ["timeout", "server_error"])
async def test_order_post_is_never_retried_and_resolved_by_lookup(
    router: respx.Router, broker: OandaBroker, failure: str
) -> None:
    lookup = router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a")
    lookup.side_effect = [
        httpx.Response(404, json={"errorMessage": "Order specified does not exist"}),
        httpx.Response(200, json=fixture("order_by_client_id_filled.json")),
    ]
    router.get(f"{ACCOUNT_PATH}/transactions/23").respond(
        json={"transaction": fixture("order_filled.json")["orderFillTransaction"]}
    )
    post = router.post(f"{ACCOUNT_PATH}/orders")
    if failure == "timeout":
        post.side_effect = httpx.ReadTimeout("timed out")
    else:
        post.respond(503, json={"errorMessage": "unavailable"})

    result = await broker.submit_order(market_order())

    assert post.call_count == 1
    assert result.status is OrderStatus.FILLED
    assert result.fill is not None and result.fill.trade_id == "23"


async def test_unresolved_submission_is_unknown(router: respx.Router, broker: OandaBroker) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").respond(404, json={})
    post = router.post(f"{ACCOUNT_PATH}/orders").mock(side_effect=httpx.ConnectError("reset"))

    result = await broker.submit_order(market_order())

    assert post.call_count == 1
    assert result.status is OrderStatus.UNKNOWN


async def test_rate_limited_order_raises_without_retry(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").respond(404, json={})
    post = router.post(f"{ACCOUNT_PATH}/orders").respond(429, headers={"Retry-After": "2"})

    with pytest.raises(RateLimitedError) as exc:
        await broker.submit_order(market_order())

    assert post.call_count == 1
    assert exc.value.retry_after == 2.0


async def test_order_below_minimum_size_is_rejected_locally(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").respond(404, json={})
    post = router.post(f"{ACCOUNT_PATH}/orders")

    result = await broker.submit_order(market_order(units=D("0.5")))

    assert not post.called
    assert result.status is OrderStatus.REJECTED


async def test_fill_without_stop_gets_one_attached(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").respond(404, json={})
    router.post(f"{ACCOUNT_PATH}/orders").respond(201, json=fixture("order_filled.json"))
    unprotected = fixture("open_trades.json")["trades"][1] | {"id": "23", "instrument": "EUR_USD"}
    unprotected["price"] = "1.16377"
    router.get(f"{ACCOUNT_PATH}/trades/23").respond(json={"trade": unprotected})
    set_orders = router.put(f"{ACCOUNT_PATH}/trades/23/orders").respond(
        json=fixture("trade_orders.json")
    )

    await broker.submit_order(market_order())

    body = json.loads(set_orders.calls.last.request.content)
    assert body == {"stopLoss": {"price": "1.16010", "timeInForce": "GTC"}}


async def test_fill_whose_stop_cannot_be_attached_is_closed(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").respond(404, json={})
    router.post(f"{ACCOUNT_PATH}/orders").respond(201, json=fixture("order_filled.json"))
    unprotected = fixture("open_trades.json")["trades"][1] | {"id": "23", "instrument": "EUR_USD"}
    router.get(f"{ACCOUNT_PATH}/trades/23").respond(json={"trade": unprotected})
    router.put(f"{ACCOUNT_PATH}/trades/23/orders").respond(
        400, json={"stopLossOrderRejectTransaction": {"rejectReason": "X"}, "errorMessage": "no"}
    )
    close_body = fixture("trade_close.json")
    close_body["orderFillTransaction"]["tradesClosed"][0]["tradeID"] = "23"
    close = router.put(f"{ACCOUNT_PATH}/trades/23/close").respond(json=close_body)

    result = await broker.submit_order(market_order())

    assert close.called
    assert result.status is OrderStatus.FILLED


async def test_close_trade(router: respx.Router, broker: OandaBroker) -> None:
    route = router.put(f"{ACCOUNT_PATH}/trades/2313/close").respond(
        json=fixture("trade_close.json")
    )

    fill = await broker.close_trade("2313")

    assert json.loads(route.calls.last.request.content) == {"units": "ALL"}
    assert (fill.trade_id, fill.side, fill.units) == ("2313", Side.SELL, D(100))
    assert fill.price == D("1.09289")  # per-trade price missing: transaction price is used
    assert fill.realized_pl == D("-0.1455")
    assert fill.reason is FillReason.CLOSE


async def test_partial_close_formats_units(router: respx.Router, broker: OandaBroker) -> None:
    router.get(f"{ACCOUNT_PATH}/trades/2313").respond(
        json={"trade": fixture("open_trades.json")["trades"][0]}
    )
    route = router.put(f"{ACCOUNT_PATH}/trades/2313/close").respond(
        json=fixture("trade_close.json")
    )

    await broker.close_trade("2313", D("50.7"))

    assert json.loads(route.calls.last.request.content) == {"units": "50"}


async def test_close_cancelled_when_market_halted(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.put(f"{ACCOUNT_PATH}/trades/35/close").respond(
        json=fixture("order_cancelled_market_halted.json")
    )

    with pytest.raises(BrokerRejectedError) as exc:
        await broker.close_trade("35")

    assert exc.value.code == "MARKET_HALTED"


async def test_modify_trade_exits(router: respx.Router, broker: OandaBroker) -> None:
    router.get(f"{ACCOUNT_PATH}/trades/2313").respond(
        json={"trade": fixture("open_trades.json")["trades"][0]}
    )
    route = router.put(f"{ACCOUNT_PATH}/trades/2313/orders").respond(
        json=fixture("trade_orders.json")
    )

    await broker.modify_trade_exits("2313", stop_loss=D("1.1"), take_profit=D("1.05"))
    await broker.modify_trade_exits("2313")  # nothing to change: no request

    assert route.call_count == 1
    assert json.loads(route.calls.last.request.content) == {
        "stopLoss": {"price": "1.10000", "timeInForce": "GTC"},
        "takeProfit": {"price": "1.05000", "timeInForce": "GTC"},
    }


async def test_close_all_closes_each_side(router: respx.Router, broker: OandaBroker) -> None:
    router.get(f"{ACCOUNT_PATH}/openPositions").respond(json=fixture("open_positions.json"))
    eur = router.put(f"{ACCOUNT_PATH}/positions/EUR_USD/close").respond(
        json={"longOrderFillTransaction": fixture("trade_close.json")["orderFillTransaction"]}
    )
    jpy = router.put(f"{ACCOUNT_PATH}/positions/USD_JPY/close").respond(
        json={"shortOrderCancelTransaction": {"reason": "MARKET_HALTED"}}
    )

    fills = await broker.close_all()

    assert json.loads(eur.calls.last.request.content) == {"longUnits": "ALL"}
    assert json.loads(jpy.calls.last.request.content) == {"shortUnits": "ALL"}
    assert [f.trade_id for f in fills] == ["2313"]


# ------------------------------------------------------------------------- errors and retries


async def test_4xx_is_raised_without_retry(router: respx.Router, broker: OandaBroker) -> None:
    route = router.get(f"{ACCOUNT_PATH}/summary").respond(
        400, json={"errorMessage": "Invalid value specified for 'accountID'"}
    )

    with pytest.raises(BrokerRejectedError) as exc:
        await broker.get_account()

    assert route.call_count == 1
    assert exc.value.status_code == 400


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_errors(router: respx.Router, broker: OandaBroker, status: int) -> None:
    route = router.get(f"{ACCOUNT_PATH}/summary").respond(status, json={"errorMessage": "no"})

    with pytest.raises(BrokerAuthError):
        await broker.get_account()

    assert route.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(503, json={"errorMessage": "down"}),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
        httpx.Response(200, text="not json"),
    ],
    ids=["5xx", "timeout", "connect", "malformed"],
)
async def test_gets_are_retried_with_backoff_then_fail(
    router: respx.Router,
    broker: OandaBroker,
    sleep: RecordingSleep,
    failure: httpx.Response | Exception,
) -> None:
    route = router.get(f"{ACCOUNT_PATH}/summary").mock(side_effect=[failure] * 3)

    with pytest.raises(BrokerUnavailableError) as exc:
        await broker.get_account()

    assert route.call_count == 3
    assert len(sleep.calls) == 2
    assert 0.25 <= sleep.calls[0] <= 0.5 and 0.5 <= sleep.calls[1] <= 1.0
    assert exc.value.endpoint == "account_summary"


async def test_get_recovers_after_transient_failure(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.get(f"{ACCOUNT_PATH}/summary").mock(
        side_effect=[
            httpx.Response(502),
            httpx.Response(200, json=fixture("account_summary.json")),
        ]
    )

    assert (await broker.get_account()).currency == "EUR"


async def test_429_honours_retry_after(
    router: respx.Router, broker: OandaBroker, sleep: RecordingSleep
) -> None:
    router.get(f"{ACCOUNT_PATH}/summary").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=fixture("account_summary.json")),
        ]
    )

    await broker.get_account()

    assert sleep.calls == [7.0]


async def test_pricing_snapshot(router: respx.Router, broker: OandaBroker) -> None:
    route = router.get(f"{ACCOUNT_PATH}/pricing").respond(json=fixture("pricing.json"))

    (price,) = await broker.get_prices(["EUR_USD"])

    assert route.calls.last.request.url.params["instruments"] == "EUR_USD"
    assert (price.bid, price.ask, price.tradeable) == (D("1.12157"), D("1.12170"), True)


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.get_trade("../../v3/accounts"),
        lambda c: c.get_order("@bad id"),
        lambda c: c.candles("EUR/USD", {}),
        lambda c: c.get_transaction("12;3"),
        lambda c: c.pricing([]),
    ],
    ids=["trade", "order", "instrument", "transaction", "empty"],
)
async def test_invalid_identifiers_never_reach_a_url(router: respx.Router, call: object) -> None:
    client = practice_client(router)
    catch_all = router.route().respond(200, json={})

    with pytest.raises(ValueError, match=r"invalid|at least one"):
        await call(client)  # type: ignore[operator]

    assert not catch_all.called


# ------------------------------------------------------------------------- order lookups


async def test_find_order_reports_cancelled_and_pending_orders(
    router: respx.Router, broker: OandaBroker
) -> None:
    cancelled = {"id": "64", "state": "CANCELLED", "cancellingTransactionID": "65"}
    pending = {"id": "70", "state": "PENDING"}
    router.get(f"{ACCOUNT_PATH}/orders/@afx-cancelled").respond(json={"order": cancelled})
    router.get(f"{ACCOUNT_PATH}/orders/@afx-pending").respond(json={"order": pending})
    router.get(f"{ACCOUNT_PATH}/orders/@afx-broken").respond(500, json={})
    router.get(f"{ACCOUNT_PATH}/transactions/65").respond(
        json={
            "transaction": fixture("order_cancelled_market_halted.json")["orderCancelTransaction"]
        }
    )

    gone = await broker.find_order("afx-cancelled")
    waiting = await broker.find_order("afx-pending")

    assert gone is not None and (gone.status, gone.reason) == (
        OrderStatus.CANCELLED,
        "MARKET_HALTED",
    )
    assert waiting is not None and waiting.status is OrderStatus.SUBMITTED
    with pytest.raises(BrokerUnavailableError):
        await broker.find_order("afx-broken")


async def test_lookup_failure_after_timeout_is_unknown(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.get(f"{ACCOUNT_PATH}/orders/@afx-7f3c2a").mock(
        side_effect=[httpx.Response(404, json={}), *[httpx.Response(503)] * 3]
    )
    router.post(f"{ACCOUNT_PATH}/orders").mock(side_effect=httpx.ReadTimeout("slow"))

    result = await broker.submit_order(market_order())

    assert result.status is OrderStatus.UNKNOWN


async def test_unknown_instrument_is_rejected(router: respx.Router) -> None:
    router.get(f"{ACCOUNT_PATH}/instruments").respond(json={"instruments": []})
    broker = OandaBroker(practice_client(router))

    with pytest.raises(BrokerRejectedError, match="not tradeable"):
        await broker.submit_order(market_order())


async def test_rejected_exit_change_raises(router: respx.Router, broker: OandaBroker) -> None:
    router.get(f"{ACCOUNT_PATH}/trades/2313").respond(
        json={"trade": fixture("open_trades.json")["trades"][0]}
    )
    router.put(f"{ACCOUNT_PATH}/trades/2313/orders").respond(
        json={"stopLossOrderRejectTransaction": {"rejectReason": "STOP_LOSS_ON_FILL_LOSS"}}
    )

    with pytest.raises(BrokerRejectedError, match="exit change rejected"):
        await broker.modify_trade_exits("2313", stop_loss=D("1.2"))


async def test_close_fill_for_another_trade_is_an_error(
    router: respx.Router, broker: OandaBroker
) -> None:
    router.put(f"{ACCOUNT_PATH}/trades/9999/close").respond(json=fixture("trade_close.json"))

    with pytest.raises(BrokerRejectedError, match="did not reference"):
        await broker.close_trade("9999")
